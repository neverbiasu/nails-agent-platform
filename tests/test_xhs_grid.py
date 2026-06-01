"""Grid image detection & splitting tests (TASK-3 updated for _classify_image)."""

from __future__ import annotations

from pathlib import Path

import pytest

# numpy/cv2 are optional in CI (kept out of the base install — see PR #6 which
# lazy-imports them in the fetcher). Skip this module when numpy is unavailable.
np = pytest.importorskip("numpy", reason="numpy required for grid image tests")

from PIL import Image, ImageDraw

from nails_agent.tools.fetchers.xhs_mcp_fetcher import XHSMCPFetcher


def _make_image(tmp_path: Path, name: str, size: tuple[int, int], color=(180, 160, 140)) -> Path:
    p = tmp_path / name
    Image.new("RGB", size, color).save(p)
    return p


def _make_grid9(tmp_path: Path, name: str = "grid9.png", size: int = 900) -> Path:
    """Create a synthetic 3×3 grid image with visible separator lines."""
    p = tmp_path / name
    img = Image.new("RGB", (size, size), (200, 180, 160))
    draw = ImageDraw.Draw(img)
    cell = size // 3
    # Draw separator lines (dark) so grid detection fires
    for i in (1, 2):
        draw.line([(i * cell, 0), (i * cell, size)], fill=(20, 20, 20), width=4)
        draw.line([(0, i * cell), (size, i * cell)], fill=(20, 20, 20), width=4)
    img.save(p)
    return p


# ── _classify_image ────────────────────────────────────────────────────────────


def test_wide_strip_classified(tmp_path: Path):
    """Wide horizontal image → 'wide_strip'."""
    p = _make_image(tmp_path, "wide.png", (3000, 1000))
    assert XHSMCPFetcher._classify_image(p) == "wide_strip"


def test_tall_strip_classified(tmp_path: Path):
    """Tall narrow image → 'wide_strip'."""
    p = _make_image(tmp_path, "tall.png", (400, 1200))
    assert XHSMCPFetcher._classify_image(p) == "wide_strip"


def test_single_nail_normal(tmp_path: Path):
    """Normal portrait nail photo → 'normal'."""
    p = _make_image(tmp_path, "normal.png", (800, 1200))
    assert XHSMCPFetcher._classify_image(p) == "normal"


def test_small_square_normal(tmp_path: Path):
    """Small square (< 600 px) → 'normal' regardless of grid lines."""
    p = _make_image(tmp_path, "small.png", (300, 300))
    assert XHSMCPFetcher._classify_image(p) == "normal"


def test_nonexistent_file(tmp_path: Path):
    """Missing file → 'normal' (no crash)."""
    assert XHSMCPFetcher._classify_image(tmp_path / "nope.png") == "normal"


def test_grid9_detected(tmp_path: Path):
    """Large square with 2 horizontal + 2 vertical dark lines → 'grid9'."""
    p = _make_grid9(tmp_path)
    result = XHSMCPFetcher._classify_image(p)
    assert result == "grid9", f"Expected grid9, got {result}"


def _make_portrait_grid9(tmp_path: Path, name: str = "pgrid.png", size=(900, 1200)) -> Path:
    """3×3 grid of distinct solid-color cells abutting directly — no separator
    lines, portrait 3:4 ratio. This mirrors the real XHS grid format (cells touch
    with no gutter, e.g. 1080×1440) that the old ratio/trough detector missed."""
    p = tmp_path / name
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    cw, ch = size[0] // 3, size[1] // 3
    colors = [
        (40, 40, 40),
        (220, 220, 220),
        (120, 80, 160),
        (200, 180, 160),
        (30, 160, 90),
        (240, 200, 40),
        (80, 120, 200),
        (160, 40, 40),
        (200, 200, 120),
    ]
    k = 0
    for r in range(3):
        for c in range(3):
            draw.rectangle([c * cw, r * ch, (c + 1) * cw - 1, (r + 1) * ch - 1], fill=colors[k])
            k += 1
    img.save(p)
    return p


def test_portrait_grid9_no_separators(tmp_path: Path):
    """Portrait 3×3 grid whose cells abut directly (no gutter lines) → 'grid9'.

    Real XHS composites are 3:4 portrait with cells touching, so the old
    near-square ratio gate (0.85–1.18) rejected every one of them.
    """
    p = _make_portrait_grid9(tmp_path)
    result = XHSMCPFetcher._classify_image(p)
    assert result == "grid9", f"Expected grid9, got {result}"


# ── _split_grid9 ───────────────────────────────────────────────────────────────


def test_split_grid9_produces_cells(tmp_path: Path):
    """Splitting a 9-grid image yields 1-2 cell files."""
    src = _make_grid9(tmp_path, "src.png", size=900)
    cells = XHSMCPFetcher._split_grid9(src, tmp_path, "test")
    assert len(cells) >= 1
    for cell in cells:
        assert cell.exists()
        with Image.open(cell) as img:
            w, h = img.size
            # Each cell should be roughly 1/3 of the original
            assert 200 <= w <= 400
            assert 200 <= h <= 400


def test_split_grid9_cleans_up_unchosen(tmp_path: Path):
    """After splitting, only the best cells remain; unchosen cells are deleted."""
    src = _make_grid9(tmp_path, "src2.png", size=900)
    cells = XHSMCPFetcher._split_grid9(src, tmp_path, "cleanup_test")
    all_webp = list(tmp_path.glob("cleanup_test_cell*.webp"))
    # Only kept cells should remain
    assert set(all_webp) == set(cells)
