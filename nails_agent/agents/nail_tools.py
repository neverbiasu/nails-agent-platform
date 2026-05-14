"""
All @function_tool definitions for the Nails Agent Platform.

Tools are pure Python functions decorated with @function_tool from openai-agents.
They can be shared across multiple Agent instances (TrendScout, Campaign, etc.).

Tool naming convention: verb_noun (search_xhs, write_xhs_copy, schedule_posts)
"""

from __future__ import annotations

import json
import os
from typing import Optional

from agents import function_tool


# ══════════════════════════════════════════════════════════════════════════════
# Data Collection Tools
# ══════════════════════════════════════════════════════════════════════════════


@function_tool
def search_xhs(keywords: list[str], limit_per_keyword: int = 20) -> str:
    """
    Search Xiaohongshu (小红书) for nail trend posts.
    Returns JSON list of post signals with title, tags, likes, collects.
    Each signal has: trend_id, caption, style_tags, likes, collects, publish_time.
    """
    try:
        from nails_agent.tools.fetchers.xhs_mcp_fetcher import XHSMCPFetcher

        fetcher = XHSMCPFetcher()
        if not fetcher.is_available():
            return json.dumps({"error": "XHS MCP server not running", "signals": []})
        signals = []
        for kw in keywords:
            batch = fetcher.search(kw, limit=limit_per_keyword)
            signals.extend(s.model_dump() for s in batch)
        # Deduplicate
        seen, unique = set(), []
        for s in signals:
            tid = s.get("trend_id", "")
            if tid and tid not in seen:
                seen.add(tid)
                unique.append(s)
            elif not tid:
                unique.append(s)
        return json.dumps(
            {"count": len(unique), "signals": unique}, ensure_ascii=False, default=str
        )
    except Exception as exc:
        return json.dumps({"error": str(exc), "signals": []})


@function_tool
def search_douyin(keywords: list[str], limit_per_keyword: int = 15) -> str:
    """
    Search Douyin (抖音) for nail trend videos.
    Returns JSON list of signals with caption, likes, shares, style_tags.
    """
    try:
        from nails_agent.tools.fetchers.douyin_cdp import DouyinCDPFetcher

        fetcher = DouyinCDPFetcher()
        signals = fetcher.search(keywords, limit_per_kw=limit_per_keyword)
        return json.dumps(
            {"count": len(signals), "signals": [s.model_dump() for s in signals]},
            ensure_ascii=False,
            default=str,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc), "signals": []})


@function_tool
def search_instagram(tags: list[str], limit_per_tag: int = 15) -> str:
    """
    Search Instagram for nail photos by hashtag.
    Returns JSON list of signals with caption, likes, style_tags.
    """
    try:
        from nails_agent.tools.fetchers.instagram_fetcher import InstagramFetcher

        fetcher = InstagramFetcher()
        signals = fetcher.search(tags, limit_per_tag=limit_per_tag)
        return json.dumps(
            {"count": len(signals), "signals": [s.model_dump() for s in signals]},
            ensure_ascii=False,
            default=str,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc), "signals": []})


@function_tool
def get_style_library() -> str:
    """
    Return the current nail style inventory (existing styles the brand already has).
    Use this to identify style gaps — what's trending that we don't have yet.
    """
    data_dir = os.environ.get("NAILS_DATA_DIR", "demo/data")
    path = os.path.join(data_dir, "style_library.json")
    try:
        with open(path, encoding="utf-8") as f:
            library = json.load(f)
        return json.dumps({"count": len(library), "styles": library[:20]}, ensure_ascii=False)
    except Exception:
        return json.dumps({"count": 0, "styles": []})


# ══════════════════════════════════════════════════════════════════════════════
# Copywriting Tools (for CampaignAgent)
# ══════════════════════════════════════════════════════════════════════════════


@function_tool
def check_xhs_compliance(copy_text: str) -> str:
    """
    Check XHS marketing copy for banned commercial keywords.
    Returns a JSON report: {compliant: bool, violations: [...], suggestion: str}
    """
    banned = [
        "限时",
        "爆款",
        "立即购买",
        "全网最低",
        "秒杀",
        "薅羊毛",
        "白嫖",
        "最便宜",
        "史低价",
        "绝绝子",
        "绝了",
        "YYDS",
        "内部价",
        "福利价",
        "划算",
        "超值",
        "不买后悔",
        "手慢无",
    ]
    violations = [w for w in banned if w in copy_text]
    compliant = len(violations) == 0
    suggestion = "" if compliant else f"建议去掉：{', '.join(violations)}"
    return json.dumps(
        {
            "compliant": compliant,
            "violations": violations,
            "suggestion": suggestion,
        },
        ensure_ascii=False,
    )


