import io
import math
from typing import Optional
import numpy as np
from PIL import Image
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

# Rule thresholds
MOTION_PLAY = 30
MOTION_STILL = 5
COMPACT_CURL = 0.70
COMPACT_SIT = 0.60
STILL_FRAMES_SLEEP = 12
HEAD_DOWN_RATIO = 0.35  # nose_y > bbox_top + ratio*bbox_h → head is low (eating)
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


def _motion_score(curr_box: list, prev_box: Optional[list]) -> float:
    if prev_box is None:
        return 0.0
    cx1, cy1 = _center(prev_box)
    cx2, cy2 = _center(curr_box)
    return math.sqrt((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2)


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


def _classify(motion: float, compact: float, still_count: int,
              pose: dict) -> tuple[str, float]:
    # Fast motion → playing regardless of pose
    if motion > MOTION_PLAY:
        return "play", 0.9

    # Eating: head explicitly down (pose-based, more reliable than box heuristic)
    if pose.get("head_down") and motion < 20:
        return "food", 0.85

    # Sleep: long stillness + curled body
    if motion <= MOTION_STILL and still_count >= STILL_FRAMES_SLEEP and compact >= COMPACT_CURL:
        return "sleep", 0.95

    # Eating fallback (no pose): tall narrow box
    if not pose and compact < 0.5 and motion < 20:
        return "food", 0.70

    # Daydreaming: extended body span (stretched out) or moderate compactness
    body_span = pose.get("body_span", 0)
    if motion < 15 and (compact < COMPACT_SIT or body_span > 0.6):
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
        state.set_state("unknown", 0.0)
        state.set_prev_box(None)
        return state.get_state()

    confs = boxes.conf.cpu().numpy()
    best_idx = int(np.argmax(confs))
    box = boxes.xyxy[best_idx].cpu().numpy().tolist()

    prev_box = state.get_prev_box()
    motion = _motion_score(box, prev_box)
    compact = _compactness(box)

    still_count = state._store.get("still_count", 0)
    if motion <= MOTION_STILL:
        still_count += 1
    else:
        still_count = 0

    pose = _pose_features(img_np, box)

    raw_state, confidence = _classify(motion, compact, still_count, pose)
    state.set_state(raw_state, confidence)
    state.set_prev_box(box)
    state._store["still_count"] = still_count

    return {
        **state.get_state(),
        "box": box,
        "motion": round(motion, 2),
        "compactness": round(compact, 3),
        "still_count": still_count,
        "pose": {k: round(float(v), 3) if isinstance(v, (float, np.floating)) else bool(v)
                 for k, v in pose.items()},
    }
