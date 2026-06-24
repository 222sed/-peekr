from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import analyzer
import state
import time
import json
import io
import numpy as np
from PIL import Image

app = FastAPI(title="Peekr Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_feeding_zone(raw_zone: str | None) -> dict | None:
    if not raw_zone:
        return None

    try:
        zone = json.loads(raw_zone)
        values = {key: float(zone[key]) for key in ("x", "y", "width", "height")}
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid feeding_zone")

    x, y = values["x"], values["y"]
    width, height = values["width"], values["height"]
    if (
        x < 0 or y < 0 or width <= 0 or height <= 0
        or x + width > 1 or y + height > 1
    ):
        raise HTTPException(status_code=400, detail="feeding_zone must use 0-1 coordinates")
    return values


def _parse_optional_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid numeric metadata")


def _parse_optional_int(value: str | None) -> int | None:
    parsed = _parse_optional_float(value)
    if parsed is None:
        return None
    return int(parsed)


@app.post("/api/frame")
async def receive_frame(
    file: UploadFile = File(...),
    feeding_zone: str | None = Form(default=None),
    device_id: str = Form(default=""),
    captured_at: str | None = Form(default=None),
    battery_level: str | None = Form(default=None),
    is_charging: str = Form(default="false"),
):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Expected an image file")
    state.update_frame_info(
        device_id=device_id,
        captured_at=_parse_optional_float(captured_at),
        battery_level=_parse_optional_int(battery_level),
        is_charging=is_charging.lower() in {"1", "true", "yes", "on"},
    )
    img_bytes = await file.read()
    zone = _parse_feeding_zone(feeding_zone)
    calibrations = state.get_food_calibrations(device_id)
    food_calibrated = "empty" in calibrations and "full" in calibrations
    state.set_food_remaining(
        state._store.get("food_remaining") if food_calibrated else None,
        food_calibrated,
    )
    result = analyzer.analyze(
        img_bytes,
        feeding_zone=zone,
        food_calibrations=calibrations,
    )
    print(f"[frame] state={result['state']}  motion={result.get('motion')}  compact={result.get('compactness')}")
    return result


@app.post("/api/food-calibration")
async def save_food_calibration(
    file: UploadFile = File(...),
    feeding_zone: str = Form(...),
    device_id: str = Form(...),
    level: str = Form(...),
):
    if level not in {"empty", "full"}:
        raise HTTPException(status_code=400, detail="level must be empty or full")
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Expected an image file")
    zone = _parse_feeding_zone(feeding_zone)
    img_bytes = await file.read()
    img_np = np.array(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
    signature = analyzer.food_signature(img_np, zone)
    state.save_food_calibration(device_id, level, signature)
    calibrations = state.get_food_calibrations(device_id)
    calibrated = "empty" in calibrations and "full" in calibrations
    state.set_food_remaining(state._store.get("food_remaining"), calibrated)
    return {"ok": True, "level": level, "calibrated": calibrated}


@app.get("/api/status")
def get_status():
    return state.get_dashboard()


@app.get("/api/today")
def get_today():
    return state.get_today_summary()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/stream")
def stream_status():
    last_state = None

    def generate():
        nonlocal last_state
        while True:
            current = state.get_state()
            if current != last_state:
                last_state = current.copy()
                yield f"data: {json.dumps(current)}\n\n"
            time.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream")
