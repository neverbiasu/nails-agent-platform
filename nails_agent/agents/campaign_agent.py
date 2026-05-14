"""
CampaignAgent — public API for running campaign strategy generation.

Uses openai-agents SDK Runner with CampaignAgent (Qwen3 / Claude via OpenRouter).
Falls back to rule-based if no API key is available.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta, date
from typing import TYPE_CHECKING, Callable, List, Optional

if TYPE_CHECKING:
    from nails_agent.models.schemas import CampaignStrategyResult, StyleCard, TrendAnalysisResult

logger = logging.getLogger(__name__)
_TZ8 = timezone(timedelta(hours=8))


def run_campaign_agent(
    trend_result: "TrendAnalysisResult",
    max_cards: int = 6,
    progress_cb: Optional[Callable[[str], None]] = None,
    max_turns: int = 30,
) -> "CampaignStrategyResult":
    """
    Run the LLM-powered CampaignAgent and return a CampaignStrategyResult.
    Falls back to rule-based if no API key is available.
    """
    from nails_agent.agents.agent_config import is_available

    if not is_available():
        if progress_cb:
            progress_cb("⚠️ 无 API key → 规则引擎模式")
        return _rule_based_fallback(trend_result, progress_cb)

    # Clear old campaign cards
    output_dir = os.environ.get("NAILS_OUTPUT_DIR", "demo/output")
    _clear_file(os.path.join(output_dir, "_campaign_cards.json"))
    _clear_file(os.path.join(output_dir, "campaign.json"))

    # Build context message
    context = _format_trend_context(trend_result, max_cards)
    user_msg = (
        f"为以下热门美甲款式生成完整运营策略。\n\n{context}\n\n"
        f"生成最多 {max_cards} 款的风格卡片，每款都要有三平台文案。"
        "完成后调用 finalise_campaign。"
    )

    try:
        import asyncio
        from nails_agent.agents.nail_agents import get_campaign_agent

        agent = get_campaign_agent()
        if progress_cb:
            progress_cb("🤖 CampaignAgent 启动 (Qwen3)…")

        asyncio.get_event_loop().run_until_complete(
            _run_with_progress(agent, user_msg, progress_cb, max_turns)
        )
    except Exception as exc:
        logger.exception("CampaignAgent failed: %s", exc)
        if progress_cb:
            progress_cb(f"⚠️ Agent 异常 ({exc})，回退规则模式")
        return _rule_based_fallback(trend_result, progress_cb)

    return _load_campaign_result(output_dir, progress_cb)


async def _run_with_progress(agent, user_msg: str, progress_cb, max_turns: int):
    from agents import Runner

    async with Runner.run_streamed(agent, user_msg, max_turns=max_turns) as stream:
        async for event in stream.stream_events():
            if hasattr(event, "type") and event.type == "run_item_stream_event":
                item = event.item
                if hasattr(item, "raw_item"):
                    ri = item.raw_item
                    name = getattr(ri, "name", "") if hasattr(ri, "name") else ""
                    if name and progress_cb:
                        progress_cb(f"🔧 {name}(…)")
    return stream.final_output


def _format_trend_context(result: "TrendAnalysisResult", max_styles: int) -> str:
    lines = ["## 趋势数据（按热度排序）"]
    for st in result.style_trends[:max_styles]:
        lines.append(
            f"- **{st.tag}** | category: {st.category} | "
            f"帖数: {st.post_count} | 互动: {st.total_engagement:,} | "
            f"分: {st.aggregated_score:.0f}"
            + (f'\n  样本文案: "{st.sample_caption[:60]}"' if st.sample_caption else "")
        )
    if result.patterns:
        lines.append("\n## 观察到的模式")
        for p in result.patterns[:3]:
            lines.append(f"- {p}")
    if result.anomalies:
        lines.append("\n## 48h 突发趋势")
        for a in result.anomalies[:3]:
            lines.append(f"- {a}")
    return "\n".join(lines)


def _load_campaign_result(output_dir: str, progress_cb) -> "CampaignStrategyResult":
    from nails_agent.models.schemas import CampaignStrategyResult

    campaign_path = os.path.join(output_dir, "campaign.json")
    try:
        with open(campaign_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("campaign.json not found: %s", exc)
        return CampaignStrategyResult(style_cards=[])

    summary = data.get("summary", {})
    style_cards: List[StyleCard] = []
    for raw in data.get("cards", []):
        try:
            style_cards.append(_build_style_card(raw))
        except Exception as e:
            logger.warning("Skipped malformed card %s: %s", raw.get("style_name"), e)

    result = CampaignStrategyResult(
        style_cards=style_cards,
        executive_summary=summary.get("executive_summary", ""),
        top_3_styles=summary.get("top_3_styles", []),
        generated_at=datetime.now(_TZ8).isoformat(),
    )
    if progress_cb:
        progress_cb(f"✅ 运营策略完成：{len(style_cards)} 张风格卡片")
    return result


def _build_style_card(raw: dict) -> "StyleCard":
    from nails_agent.models.schemas import StyleCard, PlatformVariant, PricingInfo, PublishSchedule

    today = date.today()
    offset = int(raw.get("publish_day_offset", 1))
    pub_date = today + timedelta(days=offset)

    return StyleCard(
        style_id=raw.get("style_id", raw["style_name"]),
        trend_id=raw.get("style_id", raw["style_name"]),
        style_name=raw["style_name"],
        style_tags=[raw["style_name"]],
        launch_priority_score=float(raw.get("trend_score", 50)),
        platform_variants={
            "xiaohongshu": PlatformVariant(
                caption=raw.get("xhs_caption", ""),
                hashtags=raw.get("xhs_hashtags", []),
            ),
            "douyin": PlatformVariant(
                caption=raw.get("douyin_caption", ""),
                hashtags=raw.get("douyin_hashtags", []),
            ),
            "instagram": PlatformVariant(
                caption=raw.get("instagram_caption", ""),
                hashtags=raw.get("instagram_hashtags", []),
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


def _rule_based_fallback(trend_result, progress_cb) -> "CampaignStrategyResult":
    from nails_agent.agents.workers.campaign_strategist import generate_campaign
    from nails_agent.models.schemas import ValueEvaluationResult, MetricSnapshot

    snapshots = [
        MetricSnapshot(
            rank=i + 1,
            keyword=st.tag,
            trend_id=st.tag,
            external_heat_score=min(100, st.aggregated_score),
            trend_growth_score=50.0,
            style_gap_score=50.0,
            launch_priority_score=min(100, st.aggregated_score),
        )
        for i, st in enumerate(trend_result.style_trends[:6])
    ]
    value_eval = ValueEvaluationResult(snapshots=snapshots)
    return generate_campaign(trend_result, value_eval)


def _clear_file(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
