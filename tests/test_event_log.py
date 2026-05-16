"""Tests for EventLog write/read and CandidatePackage persistence (A1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nails_agent.memory.event_log import EventLog
from nails_agent.models.schemas import CandidatePackage, ReviewDecision


@pytest.fixture()
def event_log(tmp_path: Path) -> EventLog:
    return EventLog(db_path=tmp_path / "test_memory.db")


def test_write_and_read_by_trigger(event_log: EventLog) -> None:
    trigger_id = "test-trigger-001"

    e1 = event_log.write(
        event_type="TriggerEvent",
        payload={"source": "manual", "keywords": ["French tips"]},
        trigger_id=trigger_id,
        agent_id="TriggerGateway",
    )
    e2 = event_log.write(
        event_type="TrendEvent",
        payload={"top_keywords": ["French tips", "nail art"], "confidence": 0.85},
        trigger_id=trigger_id,
        agent_id="TrendAnalyst",
    )

    entries = event_log.list_by_trigger(trigger_id)

    assert len(entries) == 2
    assert entries[0].id == e1.id
    assert entries[0].event_type == "TriggerEvent"
    assert entries[0].payload["source"] == "manual"
    assert entries[1].id == e2.id
    assert entries[1].event_type == "TrendEvent"
    assert entries[1].agent_id == "TrendAnalyst"


def test_list_by_trigger_pagination(event_log: EventLog) -> None:
    trigger_id = "test-trigger-002"
    for i in range(5):
        event_log.write(event_type=f"Event{i}", payload={"i": i}, trigger_id=trigger_id)

    page1 = event_log.list_by_trigger(trigger_id, limit=3, offset=0)
    page2 = event_log.list_by_trigger(trigger_id, limit=3, offset=3)

    assert len(page1) == 3
    assert len(page2) == 2


def test_list_recent(event_log: EventLog) -> None:
    event_log.write(event_type="TriggerEvent", payload={}, trigger_id="t1")
    event_log.write(event_type="TrendEvent", payload={}, trigger_id="t2")

    recent = event_log.list_recent(limit=10)
    assert len(recent) == 2


def test_trigger_isolation(event_log: EventLog) -> None:
    event_log.write(event_type="TriggerEvent", payload={}, trigger_id="trigger-A")
    event_log.write(event_type="TrendEvent", payload={}, trigger_id="trigger-B")

    a_entries = event_log.list_by_trigger("trigger-A")
    b_entries = event_log.list_by_trigger("trigger-B")

    assert len(a_entries) == 1
    assert len(b_entries) == 1
    assert a_entries[0].trigger_id == "trigger-A"
    assert b_entries[0].trigger_id == "trigger-B"


def test_save_and_get_candidate(event_log: EventLog) -> None:
    trigger_id = "test-trigger-003"
    pkg = CandidatePackage(
        trigger_id=trigger_id,
        trend_summary="法式甲和渐变色是本周 XHS 热门趋势",
        strategy="推荐在周末发布短视频内容，配合活动促销",
        assets=["asset_001.png"],
        review_score=0.82,
    )

    event_log.save_candidate(pkg)
    retrieved = event_log.get_candidate(trigger_id)

    assert retrieved is not None
    assert retrieved.trigger_id == trigger_id
    assert retrieved.review_score == pytest.approx(0.82)
    assert "法式甲" in retrieved.trend_summary


def test_update_candidate_review(event_log: EventLog) -> None:
    trigger_id = "test-trigger-004"
    pkg = CandidatePackage(
        trigger_id=trigger_id,
        trend_summary="Test trend",
        strategy="Test strategy",
        review_score=0.7,
    )
    event_log.save_candidate(pkg)

    decision = ReviewDecision(
        status="pass",
        reason="内容质量达标，风险可控",
        suggestions=["可适当增加互动话题"],
        risk_flags=[],
    )
    event_log.update_candidate_review(trigger_id, decision, status="pending_human")

    # Verify review_status updated in DB
    with event_log._store._conn() as conn:
        row = conn.execute(
            "SELECT review_status, review_output FROM candidate_packages WHERE trigger_id = ?",
            (trigger_id,),
        ).fetchone()

    assert row["review_status"] == "pending_human"
    import json

    output = json.loads(row["review_output"])
    assert output["status"] == "pass"
    assert "内容质量达标" in output["reason"]


def test_get_candidate_returns_none_when_missing(event_log: EventLog) -> None:
    result = event_log.get_candidate("nonexistent-trigger")
    assert result is None
