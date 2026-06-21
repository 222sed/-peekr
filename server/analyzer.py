import base64
import io
import math
import statistics
from typing import Optional
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import torch
from ultralytics import YOLO

import state

# torch 2.6+ changed weights_only default to True, which breaks ultralytics 8.2.x .pt files.
_orig_torch_load = torch.load

def _patched_torch_load(f, *args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_torch_load(f, *args, **kwargs)

torch.load = _patched_torch_load

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
HEAD_DOWN_FRAMES_FOOD = 2
MISSED_FRAMES_UNKNOWN = 3
POSE_CONF_MIN = 0.3     # ignore keypoints below this confidence


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


def _classify(motion: float, stable_motion: float, compact: float,
              still_count: int, head_down_count: int,
              pose: dict) -> tuple[str, float]:
    # Fast relative movement over either of the latest two frames.
    if motion >= MOTION_PLAY_RATIO:
        return "play", 0.9

    # Require a low head for more than one frame to avoid food false positives.
    if (
        head_down_count >= HEAD_DOWN_FRAMES_FOOD
        and stable_motion < MOTION_PLAY_RATIO
    ):
        return "food", 0.85

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


def analyze(img_bytes: bytes) -> dict:
    model = _get_yolo()
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img_np = np.array(img)

    results = model(img_np, classes=[CAT_CLASS_ID], verbose=False)
    boxes = results[0].boxes

    if boxes is None or len(boxes) == 0:
        missed_count = state._store.get("missed_count", 0) + 1
        state._store["missed_count"] = missed_count
        # Brief detector misses are common. Keep the previous state for two
        # frames instead of making the UI flicker to unknown immediately.
        if missed_count >= MISSED_FRAMES_UNKNOWN:
            state.set_state("unknown", 0.0)
            state.set_prev_box(None)
            state._store["still_count"] = 0
            state._store["motion_history"] = []
        return state.get_state()

    state._store["missed_count"] = 0
    confs = boxes.conf.cpu().numpy()
    best_idx = int(np.argmax(confs))
    box = boxes.xyxy[best_idx].cpu().numpy().tolist()
    detection_confidence = float(confs[best_idx])

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
    head_down_count = state._store.get("head_down_count", 0)
    if pose.get("head_down") and stable_motion < MOTION_PLAY_RATIO:
        head_down_count += 1
    else:
        head_down_count = 0

    raw_state, confidence = _classify(
        recent_motion,
        stable_motion,
        compact,
        still_count,
        head_down_count,
        pose,
    )
    print(
        f"[debug] detect={detection_confidence:.2f} "
        f"motion={motion_ratio:.3f} smooth={stable_motion:.3f} "
        f"compact={compact:.3f} still={still_count} "
        f"head_down={head_down_count} pose={pose} -> {raw_state}"
    )
    state.set_state(raw_state, confidence)
    state.set_prev_box(box)
    state._store["still_count"] = still_count
    state._store["head_down_count"] = head_down_count

    preview_b64 = _draw_box(img, box, raw_state, confidence)

    return {
        **state.get_state(),
        "box": box,
        "detection_confidence": round(detection_confidence, 3),
        "motion": round(motion_ratio, 4),
        "motion_pixels": round(motion_pixels, 2),
        "motion_smooth": round(stable_motion, 4),
        "compactness": round(compact, 3),
        "still_count": still_count,
        "head_down_count": head_down_count,
        "pose": {k: round(float(v), 3) if isinstance(v, (float, np.floating)) else bool(v)
                 for k, v in pose.items()},
        "preview": preview_b64,
    }


def _draw_box(img: Image.Image, box: list, label: str, conf: float) -> str:
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
