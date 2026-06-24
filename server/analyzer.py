import base64
import io
import math
import statistics
from collections import deque
from typing import Optional
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import torch
from ultralytics import YOLO
import ultralytics.utils.torch_utils as torch_utils

import state

# torch 2.6+ changed weights_only default to True, which breaks ultralytics 8.2.x .pt files.
_orig_torch_load = torch.load

def _patched_torch_load(f, *args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_torch_load(f, *args, **kwargs)

torch.load = _patched_torch_load

_orig_get_cpu_info = torch_utils.get_cpu_info


def _safe_get_cpu_info() -> str:
    try:
        return _orig_get_cpu_info()
    except Exception:
        return "CPU"


torch_utils.get_cpu_info = _safe_get_cpu_info

_yolo_model: Optional[YOLO] = None
_pose_model = None  # rtmlib Animal, lazy-loaded

CAT_CLASS_ID = 15  # COCO class index for "cat"

# Keypoint indices (animal17 skeleton from rtmlib/apt36k)
KP_NOSE      = 2
KP_NECK      = 3
KP_ROOT_TAIL = 4

# Rule thresholds. Motion is normalised by the cat box diagonal, so these
# values work more consistently at different camera distances/resolutions.
MOTION_PLAY_RATIO = 0.10
MOTION_STILL_RATIO = 0.025
COMPACT_CURL = 0.70
COMPACT_SIT = 0.60
STILL_FRAMES_SLEEP = 8
HEAD_DOWN_RATIO = 0.42
FEEDING_ZONE_FRAMES_FOOD = 3
MISSED_FRAMES_UNKNOWN = 3
POSE_CONF_MIN = 0.3     # ignore keypoints below this confidence
MIN_BRIGHTNESS = 45.0
MAX_BRIGHTNESS = 225.0
MIN_CONTRAST = 22.0
MIN_SHARPNESS = 7.0
MIN_CAT_AREA_RATIO = 0.035
_food_remaining_history: deque = deque(maxlen=5)
_activity_history: deque = deque(maxlen=5)


def _image_quality(img_np: np.ndarray) -> dict:
    gray = (
        img_np[:, :, 0].astype(np.float32) * 0.299
        + img_np[:, :, 1].astype(np.float32) * 0.587
        + img_np[:, :, 2].astype(np.float32) * 0.114
    )
    brightness = float(gray.mean())
    contrast = float(gray.std())
    edge_x = np.abs(np.diff(gray, axis=1)).mean() if gray.shape[1] > 1 else 0.0
    edge_y = np.abs(np.diff(gray, axis=0)).mean() if gray.shape[0] > 1 else 0.0
    sharpness = float((edge_x + edge_y) / 2)

    warnings = []
    if brightness < MIN_BRIGHTNESS:
        warnings.append("too_dark")
    elif brightness > MAX_BRIGHTNESS:
        warnings.append("too_bright")
    if contrast < MIN_CONTRAST:
        warnings.append("low_contrast")
    if sharpness < MIN_SHARPNESS:
        warnings.append("blurry")

    return {
        "brightness": round(brightness, 1),
        "contrast": round(contrast, 1),
        "sharpness": round(sharpness, 1),
        "warnings": warnings,
    }


def _get_yolo() -> YOLO:
    global _yolo_model
    if _yolo_model is None:
        _yolo_model = YOLO("yolov8n.pt")
    return _yolo_model


def _get_pose():
    global _pose_model
    if _pose_model is None:
        from rtmlib import Animal
        # lightweight mode: yolox_tiny detector + vitpose-s pose model (~60 MB total)
        _pose_model = Animal(mode="lightweight", backend="onnxruntime", device="cpu")
    return _pose_model


def _center(box: list) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _compactness(box: list) -> float:
    w = box[2] - box[0]
    h = box[3] - box[1]
    if max(w, h) == 0:
        return 1.0
    return min(w, h) / max(w, h)


def _motion_score(curr_box: list, prev_box: Optional[list]) -> tuple[float, float]:
    if prev_box is None:
        return 0.0, 0.0
    cx1, cy1 = _center(prev_box)
    cx2, cy2 = _center(curr_box)
    pixels = math.sqrt((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2)

    prev_diag = math.hypot(prev_box[2] - prev_box[0], prev_box[3] - prev_box[1])
    curr_diag = math.hypot(curr_box[2] - curr_box[0], curr_box[3] - curr_box[1])
    reference_diag = max((prev_diag + curr_diag) / 2, 1.0)
    return pixels, pixels / reference_diag


def _activity_score(motion_ratio: float, pose: dict, previous_pose: dict) -> int:
    motion_component = min(max(motion_ratio / 0.18, 0.0), 1.0) * 75.0
    pose_changes = []
    if "nose_rel_y" in pose and "nose_rel_y" in previous_pose:
        pose_changes.append(
            min(abs(pose["nose_rel_y"] - previous_pose["nose_rel_y"]) / 0.25, 1.0)
        )
    if "body_span" in pose and "body_span" in previous_pose:
        pose_changes.append(
            min(abs(pose["body_span"] - previous_pose["body_span"]) / 0.20, 1.0)
        )
    pose_component = (statistics.mean(pose_changes) if pose_changes else 0.0) * 25.0
    raw_score = min(100.0, motion_component + pose_component)
    _activity_history.append(raw_score)
    return int(round(statistics.median(_activity_history)))


def _pose_features(img_np: np.ndarray, box: list) -> dict:
    """Run rtmlib Animal pose on the cropped cat region, return derived features."""
    try:
        pose = _get_pose()
        keypoints, scores = pose(img_np)  # shape: (N, 17, 2), (N, 17)
    except Exception as e:
        print(f"[pose] error: {e}")
        return {}

    if keypoints is None or len(keypoints) == 0:
        print("[pose] no keypoints detected")
        return {}

    # Pick the detection whose bbox center is closest to our YOLO box center
    cx, cy = _center(box)
    best_i, best_d = 0, float("inf")
    for i, kps in enumerate(keypoints):
        valid = scores[i] > POSE_CONF_MIN
        if not valid.any():
            continue
        kx = kps[valid, 0].mean()
        ky = kps[valid, 1].mean()
        d = math.sqrt((kx - cx) ** 2 + (ky - cy) ** 2)
        if d < best_d:
            best_d, best_i = d, i

    kps = keypoints[best_i]    # (17, 2)
    sc  = scores[best_i]       # (17,)

    feats = {}

    # Head-down: nose y position relative to bounding box
    if sc[KP_NOSE] >= POSE_CONF_MIN:
        bbox_h = box[3] - box[1]
        if bbox_h > 0:
            nose_rel = (kps[KP_NOSE][1] - box[1]) / bbox_h
            feats["nose_rel_y"] = float(nose_rel)
            feats["head_down"] = nose_rel > HEAD_DOWN_RATIO
        image_h, image_w = img_np.shape[:2]
        if image_w > 0 and image_h > 0:
            feats["nose_x"] = float(kps[KP_NOSE][0] / image_w)
            feats["nose_y"] = float(kps[KP_NOSE][1] / image_h)

    # Body span: distance from neck to tail root (normalised by bbox diagonal)
    if sc[KP_NECK] >= POSE_CONF_MIN and sc[KP_ROOT_TAIL] >= POSE_CONF_MIN:
        neck = kps[KP_NECK]
        tail = kps[KP_ROOT_TAIL]
        span = math.sqrt((neck[0] - tail[0]) ** 2 + (neck[1] - tail[1]) ** 2)
        bbox_diag = math.sqrt((box[2] - box[0]) ** 2 + (box[3] - box[1]) ** 2)
        if bbox_diag > 0:
            feats["body_span"] = float(span / bbox_diag)

    print(f"[pose] detected {len(keypoints)} animals, using index {best_i}, feats={feats}")
    return feats


def _point_in_zone(x: float, y: float, zone: Optional[dict]) -> bool:
    if not zone:
        return False
    return (
        zone["x"] <= x <= zone["x"] + zone["width"]
        and zone["y"] <= y <= zone["y"] + zone["height"]
    )


def _zone_crop(img_np: np.ndarray, zone: Optional[dict]) -> Optional[np.ndarray]:
    if not zone:
        return None
    height, width = img_np.shape[:2]
    x1 = max(0, min(width - 1, int(zone["x"] * width)))
    y1 = max(0, min(height - 1, int(zone["y"] * height)))
    x2 = max(x1 + 1, min(width, int((zone["x"] + zone["width"]) * width)))
    y2 = max(y1 + 1, min(height, int((zone["y"] + zone["height"]) * height)))
    crop = img_np[y1:y2, x1:x2]
    return crop if crop.size else None


def _food_measurement_zone(zone: Optional[dict]) -> Optional[dict]:
    if not zone:
        return None
    return {
        "x": zone["x"] + zone["width"] * 0.08,
        "y": zone["y"] + zone["height"] * 0.45,
        "width": zone["width"] * 0.84,
        "height": zone["height"] * 0.5,
    }


def food_signature(img_np: np.ndarray, zone: Optional[dict]) -> list[float]:
    crop = _zone_crop(img_np, _food_measurement_zone(zone))
    if crop is None:
        raise ValueError("feeding zone is required")
    sample = np.array(
        Image.fromarray(crop).resize((48, 48), Image.Resampling.BILINEAR),
        dtype=np.float32,
    ) / 255.0
    features = []
    for channel in range(3):
        values = sample[:, :, channel]
        histogram, _ = np.histogram(values, bins=8, range=(0.0, 1.0), density=True)
        histogram = histogram / max(float(histogram.sum()), 1.0)
        features.extend(histogram.tolist())
        features.extend([float(values.mean()), float(values.std())])
    return [round(float(value), 6) for value in features]


def _box_zone_overlap(box: list, zone: Optional[dict], image_width: int, image_height: int) -> float:
    if not zone:
        return 0.0
    zx1 = zone["x"] * image_width
    zy1 = zone["y"] * image_height
    zx2 = (zone["x"] + zone["width"]) * image_width
    zy2 = (zone["y"] + zone["height"]) * image_height
    ix1, iy1 = max(box[0], zx1), max(box[1], zy1)
    ix2, iy2 = min(box[2], zx2), min(box[3], zy2)
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    zone_area = max((zx2 - zx1) * (zy2 - zy1), 1.0)
    return intersection / zone_area


def estimate_food_remaining(
    img_np: np.ndarray,
    zone: Optional[dict],
    calibrations: dict,
    cat_box: Optional[list] = None,
) -> Optional[int]:
    if "empty" not in calibrations or "full" not in calibrations or not zone:
        return None
    measurement_zone = _food_measurement_zone(zone)
    if (
        cat_box
        and _box_zone_overlap(
            cat_box, measurement_zone, img_np.shape[1], img_np.shape[0]
        ) > 0.18
    ):
        return None
    current = np.array(food_signature(img_np, zone), dtype=np.float32)
    empty = np.array(calibrations["empty"], dtype=np.float32)
    full = np.array(calibrations["full"], dtype=np.float32)
    axis = full - empty
    denominator = float(np.dot(axis, axis))
    if denominator < 1e-8:
        return None
    ratio = float(np.dot(current - empty, axis) / denominator)
    percent = int(round(max(0.0, min(1.0, ratio)) * 100))
    _food_remaining_history.append(percent)
    return int(round(statistics.median(_food_remaining_history)))


def _classify(motion: float, stable_motion: float, compact: float,
              still_count: int, feeding_zone_count: int,
              pose: dict) -> tuple[str, float]:
    # Fast relative movement over either of the latest two frames.
    if motion >= MOTION_PLAY_RATIO:
        return "play", 0.9

    # Food requires the nose to remain inside the user-calibrated feeding zone.
    if (
        feeding_zone_count >= FEEDING_ZONE_FRAMES_FOOD
        and stable_motion < MOTION_PLAY_RATIO
    ):
        return "food", 0.92

    body_span = pose.get("body_span")
    curled = compact >= COMPACT_CURL or (
        body_span is not None and body_span < 0.38
    )

    # Sleep: sustained stillness plus a compact/curled body.
    if still_count >= STILL_FRAMES_SLEEP and curled:
        return "sleep", 0.95

    # Awake but not moving enough to count as play.
    if stable_motion < MOTION_PLAY_RATIO:
        return "dream", 0.80

    prev = state.get_state()["state"]
    return (prev if prev != "unknown" else "dream"), 0.50


def analyze(
    img_bytes: bytes,
    feeding_zone: Optional[dict] = None,
    food_calibrations: Optional[dict] = None,
) -> dict:
    model = _get_yolo()
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img_np = np.array(img)
    quality = _image_quality(img_np)

    results = model(img_np, classes=[CAT_CLASS_ID], verbose=False)
    boxes = results[0].boxes

    if boxes is None or len(boxes) == 0:
        food_remaining = estimate_food_remaining(
            img_np, feeding_zone, food_calibrations or {}
        )
        if food_remaining is not None:
            state.set_food_remaining(food_remaining, True)
        missed_count = state._store.get("missed_count", 0) + 1
        state._store["missed_count"] = missed_count
        # Brief detector misses are common. Keep the previous state for two
        # frames instead of making the UI flicker to unknown immediately.
        if missed_count >= MISSED_FRAMES_UNKNOWN:
            state.set_state("unknown", 0.0)
            state.set_prev_box(None)
            state._store["still_count"] = 0
            state._store["motion_history"] = []
            state._store["feeding_zone_count"] = 0
            state._store["previous_pose"] = {}
            _activity_history.clear()
        return {
            **state.get_state(),
            "cat_detected": False,
            "quality": quality,
            "food_remaining": food_remaining,
            "feeding": state.get_feeding_feedback(
                zone_configured=feeding_zone is not None,
                cat_detected=False,
                in_zone=False,
                zone_frames=0,
            ),
        }

    state._store["missed_count"] = 0
    confs = boxes.conf.cpu().numpy()
    best_idx = int(np.argmax(confs))
    box = boxes.xyxy[best_idx].cpu().numpy().tolist()
    detection_confidence = float(confs[best_idx])
    food_remaining = estimate_food_remaining(
        img_np, feeding_zone, food_calibrations or {}, box
    )
    if food_remaining is not None:
        state.set_food_remaining(food_remaining, True)
    image_area = max(img.width * img.height, 1)
    cat_area = max((box[2] - box[0]) * (box[3] - box[1]), 0)
    cat_area_ratio = float(cat_area / image_area)
    if cat_area_ratio < MIN_CAT_AREA_RATIO:
        quality["warnings"].append("cat_too_small")

    prev_box = state.get_prev_box()
    motion_pixels, motion_ratio = _motion_score(box, prev_box)
    compact = _compactness(box)

    motion_history = state._store.get("motion_history", [])
    motion_history.append(motion_ratio)
    motion_history = motion_history[-3:]
    state._store["motion_history"] = motion_history
    recent_motion = max(motion_history[-2:])
    stable_motion = statistics.median(motion_history)

    still_count = state._store.get("still_count", 0)
    if stable_motion <= MOTION_STILL_RATIO:
        still_count += 1
    else:
        still_count = 0

    pose = _pose_features(img_np, box)
    previous_pose = state._store.get("previous_pose", {})
    activity_score = _activity_score(motion_ratio, pose, previous_pose)
    state._store["previous_pose"] = pose
    state.record_activity(activity_score)
    nose_in_feeding_zone = (
        "nose_x" in pose
        and "nose_y" in pose
        and _point_in_zone(pose["nose_x"], pose["nose_y"], feeding_zone)
    )

    zone_signature = (
        feeding_zone["x"],
        feeding_zone["y"],
        feeding_zone["width"],
        feeding_zone["height"],
    ) if feeding_zone else None
    if state._store.get("feeding_zone_signature") != zone_signature:
        state._store["feeding_zone_count"] = 0
        state._store["feeding_zone_signature"] = zone_signature

    feeding_zone_count = state._store.get("feeding_zone_count", 0)
    if nose_in_feeding_zone and stable_motion < MOTION_PLAY_RATIO:
        feeding_zone_count += 1
    else:
        feeding_zone_count = 0

    raw_state, confidence = _classify(
        recent_motion,
        stable_motion,
        compact,
        still_count,
        feeding_zone_count,
        pose,
    )
    print(
        f"[debug] detect={detection_confidence:.2f} "
        f"motion={motion_ratio:.3f} smooth={stable_motion:.3f} "
        f"compact={compact:.3f} still={still_count} "
        f"feeding_zone={feeding_zone_count} nose_in_zone={nose_in_feeding_zone} "
        f"activity={activity_score} pose={pose} -> {raw_state}"
    )
    state.set_state(raw_state, confidence)
    state.set_prev_box(box)
    state._store["still_count"] = still_count
    state._store["feeding_zone_count"] = feeding_zone_count
    feeding_feedback = state.get_feeding_feedback(
        zone_configured=feeding_zone is not None,
        cat_detected=True,
        in_zone=nose_in_feeding_zone,
        zone_frames=feeding_zone_count,
    )

    preview_b64 = _draw_box(img, box, raw_state, confidence)

    return {
        **state.get_state(),
        "box": box,
        "cat_detected": True,
        "cat_area_ratio": round(cat_area_ratio, 4),
        "detection_confidence": round(detection_confidence, 3),
        "motion": round(motion_ratio, 4),
        "motion_pixels": round(motion_pixels, 2),
        "motion_smooth": round(stable_motion, 4),
        "compactness": round(compact, 3),
        "still_count": still_count,
        "feeding_zone_configured": feeding_zone is not None,
        "feeding_zone_count": feeding_zone_count,
        "nose_in_feeding_zone": nose_in_feeding_zone,
        "feeding": feeding_feedback,
        "pose": {k: round(float(v), 3) if isinstance(v, (float, np.floating)) else bool(v)
                 for k, v in pose.items()},
        "activity_score": activity_score,
        "quality": quality,
        "food_remaining": food_remaining,
        "preview": preview_b64,
    }


def _draw_box(
    img: Image.Image,
    box: list,
    label: str,
    conf: float,
) -> str:
    STATE_COLORS = {
        "sleep": "#6C8EBF",
        "play":  "#F4A436",
        "food":  "#82B366",
        "dream": "#9673A6",
    }
    color = STATE_COLORS.get(label, "#AAAAAA")

    draw = ImageDraw.Draw(img)
    x1, y1, x2, y2 = [int(v) for v in box]
    lw = max(3, int(min(img.width, img.height) * 0.005))
    draw.rectangle([x1, y1, x2, y2], outline=color, width=lw)

    text = f"{label} {conf:.0%}"
    font_size = max(16, int(min(img.width, img.height) * 0.04))
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    tx, ty = x1 + 4, max(0, y1 - font_size - 4)
    bbox = draw.textbbox((tx, ty), text, font=font)
    draw.rectangle(bbox, fill=color)
    draw.text((tx, ty), text, fill="white", font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
