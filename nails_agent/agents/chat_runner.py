"""
ChatPipelineRunner — state machine driver for the Agent Chat UI.

Stateless w.r.t. session: every call to `advance(action, store)` reads context
from `store`, produces new events, and returns them. The UI persists `store`
across Streamlit reruns; the runner never holds Python attributes.

The 4-step pipeline is unchanged — we just split it across phases with
checkpoints in between.

State machine:
    idle ─start─▶ plan_review
    plan_review ─approve─▶ collecting (+ Step 1 trend analysis) ─▶ trends_review
    trends_review ─approve─▶ evaluating (Step 2) ─▶ strategy_review
    strategy_review ─approve─▶ reporting (Step 3 + Step 4) ─▶ done

    any phase ─interrupt─▶ interrupted (graceful, between tool calls)
    any phase ─exception─▶ error (recoverable)
"""
from __future__ import annotations

import time
import traceback
from typing import Any, Dict, List, Optional

from nails_agent.agents.chat_events import (
    ChatEvent,
    CheckpointChoice,
    ChartOutput,
    GalleryItem,
    ImageGalleryOutput,
    MarkdownOutput,
    TableOutput,
    UserAction,
    make_checkpoint,
    make_error,
    make_message,
    make_phase_enter,
    make_phase_output,
    make_progress,
    make_tool_call,
)
from nails_agent.agents.workers import (
    asset_generator,
    campaign_strategist,
    summarizer,
    trend_analyst,
    value_evaluator,
)
from nails_agent.memory.store import MemoryStore
from nails_agent.models.schemas import (
    PipelineState,
    StyleLibraryItem,
    TrendSignal,
)
from nails_agent.tools.fetchers.signal_collector import (
    DOUYIN_KEYWORDS,
    IG_NAIL_TAGS,
    SignalCollector,
    XHS_KEYWORDS,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


class ChatPipelineRunner:
    """
    advance(action, store) is the single entry point.

    `store` keys this class touches:
      • events           — append new events (UI does the actual append)
      • phase            — read current state
      • context          — scratch for signals, analysis, eval results, etc.
      • start_time       — set on first start, used for elapsed_ms
      • pending_interrupt — read in long loops; honoured at safe breakpoints
    """

    def __init__(self,
                 collector: Optional[SignalCollector] = None,
                 memory: Optional[MemoryStore] = None,
                 library_path: str = "demo/data/style_library.json"):
        self.collector = collector or SignalCollector(
            mock_data_path="demo/data/trend_signals.json",
        )
        self.memory = memory or MemoryStore()
        self.library_path = library_path

    # ── Public entry ──────────────────────────────────────────────────────────

    def advance(self, action: UserAction, store: Dict[str, Any]) -> List[ChatEvent]:
        """Run forward until the next checkpoint / terminal state."""
        try:
            if action.type == "start":
                return self._handle_start(action, store)
            if action.type == "choose":
                return self._handle_choice(action, store)
            if action.type == "interrupt":
                return self._handle_interrupt(action, store)
        except Exception as exc:
            return [make_error(
                phase=store.get("phase", "idle"),
                message=f"Unexpected runner error: {exc}",
                recoverable=False,
                traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
            )]
        return []

    # ── Action handlers ───────────────────────────────────────────────────────

    def _handle_start(self, action: UserAction, store: Dict[str, Any]) -> List[ChatEvent]:
        if store["phase"] != "idle":
            return [make_message("assistant",
                                  "⚠️ 当前已经在跑了，先完成或中止再开始新会话。")]
        store["start_time"] = time.time()
        payload = action.payload or {}
        text = payload.get("text", "").strip() or "开始今日分析"
        # The UI can render the user's own bubble first (better UX during slow
        # source probes). Honour that and don't double-emit it here.
        events: List[ChatEvent] = []
        if not payload.get("skip_user_bubble"):
            events.append(make_message("user", text))
        events.extend(self._phase_plan_review(store))
        return events

    def _handle_choice(self, action: UserAction, store: Dict[str, Any]) -> List[ChatEvent]:
        cp = (action.payload or {}).get("checkpoint_id")
        choice = (action.payload or {}).get("choice_id")
        form = (action.payload or {}).get("form") or {}

        echo = make_message("user", f"[{choice}] @ {cp}", icon="✅")

        # ── plan_review ──
        if cp == "plan_review":
            if choice == "approve":
                return [echo, *self._phase_collecting(store), *self._phase_trends_review(store)]
            if choice == "abort":
                store["phase"] = "idle"
                return [echo, make_message("assistant", "已取消。")]

        # ── trends_review ──
        if cp == "trends_review":
            if choice == "approve":
                return [echo, *self._phase_evaluating(store), *self._phase_strategy_review(store)]
            if choice == "adjust_kws":
                # Apply new keywords and re-run collecting
                kws_raw = form.get("keywords", "")
                kws = [k.strip() for k in kws_raw.replace("，", ",").split(",") if k.strip()]
                if kws:
                    store["context"]["custom_keywords"] = kws
                return [echo, *self._phase_collecting(store), *self._phase_trends_review(store)]
            if choice == "abort":
                store["phase"] = "interrupted"
                return [echo, make_message("assistant", "已中止流程。")]

        # ── strategy_review ──
        if cp == "strategy_review":
            if choice == "approve":
                return [echo, *self._phase_reporting(store)]
            if choice == "abort":
                store["phase"] = "interrupted"
                return [echo, make_message("assistant", "已中止流程。")]

        # ── error checkpoints ──
        if choice == "retry":
            # Re-run from the failed phase
            failed = store.get("phase", "idle")
            store["phase"] = "idle"  # reset so handlers fire
            if failed == "collecting":
                return [echo, *self._phase_collecting(store), *self._phase_trends_review(store)]
            if failed == "evaluating":
                return [echo, *self._phase_evaluating(store), *self._phase_strategy_review(store)]
            if failed == "reporting":
                return [echo, *self._phase_reporting(store)]
            return [echo, make_message("assistant", "未知阶段，无法重试。")]
        if choice == "abort":
            store["phase"] = "interrupted"
            return [echo, make_message("assistant", "已中止。")]

        return [make_message("assistant", f"未处理的 checkpoint 决定：{cp}/{choice}")]

    def _handle_interrupt(self, action: UserAction, store: Dict[str, Any]) -> List[ChatEvent]:
        # Graceful interrupt was already flagged by the UI; if we got here
        # the runner is between tool calls. Just acknowledge.
        store["phase"] = "interrupted"
        return [make_message("assistant", "已中止当前操作。")]

    # ── Phase implementations ────────────────────────────────────────────────

    def _phase_plan_review(self, store: Dict[str, Any]) -> List[ChatEvent]:
        # Probe sources so the plan reflects reality
        status = self.collector.source_status()
        ready = [k for k, v in status.items() if v]
        ready_str = ", ".join(ready) if ready else "仅 mock"
        plan_md = (
            "**📋 准备计划**\n\n"
            f"- **数据源就绪**: {ready_str}\n"
            f"- **关键词**: XHS {len(XHS_KEYWORDS)}, 抖音 {len(DOUYIN_KEYWORDS)}, "
            f"Instagram {len(IG_NAIL_TAGS)}\n"
            "- **目标**: 每平台 ≥100 条信号（去重后）\n"
            "- **流程**: 抓取 → 趋势分析 → 价值评估 + 素材生成 → 策略 → 报告\n"
            "- 每个关键节点会暂停等你确认。"
        )
        return [
            make_phase_enter("plan_review", "Plan", _elapsed(store)),
            make_message("assistant", plan_md, icon="🤖"),
            make_checkpoint(
                "plan_review",
                "确认开始？",
                choices=[
                    CheckpointChoice(id="approve", label="✓ 开始", style="primary", priority="P0"),
                    CheckpointChoice(id="abort",   label="✗ 取消", style="danger",  priority="P0"),
                ],
            ),
        ]

    def _phase_collecting(self, store: Dict[str, Any]) -> List[ChatEvent]:
        events: List[ChatEvent] = [
            make_phase_enter("collecting", "Step 1/4 数据采集 + 趋势分析", _elapsed(store)),
        ]

        # Use custom keywords if user adjusted them, else default
        ctx = store.setdefault("context", {})
        custom = ctx.get("custom_keywords")
        kws = custom if custom else None  # None → collector uses per-platform defaults

        # ── Source probing (each becomes a tool_call event) ────────────────
        status = self.collector.source_status()
        for src in ("xhs", "douyin_cdp", "instagram"):
            available = status.get(src, False)
            events.append(make_tool_call(
                tool=f"signal_collector.probe[{src}]",
                args={},
                status="ok" if available else "error",
                duration_ms=0,
                result_summary="ready" if available else "unavailable",
            ))

        # Graceful interrupt check
        if store.get("pending_interrupt"):
            store["pending_interrupt"] = False
            store["phase"] = "interrupted"
            events.append(make_message("assistant", "已中止采集。"))
            return events

        # ── The actual collection (single big tool call) ───────────────────
        t0 = _now_ms()
        try:
            signals = self.collector.collect(
                keywords=kws,
                use_mock_fallback=True,
                use_tikhub=False,
            )
        except Exception as exc:
            events.append(make_error(
                phase="collecting",
                message=f"采集失败: {exc}",
                recoverable=True,
                traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
            ))
            store["phase"] = "collecting"
            return events
        dt = _now_ms() - t0

        by_platform: Dict[str, int] = {}
        for s in signals:
            by_platform[s.platform] = by_platform.get(s.platform, 0) + 1

        events.append(make_tool_call(
            tool="SignalCollector.collect",
            args={"keywords": kws or "platform-defaults"},
            status="ok",
            duration_ms=dt,
            result_summary=f"{len(signals)} signals · " +
                           " / ".join(f"{p} {n}" for p, n in by_platform.items()),
        ))

        if not signals:
            events.append(make_error(
                phase="collecting",
                message="未采集到任何信号。检查数据源是否就绪。",
                recoverable=True,
            ))
            store["phase"] = "collecting"
            return events

        ctx["signals"] = signals

        # ── Step 1 inline: trend analysis ──────────────────────────────────
        t0 = _now_ms()
        analysis = trend_analyst.analyse(signals)
        events.append(make_tool_call(
            tool="trend_analyst.analyse",
            args={"signals_in": len(signals)},
            status="ok",
            duration_ms=_now_ms() - t0,
            result_summary=f"top {len(analysis.top_10)} trends · "
                           f"{len(analysis.patterns)} patterns",
        ))
        ctx["analysis"] = analysis
        return events

    def _phase_trends_review(self, store: Dict[str, Any]) -> List[ChatEvent]:
        ctx = store["context"]
        analysis = ctx["analysis"]
        signals = ctx["signals"]

        # Top-10 keywords + composite scores
        top = analysis.top_10[:10]
        events: List[ChatEvent] = [
            make_phase_enter("trends_review", "趋势分析结果", _elapsed(store)),
        ]

        # Table: top-10 with platform + likes
        events.append(make_phase_output(
            "trends_review",
            TableOutput(
                title="Top 10 趋势",
                columns=["排名", "关键词", "平台", "点赞", "综合分"],
                rows=[
                    [i + 1, s.keyword, s.platform, s.likes, round(s.composite_score, 1)]
                    for i, s in enumerate(top)
                ],
            ),
        ))

        # Chart: composite-score bar
        events.append(make_phase_output(
            "trends_review",
            ChartOutput(
                title="Top 10 综合热度",
                chart_type="bar",
                x=[round(s.composite_score, 1) for s in top],
                y=[f"{s.keyword[:14]}" for s in top],
            ),
        ))

        # Pattern markdown summary (patterns is List[str])
        if analysis.patterns:
            md = "\n".join(f"- {p}" for p in analysis.patterns[:8])
            events.append(make_phase_output(
                "trends_review",
                MarkdownOutput(title="高频风格模式", body=md),
            ))

        kw_default = ",".join(XHS_KEYWORDS[:5])
        from nails_agent.agents.chat_events import FormField
        events.append(make_checkpoint(
            "trends_review",
            f"已采集 {len(signals)} 条 / 分析出 {len(analysis.top_10)} 个 top 趋势。是否继续到价值评估？",
            choices=[
                CheckpointChoice(id="approve", label="✓ 继续到价值评估", style="primary", priority="P1"),
                CheckpointChoice(
                    id="adjust_kws", label="🔧 调关键词重抓", style="secondary", priority="P0",
                    form=[FormField(name="keywords", label="关键词（逗号分隔）",
                                     type="text", default=kw_default)],
                ),
                CheckpointChoice(id="abort", label="✗ 结束", style="danger", priority="P0"),
            ],
            auto_approve_after_s=15,
            auto_approve_choice_id="approve",
        ))
        return events

    def _phase_evaluating(self, store: Dict[str, Any]) -> List[ChatEvent]:
        ctx = store["context"]
        analysis = ctx["analysis"]
        library = self._load_library()

        events: List[ChatEvent] = [
            make_phase_enter("evaluating", "Step 2/4 价值评估 + 素材生成", _elapsed(store)),
        ]

        # value_evaluator
        t0 = _now_ms()
        try:
            value_result = value_evaluator.evaluate(analysis, library)
        except Exception as exc:
            events.append(make_error(
                phase="evaluating",
                message=f"value_evaluator 失败: {exc}",
                recoverable=True,
                traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
            ))
            store["phase"] = "evaluating"
            return events
        events.append(make_tool_call(
            tool="value_evaluator.evaluate",
            args={"top_trends": len(analysis.top_10), "library_items": len(library)},
            status="ok",
            duration_ms=_now_ms() - t0,
            result_summary=f"{len(value_result.snapshots)} metric snapshots",
        ))
        ctx["value_result"] = value_result

        # asset_generator
        t0 = _now_ms()
        try:
            asset_result = asset_generator.generate(analysis)
        except Exception as exc:
            events.append(make_error(
                phase="evaluating",
                message=f"asset_generator 失败: {exc}",
                recoverable=True,
                traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
            ))
            store["phase"] = "evaluating"
            return events
        events.append(make_tool_call(
            tool="asset_generator.generate",
            args={"top_trends": len(analysis.top_10)},
            status="ok",
            duration_ms=_now_ms() - t0,
            result_summary=f"{len(asset_result.drafts)} card drafts",
        ))
        ctx["asset_result"] = asset_result

        # Inline outputs (no checkpoint — auto-proceed to strategy_review)
        events.append(make_phase_output(
            "evaluating",
            TableOutput(
                title="价值评估 Top 10",
                columns=["排名", "关键词", "外部热度", "新鲜度", "风格缺口", "优先级"],
                rows=[
                    [s.rank, s.keyword, s.external_heat_score, s.trend_growth_score,
                     s.style_gap_score, s.launch_priority_score]
                    for s in value_result.snapshots
                ],
            ),
        ))
        events.append(make_phase_output(
            "evaluating",
            ImageGalleryOutput(
                title="素材卡片草稿",
                items=[
                    GalleryItem(
                        url=d.image_url or "",
                        caption=d.style_name,
                        badge=f"P · {d.launch_priority_score:.0f}",
                    )
                    for d in asset_result.drafts[:8]
                ],
            ),
        ))
        return events

    def _phase_strategy_review(self, store: Dict[str, Any]) -> List[ChatEvent]:
        ctx = store["context"]
        events: List[ChatEvent] = [
            make_phase_enter("strategy_review", "Step 3/4 运营策略", _elapsed(store)),
        ]
        t0 = _now_ms()
        try:
            campaign = campaign_strategist.strategise(ctx["value_result"], ctx["asset_result"])
        except Exception as exc:
            events.append(make_error(
                phase="strategy_review",
                message=f"campaign_strategist 失败: {exc}",
                recoverable=True,
                traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
            ))
            store["phase"] = "evaluating"   # retry from evaluating
            return events
        events.append(make_tool_call(
            tool="campaign_strategist.strategise",
            args={},
            status="ok",
            duration_ms=_now_ms() - t0,
            result_summary=f"{len(campaign.style_cards)} cards",
        ))
        ctx["campaign"] = campaign

        # Strategy markdown
        p0 = [c for c in campaign.style_cards if c.schedule and c.schedule.priority == "P0"]
        p1 = [c for c in campaign.style_cards if c.schedule and c.schedule.priority == "P1"]
        md_lines = [f"### P0 立即上线（{len(p0)} 款）"]
        for c in p0[:5]:
            slot = (c.schedule.xiaohongshu_publish_at
                    if c.schedule else "—") or "—"
            md_lines.append(f"- **{c.style_name}** · 小红书: {slot}")
        if p1:
            md_lines.append(f"\n### P1 储备（{len(p1)} 款）")
            for c in p1[:5]:
                md_lines.append(f"- {c.style_name}")
        events.append(make_phase_output(
            "strategy_review",
            MarkdownOutput(title="本轮策略", body="\n".join(md_lines)),
        ))

        events.append(make_checkpoint(
            "strategy_review",
            f"策略已生成（P0 {len(p0)}, P1 {len(p1)}）。是否写入记忆并出报告？",
            choices=[
                CheckpointChoice(id="approve", label="✓ 出报告", style="primary", priority="P0"),
                CheckpointChoice(id="abort",   label="✗ 中止",   style="danger",  priority="P0"),
            ],
        ))
        return events

    def _phase_reporting(self, store: Dict[str, Any]) -> List[ChatEvent]:
        ctx = store["context"]
        events: List[ChatEvent] = [
            make_phase_enter("reporting", "Step 4/4 出报告 + 蒸馏记忆", _elapsed(store)),
        ]

        # Build a PipelineState for summarizer + memory (it's the schema both expect)
        state = PipelineState()
        state.trend_analysis = ctx["analysis"]
        state.value_evaluation = ctx["value_result"]
        state.asset_generation = ctx["asset_result"]
        state.campaign_strategy = ctx["campaign"]

        t0 = _now_ms()
        try:
            report = summarizer.summarise(state)
        except Exception as exc:
            events.append(make_error(
                phase="reporting",
                message=f"summarizer 失败: {exc}",
                recoverable=True,
                traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
            ))
            store["phase"] = "reporting"
            return events
        events.append(make_tool_call(
            tool="summarizer.summarise",
            args={},
            status="ok",
            duration_ms=_now_ms() - t0,
            result_summary=f"{len(report.markdown)} chars",
        ))
        ctx["report"] = report

        # Memory distillation (best-effort; failure shouldn't break the pipeline)
        try:
            new_insights = self.memory.distill(state.pipeline_id)
            events.append(make_tool_call(
                tool="memory.distill",
                args={"pipeline_id": state.pipeline_id},
                status="ok",
                result_summary=f"{len(new_insights)} new insights",
            ))
        except Exception as exc:
            events.append(make_tool_call(
                tool="memory.distill",
                args={},
                status="error",
                result_summary=str(exc),
            ))

        # Final report output
        events.append(make_phase_output(
            "reporting",
            MarkdownOutput(title="📄 运营报告", body=report.markdown),
        ))

        # Terminal state
        events.append(make_phase_enter("done", "完成 ✅", _elapsed(store)))
        events.append(make_message("assistant", "本轮完成。输入新指令开始下一轮。"))
        store["phase"] = "done"
        return events

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _load_library(self) -> List[StyleLibraryItem]:
        import json
        try:
            with open(self.library_path, encoding="utf-8") as f:
                return [StyleLibraryItem(**item) for item in json.load(f)]
        except Exception:
            return []


def _elapsed(store: Dict[str, Any]) -> int:
    t0 = store.get("start_time")
    if not t0:
        return 0
    return int((time.time() - t0) * 1000)
