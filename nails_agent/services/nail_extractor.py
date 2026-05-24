"""Nail region extraction via Roboflow instance segmentation.

Wraps the Roboflow ``fingernail-segmentation`` model to crop individual
nail regions from a hand/nail photo.  The cropped images are written to a
caller-specified (or temp) directory and their paths are returned.

Dependencies:
    pip install inference-sdk opencv-contrib-python numpy

All heavy imports (``cv2``, ``numpy``, ``inference_sdk``) are lazy so this
module can be imported safely in environments that lack them (e.g. CI).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_ID = "fingernail-segmentation-yy1l7/3"
_DEFAULT_API_URL = "https://detect.roboflow.com"


# ---------------------------------------------------------------------------
# Lazy import helpers
# ---------------------------------------------------------------------------

def _require_deps() -> None:
    """Raise a clear error if cv2 / numpy / inference_sdk are missing."""
    try:
        import cv2 as _cv2  # noqa: F401
        import numpy as _np  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "cv2 and numpy are required for nail extraction. "
            "Install via: pip install -e '.[consumer]'"
        ) from exc
    try:
        import inference_sdk as _sdk  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "inference-sdk is required for Roboflow nail extraction. "
            "Install via: pip install inference-sdk"
        ) from exc


# ---------------------------------------------------------------------------
# Internal helpers (match original extract_nails.py logic)
# ---------------------------------------------------------------------------

def _imread_unicode(path: str) -> Any:
    """Read an image from a path that may contain non-ASCII characters."""
    import cv2
    import numpy as np

    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return image


def _imwrite_unicode(path: str, image: Any) -> bool:
    """Write an image to a path that may contain non-ASCII characters."""
    import cv2

    ext = Path(path).suffix or ".png"
    success, buffer = cv2.imencode(ext, image)
    if success:
        buffer.tofile(path)
    return bool(success)


def _get_predictions(result: Any) -> list[dict]:
    """Walk a (possibly nested) Roboflow response to find ``predictions``."""
    if isinstance(result, dict):
        if "predictions" in result:
            return result["predictions"]
        for key in ("output", "outputs", "result", "results"):
            if key in result:
                preds = _get_predictions(result[key])
                if preds:
                    return preds
    if isinstance(result, list):
        for item in result:
            preds = _get_predictions(item)
            if preds:
                return preds
    return []


def _extract_one_nail(
    image: Any,
    points: list[dict[str, int]],
    padding: int = 8,
) -> Any:
    """Crop a single nail region as a BGRA image (transparent background)."""
    import cv2
    import numpy as np

    h, w = image.shape[:2]
    polygon = np.array([[int(p["x"]), int(p["y"])] for p in points], dtype=np.int32)

    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [polygon], 255)

    b, g, r = cv2.split(image)
    rgba = cv2.merge([b, g, r, mask])

    x, y, box_w, box_h = cv2.boundingRect(polygon)
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(w, x + box_w + padding)
    y2 = min(h, y + box_h + padding)

    return rgba[y1:y2, x1:x2]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_nail_crops(
    image_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    api_key: str | None = None,
    api_url: str | None = None,
    model_id: str | None = None,
    confidence_threshold: float = 0.4,
) -> list[Path]:
    """Detect and crop individual nails from *image_path*.

    Returns a list of ``Path`` objects pointing to the saved crop PNGs
    (sorted largest-area first).  Returns ``[]`` — never raises — when no
    nails are detected or the API call fails.

    Parameters
    ----------
    image_path:
        Local file path to the source image.
    output_dir:
        Directory for saved crops.  Defaults to a new temp directory.
    api_key:
        Roboflow API key.  Falls back to ``ROBOFLOW_API_KEY`` env var.
    api_url:
        Roboflow API URL.  Defaults to ``https://detect.roboflow.com``.
    model_id:
        Roboflow model identifier.  Defaults to
        ``fingernail-segmentation-yy1l7/3``.
    confidence_threshold:
        Minimum detection confidence (0-1).
    """
    # Check API key first — if absent, skip without requiring heavy deps
    resolved_key = api_key or os.environ.get("ROBOFLOW_API_KEY", "")
    if not resolved_key:
        logger.warning("ROBOFLOW_API_KEY not set — skipping nail extraction")
        return []

    src = Path(image_path)
    if not src.exists():
        logger.warning("Image not found: %s", src)
        return []

    _require_deps()
    from inference_sdk import InferenceHTTPClient

    image = _imread_unicode(str(src))
    if image is None:
        logger.warning("Failed to read image: %s", src)
        return []

    # Call Roboflow
    client = InferenceHTTPClient(
        api_url=api_url or _DEFAULT_API_URL,
        api_key=resolved_key,
    )
    try:
        result = client.infer(str(src), model_id=model_id or _DEFAULT_MODEL_ID)
    except Exception:
        logger.exception("Roboflow inference failed for %s", src)
        return []

    predictions = _get_predictions(result)
    if not predictions:
        logger.info("No nails detected in %s", src)
        return []

    # Prepare output directory
    out = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="nail_crops_"))
    out.mkdir(parents=True, exist_ok=True)

    crops: list[tuple[int, Path]] = []  # (area, path)
    for i, pred in enumerate(predictions):
        if pred.get("confidence", 1.0) < confidence_threshold:
            continue
        points = pred.get("points")
        if not points:
            continue
        nail_crop = _extract_one_nail(image, points)
        h, w = nail_crop.shape[:2]
        crop_path = out / f"nail_{i}.png"
        _imwrite_unicode(str(crop_path), nail_crop)
        crops.append((h * w, crop_path))

    # Return largest-area first (most likely the best single-nail crop)
    crops.sort(key=lambda t: t[0], reverse=True)
    paths = [p for _, p in crops]

    logger.info("Extracted %d nail crops from %s", len(paths), src)
    return paths
