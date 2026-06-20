from collections import deque, Counter
from typing import Optional
import time

_store = {
    "state": "unknown",
    "confidence": 0.0,
    "updated_at": 0.0,
    "prev_box": None,
    "last_frame_at": 0.0,
}

_state_buffer: deque = deque(maxlen=2)


def get_state() -> dict:
    return {
        "state": _store["state"],
        "confidence": _store["confidence"],
        "updated_at": _store["updated_at"],
        "offline": time.time() - _store["last_frame_at"] > 60,
    }


def update_frame_time() -> None:
    _store["last_frame_at"] = time.time()


def set_state(state: str, confidence: float = 1.0) -> str:
    _state_buffer.append(state)
    smoothed = _smooth()
    _store["state"] = smoothed
    _store["confidence"] = confidence
    _store["updated_at"] = time.time()
    return smoothed


def get_prev_box() -> Optional[list]:
    return _store["prev_box"]


def set_prev_box(box: Optional[list]) -> None:
    _store["prev_box"] = box


def _smooth() -> str:
    if not _state_buffer:
        return "unknown"
    counts = Counter(_state_buffer)
    return counts.most_common(1)[0][0]
