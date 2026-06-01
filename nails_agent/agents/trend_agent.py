"""
TrendScoutAgent — public API for running trend analysis.

Uses openai-agents SDK Runner with TrendScoutAgent (Qwen3 / Claude via OpenRouter).
Falls back to rule-based analysis if no API key is available.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Callable, List, Optional

if TYPE_CHECKING:
    from nails_agent.models.schemas import TrendAnalysisResult

logger = logging.getLogger(__name__)

_TZ8 = timezone(timedelta(hours=8))


def run_trend_scout(
    focus_keywords: Optional[List[str]] = None,
    since_days: int = 7,
    progress_cb: Optional[Callable[[str], None]] = None,
    max_turns: int = 20,
) -> "TrendAnalysisResult":
    """
    Run the LLM-powered TrendScoutAgent via openai-agents Runner.

    Returns TrendAnalysisResult. Falls back to rule-based if no API key.
    """
    from nails_agent.agents.agent_config import is_available

    if not is_available():
        if progress_cb:
            progress_cb("⚠️ 无 API key → 规则引擎模式")
        return _rule_based_fallback(since_days, progress_cb)

    # Clear previous output so we read fresh results
    output_dir = os.environ.get("NAILS_OUTPUT_DIR", "web/output")
    _clear_file(os.path.join(output_dir, "trend_top10.json"))

    kw_hint = ""
    if focus_keywords:
        kw_hint = f"重点关注这些关键词方向：{', '.join(focus_keywords[:6])}。"

    user_msg = (
        f"分析过去 {since_days} 天的美甲趋势。{kw_hint}"
        "搜索小红书和抖音，识别真正热门的美甲款式（按互动量聚合），保存分析结果。"
    )

    try:
        import asyncio
        from nails_agent.agents.nail_agents import get_trend_scout_agent

        agent = get_trend_scout_agent()

        if progress_cb:
            progress_cb("🤖 TrendScoutAgent 启动 (Qwen3)…")

        # Run synchronously; stream events for progress (result written to disk)
        # Use asyncio.run() so this works in threads that have no running event loop
        # (e.g. Streamlit's ScriptRunner.scriptThread).
        asyncio.run(_run_with_progress(agent, user_msg, progress_cb, max_turns))

    except Exception as exc:
        logger.exception("TrendScoutAgent failed: %s", exc)
        if progress_cb:
            progress_cb(f"⚠️ Agent 异常 ({exc})，回退规则模式")
        return _rule_based_fallback(since_days, progress_cb)

    # Parse saved output
    return _load_trend_result(output_dir, progress_cb)


async def _run_with_progress(agent, user_msg: str, progress_cb, max_turns: int):
    from nails_agent.agents.agent_config import run_streamed_with_fallback

    return await run_streamed_with_fallback(agent, user_msg, progress_cb, max_turns)


def _load_trend_result(output_dir: str, progress_cb) -> "TrendAnalysisResult":
    """Load and parse the saved trend analysis from disk."""
    from nails_agent.models.schemas import TrendAnalysisResult, StyleTrend, TrendSignal

    path = os.path.join(output_dir, "trend_top10.json")
    now = datetime.now(_TZ8)

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("trend_top10.json not found or invalid: %s", exc)
        if progress_cb:
            progress_cb("⚠️ 未找到趋势文件，回退规则模式")
        return _rule_based_fallback(7, None)

    style_trends: List[StyleTrend] = []
    for st in data.get("style_trends", []):
        try:
            style_trends.append(
                StyleTrend(
                    tag=st["tag"],
                    category=st.get("category", "style"),
                    post_count=int(st.get("post_count", 0)),
                    total_engagement=int(st.get("total_engagement", 0)),
                    aggregated_score=float(st.get("aggregated_score", 0)),
                    sample_caption=st.get("sample_caption", ""),
                )
            )
        except Exception:
            pass

    # Load original raw signals to restore fields that the LLM may have dropped
    # (e.g. display_label, source_title, local_image_paths).
    raw_signals_path = os.path.join(output_dir, "trend_signals.json")
    raw_signal_map: dict = {}
    try:
        with open(raw_signals_path, encoding="utf-8") as _f:
            for sig in json.load(_f):
                tid = sig.get("trend_id") or sig.get("source_note_id")
                if tid:
                    raw_signal_map[tid] = sig
    except Exception:
        pass

    top_10: List[TrendSignal] = []
    for raw in data.get("top_10", [])[:10]:
        try:
            # Merge: original signal data is the base, LLM output overrides where present
            tid = raw.get("trend_id") or raw.get("source_note_id")
            base = dict(raw_signal_map.get(tid or "", {}))
            base.update({k: v for k, v in raw.items() if v not in (None, "", [], {})})
            top_10.append(
                TrendSignal(**{k: base.get(k, "") for k in TrendSignal.model_fields if k in base})
            )
        except Exception:
            pass

    # Synthesize a pattern from the summary if provided
    summary = data.get("summary", "")
    patterns = list(data.get("patterns", []))
    if summary and summary not in patterns:
        patterns.insert(0, summary)

    result = TrendAnalysisResult(
        top_10=top_10,
        style_trends=style_trends,
        patterns=patterns[:6],
        anomalies=list(data.get("anomalies", [])),
        timestamp=now.isoformat(),
    )
    if progress_cb:
        progress_cb(
            f"✅ 趋势分析完成：{len(style_trends)} 个风格标签，"
            f"top 3: {', '.join(st.tag for st in style_trends[:3])}"
        )
    return result


def _rule_based_fallback(since_days: int, progress_cb) -> "TrendAnalysisResult":
    from nails_agent.tools.fetchers.signal_collector import SignalCollector
    from nails_agent.agents.workers.trend_analyst import analyse

    collector = SignalCollector()
    signals = collector.collect(since_days=since_days)
    return analyse(signals)


def _clear_file(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
