"""
Worker 4: Summarizer
Input:  PipelineState (all step outputs)
Output: SummaryReport (with .markdown field)

Tone goal:
- Lead with concrete style observations (what's hot, by what margin).
- Quote real post captions as evidence; avoid generic "AI 智能" phrasing.
- Tables over flowery prose where numbers fit.
- One short verdict line per section, not a paragraph.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List

from nails_agent.models.schemas import (
    PipelineState,
    SummaryReport,
    ReportSection,
)

_TZ8 = timezone(timedelta(hours=8))

_CATEGORY_LABEL = {
    "style": "款式",
    "color": "色系",
    "material": "材质",
    "scene": "场景",
}


def summarise(state: PipelineState) -> SummaryReport:
    now = datetime.now(_TZ8)
    sections: List[ReportSection] = []

    trend = state.trend_analysis
    value = state.value_evaluation
    campaign = state.campaign_strategy
    assets = state.asset_generation

    # ── Section 1: What's hot ─────────────────────────────────────────────────
    if trend:
        lines = []
        platforms_seen = sorted({s.platform for s in trend.top_10})
        lines.append(
            f"`{now.strftime('%Y-%m-%d')}` · 来源 {' / '.join(platforms_seen) or '—'} "
            f"· 共分析 {len(trend.top_10)} 个 top 帖"
        )
        lines.append("")

        if trend.style_trends:
            lines.append("**款式热度（按聚合互动量）**")
            lines.append("")
            lines.append("| 标签 | 类别 | 出现帖数 | 累计互动 | 相对热度 |")
            lines.append("|------|------|---------:|---------:|---------:|")
            for st in trend.style_trends[:8]:
                lines.append(
                    f"| {st.tag} | {_CATEGORY_LABEL.get(st.category, st.category)} | "
                    f"{st.post_count} | {st.total_engagement:,} | {st.aggregated_score:.0f} |"
                )
            lines.append("")
            top = trend.style_trends[0]
            if top.sample_caption:
                lines.append(f"> 代表帖（标签「{top.tag}」）：「{top.sample_caption}」")
                lines.append("")
        else:
            lines.append("_未提取到稳定的风格标签，建议扩充关键词或观察更长时间窗口。_")
            lines.append("")

        if trend.patterns:
            lines.append("**风格组合**")
            for p in trend.patterns:
                lines.append(f"- {p}")
            lines.append("")

        if trend.anomalies:
            lines.append("**近 48h 突发热度**")
            for a in trend.anomalies:
                lines.append(f"- {a}")

        sections.append(ReportSection(title="📈 趋势观察", content="\n".join(lines)))

    # ── Section 2: Value evaluation ──────────────────────────────────────────
    if value and value.snapshots:
        lines = [
            "_注：本表按单帖排序，「来源关键词」是发现该帖时所用的搜索词，不代表风格名。_",
            "",
            "| 排名 | 来源关键词 | 外部热度 | 新鲜度 | 风格缺口 | 上线优先级 |",
            "|------|------------|---------:|-------:|---------:|-----------:|",
        ]
        for s in value.snapshots[:5]:
            lines.append(
                f"| {s.rank} | {s.keyword} | {s.external_heat_score:.0f} "
                f"| {s.trend_growth_score:.0f} | {s.style_gap_score:.0f} "
                f"| **{s.launch_priority_score:.0f}** |"
            )
        lines.append("")
        if value.snapshots[0].launch_priority_score >= 80:
            lines.append(
                f"→ Top 1 优先级 {value.snapshots[0].launch_priority_score:.0f}，值得立刻上线。"
            )
        sections.append(ReportSection(title="💎 价值评估", content="\n".join(lines)))

    # ── Section 3: Strategy ──────────────────────────────────────────────────
    if campaign and campaign.style_cards:
        p0 = [c for c in campaign.style_cards if c.schedule and c.schedule.priority == "P0"]
        p1 = [c for c in campaign.style_cards if c.schedule and c.schedule.priority == "P1"]
        p2 = [c for c in campaign.style_cards if c.schedule and c.schedule.priority == "P2"]
        lines = [
            f"共 {len(campaign.style_cards)} 张卡片 · P0 {len(p0)} / P1 {len(p1)} / P2 {len(p2)}",
            "",
        ]
        if p0:
            lines.append("**P0 立即上线**")
            for c in p0:
                price = c.pricing.base_price if c.pricing and c.pricing.base_price else "待定价"
                sched = c.schedule.xiaohongshu_publish_at[:10] if c.schedule else "TBD"
                lines.append(f"- {c.style_name} · {price} · 小红书 {sched}")
            lines.append("")
        if p1:
            lines.append("**P1 本周排期**")
            for c in p1[:4]:
                price = c.pricing.base_price if c.pricing and c.pricing.base_price else "待定价"
                lines.append(f"- {c.style_name} · {price}")
        sections.append(ReportSection(title="📣 运营策略", content="\n".join(lines)))

    # ── Section 4: Assets ────────────────────────────────────────────────────
    if assets and assets.drafts:
        lines = [f"已生成 {len(assets.drafts)} 张款式卡片草稿（含 3 平台变体）。", ""]
        xhs_samples = []
        for draft in assets.drafts[:3]:
            xhs = draft.platform_variants.get("xiaohongshu") if draft.platform_variants else None
            if xhs and getattr(xhs, "caption", ""):
                xhs_samples.append((draft.style_name, xhs.caption, list(xhs.hashtags or [])[:5]))
        if xhs_samples:
            lines.append("**小红书文案样例**")
            for name, cap, tags in xhs_samples:
                lines.append(f"- **{name}**")
                lines.append(f"  > {cap}")
                if tags:
                    # Some sources already include leading '#'; normalise.
                    tag_strs = [t if str(t).startswith("#") else f"#{t}" for t in tags]
                    lines.append(f"  > 标签 {' '.join(tag_strs)}")
                lines.append("")
        sections.append(ReportSection(title="🎨 素材资产", content="\n".join(lines)))

    # ── Assemble ─────────────────────────────────────────────────────────────
    md_parts = [
        "# 本轮运营简报",
        f"`{now.strftime('%Y-%m-%d %H:%M')}` · pipeline `{state.pipeline_id}`",
        "",
    ]
    for sec in sections:
        md_parts.append(f"## {sec.title}")
        md_parts.append("")
        md_parts.append(sec.content)
        md_parts.append("")

    top_3_tags: List[str] = []
    if trend and trend.style_trends:
        top_3_tags = [t.tag for t in trend.style_trends[:3]]
    elif value and value.snapshots:
        top_3_tags = [s.keyword for s in value.snapshots[:3]]

    return SummaryReport(
        pipeline_id=state.pipeline_id,
        sections=sections,
        top_3_keywords=top_3_tags,
        total_trends_analyzed=len(trend.top_10) if trend else 0,
        total_style_cards=len(campaign.style_cards) if campaign else 0,
        markdown="\n".join(md_parts),
        timestamp=now.isoformat(),
    )
