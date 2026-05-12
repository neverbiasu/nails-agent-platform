"""
CampaignAgent: LLM-powered marketing copywriter + campaign strategist.

Replaces the rule-based campaign_strategist + asset_generator workers.
Given trend analysis results, the agent generates:
  - Authentic platform-native copy (XHS 种草, Douyin hook, IG caption)
  - Pricing recommendations
  - Posting schedule
  - Full StyleCard entries

Anti-detection awareness built into system prompt:
  - XHS: avoid commercial trigger words (限时/爆款/立即购买)
  - Douyin: hook + story structure, no hard-sell openers
  - IG: English + emoji, lifestyle framing
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta, date
from typing import Any, Callable, Dict, List, Optional

from nails_agent.agents.base_tool_agent import ToolAgent, AgentResult
from nails_agent.models.schemas import (
    TrendAnalysisResult,
    CampaignStrategyResult,
    StyleCard,
    PlatformVariant,
    PricingInfo,
    PublishSchedule,
)

_TZ8 = timezone(timedelta(hours=8))

# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """\
You are a nail brand marketing strategist and copywriter for the Chinese market.
Your deliverables: for each trending nail style, generate a complete StyleCard
with authentic platform copy, pricing, and schedule.

COPY RULES — read carefully:
XHS (小红书):
  • Voice: first-person, conversational ("我最近迷上了…", "姐妹们求推荐…")
  • Format: 2–4 short paragraphs + 5–8 hashtags
  • Style: 种草式 (genuine discovery) or 提问式 (ask for recs)
  • NEVER use: 限时/爆款/立即购买/全网最低/秒杀/薅羊毛
  • DO NOT start with price or promo

Douyin:
  • Voice: hook sentence ≤ 15 chars to stop scroll, then 3-beat story
  • Structure: 痛点(pain) → 解法(solution) → 效果(result)
  • 1–3 hashtags, keep it punchy

