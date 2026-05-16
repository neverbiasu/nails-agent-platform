"""
Summarizer Agent — collects TrendAnalysisResult + CampaignStrategyResult and
formats them into a CandidatePackage ready for ReviewerGuardrail.

Does NOT make review decisions (that is Reviewer's job).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from nails_agent.memory.event_log import EventLog
from nails_agent.models.schemas import (
    CandidatePackage,
    PipelineState,
    TrendAnalysisResult,
    CampaignStrategyResult,
)

logger = logging.getLogger(__name__)

AGENT_ID = "Summarizer"


class Summarizer:
    def __init__(self, event_log: Optional[EventLog] = None, db_path: Optional[Path] = None):
        self.event_log = event_log or EventLog(db_path=db_path)

    def summarise(
        self,
        trigger_id: str,
        state: PipelineState,
    ) -> CandidatePackage:
        trend: Optional[TrendAnalysisResult] = state.trend_analysis
        campaign: Optional[CampaignStrategyResult] = state.campaign_strategy

        # ── Build trend_summary ───────────────────────────────────────────────
        if trend and trend.style_trends:
            top_tags = [t.tag for t in trend.style_trends[:5]]
            trend_summary = f"本轮趋势热词：{', '.join(top_tags)}。" + (
                f" 核心风格规律：{'; '.join(trend.patterns[:2])}" if trend.patterns else ""
            )
        elif trend and trend.top_10:
            trend_summary = f"Top 关键词：{', '.join(s.keyword for s in trend.top_10[:5])}"
        else:
            trend_summary = "暂无趋势数据"

        # ── Build strategy ────────────────────────────────────────────────────
        if campaign and campaign.style_cards:
            p0_cards = [
                c for c in campaign.style_cards if c.schedule and c.schedule.priority == "P0"
            ]
            strategy = campaign.executive_summary or (
                f"共 {len(campaign.style_cards)} 张运营卡片，其中 {len(p0_cards)} 张 P0 立即上线。"
            )
        else:
            strategy = "策略生成中"

        # ── Collect asset references ──────────────────────────────────────────
        assets: list[str] = []
        if state.asset_generation:
            assets = [d.image_url for d in state.asset_generation.drafts if d.image_url]

        # ── Compute review_score ──────────────────────────────────────────────
        review_score = self._compute_review_score(state)

        pkg = CandidatePackage(
            trigger_id=trigger_id,
            trend_summary=trend_summary,
            strategy=strategy,
            assets=assets,
            review_score=review_score,
        )

        # Persist candidate
        self.event_log.save_candidate(pkg)

        # Write SummaryEvent to chain
        self.event_log.write(
            event_type="SummaryEvent",
            payload=pkg.model_dump(),
            trigger_id=trigger_id,
            agent_id=AGENT_ID,
        )
        logger.info(
            "Summarizer: CandidatePackage saved (trigger=%s, score=%.2f)", trigger_id, review_score
        )
        return pkg

    def _compute_review_score(self, state: PipelineState) -> float:
        """
        Heuristic review score in [0, 1].
        Higher = better quality candidate, more likely to pass ReviewerGuardrail.
        """
        score = 0.0
        if state.trend_analysis and state.trend_analysis.top_10:
            signal_count = len(state.trend_analysis.top_10)
            score += min(0.3, signal_count / 30)
        if state.value_evaluation and state.value_evaluation.snapshots:
            top_priority = state.value_evaluation.snapshots[0].launch_priority_score
            score += min(0.4, top_priority / 100 * 0.4)
        if state.campaign_strategy and state.campaign_strategy.style_cards:
            card_count = len(state.campaign_strategy.style_cards)
            score += min(0.3, card_count / 10 * 0.3)
        return round(min(1.0, score), 3)
