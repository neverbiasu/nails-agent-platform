"""Tests for nail_extractor (Roboflow crop) and nail_feature_extractor integration."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

cv2 = pytest.importorskip("cv2", reason="cv2 required")
np = pytest.importorskip("numpy", reason="numpy required")

from PIL import Image

from nails_agent.services.nail_extractor import extract_nail_crops, _get_predictions


# ---------------------------------------------------------------------------
# Unit: _get_predictions parses various Roboflow response shapes
# ---------------------------------------------------------------------------


def test_get_predictions_flat():
    result = {"predictions": [{"confidence": 0.9, "points": []}]}
    assert len(_get_predictions(result)) == 1


def test_get_predictions_nested():
    result = {"outputs": [{"predictions": [{"confidence": 0.8}]}]}
    assert len(_get_predictions(result)) == 1


def test_get_predictions_empty():
    assert _get_predictions({}) == []
    assert _get_predictions({"foo": "bar"}) == []


# ---------------------------------------------------------------------------
# Integration: extract_nail_crops
# ---------------------------------------------------------------------------


def _fake_roboflow_response(w: int = 200, h: int = 300):
    """Simulate a Roboflow instance segmentation response with one nail."""
    return {
        "predictions": [
            {
                "confidence": 0.92,
                "points": [
                    {"x": 50, "y": 30},
                    {"x": 150, "y": 30},
                    {"x": 160, "y": 270},
                    {"x": 40, "y": 270},
                ],
            }
        ]
    }


def test_extract_nail_crops_with_mock_roboflow(tmp_path: Path):
    """Full round-trip: image → Roboflow REST (mocked) → crop files."""
    from PIL import ImageDraw

    img = Image.new("RGB", (200, 300), (220, 200, 190))
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 30, 150, 270], fill=(200, 20, 30))
    src = tmp_path / "hand.jpg"
    img.save(src)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _fake_roboflow_response()
    mock_resp.raise_for_status = MagicMock()

    with patch("nails_agent.services.nail_extractor.requests") as mock_requests:
        mock_requests.post.return_value = mock_resp
        crops = extract_nail_crops(
            src,
            output_dir=tmp_path / "crops",
            api_key="fake_key",
        )

    assert len(crops) >= 1
    assert all(p.exists() for p in crops)
    crop_img = Image.open(crops[0])
    assert crop_img.width < 200 or crop_img.height < 300


def test_extract_nail_crops_no_api_key(tmp_path: Path):
    """Without API key, returns empty list (no crash)."""
    img = Image.new("RGB", (100, 100))
    src = tmp_path / "test.png"
    img.save(src)

    with patch.dict("os.environ", {"ROBOFLOW_API_KEY": ""}, clear=False):
        crops = extract_nail_crops(src, api_key="")

    assert crops == []


def test_extract_nail_crops_missing_image(tmp_path: Path):
    """Missing image file returns empty list."""
    crops = extract_nail_crops(tmp_path / "nonexistent.jpg", api_key="fake")
    assert crops == []


# ---------------------------------------------------------------------------
# Integration: nail_feature_extractor with use_nail_crop
# ---------------------------------------------------------------------------


def test_feature_extractor_fallback_without_roboflow(tmp_path: Path):
    """When inference-sdk is unavailable, falls back to whole-image extraction."""
    from nails_agent.services.nail_feature_extractor import extract_nail_visual_features

    # Create a solid red image
    img = Image.new("RGB", (140, 260), (200, 30, 40))
    path = tmp_path / "red.png"
    img.save(path)

    # Patch the source function to simulate missing inference_sdk
    with patch(
        "nails_agent.services.nail_extractor.extract_nail_crops",
        side_effect=ImportError("no inference_sdk"),
    ):
        result = extract_nail_visual_features(path, "TEST_RED", use_nail_crop=True)

    assert result["primary_color_family"] == "red"
    assert result["nail_crop_used"] is False


def test_feature_extractor_uses_crop_when_available(tmp_path: Path):
    """When Roboflow returns a crop, feature extraction uses it."""
    from nails_agent.services.nail_feature_extractor import extract_nail_visual_features

    # Create a hand-like image: skin background + red nail center
    img = Image.new("RGB", (200, 300), (220, 190, 170))  # skin-tone bg
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    draw.rectangle([60, 40, 140, 260], fill=(200, 20, 30))  # red nail
    src = tmp_path / "hand_with_nail.png"
    img.save(src)

    # Create a pre-cropped nail image (just the red part)
    nail_crop = Image.new("RGB", (80, 220), (200, 20, 30))
    crop_path = tmp_path / "crop.png"
    nail_crop.save(crop_path)

    with patch(
        "nails_agent.services.nail_extractor.extract_nail_crops",
        return_value=[crop_path],
    ):
        result = extract_nail_visual_features(src, "TEST_CROP", use_nail_crop=True)

    assert result["nail_crop_used"] is True
    assert result["primary_color_family"] == "red"
    assert result["feature_source"] == "nail_crop_extract"
