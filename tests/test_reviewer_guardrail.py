"""Tests for ReviewerGuardrail rule layer — all 3 status outcomes (A5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nails_agent.agents.reviewer_guardrail import ReviewerGuardrail
from nails_agent.memory.event_log import EventLog
from nails_agent.models.schemas import CandidatePackage


@pytest.fixture()
def guardrail(tmp_path: Path) -> ReviewerGuardrail:
    el = EventLog(db_path=tmp_path / "test_review.db")
    # First save a candidate so update_candidate_review can find it
    return ReviewerGuardrail(event_log=el)


def _pkg(
    trigger_id: str, score: float, trend: str = "法式甲渐变色", strategy: str = "周末发布"
) -> CandidatePackage:
    pkg = CandidatePackage(
        trigger_id=trigger_id,
        trend_summary=trend,
        strategy=strategy,
        review_score=score,
    )
    return pkg


def _save_and_review(guardrail: ReviewerGuardrail, pkg: CandidatePackage):
    """Save candidate first so update_candidate_review doesn't silently fail."""
    guardrail.event_log.save_candidate(pkg)
    return guardrail.review(pkg)


def test_reject_on_low_score(guardrail: ReviewerGuardrail) -> None:
    pkg = _pkg("t-reject-score", score=0.1)
    decision = _save_and_review(guardrail, pkg)
    assert decision.status == "reject"
    assert len(decision.risk_flags) > 0


def test_reject_on_blacklist_keyword(guardrail: ReviewerGuardrail) -> None:
    pkg = _pkg("t-reject-blist", score=0.8, trend="违规款式大爆款", strategy="快速刷单上热门")
    decision = _save_and_review(guardrail, pkg)
    assert decision.status == "reject"
    assert any("敏感词" in f or "违规" in f or "刷单" in f for f in decision.risk_flags)


def test_revise_on_borderline_score(guardrail: ReviewerGuardrail) -> None:
    pkg = _pkg("t-revise", score=0.45)
    decision = _save_and_review(guardrail, pkg)
    assert decision.status == "revise"
    assert len(decision.suggestions) > 0


def test_pass_on_good_score(guardrail: ReviewerGuardrail) -> None:
    pkg = _pkg("t-pass", score=0.75)
    decision = _save_and_review(guardrail, pkg)
    assert decision.status == "pass"


def test_review_event_written_to_event_log(guardrail: ReviewerGuardrail) -> None:
    pkg = _pkg("t-eventlog", score=0.8)
    guardrail.event_log.save_candidate(pkg)
    guardrail.review(pkg)

    entries = guardrail.event_log.list_by_trigger("t-eventlog")
    event_types = [e.event_type for e in entries]
    assert "ReviewEvent" in event_types


def test_pass_sets_candidate_review_status_to_pending_human(guardrail: ReviewerGuardrail) -> None:
    pkg = _pkg("t-pending-human", score=0.9)
    guardrail.event_log.save_candidate(pkg)
    decision = guardrail.review(pkg)

    assert decision.status == "pass"

    with guardrail.event_log._store._conn() as conn:
        row = conn.execute(
            "SELECT review_status FROM candidate_packages WHERE trigger_id = ?",
            ("t-pending-human",),
        ).fetchone()
    assert row["review_status"] == "pending_human"


def test_reject_sets_candidate_review_status_to_rejected(guardrail: ReviewerGuardrail) -> None:
    pkg = _pkg("t-rejected", score=0.05)
    guardrail.event_log.save_candidate(pkg)
    decision = guardrail.review(pkg)

    assert decision.status == "reject"

    with guardrail.event_log._store._conn() as conn:
        row = conn.execute(
            "SELECT review_status FROM candidate_packages WHERE trigger_id = ?",
            ("t-rejected",),
        ).fetchone()
    assert row["review_status"] == "rejected"
