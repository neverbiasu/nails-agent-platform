"""
A10 — Douyin CDP fetcher unit tests.

The real Playwright CDP path requires Chrome at :9222 (not available in CI),
so most tests target the pure-Python parsing layer and the is_available() fast-fail.
"""

from __future__ import annotations

from nails_agent.tools.fetchers.douyin_cdp import (
    DouyinCDPFetcher,
    _parse_aweme,
    _extract_items,
)
from nails_agent.models.schemas import TrendSignal


# ──────────────────────────────────────────────
# _parse_aweme unit tests
# ──────────────────────────────────────────────


_AWEME_ITEM = {
    "aweme_id": "7123456789012345678",
    "desc": "冰透蓝猫眼美甲 来自星星的你 #美甲 #猫眼",
    "statistics": {
        "digg_count": 8500,
        "comment_count": 320,
        "share_count": 140,
        "collect_count": 2200,
    },
    "create_time": 1715000000,
    "text_extra": [
        {"type": 1, "hashtag_name": "美甲"},
        {"type": 1, "hashtag_name": "猫眼"},
    ],
}


def test_parse_aweme_basic():
    sig = _parse_aweme(_AWEME_ITEM, "猫眼美甲")
    assert sig is not None
    assert isinstance(sig, TrendSignal)
    assert sig.platform == "抖音"
    assert sig.keyword == "猫眼美甲"
    assert sig.likes == 8500
    assert sig.comments == 320
    assert sig.shares == 140
    assert sig.collects == 2200
    assert "猫眼" in sig.caption


def test_parse_aweme_missing_stats():
    item = {"aweme_id": "minimal001", "desc": "简单美甲"}
    sig = _parse_aweme(item, "美甲")
    assert sig is not None
    assert sig.likes == 0
    assert sig.collects == 0


def test_parse_aweme_invalid_input_returns_none():
    assert _parse_aweme(None, "美甲") is None  # type: ignore[arg-type]
    assert _parse_aweme("not a dict", "美甲") is None  # type: ignore[arg-type]


def test_parse_aweme_trend_id_format():
    sig = _parse_aweme(_AWEME_ITEM, "美甲")
    assert sig is not None
    assert "DY" in sig.trend_id or "抖音" in sig.trend_id


# ──────────────────────────────────────────────
# _extract_items unit tests
# ──────────────────────────────────────────────


def test_extract_items_from_aweme_list():
    body = {"aweme_list": [{"aweme_id": "a"}, {"aweme_id": "b"}]}
    items = _extract_items(body)
    assert len(items) == 2


def test_extract_items_from_item_list():
    body = {"item_list": [{"aweme_id": "x"}]}
    items = _extract_items(body)
    assert len(items) == 1


def test_extract_items_passthrough_list():
    body = [{"aweme_id": "1"}, {"aweme_id": "2"}]
    items = _extract_items(body)
    assert len(items) == 2


def test_extract_items_nested():
    body = {"data": {"aweme_list": [{"aweme_id": "nested"}]}}
    items = _extract_items(body)
    assert len(items) == 1


def test_extract_items_empty():
    assert _extract_items({}) == []
    assert _extract_items(None) == []  # type: ignore[arg-type]


# ──────────────────────────────────────────────
# DouyinCDPFetcher fallback tests (no Chrome needed)
# ──────────────────────────────────────────────


def test_fetcher_unavailable_when_no_chrome():
    """is_available() should return False if Chrome isn't running at :9222."""
    fetcher = DouyinCDPFetcher(cdp_url="http://localhost:19999")  # unused port
    assert fetcher.is_available() is False


def test_search_returns_empty_when_unavailable():
    """search() must return [] gracefully when Chrome is not reachable."""
    fetcher = DouyinCDPFetcher(cdp_url="http://localhost:19999")
    result = fetcher.search(keywords=["猫眼美甲"], limit_per_kw=5)
    assert result == []
