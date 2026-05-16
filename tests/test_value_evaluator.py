"""Unit tests for value_evaluator worker (no API key required)."""

from __future__ import annotations

from nails_agent.agents.workers.value_evaluator import evaluate
from nails_agent.models.schemas import (
    StyleLibraryItem,
    StyleTrend,
    TrendAnalysisResult,
    TrendSignal,
)

_EMPTY_LIBRARY: list[StyleLibraryItem] = []


def _make_signal(keyword: str, score: float, rank: int = 1) -> TrendSignal:
    likes = int(score * 10)
    return TrendSignal(
        trend_id=f"TREND_{keyword}",
        platform="xhs",
        keyword=keyword,
        caption=f"{keyword} 美甲推荐",
        likes=likes,
        collects=int(likes * 0.5),
        shares=int(likes * 0.1),
        comments=int(likes * 0.2),
        style_tags=[keyword],
        composite_score=score,
        rank=rank,
        publish_time="",
    )


def _make_trend_result(tags: list[str], scores: list[float]) -> TrendAnalysisResult:
    top_10 = [
        _make_signal(tag, score, rank=i + 1) for i, (tag, score) in enumerate(zip(tags, scores))
    ]
    style_trends = [
        StyleTrend(
            tag=tag,
            category="style",
            post_count=10,
            total_engagement=int(score * 100),
            aggregated_score=score,
            sample_caption=f"{tag} 样本文案",
        )
        for tag, score in zip(tags, scores)
    ]
    return TrendAnalysisResult(
        top_10=top_10,
        style_trends=style_trends,
        patterns=[],
        anomalies=[],
        timestamp="2026-05-14T00:00:00+08:00",
    )


def test_evaluate_returns_snapshots():
    result = _make_trend_result(["猫眼", "法式", "渐变"], [80.0, 60.0, 40.0])
    eval_result = evaluate(result, _EMPTY_LIBRARY)
    assert len(eval_result.snapshots) > 0


def test_evaluate_ranking_order():
    """Higher composite_score should generally rank higher."""
    result = _make_trend_result(["猫眼", "法式"], [90.0, 30.0])
    eval_result = evaluate(result, _EMPTY_LIBRARY)
    ranks = {s.keyword: s.rank for s in eval_result.snapshots}
    if "猫眼" in ranks and "法式" in ranks:
        assert ranks["猫眼"] <= ranks["法式"]


def test_evaluate_scores_in_range():
    result = _make_trend_result(["猫眼"], [75.0])
    eval_result = evaluate(result, _EMPTY_LIBRARY)
    for snap in eval_result.snapshots:
        assert 0.0 <= snap.external_heat_score <= 100.0
        assert 0.0 <= snap.trend_growth_score <= 100.0
        assert 0.0 <= snap.style_gap_score <= 100.0
        assert 0.0 <= snap.launch_priority_score <= 100.0


def test_evaluate_empty_trends():
    result = _make_trend_result([], [])
    eval_result = evaluate(result, _EMPTY_LIBRARY)
    assert eval_result.snapshots == []
