"""Nail visual feature extraction for enhanced nail images.

The current demo data is still mocked, but this module is ready for the
future ingestion flow: enhanced image -> NailVisualFeature.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from . import storage

try:
    import cv2
    import numpy as np

    _CV2_AVAILABLE = True
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    _CV2_AVAILABLE = False


def _require_cv2() -> None:
    if not _CV2_AVAILABLE:
        raise ImportError(
            "cv2 / numpy are required for nail feature extraction. "
            "Install the consumer extras: pip install -e '.[consumer]'"
        )


EXTRACTOR_VERSION = "opencv_kmeans_v2_focus_roi"

COLOR_NAME_BY_FAMILY = {
    "red": "红色",
    "pink": "粉色",
    "nude": "裸色",
    "white": "白色",
    "black": "黑色",
    "green": "绿色",
    "yellow": "黄色",
    "blue": "蓝色",
    "purple": "紫色",
    "gold_silver": "金银色",
    "multi": "多色",
    "unknown": "未知色",
}

DEFAULT_BY_TARGET_TYPE = {
    "color_family": "unknown",
    "color_temperature": "neutral",
    "brightness_level": "medium",
    "saturation_level": "medium",
}


def load_rgb_image(image_path: str | Path) -> np.ndarray:
    path = storage.image_path(str(image_path))
    image = Image.open(path)
    image = ImageOps.exif_transpose(image).convert("RGB")
    return np.array(image)


def _resize_for_sampling(rgb: np.ndarray, max_side: int = 560) -> np.ndarray:
    h, w = rgb.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        return cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return rgb


def _nail_attention_mask(rgb: np.ndarray) -> np.ndarray:
    """Heuristic focus mask for single-nail crops.

    We bias the sampler toward the central upper nail plate so background
    and lower finger skin do not dominate the palette.
    """
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    x_norm = (xx / max(w - 1, 1) - 0.5) / 0.42
    y_norm = (yy / max(h - 1, 1) - 0.34) / 0.66
    ellipse = np.exp(-(x_norm**2 + y_norm**2) * 1.35)

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    saturation = hsv[:, :, 1] / 255.0
    value = hsv[:, :, 2] / 255.0

    # The visible nail plate is usually more central and slightly more vivid
    # than the surrounding finger/background, but we keep a floor so nude
    # manicures are still represented.
    vividness = np.clip(0.35 + saturation * 0.9 + np.maximum(0.0, 0.72 - value) * 0.28, 0.25, 1.0)
    top_bias = np.clip(1.14 - (yy / max(h - 1, 1)) * 0.5, 0.52, 1.0)
    mask = ellipse * vividness * top_bias
    return mask.astype(np.float32)


def _sample_pixels(rgb: np.ndarray, max_side: int = 560) -> np.ndarray:
    rgb = _resize_for_sampling(rgb, max_side=max_side)
    attention = _nail_attention_mask(rgb)

    pixels = rgb.reshape(-1, 3)
    if len(pixels) == 0:
        return pixels

    hsv = cv2.cvtColor(pixels.reshape(-1, 1, 3), cv2.COLOR_RGB2HSV).reshape(-1, 3)
    value = hsv[:, 2]
    saturation = hsv[:, 1]
    weights = attention.reshape(-1)
    keep = (
        (weights >= np.percentile(weights, 20))
        & (value > np.percentile(value, 3))
        & (value < np.percentile(value, 98))
        & ~((value > 245) & (saturation < 18))
    )
    filtered = pixels[keep]
    if len(filtered) >= 120:
        return filtered

    # Fallback: keep only the highest-attention pixels so we still focus on
    # the nail even when the image is tiny or visually simple.
    attention_keep = weights >= np.percentile(weights, 35)
    filtered = pixels[attention_keep]
    return filtered if len(filtered) >= 100 else pixels


def _dominant_colors(pixels: np.ndarray, k: int = 4) -> list[dict[str, Any]]:
    if len(pixels) == 0:
        return []

    sample_size = min(len(pixels), 12000)
    rng = np.random.default_rng(42)
    sampled = (
        pixels[rng.choice(len(pixels), sample_size, replace=False)]
        if len(pixels) > sample_size
        else pixels
    )
    data = sampled.astype(np.float32)
    cluster_count = min(k, len(data))

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.4)
    _compactness, labels, centers = cv2.kmeans(
        data,
        cluster_count,
        None,
        criteria,
        5,
        cv2.KMEANS_PP_CENTERS,
    )
    counts = np.bincount(labels.flatten(), minlength=cluster_count)
    order = np.argsort(counts)[::-1]
    total = float(counts.sum()) or 1.0

    colors: list[dict[str, Any]] = []
    for index in order:
        ratio = float(counts[index] / total)
        if ratio < 0.045 and colors:
            continue
        rgb = np.clip(np.round(centers[index]), 0, 255).astype(int).tolist()
        colors.append({"rgb": rgb, "ratio": round(ratio, 3)})
    return colors[:4]


def _color_metrics(rgb: list[int]) -> dict[str, float]:
    arr_uint8 = np.array(rgb, dtype=np.uint8).reshape(1, 1, 3)
    arr_float = arr_uint8.astype(np.float32) / 255.0
    hsv = cv2.cvtColor(arr_uint8, cv2.COLOR_RGB2HSV)[0, 0]
    lab = cv2.cvtColor(arr_float, cv2.COLOR_RGB2LAB)[0, 0]
    return {
        "hsv_h": float(int(hsv[0]) * 2),
        "hsv_s": float(hsv[1] / 255.0),
        "hsv_v": float(hsv[2] / 255.0),
        "lab_l": float(lab[0]),
        "lab_a": float(lab[1]),
        "lab_b": float(lab[2]),
        "metallic_hint": _is_metallic_like(rgb, hsv, lab),
    }


def _is_metallic_like(rgb: list[int], hsv: np.ndarray, lab: np.ndarray) -> bool:
    channel_spread = max(rgb) - min(rgb)
    return bool(hsv[1] <= 75 and 38 <= lab[0] <= 88 and channel_spread <= 42)


@lru_cache(maxsize=1)
def _color_rules() -> list[dict[str, Any]]:
    rules = storage.read_data("color_feature_rules")
    return sorted(rules, key=lambda item: int(item.get("priority", 0)), reverse=True)


def _parse_range(raw: str) -> list[tuple[float | None, float | None]]:
    ranges: list[tuple[float | None, float | None]] = []
    for part in raw.split(" or "):
        part = part.strip()
        if match := re.fullmatch(r">=\s*(-?\d+(?:\.\d+)?)", part):
            ranges.append((float(match.group(1)), None))
        elif match := re.fullmatch(r"<=\s*(-?\d+(?:\.\d+)?)", part):
            ranges.append((None, float(match.group(1))))
        elif match := re.fullmatch(r">\s*(-?\d+(?:\.\d+)?)", part):
            ranges.append((float(match.group(1)), None))
        elif match := re.fullmatch(r"<\s*(-?\d+(?:\.\d+)?)", part):
            ranges.append((None, float(match.group(1))))
        elif match := re.fullmatch(r"(-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)", part):
            ranges.append((float(match.group(1)), float(match.group(2))))
        elif match := re.fullmatch(r"-?\d+(?:\.\d+)?", part):
            value = float(match.group(0))
            ranges.append((value, value))
    return ranges


def _range_match(value: float, raw_rule: str) -> bool:
    ranges = _parse_range(raw_rule)
    if not ranges:
        return False
    for lower, upper in ranges:
        if lower is not None and value < lower:
            continue
        if upper is not None and value > upper:
            continue
        return True
    return False


def _rule_matches(metrics: dict[str, Any], feature_rules: dict[str, Any]) -> bool:
    for key, raw_rule in feature_rules.items():
        if isinstance(raw_rule, bool):
            if bool(metrics.get(key)) != raw_rule:
                return False
        elif isinstance(raw_rule, str):
            if not _range_match(float(metrics.get(key, 0.0)), raw_rule):
                return False
        else:
            if metrics.get(key) != raw_rule:
                return False
    return True


def _classify(target_type: str, metrics: dict[str, Any]) -> str:
    for rule in _color_rules():
        if rule.get("target_type") != target_type:
            continue
        if _rule_matches(metrics, rule.get("feature_rules", {})):
            return rule.get("target_value", DEFAULT_BY_TARGET_TYPE.get(target_type, "unknown"))
    return DEFAULT_BY_TARGET_TYPE.get(target_type, "unknown")


def _normalize_color_family(family: str, metrics: dict[str, Any]) -> str:
    hue = metrics["hsv_h"]
    saturation = metrics["hsv_s"]
    value = metrics["hsv_v"]

    # Dark, highly saturated reds often get pushed into "black" by pure
    # brightness rules. Pull them back into the chromatic families.
    if family == "black" and saturation >= 0.42:
        if hue <= 18 or hue >= 342:
            return "red"
        if 300 <= hue < 342:
            return "purple"
        if 18 < hue <= 40:
            return "gold_silver"

    # Warm low-saturation pink-nude shades should stay closer to nude than white.
    if family == "white" and saturation >= 0.12 and value <= 0.95:
        if (hue <= 25 or hue >= 330) and metrics["lab_b"] > 10:
            return "nude"

    return family


def _contrast_level(palette: list[dict[str, Any]]) -> str:
    if len(palette) < 2:
        return "low"
    lightness = [_color_metrics(item["rgb"])["lab_l"] for item in palette[:3]]
    span = max(lightness) - min(lightness)
    if span >= 45:
        return "high"
    if span >= 22:
        return "medium"
    return "low"


def _feature_confidence(palette: list[dict[str, Any]]) -> float:
    if not palette:
        return 0.0
    primary_ratio = palette[0]["ratio"]
    palette_spread = len([item for item in palette if item["ratio"] >= 0.08])
    confidence = 0.52 + min(primary_ratio, 0.72) * 0.42
    if palette_spread >= 4:
        confidence -= 0.08
    return round(max(0.45, min(confidence, 0.92)), 2)


def _color_vector(palette: list[dict[str, Any]], size: int = 2) -> list[float]:
    vector: list[float] = []
    for item in palette[:size]:
        vector.extend([*item["rgb"], item["ratio"]])
    while len(vector) < size * 4:
        vector.append(0.0)
    return vector


def _cluster_prominence(cluster: dict[str, Any]) -> float:
    metrics = _color_metrics(cluster["rgb"])
    chroma = min(1.0, (abs(metrics["lab_a"]) + abs(metrics["lab_b"])) / 80.0)
    ratio = float(cluster["ratio"])
    saturation = float(metrics["hsv_s"])
    prominence = ratio * 0.55 + saturation * 0.35 + chroma * 0.10
    if ratio < 0.1:
        prominence -= 0.08
    return prominence


def extract_nail_visual_features(
    image_path: str | Path,
    style_id: str,
    visual_feature_id: str | None = None,
    *,
    use_nail_crop: bool = True,
) -> dict[str, Any]:
    """Extract a NailVisualFeature dict from an enhanced nail image.

    When *use_nail_crop* is ``True`` (default) and a ``ROBOFLOW_API_KEY`` is
    configured, the image is first passed through Roboflow instance
    segmentation to isolate individual nail regions.  The largest detected
    nail crop is then used for color analysis, which dramatically improves
    accuracy compared to whole-image extraction.

    Falls back to whole-image analysis silently when nail cropping is
    unavailable or detects nothing.
    """
    _require_cv2()

    effective_path: str | Path = image_path
    nail_crop_used = False
    if use_nail_crop:
        try:
            from nails_agent.services.nail_extractor import extract_nail_crops

            crops = extract_nail_crops(image_path)
            if crops:
                effective_path = crops[0]
                nail_crop_used = True
        except ImportError:
            pass  # inference-sdk not installed — fall back to whole image
        except Exception:
            import logging

            logging.getLogger(__name__).debug(
                "Nail crop failed for %s, falling back to whole image", image_path, exc_info=True
            )

    rgb = load_rgb_image(effective_path)
    pixels = _sample_pixels(rgb)
    palette = _dominant_colors(pixels)

    enriched_palette: list[dict[str, Any]] = []
    for item in palette:
        metrics = _color_metrics(item["rgb"])
        family = _normalize_color_family(_classify("color_family", metrics), metrics)
        enriched_palette.append(
            {
                "color_family": family,
                "color_name": COLOR_NAME_BY_FAMILY.get(family, "未知色"),
                "rgb": item["rgb"],
                "ratio": item["ratio"],
            }
        )

    primary = (
        max(enriched_palette, key=_cluster_prominence)
        if enriched_palette
        else {
            "color_family": "unknown",
            "color_name": "未知色",
            "rgb": [0, 0, 0],
            "ratio": 0.0,
        }
    )
    primary_metrics = _color_metrics(primary["rgb"])
    confidence = _feature_confidence(enriched_palette)
    now = storage.now_iso()

    return {
        "visual_feature_id": visual_feature_id or f"NVF_{style_id}",
        "style_id": style_id,
        "primary_color_family": primary["color_family"],
        "primary_color_name": primary["color_name"],
        "primary_color_rgb": primary["rgb"],
        "dominant_palette": enriched_palette,
        "color_temperature": _classify("color_temperature", primary_metrics),
        "brightness_level": _classify("brightness_level", primary_metrics),
        "saturation_level": _classify("saturation_level", primary_metrics),
        "contrast_level": _contrast_level(enriched_palette),
        "color_vector": _color_vector(enriched_palette),
        "extractor_version": EXTRACTOR_VERSION,
        "feature_confidence": confidence,
        "needs_manual_review": confidence < 0.62 or primary["color_family"] == "unknown",
        "feature_source": "nail_crop_extract" if nail_crop_used else "auto_color_extract",
        "nail_crop_used": nail_crop_used,
        "created_at": now,
        "updated_at": None,
    }


def upsert_nail_visual_feature(feature: dict[str, Any]) -> None:
    """Insert or replace one visual feature row in data/nail_visual_features.json."""
    rows = storage.read_data("nail_visual_features")
    replaced = False
    for index, row in enumerate(rows):
        if row.get("visual_feature_id") == feature.get("visual_feature_id") or row.get(
            "style_id"
        ) == feature.get("style_id"):
            previous_created_at = row.get("created_at")
            rows[index] = {
                **feature,
                "created_at": previous_created_at or feature["created_at"],
                "updated_at": storage.now_iso(),
            }
            replaced = True
            break
    if not replaced:
        rows.append(feature)
    storage.write_json(storage.DATA_DIR / "nail_visual_features.json", rows)
