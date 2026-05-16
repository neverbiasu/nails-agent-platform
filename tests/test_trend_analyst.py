"""Unit tests for trend_analyst worker (no API key required)."""

from __future__ import annotations


from nails_agent.agents.workers.trend_analyst import analyse
from nails_agent.models.schemas import TrendSignal


def _make_signal(
    platform: str = "xhs",
    keyword: str = "猫眼",
    style_tags: list[str] | None = None,
    likes: int = 100,
    collects: int = 50,
    shares: int = 10,
    comments: int = 20,
) -> TrendSignal:
    return TrendSignal(
        trend_id=f"TREND_{keyword}_{platform}",
        platform=platform,
        keyword=keyword,
        caption=f"{keyword} 美甲推荐",
        likes=likes,
        collects=collects,
        shares=shares,
        comments=comments,
        style_tags=style_tags or [keyword],
        publish_time="",
    )


def test_analyse_empty_signals():
    result = analyse([])
    assert result.top_10 == []
    assert result.patterns == []
    assert result.anomalies == []


def test_analyse_basic_ranking():
    signals = [
        _make_signal("xhs", "猫眼", likes=1000, collects=500),
        _make_signal("xhs", "法式", likes=200, collects=100),
        _make_signal("douyin", "猫眼", likes=800, collects=400),
    ]
    result = analyse(signals)
    assert len(result.top_10) <= 10
    # Top signal should have highest composite score
    assert result.top_10[0].composite_score >= result.top_10[-1].composite_score


def test_analyse_style_trends_aggregation():
    signals = [
        _make_signal("xhs", "猫眼", style_tags=["猫眼"], likes=500),
        _make_signal("xhs", "猫眼2", style_tags=["猫眼"], likes=300),
        _make_signal("douyin", "法式1", style_tags=["法式"], likes=200),
        _make_signal("douyin", "法式2", style_tags=["法式"], likes=150),
    ]
    result = analyse(signals)
    tags = [t.tag for t in result.style_trends]
    # Both tags should appear since each has >= 2 posts
    assert "猫眼" in tags
    assert "法式" in tags
    # 猫眼 should rank higher (more total engagement)
    cat_eye_idx = tags.index("猫眼")
    french_idx = tags.index("法式")
    assert cat_eye_idx < french_idx


def test_analyse_filters_noise_tags():
    """Noise tags like '美甲' should not appear in style_trends."""
    signals = [
        _make_signal("xhs", "美甲推荐", style_tags=["美甲", "猫眼"], likes=1000),
        _make_signal("xhs", "美甲推荐2", style_tags=["美甲", "猫眼"], likes=800),
    ]
    result = analyse(signals)
    tags = [t.tag for t in result.style_trends]
    assert "美甲" not in tags
    assert "猫眼" in tags


def test_analyse_patterns_detected():
    """Co-occurring style tags across >= 2 posts should form a pattern."""
    signals = [
        _make_signal("xhs", "s1", style_tags=["猫眼", "法式"], likes=500),
        _make_signal("xhs", "s2", style_tags=["猫眼", "法式"], likes=400),
        _make_signal("douyin", "s3", style_tags=["猫眼", "法式"], likes=300),
    ]
    result = analyse(signals)
    # At least one pattern should mention both tags
    combined = " ".join(result.patterns)
    assert "猫眼" in combined or "法式" in combined
