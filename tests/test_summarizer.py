"""
A12 — Summarizer + ValueEvaluator integration tests.

Verifies that:
  - CandidatePackage.review_score reflects ValueEvaluationResult data
  - review_score increases when value_evaluation has high-priority snapshots
  - Summarizer writes SummaryEvent to EventLog
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from nails_agent.agents.summarizer import Summarizer
from nails_agent.memory.event_log import EventLog
from nails_agent.models.schemas import (
    CandidatePackage,
    MetricSnapshot,
    PipelineState,
    StyleTrend,
    TrendAnalysisResult,
    TrendSignal,
    ValueEvaluationResult,
)


def _make_state(
    *,
    with_trend: bool = True,
    with_value: bool = False,
    value_priority: float = 80.0,
) -> PipelineState:
    state = PipelineState(pipeline_id="P001")

    if with_trend:
        signals = [
            TrendSignal(
                trend_id=f"T{i}",
                platform="小红书",
                keyword="猫眼",
                caption="猫眼美甲 推荐",
                likes=500 * (i + 1),
                collects=100,
                composite_score=70.0,
                rank=i,
            )
            for i in range(10)
        ]
        state.trend_analysis = TrendAnalysisResult(
            top_10=signals,
            style_trends=[
                StyleTrend(
                    tag="猫眼",
                    category="style",
                    post_count=80,
                    total_engagement=50000,
                    aggregated_score=85.0,
                )
            ],
            patterns=["猫眼+粉色 跨平台共振"],
            anomalies=[],
        )

    if with_value:
        snap = MetricSnapshot(
            trend_id="T0",
            keyword="猫眼",
            external_heat_score=value_priority,
            trend_growth_score=70.0,
            style_gap_score=60.0,
            launch_priority_score=value_priority,
            rank=1,
        )
        state.value_evaluation = ValueEvaluationResult(snapshots=[snap])

    return state


# ──────────────────────────────────────────────
# Basic output shape
# ──────────────────────────────────────────────


def test_summarise_returns_candidate_package():
    with tempfile.TemporaryDirectory() as tmp:
        el = EventLog(db_path=Path(tmp) / "test.db")
        summarizer = Summarizer(event_log=el)
        state = _make_state(with_trend=True)
        pkg = summarizer.summarise(trigger_id="t001", state=state)
        assert isinstance(pkg, CandidatePackage)
        assert pkg.trigger_id == "t001"
        assert len(pkg.trend_summary) > 0
        assert 0.0 <= pkg.review_score <= 1.0


def test_summarise_no_data_returns_zero_score():
    with tempfile.TemporaryDirectory() as tmp:
        el = EventLog(db_path=Path(tmp) / "test.db")
        summarizer = Summarizer(event_log=el)
        state = _make_state(with_trend=False, with_value=False)
        pkg = summarizer.summarise(trigger_id="t_empty", state=state)
        assert pkg.review_score == 0.0


# ──────────────────────────────────────────────
# A12: ValueEvaluationResult lifts review_score
# ──────────────────────────────────────────────


def test_review_score_higher_with_value_evaluation():
    """CandidatePackage.review_score must be higher when ValueEvaluationResult is present."""
    with tempfile.TemporaryDirectory() as tmp:
        el = EventLog(db_path=Path(tmp) / "test.db")
        summarizer = Summarizer(event_log=el)

        score_without = summarizer.summarise(
            trigger_id="t_no_val", state=_make_state(with_value=False)
        ).review_score

        score_with = summarizer.summarise(
            trigger_id="t_with_val",
            state=_make_state(with_value=True, value_priority=90.0),
        ).review_score

        assert score_with > score_without, (
            f"Expected value_evaluation to increase review_score, "
            f"got {score_with:.3f} <= {score_without:.3f}"
        )


def test_review_score_scales_with_priority():
    """Higher launch_priority_score should yield higher review_score."""
    with tempfile.TemporaryDirectory() as tmp:
        el = EventLog(db_path=Path(tmp) / "test.db")
        summarizer = Summarizer(event_log=el)

        low_score = summarizer.summarise(
            trigger_id="t_low",
            state=_make_state(with_value=True, value_priority=10.0),
        ).review_score

        high_score = summarizer.summarise(
            trigger_id="t_high",
            state=_make_state(with_value=True, value_priority=90.0),
        ).review_score

        assert high_score > low_score


# ──────────────────────────────────────────────
# EventLog persistence
# ──────────────────────────────────────────────


def test_summarise_writes_summary_event():
    with tempfile.TemporaryDirectory() as tmp:
        el = EventLog(db_path=Path(tmp) / "test.db")
        summarizer = Summarizer(event_log=el)
        state = _make_state(with_trend=True)
        summarizer.summarise(trigger_id="t_event", state=state)

        events = el.list_by_trigger(trigger_id="t_event")
        event_types = [e.event_type for e in events]
        assert "SummaryEvent" in event_types

        # CandidatePackage should be persisted
        candidate = el.get_candidate(trigger_id="t_event")
        assert candidate is not None
        assert candidate.trigger_id == "t_event"