@function_tool
def load_trend_context(limit: int = 5) -> str:
    """
    Load the latest trend analysis result from disk (output of TrendScoutAgent).
    Returns style_trends, patterns, anomalies for use in campaign generation.
    """
    output_dir = os.environ.get("NAILS_OUTPUT_DIR", "demo/output")
    path = os.path.join(output_dir, "trend_top10.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        style_trends = data.get("style_trends", [])[:limit]
        return json.dumps(
            {
                "style_trends": style_trends,
                "patterns": data.get("patterns", []),
                "anomalies": data.get("anomalies", []),
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc), "style_trends": []})


@function_tool(strict_mode=False)
def save_trend_analysis(
    style_trends: list[dict],
    top_10_signals: list[dict],
    patterns: list[str],
    anomalies: list[str],
    summary: str,
) -> str:
    """
    Persist the completed trend analysis to disk. Call this once when analysis is done.
    style_trends: list of {tag, category, post_count, total_engagement, aggregated_score, sample_caption}
    top_10_signals: top 10 highest-engagement posts (subset of search results)
    patterns: 2-4 style combo patterns observed
    anomalies: styles with unusual 48h growth
    summary: 2-3 sentence plain-language findings
    """
    output_dir = os.environ.get("NAILS_OUTPUT_DIR", "demo/output")
    os.makedirs(output_dir, exist_ok=True)
    payload = {
        "style_trends": style_trends,
        "top_10": top_10_signals,
        "patterns": patterns,
        "anomalies": anomalies,
        "summary": summary,
    }
    path = os.path.join(output_dir, "trend_top10.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return json.dumps({"status": "saved", "path": path, "styles": len(style_trends)})


@function_tool
def save_campaign_card(
    style_name: str,
    style_id: str,
    trend_score: float,
    category: str,
    xhs_caption: str,
    xhs_hashtags: list[str],
    douyin_caption: str,
    douyin_hashtags: list[str],
    instagram_caption: str,
    instagram_hashtags: list[str],
    base_price: str,
    tier: str,
    priority: str,
    publish_day_offset: int,
    key_selling_points: Optional[list[str]] = None,
) -> str:
    """
    Save one complete style card with platform copy to the campaign output.
    Call once per style. Appends to the campaign collection.

    tier: '基础款' | '进阶款' | '高端款'
    priority: 'P0' | 'P1' | 'P2'
    publish_day_offset: days from today (0=today, 1=tomorrow…)

    XHS copy rules (ALREADY CHECKED — make sure before calling):
    - No: 限时/爆款/立即购买/全网最低/秒杀/薅羊毛
    - Yes: 种草式、提问式、教程式

    Douyin copy rules:
    - Hook ≤15 chars, then pain→solution→result
    - 1-3 hashtags only

    Instagram copy rules:
    - English + emoji, lifestyle framing
    - 10-15 hashtags mix niche+broad
    """
    output_dir = os.environ.get("NAILS_OUTPUT_DIR", "demo/output")
    os.makedirs(output_dir, exist_ok=True)
    cards_path = os.path.join(output_dir, "_campaign_cards.json")

    # Load existing cards
    try:
        with open(cards_path, encoding="utf-8") as f:
            cards = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cards = []

    card = {
        "style_name": style_name,
        "style_id": style_id,
        "trend_score": trend_score,
        "category": category,
        "xhs_caption": xhs_caption,
        "xhs_hashtags": [t if t.startswith("#") else f"#{t}" for t in xhs_hashtags],
        "douyin_caption": douyin_caption,
        "douyin_hashtags": [t if t.startswith("#") else f"#{t}" for t in douyin_hashtags],
        "instagram_caption": instagram_caption,
        "instagram_hashtags": [t if t.startswith("#") else f"#{t}" for t in instagram_hashtags],
        "base_price": base_price,
        "tier": tier,
        "priority": priority,
        "publish_day_offset": publish_day_offset,
        "key_selling_points": key_selling_points or [],
    }
    cards.append(card)

    with open(cards_path, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)

    return json.dumps({"status": "saved", "total_cards": len(cards), "style": style_name})


@function_tool
def finalise_campaign(executive_summary: str, top_3_styles: list[str]) -> str:
    """
    Complete the campaign. Call after all save_campaign_card calls are done.
    Returns a summary of what was generated.
    """
    output_dir = os.environ.get("NAILS_OUTPUT_DIR", "demo/output")
    cards_path = os.path.join(output_dir, "_campaign_cards.json")
    try:
        with open(cards_path, encoding="utf-8") as f:
            cards = json.load(f)
    except Exception:
        cards = []

    summary = {
        "executive_summary": executive_summary,
        "top_3_styles": top_3_styles,
        "total_cards": len(cards),
        "p0_count": sum(1 for c in cards if c.get("priority") == "P0"),
        "p1_count": sum(1 for c in cards if c.get("priority") == "P1"),
    }

    # Save final campaign JSON
    campaign_path = os.path.join(output_dir, "campaign.json")
    with open(campaign_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "cards": cards}, f, ensure_ascii=False, indent=2)

    return json.dumps(summary, ensure_ascii=False)
