import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).with_name('analyzer.py').read_text(encoding='utf-8-sig')

class ResponseTests(unittest.TestCase):
    def temporal(self, elapsed, continuous, pose, previous, store):
        start = SOURCE.index('    pose_changed =')
        end = SOURCE.index('    activity_score =', start)
        import textwrap
        scope = dict(continuous=continuous, elapsed=elapsed, pose=pose,
                     previous_pose=previous, motion_ratio=0.0,
                     MOTION_STILL_RATIO=0.025, STILL_FRAMES_SLEEP=8,
                     state=SimpleNamespace(_store=store))
        exec(textwrap.dedent(SOURCE[start:end]), scope)
        return scope

    def test_pose_motion_resets_sleep(self):
        store = {'still_seconds': 40, 'moving_frames': 1}
        result = self.temporal(1, True, {'nose_rel_y': .6}, {'nose_rel_y': .4}, store)
        self.assertEqual(result['still_count'], 0)
        self.assertEqual(store['moving_frames'], 2)

    def test_sleep_uses_seconds_not_frames(self):
        store = {}
        for _ in range(23):
            result = self.temporal(1, True, {}, {}, store)
        self.assertEqual(result['still_count'], 0)
        self.assertEqual(self.temporal(1, True, {}, {}, store)['still_count'], 8)

    def test_gap_does_not_count_as_rest(self):
        store = {'still_seconds': 23}
        self.assertEqual(self.temporal(30, False, {}, {}, store)['still_count'], 0)

    def test_wake_bypasses_old_sleep_vote(self):
        from collections import deque, Counter
        tree = ast.parse(Path(__file__).with_name('state.py').read_text(encoding='utf-8-sig'))
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('set_state', '_smooth')]
        import threading, time
        scope = dict(_lock=threading.RLock(), _state_buffer=deque(['sleep'], maxlen=2),
                     _store={'state':'sleep'}, _history=deque(), Counter=Counter, time=time,
                     _save_history_event=lambda *a: None, _update_feeding_state_machine=lambda *a: None)
        exec(compile(ast.Module(body=funcs, type_ignores=[]), '<state>', 'exec'), scope)
        self.assertEqual(scope['set_state']('play', .65), 'play')

if __name__ == '__main__':
    unittest.main()
