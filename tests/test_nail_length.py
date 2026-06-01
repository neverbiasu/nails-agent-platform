"""TASK-5: Nail length classification tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from nails_agent.services.nail_extractor import classify_nail_length


@pytest.mark.parametrize(
    "wh,expected",
    [
        ((200, 400), "长甲"),  # ratio=2.0
        ((200, 300), "中甲"),  # ratio=1.5
        ((200, 220), "短甲"),  # ratio=1.1
        ((200, 360), "中甲"),  # ratio=1.8 boundary → 中甲
        ((200, 362), "长甲"),  # ratio=1.81 → 长甲
        ((200, 240), "中甲"),  # ratio=1.2 boundary → 中甲
        ((200, 238), "短甲"),  # ratio=1.19 → 短甲
    ],
)
def test_nail_length_classification(tmp_path: Path, wh: tuple[int, int], expected: str):
    img = Image.new("RGB", wh, (200, 50, 50))
    path = tmp_path / "nail.png"
    img.save(path)
    assert classify_nail_length(path) == expected


def test_nail_length_rgba_with_alpha(tmp_path: Path):
    """RGBA image uses bounding box of non-transparent pixels."""
    img = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    # Draw a tall nail shape (50x120 → ratio=2.4 → 长甲)
    draw.rectangle([125, 90, 175, 210], fill=(200, 50, 50, 255))
    path = tmp_path / "nail_alpha.png"
    img.save(path)
    assert classify_nail_length(path) == "长甲"


def test_nail_length_nonexistent_file(tmp_path: Path):
    assert classify_nail_length(tmp_path / "nope.png") == "短甲"
