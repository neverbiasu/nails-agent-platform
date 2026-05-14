"""
Hand shape, skin tone, and undertone analysis.

Uses MediaPipe Hands for landmark detection + rule-based classification.
Originally lifted from demo_v1/src/hand_analysis.py; rule JSON paths now
resolve to the canonical seed dir at the repo root (or NAILS_DATA_DIR_V2).
"""

from __future__ import annotations

import json
import math
import os
from io import BytesIO
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp")

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image, ImageOps


# Repo root: nails_agent/services/hand_analyzer.py → parents[2] is the repo.
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("NAILS_DATA_DIR_V2", str(ROOT_DIR / "data")))

# Labels live in nails_agent.services.labels so they can be imported without
# pulling MediaPipe; re-exported here for backward compat with demo_v1.
from nails_agent.services.labels import (  # noqa: E402
    HAND_SHAPE_LABELS,
    SKIN_TONE_LABELS,
    UNDERTONE_LABELS,
)

HAND_SHAPE_CENTERS = {
    "slender_long": {
        "finger_to_palm_ratio": 1.42,
        "palm_width_ratio": 0.78,
        "hand_aspect_ratio": 2.55,
    },
    "short_wide": {
        "finger_to_palm_ratio": 1.00,
        "palm_width_ratio": 0.90,
        "hand_aspect_ratio": 2.10,
    },
    "square_palm": {
        "finger_to_palm_ratio": 1.12,
        "palm_width_ratio": 0.98,
        "hand_aspect_ratio": 2.05,
    },
    "narrow_palm": {
        "finger_to_palm_ratio": 1.20,
        "palm_width_ratio": 0.68,
        "hand_aspect_ratio": 2.60,
    },
}

FINGER_CHAINS = {
    "index": [5, 6, 7, 8],
    "middle": [9, 10, 11, 12],
    "ring": [13, 14, 15, 16],
    "pinky": [17, 18, 19, 20],
}


