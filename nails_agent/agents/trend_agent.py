"""
TrendScoutAgent: LLM-powered trend intelligence.

Replaces the rule-based trend_analyst + signal_collector workers.
The agent autonomously decides which keywords to search, interprets raw
engagement data, identifies genuine style patterns, and writes human-readable
trend commentary — all via Anthropic tool_use.

Tools exposed to the LLM:
  search_social_media  — fetch posts from XHS / Douyin / Instagram
  get_style_library    — list existing styles in inventory
  report_trend_analysis — finalise and return structured TrendAnalysisResult
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional

from nails_agent.agents.base_tool_agent import ToolAgent, AgentResult
from nails_agent.models.schemas import (
    TrendSignal,
    TrendAnalysisResult,
    StyleTrend,
)

_TZ8 = timezone(timedelta(hours=8))

# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """\
You are a nail trend intelligence analyst. Your job is to:
1. Search Xiaohongshu (XHS), Douyin, and Instagram for real nail-style posts
2. Aggregate engagement data to identify which nail STYLES are genuinely popular
   (not just which search keywords you used)
3. Spot anomalies — styles that jumped in the last 48 h
4. Write concise, evidence-based observations — cite real post captions

Rules:
- A "style" is something like 猫眼, 法式, 奶油, 夏日, 渐变, 极简 — NOT the search
  keyword itself. Extract style tags from post content/titles.