Instagram:
  • Language: English + relevant emoji
  • Lifestyle framing — not product pitch
  • 10–15 hashtags, mix niche (#cateyenails) and broad (#nailart)

PRICING GUIDELINES:
  - 基础款 (simple single-color): ¥88–138
  - 进阶款 (gradient / texture): ¥138–188
  - 高端款 (3D / stone / hand-painted): ¥188–288+
  Priority: P0 for score ≥ 80, P1 for 50–80, P2 for < 50

Call create_style_card for each style. Call finalise_campaign once done with all cards.
"""

# ── Tool schemas ───────────────────────────────────────────────────────────────

_TOOLS = [
    {
        "name": "create_style_card",
        "description": (
            "Create a full StyleCard for one nail style. "
            "Provide complete platform copy for all three platforms."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "style_name": {"type": "string", "description": "e.g. '猫眼美甲'"},
                "style_id": {"type": "string", "description": "snake_case ID e.g. 'cat_eye'"},
                "trend_score": {
                    "type": "number",
                    "description": "Aggregated trend score from trend analysis",
                },
                "category": {
                    "type": "string",
                    "enum": ["style", "color", "material", "scene"],
                },
                "xhs_caption": {"type": "string", "description": "XHS post copy (2-4 paragraphs)"},
                "xhs_hashtags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "5–8 XHS hashtags WITHOUT # prefix",
                },
                "douyin_caption": {"type": "string", "description": "Douyin copy (hook + story)"},
                "douyin_hashtags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "1–3 Douyin hashtags",
                },
                "instagram_caption": {"type": "string", "description": "Instagram caption (English)"},
                "instagram_hashtags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "10–15 Instagram hashtags",
                },
                "base_price": {
                    "type": "string",
                    "description": "e.g. '¥138'",
                },
                "tier": {
                    "type": "string",
                    "enum": ["基础款", "进阶款", "高端款"],
                },
                "priority": {
                    "type": "string",
                    "enum": ["P0", "P1", "P2"],
                },
                "publish_day_offset": {
                    "type": "integer",
                    "description": "Days from today for XHS publish (0=today, 1=tomorrow…)",
                },
                "key_selling_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "3 bullet selling points for the style",
                },
            },
            "required": [
                "style_name", "style_id", "trend_score", "category",
                "xhs_caption", "xhs_hashtags",
                "douyin_caption", "douyin_hashtags",
                "instagram_caption", "instagram_hashtags",
                "base_price", "tier", "priority", "publish_day_offset",
            ],
        },
    },
    {
        "name": "finalise_campaign",
        "description": "Wrap up the campaign — call after all create_style_card calls are done.",
        "input_schema": {
            "type": "object",
            "properties": {
                "executive_summary": {
                    "type": "string",
                    "description": "2–3 sentence summary of the campaign strategy.",
                },
                "top_3_styles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Top 3 style names to push first.",
                },
            },
            "required": ["executive_summary", "top_3_styles"],
        },
    },
]


# ── Shared mutable state for tool callbacks ────────────────────────────────────

class _CampaignCollector:
    def __init__(self):
        self.cards: List[Dict[str, Any]] = []
        self.summary: Dict[str, Any] = {}

    def add_card(self, **kwargs) -> Dict[str, Any]:
        self.cards.append(kwargs)
        return {"status": "ok", "card": kwargs["style_name"]}

    def finalise(self, **kwargs) -> Dict[str, Any]:
        self.summary = kwargs
        return {"status": "ok", "total_cards": len(self.cards)}


# ── Internal schema builder ────────────────────────────────────────────────────

def _build_style_card(raw: Dict[str, Any]) -> StyleCard:
    today = date.today()
    offset = int(raw.get("publish_day_offset", 1))
    pub_date = today + timedelta(days=offset)

    xhs_tags = [t if t.startswith("#") else f"#{t}" for t in raw.get("xhs_hashtags", [])]
    dy_tags  = [t if t.startswith("#") else f"#{t}" for t in raw.get("douyin_hashtags", [])]
    ig_tags  = [t if t.startswith("#") else f"#{t}" for t in raw.get("instagram_hashtags", [])]

    style_name = raw["style_name"]
    return StyleCard(
        style_id=raw.get("style_id", style_name.lower().replace(" ", "_")),
        trend_id=raw.get("style_id", style_name),  # reuse style_id as trend_id
        style_name=style_name,
        style_tags=[style_name],
        launch_priority_score=float(raw.get("trend_score", 50)),
        platform_variants={
            "xiaohongshu": PlatformVariant(
                caption=raw.get("xhs_caption", ""),
                hashtags=xhs_tags,
            ),
            "douyin": PlatformVariant(
                caption=raw.get("douyin_caption", ""),
                hashtags=dy_tags,
            ),
            "instagram": PlatformVariant(
                caption=raw.get("instagram_caption", ""),
                hashtags=ig_tags,
            ),
        },
        pricing=PricingInfo(
            base_price=raw.get("base_price", "¥138"),
            tier=raw.get("tier", "进阶款"),
        ),
        schedule=PublishSchedule(
            priority=raw.get("priority", "P1"),
            xiaohongshu_publish_at=pub_date.isoformat(),
        ),
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def run_campaign_agent(
    trend_result: TrendAnalysisResult,
    max_cards: int = 6,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> CampaignStrategy:
    """
    Run the LLM-powered campaign agent and return a CampaignStrategy.
    Falls back to rule-based if API is unavailable.
    """
    collector = _CampaignCollector()

    # Build context from trend analysis
    trend_context = _format_trend_context(trend_result, max_cards)

    user_msg = (
        f"Create a full campaign strategy for these trending nail styles.\n\n"
        f"{trend_context}\n\n"
        f"Generate a StyleCard for each style (up to {max_cards}). "
        "Write authentic, platform-native copy. "
        "Call create_style_card for each, then finalise_campaign."
    )

    agent = ToolAgent(
        system_prompt=_SYSTEM,
        tools=_TOOLS,
        tool_functions={
            "create_style_card": collector.add_card,
            "finalise_campaign": collector.finalise,
        },
        max_iterations=25,
        max_tokens=8192,
    )

    result: AgentResult = agent.run(user_msg, progress_cb=progress_cb)

    if not result.success or not collector.cards:
        if progress_cb:
            progress_cb("⚠️ Campaign agent fallback → rule-based")
        return _rule_based_fallback(trend_result, progress_cb)

    style_cards = [_build_style_card(c) for c in collector.cards]

    return CampaignStrategyResult(
        style_cards=style_cards,
        executive_summary=collector.summary.get("executive_summary", ""),
        top_3_styles=collector.summary.get("top_3_styles", []),
        generated_at=datetime.now(_TZ8).isoformat(),
    )


def _format_trend_context(result: TrendAnalysisResult, max_styles: int) -> str:
    lines = ["## Trending Styles (by score)"]
    for st in result.style_trends[:max_styles]:
        lines.append(
            f"- **{st.tag}** — category: {st.category}, "
            f"posts: {st.post_count}, engagement: {st.total_engagement:,}, "
            f"score: {st.aggregated_score:.0f}"
            + (f'\n  Sample caption: "{st.sample_caption}"' if st.sample_caption else "")
        )
    if result.patterns:
        lines.append("\n## Observed Patterns")
        for p in result.patterns:
            lines.append(f"- {p}")
    if result.anomalies:
        lines.append("\n## Recent Anomalies (48 h)")
        for a in result.anomalies:
            lines.append(f"- {a}")
    return "\n".join(lines)


def _rule_based_fallback(
    trend_result: TrendAnalysisResult,
    progress_cb: Optional[Callable] = None,
) -> CampaignStrategyResult:
    from nails_agent.agents.workers.campaign_strategist import generate_campaign
    from nails_agent.models.schemas import ValueEvaluationResult, MetricSnapshot

    # Fake minimal ValueEvaluationResult for the old worker
    snapshots = [
        MetricSnapshot(
            rank=i + 1,
            keyword=st.tag,
            external_heat_score=min(100, st.aggregated_score),
            trend_growth_score=50.0,
            style_gap_score=50.0,
            launch_priority_score=min(100, st.aggregated_score),
        )
        for i, st in enumerate(trend_result.style_trends[:6])
    ]
    value_eval = ValueEvaluationResult(snapshots=snapshots)
    return generate_campaign(trend_result, value_eval)
