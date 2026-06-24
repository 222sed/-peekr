from collections import Counter, deque
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Optional
import sqlite3
import time


OFFLINE_AFTER_SECONDS = 60
MAX_HISTORY_EVENTS = 10000
DB_PATH = Path(__file__).with_name("peekr.db")

_store = {
    "state": "unknown",
    "confidence": 0.0,
    "updated_at": 0.0,
    "prev_box": None,
    "last_frame_at": 0.0,
    "captured_at": 0.0,
    "device_id": "",
    "battery_level": None,
    "is_charging": False,
    "activity_score": 0,
}

_state_buffer: deque = deque(maxlen=2)
_history: deque = deque(maxlen=MAX_HISTORY_EVENTS)
_lock = RLock()


def _connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS state_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state TEXT NOT NULL,
            at REAL NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_state_events_at ON state_events(at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS food_calibrations (
            device_id TEXT NOT NULL,
            level TEXT NOT NULL,
            signature TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (device_id, level)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            score REAL NOT NULL,
            at REAL NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_samples_at ON activity_samples(at)"
    )
    return connection


def _save_history_event(state: str, at: float) -> None:
    connection = _connect_db()
    try:
        connection.execute(
            "INSERT INTO state_events(state, at) VALUES (?, ?)",
            (state, at),
        )
        connection.commit()
    finally:
        connection.close()


def _load_history_events(start: float, end: float) -> list[dict]:
    connection = _connect_db()
    try:
        rows = connection.execute(
            "SELECT state, at FROM state_events WHERE at >= ? AND at <= ? ORDER BY at",
            (start, end),
        ).fetchall()
    finally:
        connection.close()
    return [{"state": row[0], "at": float(row[1])} for row in rows]


_initial_connection = _connect_db()
_initial_connection.commit()
_initial_connection.close()


def _is_offline(now: Optional[float] = None) -> bool:
    now = now or time.time()
    last_frame_at = float(_store.get("last_frame_at") or 0)
    return last_frame_at <= 0 or now - last_frame_at > OFFLINE_AFTER_SECONDS


def get_state() -> dict:
    with _lock:
        return {
            "state": _store["state"],
            "confidence": _store["confidence"],
            "updated_at": _store["updated_at"],
            "offline": _is_offline(),
            "last_frame_at": _store["last_frame_at"],
            "captured_at": _store["captured_at"],
            "device": {
                "id": _store["device_id"],
                "battery_level": _store["battery_level"],
                "is_charging": _store["is_charging"],
            },
            "activity_score": _store["activity_score"],
        }


def get_dashboard() -> dict:
    result = get_state()
    result["today"] = get_today_summary()
    result["food_remaining"] = _store.get("food_remaining")
    result["food_calibrated"] = bool(_store.get("food_calibrated"))
    return result


def save_food_calibration(device_id: str, level: str, signature: list[float]) -> None:
    import json

    connection = _connect_db()
    try:
        connection.execute(
            """
            INSERT INTO food_calibrations(device_id, level, signature, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(device_id, level) DO UPDATE SET
                signature = excluded.signature,
                updated_at = excluded.updated_at
            """,
            (device_id, level, json.dumps(signature), time.time()),
        )
        connection.commit()
    finally:
        connection.close()


def get_food_calibrations(device_id: str) -> dict[str, list[float]]:
    import json

    if not device_id:
        return {}
    connection = _connect_db()
    try:
        rows = connection.execute(
            "SELECT level, signature FROM food_calibrations WHERE device_id = ?",
            (device_id,),
        ).fetchall()
    finally:
        connection.close()
    return {row[0]: json.loads(row[1]) for row in rows}


def set_food_remaining(value: Optional[int], calibrated: bool) -> None:
    with _lock:
        _store["food_remaining"] = value
        _store["food_calibrated"] = calibrated


def record_activity(score: float) -> None:
    score = max(0.0, min(100.0, float(score)))
    now = time.time()
    with _lock:
        _store["activity_score"] = round(score)
    connection = _connect_db()
    try:
        connection.execute(
            "INSERT INTO activity_samples(score, at) VALUES (?, ?)",
            (score, now),
        )
        connection.execute(
            "DELETE FROM activity_samples WHERE at < ?",
            (now - 8 * 24 * 60 * 60,),
        )
        connection.commit()
    finally:
        connection.close()


def _today_activity_score(start: float, end: float) -> int:
    connection = _connect_db()
    try:
        row = connection.execute(
            """
            SELECT AVG(score)
            FROM activity_samples
            WHERE at >= ? AND at <= ?
            """,
            (start, end),
        ).fetchone()
    finally:
        connection.close()
    return round(float(row[0])) if row and row[0] is not None else 0


def update_frame_info(
    device_id: str = "",
    captured_at: Optional[float] = None,
    battery_level: Optional[int] = None,
    is_charging: bool = False,
) -> None:
    with _lock:
        now = time.time()
        _store["last_frame_at"] = now
        _store["captured_at"] = captured_at or now
        if device_id:
            _store["device_id"] = device_id[:80]
        if battery_level is not None:
            _store["battery_level"] = max(0, min(100, int(battery_level)))
        _store["is_charging"] = bool(is_charging)


def update_frame_time() -> None:
    update_frame_info()


def set_state(state: str, confidence: float = 1.0) -> str:
    with _lock:
        _state_buffer.append(state)
        smoothed = _smooth()
        now = time.time()
        previous = _store["state"]
        _store["state"] = smoothed
        _store["confidence"] = confidence
        _store["updated_at"] = now
        if not _history or previous != smoothed:
            _history.append({"state": smoothed, "at": now})
            _save_history_event(smoothed, now)
        return smoothed


def get_prev_box() -> Optional[list]:
    with _lock:
        return _store["prev_box"]


def set_prev_box(box: Optional[list]) -> None:
    with _lock:
        _store["prev_box"] = box


def _smooth() -> str:
    if not _state_buffer:
        return "unknown"
    counts = Counter(_state_buffer)
    return counts.most_common(1)[0][0]


def _start_of_today(now: float) -> float:
    current = datetime.fromtimestamp(now)
    return datetime(
        current.year,
        current.month,
        current.day,
    ).timestamp()


def get_today_summary() -> dict:
    with _lock:
        now = time.time()
        start = _start_of_today(now)
        offline = _is_offline(now)
        last_frame_at = float(_store.get("last_frame_at") or 0)
        battery = _store.get("battery_level")
    events = _load_history_events(start, now)

    points = [{"state": "unknown", "at": start}]
    for event in events:
        if event["at"] <= now:
            points.append(event)

    if offline and last_frame_at > 0:
        offline_at = min(last_frame_at + OFFLINE_AFTER_SECONDS, now)
        if offline_at > start:
            points.append({"state": "unknown", "at": offline_at})

    points.sort(key=lambda item: item["at"])
    compact_points = []
    for point in points:
        if compact_points and compact_points[-1]["state"] == point["state"]:
            continue
        compact_points.append(point)

    duration_by_state = Counter()
    segments = []
    total_seconds = max(now - start, 1.0)
    for index, point in enumerate(compact_points):
        end = compact_points[index + 1]["at"] if index + 1 < len(compact_points) else now
        seconds = max(0.0, end - point["at"])
        duration_by_state[point["state"]] += seconds
        if seconds > 0:
            segments.append({
                "type": point["state"] if point["state"] in {"sleep", "play", "food"} else "idle",
                "pct": round(seconds / total_seconds * 100, 2),
            })

    food_count = 0
    last_state = None
    for event in events:
        if event["state"] == "food" and last_state != "food":
            food_count += 1
        last_state = event["state"]

    tracked_seconds = sum(
        duration_by_state[name]
        for name in ("sleep", "play", "food", "dream")
    )
    stats_total = tracked_seconds if tracked_seconds > 0 else 1.0
    sleep_pct = round(duration_by_state["sleep"] / stats_total * 100)
    play_pct = round(duration_by_state["play"] / stats_total * 100)
    activity_score = _today_activity_score(start, now)
    return {
        "metrics": {
            "battery": battery,
            "food_count": food_count,
            "sleep_pct": sleep_pct,
            "play_pct": play_pct,
            "activity_score": activity_score,
        },
        "timeline": segments or [{"type": "idle", "pct": 100}],
        "event_count": len(events),
    }
