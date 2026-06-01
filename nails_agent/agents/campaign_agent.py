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
    output_dir = os.environ.get("NAILS_OUTPUT_DIR", "web/output")
    _clear_file(os.path.join(output_dir, "_campaign_cards.json"))
    _clear_file(os.path.join(output_dir, "campaign.json"))

    # Build context message
    context = _format_trend_context(trend_result, max_cards)
    user_msg = (
        f"为以下热门美甲款式生成完整运营策略。\n\n{context}\n\n"
        "要求：\n"
        f"1. 生成最多 {max_cards} 款不同风格的卡片，每款都要有三平台文案。\n"
        "2. style_name 必须具体，使用「颜色·风格」或「工艺·场景」格式，"
        "例如「蓝色猫眼·夏日」「裸粉渐变·通勤」「极简法式·约会」，"
        "禁止用「法式甲」「猫眼」这类泛名。\n"
        "3. 同一 tag 类型（如猫眼）最多出现 2 张卡片，确保整体多样性。\n"
        "完成后调用 finalise_campaign。"
    )

    try:
        import asyncio
        from nails_agent.agents.nail_agents import get_campaign_agent

        agent = get_campaign_agent()
        if progress_cb:
            progress_cb("🤖 CampaignAgent 启动 (Qwen3)…")

        asyncio.run(_run_with_progress(agent, user_msg, progress_cb, max_turns))
    except Exception as exc:
        logger.exception("CampaignAgent failed: %s", exc)
        if progress_cb:
            progress_cb(f"⚠️ Agent 异常 ({exc})，回退规则模式")
        return _rule_based_fallback(trend_result, progress_cb)

    return _load_campaign_result(output_dir, progress_cb)


async def _run_with_progress(agent, user_msg: str, progress_cb, max_turns: int):
    from nails_agent.agents.agent_config import run_streamed_with_fallback

    return await run_streamed_with_fallback(agent, user_msg, progress_cb, max_turns)


def _format_trend_context(result: "TrendAnalysisResult", max_styles: int) -> str:
    # Build a map from style tag → best matching signal (for display_label / color info)
    tag_to_signal: dict = {}
    for sig in result.top_10:
        for tag in sig.style_tags or []:
            if tag and tag not in tag_to_signal:
                tag_to_signal[tag] = sig

    lines = ["## 趋势数据（按热度排序）"]

    # Deduplicate by display_label to avoid repeating the same signal; also
    # cap same style-tag to 2 entries to ensure diversity.
    seen_labels: set = set()
    tag_card_count: dict = {}
    shown = 0
    for st in result.style_trends:
        if shown >= max_styles:
            break
        sig = tag_to_signal.get(st.tag)
        display = sig.display_label if sig and sig.display_label else st.tag
        # Skip if this display_label was already emitted
        if display in seen_labels:
            continue
        # Skip if this raw tag has hit its card cap
        if tag_card_count.get(st.tag, 0) >= 2:
            continue
        seen_labels.add(display)
        tag_card_count[st.tag] = tag_card_count.get(st.tag, 0) + 1
        shown += 1

        colors = ", ".join(sig.color_tags) if sig and sig.color_tags else ""
        color_str = f" | 颜色: {colors}" if colors else ""
        lines.append(
            f"- **{display}** | tag: {st.tag} | category: {st.category} | "
            f"帖数: {st.post_count} | 互动: {st.total_engagement:,} | "
            f"分: {st.aggregated_score:.0f}{color_str}"
            + (f'\n  样本文案: "{st.sample_caption[:60]}"' if st.sample_caption else "")
        )

    # If style_trends is empty or short, fall back to top_10 signals directly
    if shown == 0:
        seen_labels: set = set()
        for sig in result.top_10[:max_styles]:
            label = sig.display_label or (sig.style_tags[0] if sig.style_tags else sig.keyword)
            if label in seen_labels:
                continue
            seen_labels.add(label)
            colors = ", ".join(sig.color_tags) if sig.color_tags else ""
            color_str = f" | 颜色: {colors}" if colors else ""
            lines.append(f"- **{label}** | 关键词: {sig.keyword}{color_str} | 点赞: {sig.likes:,}")

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

    # IMPORTANT: use top_10 signals so the trend_id values match what
    # gen_assets() produces from the same top_10 list.  The original code used
    # st.tag as trend_id which caused a mismatch → all scores defaulted to 50 → P0=0.
    signals = trend_result.top_10[:6]
    if signals:
        # TrendSignal carries `composite_score`; fall back to raw engagement
        # (likes+comments+shares+collects) when the score wasn't computed.
        def _score(s) -> float:
            if getattr(s, "composite_score", 0):
                return float(s.composite_score)
            return float((s.likes or 0) + (s.comments or 0) + (s.shares or 0) + (s.collects or 0))

        max_score = max((_score(s) for s in signals), default=1.0) or 1.0
        snapshots = [
            MetricSnapshot(
                rank=i + 1,
                keyword=sig.keyword,
                trend_id=sig.trend_id,
                external_heat_score=round(min(100.0, _score(sig) / max_score * 100), 1),
                trend_growth_score=50.0,
                style_gap_score=50.0,
                launch_priority_score=round(min(100.0, _score(sig) / max_score * 100), 1),
            )
            for i, sig in enumerate(signals)
        ]
    else:
        # Fallback when top_10 is empty: use style_trends (trend_ids won't match
        # gen_assets drafts but there are also no drafts in that case).
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
