"""
Worker 3: Campaign Strategist
Input:  ValueEvaluationResult + AssetGenerationResult
Output: CampaignStrategyResult

Merges metric scores with drafted style cards, assigns publish schedule,
and produces final StyleCard objects ready for execution.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from nails_agent.models.schemas import (
    ValueEvaluationResult,
    AssetGenerationResult,
    MetricSnapshot,
    StyleCard,
    PublishSchedule,
    CampaignStrategyResult,
)

_TZ8 = timezone(timedelta(hours=8))


def _priority_tier(score: float) -> str:
    """
    Dynamic tiers: top ~30% → P0, next ~40% → P1, rest → P2.
    Hard threshold fallback: ≥65 P0, ≥45 P1.
    """
    if score >= 65:
        return "P0"
    if score >= 45:
        return "P1"
    return "P2"


def _next_slot(base: datetime, offset_days: int, hour: int) -> str:
    """Return ISO8601 for next occurrence of `hour:00` after base + offset_days."""
    target = base + timedelta(days=offset_days)
    target = target.replace(hour=hour, minute=0, second=0, microsecond=0)
    return target.isoformat()


def build_schedule(metric: MetricSnapshot, base: datetime) -> PublishSchedule:
    tier = _priority_tier(metric.launch_priority_score)
    if tier == "P0":
        # Publish immediately across all platforms
        return PublishSchedule(
            priority="P0",
            xiaohongshu_publish_at=_next_slot(base, 0, 20),
            douyin_publish_at=_next_slot(base, 1, 18),
            instagram_publish_at=_next_slot(base, 2, 10),
        )
    if tier == "P1":
        return PublishSchedule(
            priority="P1",
            xiaohongshu_publish_at=_next_slot(base, 2, 20),
            douyin_publish_at=_next_slot(base, 3, 18),
            instagram_publish_at=_next_slot(base, 4, 10),
        )
    return PublishSchedule(
        priority="P2",
        xiaohongshu_publish_at=_next_slot(base, 7, 20),
        douyin_publish_at=_next_slot(base, 8, 18),
        instagram_publish_at=_next_slot(base, 9, 10),
    )


def strategise(
    value_result: ValueEvaluationResult,
    asset_result: AssetGenerationResult,
) -> CampaignStrategyResult:
    now = datetime.now(_TZ8)

    # Index metrics by trend_id
    metric_map: Dict[str, MetricSnapshot] = {m.trend_id: m for m in value_result.snapshots}

    style_cards: List[StyleCard] = []
    for draft in asset_result.drafts:
        metric = metric_map.get(draft.trend_id)
        score = metric.launch_priority_score if metric else 50.0
        schedule = build_schedule(metric, now) if metric else PublishSchedule()

        data = draft.model_dump()
        data["launch_priority_score"] = score
        card = StyleCard(
            **data,
            style_id=draft.trend_id.lower().replace("trend_", "sc_"),
            generation_status="success",
            schedule=schedule,
        )
        style_cards.append(card)

    # Sort by priority score descending
    style_cards.sort(key=lambda c: c.launch_priority_score, reverse=True)

    return CampaignStrategyResult(
        style_cards=style_cards,
        timestamp=now.isoformat(),
    )


def from_files(value_path: str, asset_path: str) -> CampaignStrategyResult:
    with open(value_path, encoding="utf-8") as f:
        value_result = ValueEvaluationResult(**json.load(f))
    with open(asset_path, encoding="utf-8") as f:
        asset_result = AssetGenerationResult(**json.load(f))
    return strategise(value_result, asset_result)
