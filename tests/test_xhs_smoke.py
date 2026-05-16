"""
A9 — XHS bridge smoke tests.

Tests cover two layers:
  1. Unit-level: _feed_to_signal() parsing with mock data (always runs).
  2. Integration: XHSMCPFetcher.search() against the live bridge at :18060
     (auto-skipped when the bridge is not reachable).
"""

from __future__ import annotations

import pytest

from nails_agent.tools.fetchers.xhs_mcp_fetcher import (
    XHSMCPFetcher,
    _feed_to_signal,
)
from nails_agent.models.schemas import TrendSignal

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

_SAMPLE_FEED = {
    "id": "abc123xyz",
    "noteCard": {
        "displayTitle": "夏日猫眼美甲推荐",
        "desc": "今年最流行的猫眼款式合集 #美甲 #猫眼",
        "interactInfo": {
            "likedCount": "1200",
            "collectedCount": "340",
            "commentCount": "88",
            "sharedCount": "22",
        },
        "cover": {"urlDefault": "https://sns-img.xhscdn.com/example.jpg"},
    },
}


# ──────────────────────────────────────────────
# Unit tests — no bridge required
# ──────────────────────────────────────────────


def test_feed_to_signal_basic():
    sig = _feed_to_signal(_SAMPLE_FEED, "猫眼")
    assert sig is not None
    assert isinstance(sig, TrendSignal)
    assert sig.platform == "小红书"
    assert sig.keyword == "猫眼"
    assert "猫眼" in sig.caption
    assert sig.likes == 1200
    assert sig.collects == 340
    assert sig.comments == 88
    assert sig.shares == 22
    assert "XHS" in sig.trend_id


def test_feed_to_signal_missing_id_returns_none():
    feed_no_id = {"noteCard": {"displayTitle": "无ID笔记"}}
    assert _feed_to_signal(feed_no_id, "美甲") is None


def test_feed_to_signal_partial_interact_info():
    feed = {"id": "partial001", "noteCard": {"displayTitle": "简单美甲", "interactInfo": {}}}
    sig = _feed_to_signal(feed, "美甲")
    assert sig is not None
    assert sig.likes == 0
    assert sig.collects == 0


def test_feed_to_signal_nail_tags_classified():
    """Nail keywords in caption should produce style/color tags."""
    feed = {
        "id": "tag001",
        "noteCard": {
            "displayTitle": "法式渐变猫眼美甲",
            "desc": "粉色法式渐变款式 #美甲",
            "interactInfo": {"likedCount": "500"},
        },
    }
    sig = _feed_to_signal(feed, "法式")
    assert sig is not None
    # Should have at least one tag classified from nail keywords in caption
    has_tags = bool(sig.style_tags or sig.color_tags or sig.material_tags or sig.scene_tags)
    assert has_tags, f"Expected tags from nail caption, got none. Signal: {sig}"


# ──────────────────────────────────────────────
# Integration tests — skip if bridge is down
# ──────────────────────────────────────────────


def _bridge_is_up() -> bool:
    try:
        import requests

        r = requests.get("http://localhost:18060/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _bridge_is_up(), reason="XHS bridge not running at :18060")
def test_fetcher_is_available():
    fetcher = XHSMCPFetcher()
    # is_available() checks login status; result depends on session freshness
    result = fetcher.is_available()
    assert isinstance(result, bool)


@pytest.mark.skipif(not _bridge_is_up(), reason="XHS bridge not running at :18060")
def test_search_returns_list():
    """search() must always return a list (even if cookies expired → empty list)."""
    fetcher = XHSMCPFetcher()
    signals = fetcher.search(keywords=["猫眼美甲"], limit_per_kw=3)
    assert isinstance(signals, list)
    for s in signals:
        assert isinstance(s, TrendSignal)
        assert s.platform == "小红书"


@pytest.mark.skipif(not _bridge_is_up(), reason="XHS bridge not running at :18060")
def test_search_real_signals_when_logged_in():
    """
    Smoke test: if the XHS session is valid, at least 1 TrendSignal comes back.
    Marked xfail when cookies are stale (expected after session expiry).
    Re-run `uv run python scripts/xhs_login.py --name nails` to refresh cookies.
    """
    fetcher = XHSMCPFetcher()
    if not fetcher.is_available():
        pytest.skip("XHS session expired — run `uv run python scripts/xhs_login.py --name nails`")
    signals = fetcher.search(keywords=["猫眼美甲"], limit_per_kw=5)
    assert len(signals) >= 1, (
        "No signals returned. Cookies may be expired. "
        "Re-run: uv run python scripts/xhs_login.py --name nails"
    )
