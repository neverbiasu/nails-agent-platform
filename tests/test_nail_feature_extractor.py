from __future__ import annotations

import pytest
from pathlib import Path
from PIL import Image, ImageDraw

pytest.importorskip(
    "cv2", reason="OpenCV not installed; skipping visual feature tests (needs .[consumer] extras)"
)

from nails_agent.services.nail_feature_extractor import extract_nail_visual_features


def test_extract_focuses_on_center_nail_area(tmp_path: Path):
    canvas = Image.new("RGB", (140, 260), (240, 230, 210))
    draw = ImageDraw.Draw(canvas)

    # Central nail plate
    draw.rounded_rectangle((36, 4, 106, 228), radius=34, fill=(170, 10, 20))
    path = tmp_path / "single_nail.png"
    canvas.save(path)

    feature = extract_nail_visual_features(path, style_id="TEST_STYLE")

    assert feature["primary_color_family"] == "red"
    assert feature["feature_confidence"] >= 0.55


def test_extract_classifies_yellow_nail(tmp_path: Path):
    canvas = Image.new("RGB", (140, 260), (236, 226, 208))
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle((36, 4, 106, 228), radius=34, fill=(220, 188, 76))

    path = tmp_path / "yellow_nail.png"
    canvas.save(path)

    feature = extract_nail_visual_features(path, style_id="TEST_YELLOW_STYLE")

    assert feature["primary_color_family"] == "yellow"
    assert feature["saturation_level"] in {"medium", "high"}
