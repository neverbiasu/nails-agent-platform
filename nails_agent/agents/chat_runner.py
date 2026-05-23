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

import os
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

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
    NailStyleStoreItem,
    PipelineState,
    TrendSignal,
)
from nails_agent.services.pipeline_persistence import PipelinePersistence
from nails_agent.services.style_store_ingestion import (
    format_ingestion_markdown,
    ingest_campaign_styles,
)
from nails_agent.services.trend_presentation import (
    sample_label,
    signal_image_url,
    source_title,
    tag_summary,
)
from nails_agent.tools.fetchers.signal_collector import (
    DOUYIN_KEYWORDS,
    IG_NAIL_TAGS,
    SignalCollector,
    XHS_KEYWORDS,
)

# Load API keys early so agent detection works
load_dotenv(Path(__file__).parent.parent.parent / ".env")
load_dotenv(Path.home() / ".hermes" / ".env", override=False)


def _check_agents_available() -> bool:
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("MODELSCOPE_API_KEY")
    )


_AGENTS_AVAILABLE = _check_agents_available()


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

    def __init__(
        self,
        collector: Optional[SignalCollector] = None,
        memory: Optional[MemoryStore] = None,
        library_path: str = "data/nail_styles_store.json",
        output_dir: str = "web/output",
        use_agents: bool = True,
    ):
        self.collector = collector or SignalCollector(
            mock_data_path="web/data/trend_signals.json",
        )
        self.memory = memory or MemoryStore()
        self.library_path = library_path
        self.persistence = PipelinePersistence(memory=self.memory, output_dir=output_dir)
        self.use_agents = use_agents and _AGENTS_AVAILABLE

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
            self._mark_error(store, exc)
            return [
                make_error(
                    phase=store.get("phase", "idle"),
                    message=f"Unexpected runner error: {exc}",
                    recoverable=False,
                    traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
                )
            ]
        return []

    # ── Action handlers ───────────────────────────────────────────────────────

    def _handle_start(self, action: UserAction, store: Dict[str, Any]) -> List[ChatEvent]:
        if store["phase"] != "idle":
            return [make_message("assistant", "⚠️ 当前已经在跑了，先完成或中止再开始新会话。")]
        store["start_time"] = time.time()
        store["context"] = {}
        state = self._get_pipeline_state(store)
        state.status = "waiting_review"
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
                self._mark_stopped(store, status="cancelled", phase="plan_review")
                return [echo, make_message("assistant", "已取消。")]

        # ── trends_review (Step 1 → Step 2) ──
        if cp == "trends_review":
            if choice == "approve":
                return [echo, *self._phase_evaluating(store)]
            if choice == "adjust_kws":
                kws_raw = form.get("keywords", "")
                kws = [k.strip() for k in kws_raw.replace("，", ",").split(",") if k.strip()]
                if kws:
                    store["context"]["custom_keywords"] = kws
                return [echo, *self._phase_collecting(store), *self._phase_trends_review(store)]
            if choice == "abort":
                store["phase"] = "interrupted"
                self._mark_stopped(store, status="interrupted", phase="trends_review")
                return [echo, make_message("assistant", "已中止流程。")]

        # ── eval_review (Step 2 → Step 3) ──
        if cp == "eval_review":
            if choice == "approve":
                return [echo, *self._phase_strategy_building(store)]
            if choice == "abort":
                store["phase"] = "interrupted"
                self._mark_stopped(store, status="interrupted", phase="eval_review")
                return [echo, make_message("assistant", "已中止流程。")]

        # ── strategy_review (Step 3 → Step 4) ──
        if cp == "strategy_review":
            if choice == "approve":
                return [echo, *self._phase_reporting(store)]
            if choice == "abort":
                store["phase"] = "interrupted"
                self._mark_stopped(store, status="interrupted", phase="strategy_review")
                return [echo, make_message("assistant", "已中止流程。")]

        # ── error checkpoints ──
        if choice == "retry":
            failed = store.get("phase", "idle")
            store["phase"] = "idle"
            if failed == "collecting":
                return [echo, *self._phase_collecting(store), *self._phase_trends_review(store)]
            if failed == "evaluating":
                return [echo, *self._phase_evaluating(store)]
            if failed == "strategy_building":
                return [echo, *self._phase_strategy_building(store)]
            if failed == "reporting":
                return [echo, *self._phase_reporting(store)]
            return [echo, make_message("assistant", "未知阶段，无法重试。")]
        if choice == "abort":
            store["phase"] = "interrupted"
            self._mark_stopped(store, status="interrupted", phase=store.get("phase", "unknown"))
            return [echo, make_message("assistant", "已中止。")]

        return [make_message("assistant", f"未处理的 checkpoint 决定：{cp}/{choice}")]

    def _handle_interrupt(self, action: UserAction, store: Dict[str, Any]) -> List[ChatEvent]:
        # Graceful interrupt was already flagged by the UI; if we got here
        # the runner is between tool calls. Just acknowledge.
        store["phase"] = "interrupted"
        self._mark_stopped(store, status="interrupted", phase=store.get("phase", "unknown"))
        return [make_message("assistant", "已中止当前操作。")]

    # ── Phase implementations ────────────────────────────────────────────────

    def _phase_plan_review(self, store: Dict[str, Any]) -> List[ChatEvent]:
        # Probe sources so the plan reflects reality
        status = self.collector.source_status(refresh=True)
        ready = [k for k, v in status.items() if v]
        ready_str = ", ".join(ready) if ready else "仅 mock"
        mode_line = (
            "- **模式**: 🤖 **Agent 模式**（TrendScoutAgent + CampaignAgent，LLM 驱动）"
            if self.use_agents
            else "- **模式**: ⚙️ 规则模式（无 ANTHROPIC_API_KEY，回退到规则引擎）"
        )
        plan_md = (
            "**📋 准备计划**\n\n"
            f"- **数据源就绪**: {ready_str}\n"
            f"- **关键词**: XHS {len(XHS_KEYWORDS)}, 抖音 {len(DOUYIN_KEYWORDS)}, "
            f"Instagram {len(IG_NAIL_TAGS)}\n"
            "- **目标**: 每平台 ≥100 条信号（去重后）\n"
            f"{mode_line}\n"
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
                    CheckpointChoice(id="abort", label="✗ 取消", style="danger", priority="P0"),
                ],
            ),
        ]

    def _phase_collecting(self, store: Dict[str, Any]) -> List[ChatEvent]:
        events: List[ChatEvent] = [
            make_phase_enter("collecting", "Step 1/4 数据采集 + 趋势分析", _elapsed(store)),
        ]

        # Use custom keywords if user adjusted them, else default
        ctx = store.setdefault("context", {})
        state = self._get_pipeline_state(store)
        state.status = "running"
        state.meta.update({"phase": "collecting", "persisted_at": datetime.now().isoformat()})
        custom = ctx.get("custom_keywords")
        kws = custom if custom else None  # None → collector uses per-platform defaults

        # ── Source probing (each becomes a tool_call event) ────────────────
        status = self.collector.source_status(refresh=True)
        for src in ("xhs", "douyin_cdp", "instagram"):
            available = status.get(src, False)
            events.append(
                make_tool_call(
                    tool=f"signal_collector.probe[{src}]",
                    args={},
                    status="ok" if available else "error",
                    duration_ms=0,
                    result_summary="ready" if available else "unavailable",
                )
            )

        # Graceful interrupt check
        if store.get("pending_interrupt"):
            store["pending_interrupt"] = False
            store["phase"] = "interrupted"
            self._mark_stopped(store, status="interrupted", phase="collecting")
            events.append(make_message("assistant", "已中止采集。"))
            return events

        # ── The actual collection (single big tool call) ───────────────────
        t0 = _now_ms()
        try:
            signals = self.collector.collect(
                keywords=kws,
                use_mock_fallback=True,
                use_tikhub=False,
                refresh_sources=True,
            )
        except Exception as exc:
            events.append(
                make_error(
                    phase="collecting",
                    message=f"采集失败: {exc}",
                    recoverable=True,
                    traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
                )
            )
            store["phase"] = "collecting"
            return events
        dt = _now_ms() - t0

        by_platform: Dict[str, int] = {}
        for s in signals:
            by_platform[s.platform] = by_platform.get(s.platform, 0) + 1
        mock_run = self.collector.last_collection_used_mock
        ctx["mock_run"] = mock_run
        ctx["persist_enabled"] = bool(signals and not mock_run)
        state.meta.update(
            {
                "data_mode": "mock_preview" if mock_run else "real",
                "persist_enabled": ctx["persist_enabled"],
            }
        )

        events.append(
            make_tool_call(
                tool="SignalCollector.collect",
                args={"keywords": kws or "platform-defaults"},
                status="ok",
                duration_ms=dt,
                result_summary=f"{len(signals)} signals · "
                + " / ".join(f"{p} {n}" for p, n in by_platform.items()),
            )
        )

        if self._should_persist(store):
            self.persistence.save_state(state)
            self.persistence.persist_signals(signals)
            self.persistence.persist_rejected_candidates(
                state.pipeline_id,
                self.collector.rejected_candidates,
            )
        elif mock_run:
            events.append(
                make_tool_call(
                    tool="persistence.skip",
                    args={"reason": "mock_preview"},
                    status="ok",
                    result_summary="mock 预览模式：不写主库、不写 memory.db、不覆盖 web/output",
                )
            )

        if not signals:
            events.append(
                make_error(
                    phase="collecting",
                    message="未采集到任何信号。检查数据源是否就绪。",
                    recoverable=True,
                )
            )
            store["phase"] = "collecting"
            return events

        ctx["signals"] = signals

        # ── Step 1: trend analysis (agent or rule-based) ──────────────────
        t0 = _now_ms()
        if self.use_agents:
            events.append(
                make_tool_call(
                    tool="TrendScoutAgent.run",
                    args={"mode": "LLM", "platforms": ["xhs", "douyin"]},
                    status="ok",
                    duration_ms=0,
                    result_summary="agent启动中…",
                )
            )
            try:
                from nails_agent.agents.trend_agent import run_trend_scout

                agent_events: List[ChatEvent] = []

                def _agent_prog(msg: str) -> None:
                    agent_events.append(
                        make_progress(
                            phase="collecting",
                            text=msg,
                        )
                    )

                analysis = run_trend_scout(
                    focus_keywords=kws,
                    progress_cb=_agent_prog,
                )
                events.extend(agent_events)
                # TrendScoutAgent already collected data; use top_10 as signal proxy
                ctx["signals"] = analysis.top_10  # TrendSignal list from agent
            except Exception as exc:
                events.append(
                    make_error(
                        phase="collecting",
                        message=f"TrendScoutAgent 失败，回退规则模式: {exc}",
                        recoverable=True,
                    )
                )
                analysis = trend_analyst.analyse(signals)
        else:
            analysis = trend_analyst.analyse(signals)

        events.append(
            make_tool_call(
                tool="trend_analyst.analyse" if not self.use_agents else "TrendScoutAgent.analyse",
                args={"signals_in": len(ctx["signals"])},
                status="ok",
                duration_ms=_now_ms() - t0,
                result_summary=f"top {len(analysis.style_trends or analysis.top_10)} styles · "
                f"{len(analysis.patterns)} patterns",
            )
        )
        ctx["analysis"] = analysis
        state.step = 1
        state.trend_analysis = analysis
        if self._should_persist(store):
            self.persistence.persist_trend_analysis(state.pipeline_id, analysis)
            self.persistence.save_checkpoint(
                state,
                phase="trends_review",
                checkpoint_id="trends_review",
            )
        return events

    def _phase_trends_review(self, store: Dict[str, Any]) -> List[ChatEvent]:
        ctx = store["context"]
        analysis = ctx["analysis"]
        signals = ctx["signals"]

        top = analysis.top_10[:10]
        events: List[ChatEvent] = [
            make_phase_enter("trends_review", "趋势分析结果", _elapsed(store)),
        ]

        # ① Aggregated style trends (the actual hot styles)
        if analysis.style_trends:
            cat_label = {"style": "款式", "color": "色系", "material": "材质", "scene": "场景"}
            events.append(
                make_phase_output(
                    "trends_review",
                    TableOutput(
                        title="风格/标签热度（按聚合互动量）",
                        columns=["标签", "类别", "出现帖数", "累计互动", "相对热度"],
                        rows=[
                            [
                                t.tag,
                                cat_label.get(t.category, t.category),
                                t.post_count,
                                t.total_engagement,
                                round(t.aggregated_score, 1),
                            ]
                            for t in analysis.style_trends[:10]
                        ],
                    ),
                )
            )
            events.append(
                make_phase_output(
                    "trends_review",
                    ChartOutput(
                        title="Top 风格相对热度",
                        chart_type="bar",
                        x=[round(t.aggregated_score, 1) for t in analysis.style_trends[:10]],
                        y=[t.tag for t in analysis.style_trends[:10]],
                    ),
                )
            )

        # ② Top-10 individual posts enriched with tags and engagement metrics
        events.append(
            make_phase_output(
                "trends_review",
                TableOutput(
                    title="参考样本 · Top 10 高互动帖（含标签）",
                    columns=[
                        "排名",
                        "样本",
                        "标题摘要",
                        "标签组合",
                        "平台",
                        "点赞",
                        "收藏",
                        "综合分",
                    ],
                    rows=[
                        [
                            i + 1,
                            sample_label(s, i + 1, with_tags=False),
                            source_title(s),
                            tag_summary(s),
                            s.platform,
                            s.likes,
                            s.collects,
                            round(s.composite_score, 1),
                        ]
                        for i, s in enumerate(top)
                    ],
                ),
            )
        )
        events.append(
            make_phase_output(
                "trends_review",
                ImageGalleryOutput(
                    title="参考样本图片 · Top 10",
                    items=[
                        GalleryItem(
                            url=signal_image_url(s),
                            caption=sample_label(s, i + 1, with_tags=True),
                            badge=f"{s.platform} · 综合分 {s.composite_score:.0f}",
                        )
                        for i, s in enumerate(top)
                    ],
                ),
            )
        )

        # ③ Patterns + anomalies
        if analysis.patterns or analysis.anomalies:
            md_lines = []
            if analysis.patterns:
                md_lines.append("**风格组合**")
                for p in analysis.patterns[:5]:
                    md_lines.append(f"- {p}")
            if analysis.anomalies:
                md_lines.append("")
                md_lines.append("**近 48h 突发热度**")
                for a in analysis.anomalies[:5]:
                    md_lines.append(f"- {a}")
            events.append(
                make_phase_output(
                    "trends_review",
                    MarkdownOutput(title="组合 & 异常", body="\n".join(md_lines)),
                )
            )

        kw_default = ",".join(XHS_KEYWORDS[:5])
        from nails_agent.agents.chat_events import FormField

        events.append(
            make_checkpoint(
                "trends_review",
                f"已采集 {len(signals)} 条 / 分析出 {len(analysis.top_10)} 个 top 趋势。是否继续到价值评估？",
                choices=[
                    CheckpointChoice(
                        id="approve", label="✓ 继续到价值评估", style="primary", priority="P1"
                    ),
                    CheckpointChoice(
                        id="adjust_kws",
                        label="🔧 调关键词重抓",
                        style="secondary",
                        priority="P0",
                        form=[
                            FormField(
                                name="keywords",
                                label="关键词（逗号分隔）",
                                type="text",
                                default=kw_default,
                            )
                        ],
                    ),
                    CheckpointChoice(id="abort", label="✗ 结束", style="danger", priority="P0"),
                ],
                auto_approve_after_s=15,
                auto_approve_choice_id="approve",
            )
        )
        return events

    def _phase_evaluating(self, store: Dict[str, Any]) -> List[ChatEvent]:
        ctx = store["context"]
        analysis = ctx["analysis"]
        state = self._get_pipeline_state(store)
        state.status = "running"
        state.meta.update({"phase": "evaluating", "persisted_at": datetime.now().isoformat()})
        if self._should_persist(store):
            self.persistence.save_state(state)
        library = self._load_library()

        events: List[ChatEvent] = [
            make_phase_enter("evaluating", "Step 2/4 价值评估 + 素材生成", _elapsed(store)),
        ]

        # value_evaluator
        t0 = _now_ms()
        try:
            value_result = value_evaluator.evaluate(analysis, library)
        except Exception as exc:
            events.append(
                make_error(
                    phase="evaluating",
                    message=f"value_evaluator 失败: {exc}",
                    recoverable=True,
                    traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
                )
            )
            store["phase"] = "evaluating"
            return events
        events.append(
            make_tool_call(
                tool="value_evaluator.evaluate",
                args={"top_trends": len(analysis.top_10), "library_items": len(library)},
                status="ok",
                duration_ms=_now_ms() - t0,
                result_summary=f"{len(value_result.snapshots)} metric snapshots",
            )
        )
        ctx["value_result"] = value_result

        # asset_generator
        t0 = _now_ms()
        try:
            asset_result = asset_generator.generate(analysis)
        except Exception as exc:
            events.append(
                make_error(
                    phase="evaluating",
                    message=f"asset_generator 失败: {exc}",
                    recoverable=True,
                    traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
                )
            )
            store["phase"] = "evaluating"
            return events
        events.append(
            make_tool_call(
                tool="asset_generator.generate",
                args={"top_trends": len(analysis.top_10)},
                status="ok",
                duration_ms=_now_ms() - t0,
                result_summary=f"{len(asset_result.drafts)} card drafts",
            )
        )
        ctx["asset_result"] = asset_result
        state.step = 2
        state.value_evaluation = value_result
        state.asset_generation = asset_result
        if self._should_persist(store):
            self.persistence.persist_value_evaluation(state.pipeline_id, value_result)
            self.persistence.persist_asset_generation(state.pipeline_id, asset_result)
            self.persistence.save_checkpoint(
                state,
                phase="eval_review",
                checkpoint_id="eval_review",
            )

        # Inline outputs — show all snapshots (up to 10) as trend samples, not search keywords.
        signal_map = {s.trend_id: s for s in analysis.top_10}
        events.append(
            make_phase_output(
                "evaluating",
                TableOutput(
                    title=f"价值评估 Top {len(value_result.snapshots)}",
                    columns=[
                        "排名",
                        "样本",
                        "标签组合",
                        "外部热度",
                        "新鲜度",
                        "风格缺口",
                        "优先级",
                    ],
                    rows=[
                        [
                            s.rank,
                            _metric_sample_label(s, signal_map),
                            _metric_tag_summary(s, signal_map),
                            s.external_heat_score,
                            s.trend_growth_score,
                            s.style_gap_score,
                            s.launch_priority_score,
                        ]
                        for s in value_result.snapshots
                    ],
                ),
            )
        )
        events.append(
            make_phase_output(
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
            )
        )

        # ── Checkpoint: eval_review (Step 2 → Step 3) ─────────────────────
        events.append(make_phase_enter("eval_review", "价值评估结果", _elapsed(store)))
        top_priority = (
            value_result.snapshots[0].launch_priority_score if value_result.snapshots else 0
        )
        events.append(
            make_checkpoint(
                "eval_review",
                f"已生成 {len(value_result.snapshots)} 条评估 + {len(asset_result.drafts)} 张素材卡片。"
                f"最高优先级 {top_priority:.1f}。是否继续到策略制定？",
                choices=[
                    CheckpointChoice(
                        id="approve", label="✓ 继续到策略制定", style="primary", priority="P1"
                    ),
                    CheckpointChoice(id="abort", label="✗ 结束", style="danger", priority="P0"),
                ],
                auto_approve_after_s=15,
                auto_approve_choice_id="approve",
            )
        )
        return events

    def _phase_strategy_building(self, store: Dict[str, Any]) -> List[ChatEvent]:
        ctx = store["context"]
        analysis = ctx["analysis"]
        state = self._get_pipeline_state(store)
        state.status = "running"
        state.meta.update(
            {"phase": "strategy_building", "persisted_at": datetime.now().isoformat()}
        )
        if self._should_persist(store):
            self.persistence.save_state(state)
        events: List[ChatEvent] = [
            make_phase_enter("strategy_building", "Step 3/4 运营策略", _elapsed(store)),
        ]
        t0 = _now_ms()
        try:
            if self.use_agents:
                events.append(
                    make_tool_call(
                        tool="CampaignAgent.run",
                        args={"mode": "LLM", "styles": len(analysis.style_trends or [])},
                        status="ok",
                        duration_ms=0,
                        result_summary="agent启动中…",
                    )
                )
                from nails_agent.agents.campaign_agent import run_campaign_agent

                agent_events: List[ChatEvent] = []

                def _camp_prog(msg: str) -> None:
                    agent_events.append(
                        make_progress(
                            phase="strategy_building",
                            text=msg,
                        )
                    )

                campaign = run_campaign_agent(analysis, max_cards=6, progress_cb=_camp_prog)
                events.extend(agent_events)
            else:
                campaign = campaign_strategist.strategise(ctx["value_result"], ctx["asset_result"])
        except Exception as exc:
            events.append(
                make_error(
                    phase="strategy_building",
                    message=f"策略生成失败: {exc}",
                    recoverable=True,
                    traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
                )
            )
            store["phase"] = "strategy_building"
            return events
        events.append(
            make_tool_call(
                tool="CampaignAgent.run" if self.use_agents else "campaign_strategist.strategise",
                args={},
                status="ok",
                duration_ms=_now_ms() - t0,
                result_summary=f"{len(campaign.style_cards)} cards",
            )
        )
        ctx["campaign"] = campaign
        state.step = 3
        state.campaign_strategy = campaign
        if self._should_persist(store):
            self.persistence.persist_campaign(state.pipeline_id, campaign)
            self.persistence.save_checkpoint(
                state,
                phase="strategy_review",
                checkpoint_id="strategy_review",
            )

        # Strategy markdown
        p0 = [c for c in campaign.style_cards if c.schedule and c.schedule.priority == "P0"]
        p1 = [c for c in campaign.style_cards if c.schedule and c.schedule.priority == "P1"]
        md_lines = [f"### P0 立即上线（{len(p0)} 款）"]
        for c in p0[:5]:
            slot = (c.schedule.xiaohongshu_publish_at if c.schedule else "—") or "—"
            md_lines.append(f"- **{c.style_name}** · 小红书: {slot}")
        if p1:
            md_lines.append(f"\n### P1 储备（{len(p1)} 款）")
            for c in p1[:5]:
                md_lines.append(f"- {c.style_name}")
        events.append(
            make_phase_output(
                "strategy_building",
                MarkdownOutput(title="本轮策略", body="\n".join(md_lines)),
            )
        )

        # ── Checkpoint: strategy_review (Step 3 → Step 4) ─────────────────
        events.append(make_phase_enter("strategy_review", "策略评审", _elapsed(store)))
        events.append(
            make_checkpoint(
                "strategy_review",
                f"策略已生成（P0 {len(p0)}, P1 {len(p1)}）。是否写入记忆并出报告？",
                choices=[
                    CheckpointChoice(
                        id="approve", label="✓ 出报告", style="primary", priority="P0"
                    ),
                    CheckpointChoice(id="abort", label="✗ 中止", style="danger", priority="P0"),
                ],
            )
        )
        return events

    def _phase_reporting(self, store: Dict[str, Any]) -> List[ChatEvent]:
        ctx = store["context"]
        events: List[ChatEvent] = [
            make_phase_enter("reporting", "Step 4/4 出报告 + 蒸馏记忆", _elapsed(store)),
        ]

        # Reuse the same PipelineState so report, artifacts, and memory share one pipeline_id.
        state = self._get_pipeline_state(store)
        state.status = "running"
        state.step = 4
        state.meta.update({"phase": "reporting", "persisted_at": datetime.now().isoformat()})
        state.trend_analysis = ctx["analysis"]
        state.value_evaluation = ctx["value_result"]
        state.asset_generation = ctx["asset_result"]
        state.campaign_strategy = ctx["campaign"]
        if self._should_persist(store):
            self.persistence.save_state(state)

        if self._should_persist(store):
            t_ingest = _now_ms()
            try:
                ingestion = ingest_campaign_styles(
                    state.trend_analysis,
                    state.campaign_strategy,
                    memory=self.memory,
                    data_dir=Path(self.library_path).parent,
                )
                state.meta["style_store_ingestion"] = ingestion
                self.persistence.save_state(state)
                events.append(
                    make_tool_call(
                        tool="style_store_ingestion.ingest_campaign_styles",
                        args={"priorities": ["P0", "P1"]},
                        status="ok",
                        duration_ms=_now_ms() - t_ingest,
                        result_summary=ingestion["summary"],
                    )
                )
                events.append(
                    make_phase_output(
                        "reporting",
                        MarkdownOutput(
                            title="🧩 款式入库同步", body=format_ingestion_markdown(ingestion)
                        ),
                    )
                )
            except Exception as exc:
                events.append(
                    make_error(
                        phase="reporting",
                        message=f"款式入库同步失败: {exc}",
                        recoverable=True,
                        traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
                    )
                )
        else:
            events.append(
                make_tool_call(
                    tool="style_store_ingestion.skip",
                    args={"reason": "mock_preview"},
                    status="ok",
                    result_summary="mock 预览模式：跳过真实入库与 memory.db 写入",
                )
            )

        t0 = _now_ms()
        try:
            report = summarizer.summarise(state)
        except Exception as exc:
            events.append(
                make_error(
                    phase="reporting",
                    message=f"summarizer 失败: {exc}",
                    recoverable=True,
                    traceback_text=traceback.format_exc() if store.get("dev_mode") else None,
                )
            )
            store["phase"] = "reporting"
            return events
        events.append(
            make_tool_call(
                tool="summarizer.summarise",
                args={},
                status="ok",
                duration_ms=_now_ms() - t0,
                result_summary=f"{len(report.markdown)} chars",
            )
        )
        ctx["report"] = report
        state.report = report
        if self._should_persist(store):
            self.persistence.persist_report(state.pipeline_id, report)
            self.persistence.write_report_markdown(report.markdown)

        # Memory distillation (best-effort; failure shouldn't break the pipeline)
        if self._should_persist(store):
            try:
                new_insights = self.memory.distill(state.pipeline_id)
                events.append(
                    make_tool_call(
                        tool="memory.distill",
                        args={"pipeline_id": state.pipeline_id},
                        status="ok",
                        result_summary=f"{len(new_insights)} new insights",
                    )
                )
            except Exception as exc:
                events.append(
                    make_tool_call(
                        tool="memory.distill",
                        args={},
                        status="error",
                        result_summary=str(exc),
                    )
                )
        else:
            events.append(
                make_tool_call(
                    tool="memory.distill.skip",
                    args={"reason": "mock_preview"},
                    status="ok",
                    result_summary="mock 预览模式：不写 memory.db",
                )
            )

        # Final report output
        state.status = "done"
        state.finished_at = datetime.now().isoformat()
        state.meta.update({"phase": "done", "persisted_at": datetime.now().isoformat()})
        if self._should_persist(store):
            self.persistence.save_state(state)
        events.append(
            make_phase_output(
                "reporting",
                MarkdownOutput(title="📄 运营报告", body=report.markdown),
            )
        )

        # Terminal state
        events.append(make_phase_enter("done", "完成 ✅", _elapsed(store)))
        events.append(make_message("assistant", "本轮完成。输入新指令开始下一轮。"))
        store["phase"] = "done"
        return events

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_pipeline_state(self, store: Dict[str, Any]) -> PipelineState:
        ctx = store.setdefault("context", {})
        state = ctx.get("pipeline_state")
        if isinstance(state, PipelineState):
            return state
        if isinstance(state, dict):
            state = PipelineState(**state)
        else:
            state = PipelineState()
        ctx["pipeline_state"] = state
        return state

    def _mark_stopped(self, store: Dict[str, Any], status: str, phase: str) -> None:
        try:
            if not self._should_persist(store):
                return
            state = self._get_pipeline_state(store)
            state.status = status
            state.finished_at = datetime.now().isoformat()
            state.meta.update({"phase": phase, "persisted_at": datetime.now().isoformat()})
            self.persistence.save_state(state)
        except Exception:
            # Stopping should never raise a second UI error.
            pass

    def _mark_error(self, store: Dict[str, Any], exc: Exception) -> None:
        try:
            if not self._should_persist(store):
                return
            state = self._get_pipeline_state(store)
            state.status = "error"
            state.errors.append(str(exc))
            state.meta.update(
                {
                    "phase": store.get("phase", "unknown"),
                    "persisted_at": datetime.now().isoformat(),
                }
            )
            self.persistence.save_state(state)
        except Exception:
            pass

    def _load_library(self) -> List[NailStyleStoreItem]:
        import json

        paths = [
            Path(self.library_path),
            Path("data/nail_styles_store.json"),
            Path("data/nail_styles_v2.json"),
        ]
        for path in paths:
            if not path.exists():
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    return [NailStyleStoreItem(**item) for item in json.load(f)]
            except Exception:
                continue
        return []

    @staticmethod
    def _should_persist(store: Dict[str, Any]) -> bool:
        return bool(store.get("context", {}).get("persist_enabled"))


def _elapsed(store: Dict[str, Any]) -> int:
    t0 = store.get("start_time")
    if not t0:
        return 0
    return int((time.time() - t0) * 1000)


def _metric_sample_label(metric: Any, signal_map: Dict[str, TrendSignal]) -> str:
    sig = signal_map.get(metric.trend_id)
    if sig:
        return sample_label(sig, metric.rank, with_tags=False)
    if getattr(metric, "display_label", ""):
        return metric.display_label
    return f"样本 {metric.rank:02d}" if getattr(metric, "rank", 0) else "趋势样本"


def _metric_tag_summary(metric: Any, signal_map: Dict[str, TrendSignal]) -> str:
    sig = signal_map.get(metric.trend_id)
    if sig:
        return tag_summary(sig)
    return getattr(metric, "tag_summary", "") or "待补充标签"