@lru_cache(maxsize=None)
def _read_rule_file(filename: str) -> list[dict[str, Any]]:
    path = DATA_DIR / filename
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _sorted_rules(filename: str, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rules = _read_rule_file(filename) or fallback
    return sorted(rules, key=lambda item: int(item.get("priority", 0)), reverse=True)


def _metric_value(metrics: dict[str, Any], key: str) -> float:
    if key == "ycrcb_cr_minus_cb":
        return float(metrics.get("ycrcb_cr", 0.0)) - float(metrics.get("ycrcb_cb", 0.0))
    if key == "ycrcb_cb_minus_cr":
        return float(metrics.get("ycrcb_cb", 0.0)) - float(metrics.get("ycrcb_cr", 0.0))
    return float(metrics.get(key, 0.0))


def _matches_rule(metrics: dict[str, Any], rule: dict[str, Any]) -> bool:
    if rule.get("default"):
        return True
    if "any_rules" in rule:
        if not any(_matches_rule(metrics, child_rule) for child_rule in rule["any_rules"]):
            return False
    if "all_rules" in rule:
        if not all(_matches_rule(metrics, child_rule) for child_rule in rule["all_rules"]):
            return False

    suffixes = [
        ("_max_exclusive", lambda value, target: value < target),
        ("_min_exclusive", lambda value, target: value > target),
        ("_min", lambda value, target: value >= target),
        ("_max", lambda value, target: value <= target),
        ("_lt", lambda value, target: value < target),
        ("_gt", lambda value, target: value > target),
    ]
    for raw_key, target in rule.items():
        if raw_key in {"default", "any_rules", "all_rules"}:
            continue
        matched_suffix = False
        for suffix, comparator in suffixes:
            if raw_key.endswith(suffix):
                metric_key = raw_key[: -len(suffix)]
                if not comparator(_metric_value(metrics, metric_key), float(target)):
                    return False
                matched_suffix = True
                break
        if not matched_suffix and _metric_value(metrics, raw_key) != float(target):
            return False
    return True


def _fallback_hand_shape_rules() -> list[dict[str, Any]]:
    return [
        {
            "hand_shape": "unknown",
            "feature_rules": {"landmark_visibility_score_lt": 0.70},
            "center": None,
            "confidence": 0.0,
            "reason": "手部关键点不完整",
            "priority": 100,
        },
        {
            "hand_shape": "square_palm",
            "feature_rules": {"landmark_visibility_score_min": 0.70, "palm_width_ratio_min": 0.95},
            "center": HAND_SHAPE_CENTERS["square_palm"],
            "confidence": 0.84,
            "reason": "掌宽比例较高，接近方掌",
            "priority": 90,
        },
        {
            "hand_shape": "slender_long",
            "feature_rules": {
                "landmark_visibility_score_min": 0.70,
                "finger_to_palm_ratio_min": 1.35,
                "palm_width_ratio_max": 0.82,
            },
            "center": HAND_SHAPE_CENTERS["slender_long"],
            "confidence": 0.88,
            "reason": "手指相对掌长更长，掌形偏窄",
            "priority": 80,
        },
        {
            "hand_shape": "narrow_palm",
            "feature_rules": {"landmark_visibility_score_min": 0.70, "palm_width_ratio_max": 0.72},
            "center": HAND_SHAPE_CENTERS["narrow_palm"],
            "confidence": 0.84,
            "reason": "掌宽比例较低，整体偏窄",
            "priority": 70,
        },
        {
            "hand_shape": "short_wide",
            "feature_rules": {
                "landmark_visibility_score_min": 0.70,
                "finger_to_palm_ratio_max": 1.05,
                "palm_width_ratio_min": 0.84,
            },
            "center": HAND_SHAPE_CENTERS["short_wide"],
            "confidence": 0.84,
            "reason": "手指相对较短，掌宽比例偏高",
            "priority": 60,
        },
    ]


def _fallback_skin_tone_rules() -> list[dict[str, Any]]:
    return [
        {
            "skin_tone": "unknown",
            "feature_rules": {"any_rules": [{"sample_stability_lt": 0.35}, {"sample_size_lt": 30}]},
            "confidence_cap": 0.0,
            "reason": "肤色采样区域不稳定",
            "priority": 100,
        },
        {
            "skin_tone": "cool_fair",
            "feature_rules": {
                "sample_stability_min": 0.35,
                "sample_size_min": 30,
                "lab_l_min": 78,
                "lab_b_lt": 13,
            },
            "confidence_cap": 0.90,
            "reason": "高明度且黄调较低",
            "priority": 90,
        },
        {
            "skin_tone": "warm_fair",
            "feature_rules": {
                "sample_stability_min": 0.35,
                "sample_size_min": 30,
                "lab_l_min": 76,
                "lab_b_min": 13,
            },
            "confidence_cap": 0.90,
            "reason": "高明度且黄调较明显",
            "priority": 80,
        },
        {
            "skin_tone": "natural",
            "feature_rules": {
                "sample_stability_min": 0.35,
                "sample_size_min": 30,
                "lab_l_min": 62,
                "lab_l_lt": 76,
                "lab_b_lt": 18,
            },
            "confidence_cap": 0.88,
            "reason": "中等明度，黄调不过强",
            "priority": 70,
        },
        {
            "skin_tone": "warm_yellow",
            "feature_rules": {
                "sample_stability_min": 0.35,
                "sample_size_min": 30,
                "lab_l_min": 62,
                "lab_l_lt": 76,
                "lab_b_min": 18,
            },
            "confidence_cap": 0.88,
            "reason": "中等明度且黄调明显",
            "priority": 60,
        },
        {
            "skin_tone": "wheat",
            "feature_rules": {
                "sample_stability_min": 0.35,
                "sample_size_min": 30,
                "lab_l_min": 48,
                "lab_l_lt": 62,
            },
            "confidence_cap": 0.86,
            "reason": "明度较低，接近小麦肤色",
            "priority": 50,
        },
        {
            "skin_tone": "deep",
            "feature_rules": {"sample_stability_min": 0.35, "sample_size_min": 30, "lab_l_lt": 48},
            "confidence_cap": 0.86,
            "reason": "明度较低，接近深肤色",
            "priority": 40,
        },
    ]


def _fallback_undertone_rules() -> list[dict[str, Any]]:
    return [
        {
            "undertone": "unknown",
            "feature_rules": {"any_rules": [{"sample_stability_lt": 0.35}, {"sample_size_lt": 30}]},
            "confidence_cap": 0.0,
            "reason": "肤色采样区域不稳定",
            "priority": 100,
        },
        {
            "undertone": "neutral",
            "feature_rules": {
                "sample_stability_min": 0.35,
                "sample_size_min": 30,
                "hsv_s_lt": 0.12,
                "lab_b_min": 10,
                "lab_b_max": 18,
            },
            "confidence_cap": 0.86,
            "reason": "饱和度较低，冷暖不明显",
            "priority": 90,
        },
        {
            "undertone": "warm",
            "feature_rules": {
                "sample_stability_min": 0.35,
                "sample_size_min": 30,
                "any_rules": [{"lab_b_min": 18}, {"ycrcb_cr_minus_cb_min": 12}],
            },
            "confidence_cap": 0.88,
            "reason": "黄调或红色色度更明显",
            "priority": 80,
        },
        {
            "undertone": "cool",
            "feature_rules": {
                "sample_stability_min": 0.35,
                "sample_size_min": 30,
                "any_rules": [{"lab_b_max": 10}, {"ycrcb_cb_minus_cr_min": 8}],
            },
            "confidence_cap": 0.88,
            "reason": "蓝调/冷调特征更明显",
            "priority": 70,
        },
        {
            "undertone": "neutral",
            "feature_rules": {"default": True},
            "confidence_cap": 0.78,
            "reason": "冷暖特征接近，归为中性",
            "priority": 1,
        },
    ]


def _hand_shape_rules() -> list[dict[str, Any]]:
    return _sorted_rules("hand_shape_definitions.json", _fallback_hand_shape_rules())


def _skin_tone_rules() -> list[dict[str, Any]]:
    return _sorted_rules("skin_tone_definitions.json", _fallback_skin_tone_rules())


def _undertone_rules() -> list[dict[str, Any]]:
    return _sorted_rules("undertone_definitions.json", _fallback_undertone_rules())


def _hand_shape_centers() -> dict[str, dict[str, float]]:
    centers: dict[str, dict[str, float]] = {}
    for rule in _hand_shape_rules():
        center = rule.get("center")
        shape = rule.get("hand_shape")
        if shape and center:
            centers[shape] = center
    return centers or HAND_SHAPE_CENTERS


@dataclass
class HandDetection:
    points: np.ndarray
    handedness: str
    score: float


def load_image(source: str | Path | bytes) -> Image.Image:
    if isinstance(source, bytes):
        image = Image.open(BytesIO(source))
    else:
        image = Image.open(source)
    return ImageOps.exif_transpose(image).convert("RGB")


def _distance(points: np.ndarray, a: int, b: int) -> float:
    return float(np.linalg.norm(points[a] - points[b]))


def _chain_length(points: np.ndarray, chain: list[int]) -> float:
    return sum(_distance(points, chain[i], chain[i + 1]) for i in range(len(chain) - 1))


def _detect_hand(rgb: np.ndarray) -> HandDetection | None:
    mp_hands = mp.solutions.hands
    with mp_hands.Hands(
        static_image_mode=True,
        max_num_hands=1,
        model_complexity=1,
        min_detection_confidence=0.45,
    ) as hands:
        result = hands.process(rgb)

    if not result.multi_hand_landmarks:
        return None

    h, w = rgb.shape[:2]
    landmarks = result.multi_hand_landmarks[0].landmark
    points = np.array([[lm.x * w, lm.y * h] for lm in landmarks], dtype=np.float32)
    in_frame = np.mean(
        (points[:, 0] >= -0.05 * w)
        & (points[:, 0] <= 1.05 * w)
        & (points[:, 1] >= -0.05 * h)
        & (points[:, 1] <= 1.05 * h)
    )
    handedness = "unknown"
    score = float(in_frame)
    if result.multi_handedness:
        category = result.multi_handedness[0].classification[0]
        handedness = category.label
        score = min(score, float(category.score))
    return HandDetection(points=points, handedness=handedness, score=score)


def _hand_metrics(points: np.ndarray, visibility_score: float) -> dict[str, float]:
    palm_width = _distance(points, 5, 17)
    palm_length = _distance(points, 0, 9)
    middle_tip_height = _distance(points, 0, 12)
    finger_lengths = {name: _chain_length(points, chain) for name, chain in FINGER_CHAINS.items()}
    avg_finger_length = float(np.mean(list(finger_lengths.values())))
    finger_variance = float(np.std(list(finger_lengths.values())) / max(avg_finger_length, 1e-6))

    return {
        "palm_width": palm_width,
        "palm_length": palm_length,
        "avg_finger_length": avg_finger_length,
        "finger_to_palm_ratio": avg_finger_length / max(palm_length, 1e-6),
        "palm_width_ratio": palm_width / max(palm_length, 1e-6),
        "hand_aspect_ratio": middle_tip_height / max(palm_width, 1e-6),
        "finger_length_variance": finger_variance,
        "landmark_visibility_score": visibility_score,
    }


def _nearest_hand_shape(metrics: dict[str, float]) -> tuple[str, float]:
    weights = {
        "finger_to_palm_ratio": 1.2,
        "palm_width_ratio": 1.4,
        "hand_aspect_ratio": 0.6,
    }
    best_shape = "unknown"
    best_distance = math.inf
    for shape, center in _hand_shape_centers().items():
        distance = 0.0
        for key, weight in weights.items():
            distance += ((metrics[key] - center[key]) * weight) ** 2
        distance = math.sqrt(distance)
        if distance < best_distance:
            best_shape = shape
            best_distance = distance
    confidence = max(0.52, min(0.92, 1.0 - best_distance / 1.2))
    return best_shape, confidence


def classify_hand_shape(metrics: dict[str, float]) -> tuple[str, float, str]:
    for rule in _hand_shape_rules():
        if _matches_rule(metrics, rule.get("feature_rules", {})):
            shape = rule.get("hand_shape", "unknown")
            confidence = float(rule.get("confidence", 0.0))
            reason = rule.get("reason", "按外部规则命中手型")
            return shape, confidence, reason

    shape, confidence = _nearest_hand_shape(metrics)
    return shape, confidence, "按关键比例距离最近的手型中心归类"


def _sample_skin_pixels(rgb: np.ndarray, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h, w = rgb.shape[:2]
    palm_center = np.mean(points[[0, 5, 9, 13, 17]], axis=0)
    palm_width = _distance(points, 5, 17)
    radius_x = max(12.0, palm_width * 0.34)
    radius_y = max(12.0, palm_width * 0.42)

    yy, xx = np.ogrid[:h, :w]
    mask = ((xx - palm_center[0]) / radius_x) ** 2 + ((yy - palm_center[1]) / radius_y) ** 2 <= 1.0

    pixels = rgb[mask]
    if len(pixels) == 0:
        return pixels, mask

    hsv = cv2.cvtColor(pixels.reshape(-1, 1, 3), cv2.COLOR_RGB2HSV).reshape(-1, 3)
    value = hsv[:, 2]
    saturation = hsv[:, 1]
    keep = (
        (value > np.percentile(value, 10)) & (value < np.percentile(value, 92)) & (saturation < 210)
    )
    filtered = pixels[keep]
    if len(filtered) < 30:
        filtered = pixels
    return filtered, mask


def _color_metrics(pixels: np.ndarray) -> dict[str, Any]:
    if len(pixels) == 0:
        return {
            "median_rgb": [0, 0, 0],
            "lab_l": 0.0,
            "lab_a": 0.0,
            "lab_b": 0.0,
            "hsv_h": 0.0,
            "hsv_s": 0.0,
            "ycrcb_y": 0.0,
            "ycrcb_cr": 0.0,
            "ycrcb_cb": 0.0,
            "sample_stability": 0.0,
            "sample_size": 0,
        }

    median_rgb = np.median(pixels, axis=0).astype(np.uint8)
    rgb_float = median_rgb.reshape(1, 1, 3).astype(np.float32) / 255.0
    lab = cv2.cvtColor(rgb_float, cv2.COLOR_RGB2LAB)[0, 0]
    hsv = cv2.cvtColor(median_rgb.reshape(1, 1, 3), cv2.COLOR_RGB2HSV)[0, 0]
    ycrcb = cv2.cvtColor(median_rgb.reshape(1, 1, 3), cv2.COLOR_RGB2YCrCb)[0, 0]

    spread = float(np.mean(np.std(pixels.astype(np.float32), axis=0)))
    sample_stability = max(0.0, min(1.0, 1.0 - spread / 58.0))

    return {
        "median_rgb": [int(v) for v in median_rgb.tolist()],
        "lab_l": float(lab[0]),
        "lab_a": float(lab[1]),
        "lab_b": float(lab[2]),
        "hsv_h": float(hsv[0] * 2),
        "hsv_s": float(hsv[1] / 255.0),
        "ycrcb_y": float(ycrcb[0]),
        "ycrcb_cr": float(ycrcb[1]),
        "ycrcb_cb": float(ycrcb[2]),
        "sample_stability": sample_stability,
        "sample_size": int(len(pixels)),
    }


def classify_skin_tone(color: dict[str, Any]) -> tuple[str, float, str]:
    for rule in _skin_tone_rules():
        if _matches_rule(color, rule.get("feature_rules", {})):
            skin_tone = rule.get("skin_tone", "unknown")
            confidence_cap = float(rule.get("confidence_cap", 0.0))
            confidence = min(confidence_cap, float(color.get("sample_stability", 0.0)))
            return skin_tone, confidence, rule.get("reason", "按外部规则命中肤色")

    if color["sample_stability"] < 0.35 or color["sample_size"] < 30:
        return "unknown", 0.0, "肤色采样区域不稳定"
    return "natural", 0.62, "落在边界区间，归为自然肤色"


def classify_undertone(color: dict[str, Any]) -> tuple[str, float, str]:
    for rule in _undertone_rules():
        if _matches_rule(color, rule.get("feature_rules", {})):
            undertone = rule.get("undertone", "unknown")
            confidence_cap = float(rule.get("confidence_cap", 0.0))
            confidence = min(confidence_cap, float(color.get("sample_stability", 0.0)))
            return undertone, confidence, rule.get("reason", "按外部规则命中冷暖调")

    if color["sample_stability"] < 0.35 or color["sample_size"] < 30:
        return "unknown", 0.0, "肤色采样区域不稳定"
    return "neutral", min(0.78, color["sample_stability"]), "冷暖特征接近，归为中性"


def _annotate(rgb: np.ndarray, detection: HandDetection, sample_mask: np.ndarray) -> Image.Image:
    annotated = rgb.copy()
    overlay = annotated.copy()
    overlay[sample_mask] = np.array([255, 92, 122], dtype=np.uint8)
    annotated = cv2.addWeighted(overlay, 0.25, annotated, 0.75, 0)

    mp_hands = mp.solutions.hands
    for a, b in mp_hands.HAND_CONNECTIONS:
        pa = tuple(np.round(detection.points[a]).astype(int))
        pb = tuple(np.round(detection.points[b]).astype(int))
        cv2.line(annotated, pa, pb, (80, 220, 255), 2, cv2.LINE_AA)
    for point in detection.points:
        cv2.circle(
            annotated, tuple(np.round(point).astype(int)), 4, (255, 255, 255), -1, cv2.LINE_AA
        )
        cv2.circle(annotated, tuple(np.round(point).astype(int)), 4, (45, 45, 55), 1, cv2.LINE_AA)
    return Image.fromarray(annotated)


def analyze_hand_image(source: str | Path | bytes) -> dict[str, Any]:
    image = load_image(source)
    rgb = np.array(image)
    detection = _detect_hand(rgb)
    if detection is None:
        return {
            "ok": False,
            "error": "未检测到完整手部，请上传自然光下、手背完整露出的图片。",
            "original_image": image,
            "annotated_image": image,
            "hand_shape": "unknown",
            "hand_shape_label": HAND_SHAPE_LABELS["unknown"],
            "skin_tone": "unknown",
            "skin_tone_label": SKIN_TONE_LABELS["unknown"],
            "undertone": "unknown",
            "undertone_label": UNDERTONE_LABELS["unknown"],
            "metrics": {},
            "color_metrics": {},
        }

    metrics = _hand_metrics(detection.points, detection.score)
    hand_shape, hand_confidence, hand_reason = classify_hand_shape(metrics)

    skin_pixels, sample_mask = _sample_skin_pixels(rgb, detection.points)
    color_metrics = _color_metrics(skin_pixels)
    skin_tone, skin_confidence, skin_reason = classify_skin_tone(color_metrics)
    undertone, undertone_confidence, undertone_reason = classify_undertone(color_metrics)

    return {
        "ok": True,
        "original_image": image,
        "annotated_image": _annotate(rgb, detection, sample_mask),
        "hand_shape": hand_shape,
        "hand_shape_label": HAND_SHAPE_LABELS[hand_shape],
        "hand_shape_confidence": round(hand_confidence, 3),
        "hand_shape_reason": hand_reason,
        "skin_tone": skin_tone,
        "skin_tone_label": SKIN_TONE_LABELS[skin_tone],
        "skin_confidence": round(skin_confidence, 3),
        "skin_reason": skin_reason,
        "undertone": undertone,
        "undertone_label": UNDERTONE_LABELS[undertone],
        "undertone_confidence": round(undertone_confidence, 3),
        "undertone_reason": undertone_reason,
        "median_rgb": color_metrics["median_rgb"],
        "handedness": detection.handedness,
        "metrics": {key: round(value, 4) for key, value in metrics.items()},
        "color_metrics": {
            key: (round(value, 4) if isinstance(value, float) else value)
            for key, value in color_metrics.items()
        },
    }