- Avoid vague claims. Back observations with numbers (engagement counts).
- Call report_trend_analysis exactly once when you have enough data.
- Do NOT make up post data. Only report what the tools returned.
"""

# ── Tool schemas ───────────────────────────────────────────────────────────────

_TOOLS = [
    {
        "name": "search_social_media",
        "description": (
            "Fetch nail-trend posts from one or more platforms. "
            "Returns a list of post signals with title, tags, engagement, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Search keywords, e.g. ['猫眼美甲', '法式美甲']",
                },
                "platforms": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["xhs", "douyin", "instagram"]},
                    "description": "Platforms to search. Defaults to ['xhs', 'douyin'].",
                },
                "limit_per_keyword": {
                    "type": "integer",
                    "description": "Max signals per keyword per platform (default 20)",
                },
            },
            "required": ["keywords"],
        },
    },
    {
        "name": "get_style_library",
        "description": "Return the list of nail styles currently in inventory.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "report_trend_analysis",
        "description": (
            "Finalise the trend analysis. Call this once you've collected enough data. "
            "The top_10 list should be the 10 highest-engagement posts you saw. "
            "style_trends should aggregate by style tag (not keyword). "
            "patterns/anomalies should be human-readable bullet strings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "top_10": {
                    "type": "array",
                    "description": "List of top 10 post signals (raw dicts from search).",
                    "items": {"type": "object"},
                },
                "style_trends": {
                    "type": "array",
                    "description": "Aggregated style trends sorted by score desc.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tag": {"type": "string"},
                            "category": {
                                "type": "string",
                                "enum": ["style", "color", "material", "scene"],
                            },
                            "post_count": {"type": "integer"},
                            "total_engagement": {"type": "integer"},
                            "aggregated_score": {"type": "number"},
                            "sample_caption": {"type": "string"},
                        },
                        "required": ["tag", "category", "post_count", "total_engagement", "aggregated_score"],
                    },
                },
                "patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2-4 observed style combination patterns.",
                },
                "anomalies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Styles with abnormal recent growth (last 48 h).",
                },
                "summary": {
                    "type": "string",
                    "description": "2-3 sentence natural-language summary of findings.",
                },
            },
            "required": ["top_10", "style_trends", "patterns", "anomalies"],
        },
    },
]


# ── Tool implementations ───────────────────────────────────────────────────────

def _search_social_media(
    keywords: List[str],
    platforms: Optional[List[str]] = None,
    limit_per_keyword: int = 20,
) -> Dict[str, Any]:
    platforms = platforms or ["xhs", "douyin"]
    signals: List[Dict] = []
    errors: List[str] = []

    for platform in platforms:
        try:
            if platform == "xhs":
                from nails_agent.tools.fetchers.xhs_mcp_fetcher import XHSMCPFetcher
                fetcher = XHSMCPFetcher()
                if fetcher.is_available():
                    for kw in keywords:
                        batch = fetcher.search(kw, limit=limit_per_keyword)
                        signals.extend(s.model_dump() for s in batch)
                else:
                    errors.append("XHS MCP server not available")

            elif platform == "douyin":
                from nails_agent.tools.fetchers.douyin_cdp import DouyinCDPFetcher
                fetcher = DouyinCDPFetcher()
                batch = fetcher.search(keywords, limit_per_kw=limit_per_keyword)
                signals.extend(s.model_dump() for s in batch)

            elif platform == "instagram":
                from nails_agent.tools.fetchers.instagram_fetcher import InstagramFetcher
                fetcher = InstagramFetcher()
                batch = fetcher.search(keywords, limit_per_tag=limit_per_keyword)
                signals.extend(s.model_dump() for s in batch)

        except Exception as exc:
            errors.append(f"{platform}: {exc}")

    # Deduplicate by trend_id
    seen: set = set()
    unique: List[Dict] = []
    for s in signals:
        tid = s.get("trend_id", "")
        if tid and tid not in seen:
            seen.add(tid)
            unique.append(s)
        elif not tid:
            unique.append(s)

    return {
        "count": len(unique),
        "signals": unique,
        "errors": errors,
    }


def _get_style_library() -> List[Dict]:
    data_dir = os.environ.get("NAILS_DATA_DIR", "demo/data")
    path = os.path.join(data_dir, "style_library.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


# Shared state so report_trend_analysis can pass the result back
_REPORT_SLOT: Dict[str, Any] = {}


def _report_trend_analysis(**kwargs) -> Dict[str, Any]:
    _REPORT_SLOT.update(kwargs)
    return {"status": "ok", "style_count": len(kwargs.get("style_trends", []))}


_TOOL_FNS = {
    "search_social_media": _search_social_media,
    "get_style_library": _get_style_library,
    "report_trend_analysis": _report_trend_analysis,
}


# ── Public API ─────────────────────────────────────────────────────────────────

def run_trend_scout(
    focus_keywords: Optional[List[str]] = None,
    since_days: int = 7,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> TrendAnalysisResult:
    """
    Run the LLM-powered trend scout and return a TrendAnalysisResult.

    Falls back gracefully to rule-based analysis if the API is unavailable.
    """
    _REPORT_SLOT.clear()

    keywords_hint = ""
    if focus_keywords:
        keywords_hint = (
            f"Focus on these keyword areas: {', '.join(focus_keywords)}. "
            "You may add related terms."
        )

    user_msg = (
        f"Analyse nail trends from the last {since_days} days. "
        f"{keywords_hint} "
        "Search across XHS and Douyin. "
        "Identify top styles by engagement and call report_trend_analysis with your findings."
    )

    agent = ToolAgent(
        system_prompt=_SYSTEM,
        tools=_TOOLS,
        tool_functions=_TOOL_FNS,
        max_iterations=15,
        max_tokens=4096,
    )

    result: AgentResult = agent.run(user_msg, progress_cb=progress_cb)

    if not result.success or not _REPORT_SLOT:
        # Fallback to rule-based
        if progress_cb:
            progress_cb("⚠️ Agent fallback → rule-based trend analysis")
        return _rule_based_fallback(since_days, progress_cb)

    return _build_result_from_report(_REPORT_SLOT, result.text)


def _build_result_from_report(report: Dict[str, Any], summary_text: str) -> TrendAnalysisResult:
    """Convert the agent's reported dict into a TrendAnalysisResult."""
    now = datetime.now(_TZ8)

    # Parse top_10
    top_10: List[TrendSignal] = []
    for raw in report.get("top_10", [])[:10]:
        try:
            top_10.append(TrendSignal(**{
                k: raw.get(k, "")
                for k in TrendSignal.model_fields
            }))
        except Exception:
            pass

    # Parse style_trends
    style_trends: List[StyleTrend] = []
    for st in report.get("style_trends", []):
        try:
            style_trends.append(StyleTrend(
                tag=st["tag"],
                category=st.get("category", "style"),
                post_count=int(st.get("post_count", 0)),
                total_engagement=int(st.get("total_engagement", 0)),
                aggregated_score=float(st.get("aggregated_score", 0)),
                sample_caption=st.get("sample_caption", ""),
            ))
        except Exception:
            pass

    # Merge summary_text into patterns if provided
    patterns = list(report.get("patterns", []))
    if summary_text and summary_text not in patterns:
        patterns.insert(0, summary_text.strip())

    return TrendAnalysisResult(
        top_10=top_10,
        style_trends=style_trends,
        patterns=patterns[:6],
        anomalies=list(report.get("anomalies", [])),
        timestamp=now.isoformat(),
    )


def _rule_based_fallback(
    since_days: int,
    progress_cb: Optional[Callable] = None,
) -> TrendAnalysisResult:
    """Rule-based fallback (original workers)."""
    from nails_agent.tools.fetchers.signal_collector import SignalCollector
    from nails_agent.agents.workers.trend_analyst import analyse

    collector = SignalCollector()
    signals = collector.collect(since_days=since_days, progress_cb=progress_cb)
    return analyse(signals)
