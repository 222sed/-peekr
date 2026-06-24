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
FEEDING_CONFIRM_SECONDS = 15
FEEDING_END_GRACE_SECONDS = 20

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
    "feeding_candidate_started_at": None,
    "active_feeding_event_id": None,
    "active_feeding_started_at": None,
    "last_food_seen_at": None,
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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS feeding_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at REAL NOT NULL,
            ended_at REAL,
            duration_seconds REAL,
            confirmed INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_feeding_events_started_at ON feeding_events(started_at)"
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


def _create_feeding_event(started_at: float) -> int:
    connection = _connect_db()
    try:
        cursor = connection.execute(
            "INSERT INTO feeding_events(started_at, confirmed) VALUES (?, 1)",
            (started_at,),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def _finish_feeding_event(event_id: int, ended_at: float) -> None:
    connection = _connect_db()
    try:
        row = connection.execute(
            "SELECT started_at FROM feeding_events WHERE id = ? AND ended_at IS NULL",
            (event_id,),
        ).fetchone()
        if not row:
            return
        started_at = float(row[0])
        duration = max(0.0, ended_at - started_at)
        connection.execute(
            """
            UPDATE feeding_events
            SET ended_at = ?, duration_seconds = ?
            WHERE id = ? AND ended_at IS NULL
            """,
            (ended_at, duration, event_id),
        )
        connection.commit()
    finally:
        connection.close()


def _load_feeding_events(start: float, end: float) -> list[dict]:
    connection = _connect_db()
    try:
        rows = connection.execute(
            """
            SELECT id, started_at, ended_at, duration_seconds
            FROM feeding_events
            WHERE started_at >= ? AND started_at <= ?
            ORDER BY started_at
            """,
            (start, end),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "id": int(row[0]),
            "started_at": float(row[1]),
            "ended_at": None if row[2] is None else float(row[2]),
            "duration_seconds": None if row[3] is None else float(row[3]),
        }
        for row in rows
    ]


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


def get_feeding_feedback(
    zone_configured: bool,
    cat_detected: bool,
    in_zone: bool,
    zone_frames: int = 0,
) -> dict:
    with _lock:
        now = time.time()
        candidate_started_at = _store.get("feeding_candidate_started_at")
        active_event_id = _store.get("active_feeding_event_id")
        active_started_at = _store.get("active_feeding_started_at")

        candidate_seconds = (
            max(0.0, now - float(candidate_started_at))
            if candidate_started_at
            else 0.0
        )
        active_seconds = (
            max(0.0, now - float(active_started_at))
            if active_started_at
            else 0.0
        )
        remaining_seconds = max(0.0, FEEDING_CONFIRM_SECONDS - candidate_seconds)

        if not zone_configured:
            status = "zone_missing"
        elif not cat_detected:
            status = "cat_missing"
        elif active_event_id:
            status = "confirmed"
        elif in_zone:
            status = "candidate"
        else:
            status = "outside"

        return {
            "zone_set": bool(zone_configured),
            "cat_detected": bool(cat_detected),
            "in_zone": bool(in_zone),
            "zone_frames": int(zone_frames or 0),
            "candidate_seconds": round(candidate_seconds, 1),
            "confirm_seconds": FEEDING_CONFIRM_SECONDS,
            "remaining_seconds": round(remaining_seconds, 1),
            "confirmed": bool(active_event_id),
            "active": bool(active_event_id),
            "active_seconds": round(active_seconds, 1),
            "status": status,
        }


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


def _feeding_summary(start: float, end: float, now: float) -> dict:
    events = _load_feeding_events(start, end)
    active_event_id = _store.get("active_feeding_event_id")
    active_started_at = _store.get("active_feeding_started_at")

    normalized = []
    for event in events:
        ended_at = event["ended_at"]
        duration = event["duration_seconds"]
        is_active = active_event_id == event["id"] and ended_at is None
        if is_active:
            ended_at = None
            duration = max(0.0, now - float(event["started_at"]))
        normalized.append({
            "id": event["id"],
            "started_at": event["started_at"],
            "ended_at": ended_at,
            "duration_seconds": round(float(duration or 0)),
            "active": bool(is_active),
        })

    if active_event_id and active_started_at and not any(item["id"] == active_event_id for item in normalized):
        normalized.append({
            "id": int(active_event_id),
            "started_at": float(active_started_at),
            "ended_at": None,
            "duration_seconds": round(max(0.0, now - float(active_started_at))),
            "active": True,
        })

    normalized.sort(key=lambda item: item["started_at"])
    latest = normalized[-1] if normalized else None
    total_duration = round(sum(float(item["duration_seconds"] or 0) for item in normalized))
    return {
        "count": len(normalized),
        "latest": latest,
        "active": next((item for item in normalized if item["active"]), None),
        "total_duration_seconds": total_duration,
        "events": normalized[-6:],
    }


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
        _update_feeding_state_machine(smoothed, now)
        return smoothed


def _update_feeding_state_machine(current_state: str, now: float) -> None:
    if current_state == "food":
        _store["last_food_seen_at"] = now
        if _store.get("active_feeding_event_id"):
            return
        candidate_started_at = _store.get("feeding_candidate_started_at")
        if candidate_started_at is None:
            _store["feeding_candidate_started_at"] = now
            return
        if now - float(candidate_started_at) >= FEEDING_CONFIRM_SECONDS:
            event_id = _create_feeding_event(float(candidate_started_at))
            _store["active_feeding_event_id"] = event_id
            _store["active_feeding_started_at"] = float(candidate_started_at)
        return

    candidate_started_at = _store.get("feeding_candidate_started_at")
    active_event_id = _store.get("active_feeding_event_id")
    last_food_seen_at = _store.get("last_food_seen_at")

    if active_event_id:
        if last_food_seen_at and now - float(last_food_seen_at) >= FEEDING_END_GRACE_SECONDS:
            _finish_feeding_event(int(active_event_id), float(last_food_seen_at))
            _store["active_feeding_event_id"] = None
            _store["active_feeding_started_at"] = None
            _store["feeding_candidate_started_at"] = None
            _store["last_food_seen_at"] = None
        return

    if candidate_started_at and last_food_seen_at and now - float(last_food_seen_at) >= FEEDING_END_GRACE_SECONDS:
        _store["feeding_candidate_started_at"] = None
        _store["last_food_seen_at"] = None


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
        if offline:
            _update_feeding_state_machine("unknown", now)
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

    tracked_seconds = sum(
        duration_by_state[name]
        for name in ("sleep", "play", "food", "dream")
    )
    stats_total = tracked_seconds if tracked_seconds > 0 else 1.0
    sleep_pct = round(duration_by_state["sleep"] / stats_total * 100)
    play_pct = round(duration_by_state["play"] / stats_total * 100)
    activity_score = _today_activity_score(start, now)
    feeding = _feeding_summary(start, now, now)
    return {
        "metrics": {
            "battery": battery,
            "food_count": feeding["count"],
            "sleep_pct": sleep_pct,
            "play_pct": play_pct,
            "activity_score": activity_score,
        },
        "timeline": segments or [{"type": "idle", "pct": 100}],
        "event_count": len(events),
        "feeding": feeding,
    }
