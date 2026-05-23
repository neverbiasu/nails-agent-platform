"""
Pipeline Orchestrator.

Runs the 4-step nail-trend pipeline:
  Step 1  → trend_analyst      : TrendSignal[]   → TrendAnalysisResult
  Step 2a → value_evaluator    : analysis + lib  → ValueEvaluationResult
  Step 2b → asset_generator    : analysis        → AssetGenerationResult
  Step 3  → campaign_strategist: value + assets  → CampaignStrategyResult
  Step 4  → summarizer         : PipelineState   → SummaryReport

State is held in PipelineState (L1 / in-memory).
Completed step outputs are persisted to MemoryStore (L2 / SQLite+FTS5).
After each pipeline, distill() promotes patterns to long-term insights.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from nails_agent.models.schemas import (
    PipelineState,
    TrendCluster,
    TrendEvent,
    StrategyEvent,
    TrendSignal,
    NailStyleStoreItem,
    TriggerEvent,
)
from nails_agent.memory.store import MemoryStore
from nails_agent.memory.event_log import EventLog
from nails_agent.services.pipeline_persistence import PipelinePersistence
from nails_agent.services.style_store_ingestion import ingest_campaign_styles
from nails_agent.services.trend_presentation import sample_label
from nails_agent.tools.fetchers.signal_collector import SignalCollector, DEFAULT_NAIL_KEYWORDS
from nails_agent.agents.workers import (
    value_evaluator,
    asset_generator,
    campaign_strategist,
    summarizer,
)

# Agent-powered workers (fall back to rule-based if ANTHROPIC_API_KEY missing)
from nails_agent.agents.trend_agent import run_trend_scout
from nails_agent.agents.campaign_agent import run_campaign_agent
from nails_agent.agents.summarizer import Summarizer
from nails_agent.agents.reviewer_guardrail import ReviewerGuardrail

logger = logging.getLogger(__name__)

AGENT_ID = "Orchestrator"


class PipelineOrchestrator:
    def __init__(
        self,
        memory: Optional[MemoryStore] = None,
        event_log: Optional[EventLog] = None,
        data_dir: str = "web/data",
        output_dir: str = "web/output",
        keywords: Optional[List[str]] = None,
        collector: Optional[SignalCollector] = None,
        use_agents: bool = True,  # use LLM-powered agents (falls back if API key absent)
    ):
        self.memory = memory or MemoryStore()
        self.event_log = event_log or EventLog()
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.persistence = PipelinePersistence(memory=self.memory, output_dir=self.output_dir)
        self.keywords = keywords or DEFAULT_NAIL_KEYWORDS
        import os as _os

        self.use_agents = use_agents and bool(
            _os.environ.get("ANTHROPIC_API_KEY")
            or _os.environ.get("OPENROUTER_API_KEY")
            or _os.environ.get("MODELSCOPE_API_KEY")
        )
        # SignalCollector: uses TikHub + XHS Skills + mock fallback
        self.collector = collector or SignalCollector(
            mock_data_path=str(self.data_dir / "trend_signals.json"),
        )

    # ── Public entry point ──────────────────────────────────────────────────

    def run(
        self,
        signals: Optional[List[TrendSignal]] = None,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> PipelineState:
        """
        Execute the full 4-step pipeline.

        Args:
            signals: Pre-loaded trend signals. If None, loaded from data_dir.
            progress_cb: Optional callback(message) for progress reporting.
        """
        state = PipelineState()
        state.status = "running"
        self.collector.rejected_candidates = []
        emit = progress_cb or (lambda msg: logger.info(msg))
        provided_signals = signals is not None
        persist_enabled = True

        try:
            # ── Load inputs ────────────────────────────────────────────────
            if signals is None:
                status = self.collector.source_status()
                live = [k for k, v in status.items() if v and k != "mock"]
                emit(f"📡 数据源：{', '.join(live) if live else '📦 mock (无实时源)'}")
                signals = self.collector.collect(keywords=self.keywords)
                emit(f"📥 获取信号 {len(signals)} 条")
            mock_preview = (not provided_signals) and self.collector.last_collection_used_mock
            persist_enabled = not mock_preview
            state.meta.update(
                {
                    "data_mode": "mock_preview" if mock_preview else "real",
                    "persist_enabled": persist_enabled,
                }
            )
            if persist_enabled:
                self._save_state(state)
            else:
                emit("📦 Mock 预览模式：不写 memory.db、不覆盖 web/output、不入主库")
            # Persist raw signals so the demo UI can show real data
            if persist_enabled:
                self._persist_signals(signals)
                self._persist_rejected_candidates(state.pipeline_id)
            library = self._load_library()

            # ── Step 1: Trend Analysis ─────────────────────────────────────
            emit("⏳ Step 1/4 趋势分析中…")
            state.step = 1
            if self.use_agents:
                emit("🤖 TrendScoutAgent 启动（LLM 驱动）…")
                analysis = run_trend_scout(
                    focus_keywords=self.keywords[:5],
                    progress_cb=emit,
                )
            else:
                from nails_agent.agents.workers import trend_analyst

                analysis = trend_analyst.analyse(signals)
            state.trend_analysis = analysis
            if persist_enabled:
                self._persist_trend_analysis(state.pipeline_id, analysis)
            top_tags = [st.tag for st in analysis.style_trends[:3]] or [
                sample_label(s, i + 1, with_tags=True) for i, s in enumerate(analysis.top_10[:3])
            ]
            emit(f"✅ Step 1 完成 — top 风格：{', '.join(top_tags)}")

            # ── Step 2a + 2b in parallel ───────────────────────────────────
            emit("⏳ Step 2/4 价值评估 & 素材生成（并行）…")
            state.step = 2
            with ThreadPoolExecutor(max_workers=2) as pool:
                f_value = pool.submit(value_evaluator.evaluate, analysis, library)
                f_assets = pool.submit(asset_generator.generate, analysis)
                value_result = f_value.result()
                asset_result = f_assets.result()

            state.value_evaluation = value_result
            state.asset_generation = asset_result
            if persist_enabled:
                self._persist_value_evaluation(state.pipeline_id, value_result)
                self._persist_asset_generation(state.pipeline_id, asset_result)
            emit(
                f"✅ Step 2 完成 — {len(value_result.snapshots)} 条评估, {len(asset_result.drafts)} 张卡片草稿"
            )

            # ── Step 3: Campaign Strategy ──────────────────────────────────
            emit("⏳ Step 3/4 运营策略制定中…")
            state.step = 3
            if self.use_agents:
                emit("🤖 CampaignAgent 启动（LLM 文案生成）…")
                campaign = run_campaign_agent(analysis, max_cards=6, progress_cb=emit)
            else:
                campaign = campaign_strategist.strategise(value_result, asset_result)
            state.campaign_strategy = campaign
            if persist_enabled:
                self._persist_campaign(state.pipeline_id, campaign)
                ingestion = ingest_campaign_styles(
                    analysis, campaign,
                    memory=self.memory,
                    data_dir=str(self.data_dir),
                )
                state.meta["style_store_ingestion"] = ingestion
            else:
                ingestion = {"summary": "mock 预览模式：跳过真实入库"}
            p0_count = sum(
                1 for c in campaign.style_cards if c.schedule and c.schedule.priority == "P0"
            )
            emit(
                f"✅ Step 3 完成 — {len(campaign.style_cards)} 张策略卡片，P0 立即上线 {p0_count} 款"
            )
            emit(f"✅ 款式入库同步 — {ingestion['summary']}")

            # ── Step 4: Summary Report ─────────────────────────────────────
            emit("⏳ Step 4/4 生成运营报告…")
            state.step = 4
            report = summarizer.summarise(state)
            state.report = report
            if persist_enabled:
                self._persist_report(state.pipeline_id, report)
                self._write_markdown(state.pipeline_id, report.markdown)
            emit("✅ Step 4 完成 — 报告已生成")

            # ── Distill long-term memory ───────────────────────────────────
            if persist_enabled:
                new_insights = self.memory.distill(state.pipeline_id)
                if new_insights:
                    emit(f"🧠 记忆蒸馏：{len(new_insights)} 条新洞察写入长期记忆")

            state.status = "done"
            state.finished_at = datetime.now().isoformat()

        except Exception as exc:
            logger.exception("Pipeline error at step %d", state.step)
            state.errors.append(f"Step {state.step}: {exc}")
            state.status = "error"

        if persist_enabled:
            self._save_state(state)
        return state

    def run_step1_only(
        self,
        signals: Optional[List[TrendSignal]] = None,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> PipelineState:
        state = PipelineState()
        state.status = "running"
        emit = progress_cb or (lambda msg: logger.info(msg))
        provided_signals = signals is not None
        persist_enabled = provided_signals
        try:
            emit("⏳ Step 1 趋势分析中…")
            if self.use_agents:
                emit("🤖 TrendScoutAgent 启动…")
                analysis = run_trend_scout(
                    focus_keywords=self.keywords[:5],
                    progress_cb=emit,
                )
            else:
                signals = signals or self._load_signals()
                from nails_agent.agents.workers import trend_analyst

                analysis = trend_analyst.analyse(signals)
            state.trend_analysis = analysis
            state.step = 1
            if persist_enabled:
                self._persist_trend_analysis(state.pipeline_id, analysis)
            else:
                emit("📦 Mock 预览模式：不写 memory.db、不覆盖 web/output")
            emit("✅ Step 1 完成")
            state.status = "done"
        except Exception as exc:
            state.errors.append(str(exc))
            state.status = "error"
        if persist_enabled:
            self._save_state(state)
        return state

    # ── EventLog-aware pipeline (A3) ────────────────────────────────────────

    def run_pipeline(self, trigger: TriggerEvent) -> PipelineState:
        """
        Run the full pipeline for a given TriggerEvent, writing EventLog at each step.

        Chain: TrendAnalyst → ValueEvaluator → CampaignStrategist → Summarizer
        Each step result is written to event_log before proceeding.
        """
        trigger_id = trigger.trigger_id
        keywords = trigger.keywords or self.keywords

        def emit(msg: str) -> None:
            logger.info("[run_pipeline:%s] %s", trigger_id[:8], msg)

        state = PipelineState()
        state.status = "running"
        persist_enabled = True

        try:
            # ── Load signals ───────────────────────────────────────────────
            status = self.collector.source_status()
            live = [k for k, v in status.items() if v and k != "mock"]
            emit(f"📡 数据源：{', '.join(live) if live else '📦 mock'}")
            signals = self.collector.collect(keywords=keywords)
            emit(f"📥 获取信号 {len(signals)} 条")
            mock_preview = self.collector.last_collection_used_mock
            persist_enabled = not mock_preview
            state.meta.update(
                {
                    "data_mode": "mock_preview" if mock_preview else "real",
                    "persist_enabled": persist_enabled,
                }
            )
            if persist_enabled:
                self._save_state(state)
                self._persist_signals(signals)
                self._persist_rejected_candidates(state.pipeline_id)
            else:
                emit("📦 Mock 预览模式：不写 memory.db、不覆盖 web/output、不入主库")
            library = self._load_library()

            # ── Step 1: Trend Analysis ─────────────────────────────────────
            emit("⏳ Step 1 趋势分析中…")
            state.step = 1
            if self.use_agents:
                analysis = run_trend_scout(focus_keywords=keywords[:5], progress_cb=emit)
            else:
                from nails_agent.agents.workers import trend_analyst as _ta

                analysis = _ta.analyse(signals)
            state.trend_analysis = analysis
            if persist_enabled:
                self._persist_trend_analysis(state.pipeline_id, analysis)

            trend_event = TrendEvent(
                trigger_id=trigger_id,
                clusters=[
                    TrendCluster(
                        cluster_id=f"cluster_{i}",
                        keywords=[
                            sample_label(s, i * 3 + j + 1, with_tags=True)
                            for j, s in enumerate(analysis.top_10[i * 3 : i * 3 + 3])
                        ],
                        top_tags=analysis.top_10[i * 3].style_tags
                        if analysis.top_10[i * 3 :]
                        else [],
                    )
                    for i in range(min(3, (len(analysis.top_10) + 2) // 3))
                ],
                top_keywords=[
                    sample_label(s, i + 1, with_tags=True)
                    for i, s in enumerate(analysis.top_10[:10])
                ],
                confidence=min(1.0, len(signals) / 100),
            )
            if persist_enabled:
                self.event_log.write(
                    event_type="TrendEvent",
                    payload=trend_event.model_dump(),
                    trigger_id=trigger_id,
                    agent_id="TrendAnalyst",
                )
            emit(f"✅ Step 1 完成 — top 样本：{', '.join(trend_event.top_keywords[:3])}")

            # ── Step 2: Value Evaluation + Asset Generation (parallel) ─────
            emit("⏳ Step 2 价值评估 & 素材生成（并行）…")
            state.step = 2
            with ThreadPoolExecutor(max_workers=2) as pool:
                f_value = pool.submit(value_evaluator.evaluate, analysis, library)
                f_assets = pool.submit(asset_generator.generate, analysis)
                value_result = f_value.result()
                asset_result = f_assets.result()
            state.value_evaluation = value_result
            state.asset_generation = asset_result
            if persist_enabled:
                self._persist_value_evaluation(state.pipeline_id, value_result)
                self._persist_asset_generation(state.pipeline_id, asset_result)
            emit(f"✅ Step 2 完成 — {len(value_result.snapshots)} 条评估")

            # ── Step 3: Campaign Strategy ──────────────────────────────────
            emit("⏳ Step 3 运营策略制定中…")
            state.step = 3
            if self.use_agents:
                campaign = run_campaign_agent(analysis, max_cards=6, progress_cb=emit)
            else:
                campaign = campaign_strategist.strategise(value_result, asset_result)
            state.campaign_strategy = campaign
            if persist_enabled:
                self._persist_campaign(state.pipeline_id, campaign)
                ingestion = ingest_campaign_styles(
                    analysis, campaign,
                    memory=self.memory,
                    data_dir=str(self.data_dir),
                )
                state.meta["style_store_ingestion"] = ingestion
            else:
                ingestion = {"summary": "mock 预览模式：跳过真实入库"}

            strategy_event = StrategyEvent(
                trigger_id=trigger_id,
                strategy_summary=campaign.executive_summary
                or (campaign.style_cards[0].style_name if campaign.style_cards else "策略已生成"),
                platform_variants=[c.model_dump() for c in campaign.style_cards[:3]],
                publish_schedule=campaign.style_cards[0].schedule.model_dump()
                if campaign.style_cards and campaign.style_cards[0].schedule
                else None,
            )
            if persist_enabled:
                self.event_log.write(
                    event_type="StrategyEvent",
                    payload=strategy_event.model_dump(),
                    trigger_id=trigger_id,
                    agent_id="CampaignStrategist",
                )
            emit(f"✅ Step 3 完成 — {len(campaign.style_cards)} 张策略卡片")
            emit(f"✅ 款式入库同步 — {ingestion['summary']}")

            # ── Step 4: Summary Report + CandidatePackage ─────────────────
            emit("⏳ Step 4 生成运营报告…")
            state.step = 4
            report = summarizer.summarise(state)
            state.report = report
            if persist_enabled:
                self._persist_report(state.pipeline_id, report)
                self._write_markdown(state.pipeline_id, report.markdown)

            # Build CandidatePackage
            if persist_enabled:
                agent_summarizer = Summarizer(event_log=self.event_log)
                candidate = agent_summarizer.summarise(trigger_id=trigger_id, state=state)
                emit(
                    f"✅ Step 4 完成 — CandidatePackage ready (score={candidate.review_score:.2f})"
                )
            else:
                candidate = None
                emit("✅ Step 4 完成 — mock 预览报告已生成")

            # ReviewerGuardrail (rules + optional LLM)
            if persist_enabled and candidate is not None:
                emit("⏳ ReviewerGuardrail 审查中…")
                reviewer = ReviewerGuardrail(event_log=self.event_log)
                review_decision = reviewer.review(candidate)
                emit(f"✅ 审查完成 — {review_decision.status}: {review_decision.reason[:60]}")

            if persist_enabled:
                new_insights = self.memory.distill(state.pipeline_id)
                if new_insights:
                    emit(f"🧠 记忆蒸馏：{len(new_insights)} 条新洞察")

            state.status = "done"
            state.finished_at = datetime.now().isoformat()

        except Exception as exc:
            logger.exception("run_pipeline error at step %d for trigger %s", state.step, trigger_id)
            state.errors.append(f"Step {state.step}: {exc}")
            state.status = "error"
            if persist_enabled:
                self.event_log.write(
                    event_type="ErrorEvent",
                    payload={"error": str(exc), "step": state.step},
                    trigger_id=trigger_id,
                    agent_id=AGENT_ID,
                )

        if persist_enabled:
            self._save_state(state)
        return state

    # ── Data loading ────────────────────────────────────────────────────────

    def _load_signals(self) -> List[TrendSignal]:
        """Legacy method: direct mock load (bypasses SignalCollector)."""
        path = self.data_dir / "trend_signals.json"
        with open(path, encoding="utf-8") as f:
            return [TrendSignal(**item) for item in json.load(f)]

    def source_status(self) -> dict:
        return self.collector.source_status()

    def _load_library(self) -> List[NailStyleStoreItem]:
        for name in ("nail_styles_store.json", "nail_styles_v2.json"):
            path = self.data_dir / name
            if not path.exists():
                continue
            with open(path, encoding="utf-8") as f:
                return [NailStyleStoreItem(**item) for item in json.load(f)]
        return []

    # ── Shared persistence wrappers ────────────────────────────────────────

    def _persist_signals(self, signals: List[TrendSignal]) -> None:
        self.persistence.persist_signals(signals)

    def _persist_rejected_candidates(self, pipeline_id: str) -> None:
        self.persistence.persist_rejected_candidates(
            pipeline_id,
            self.collector.rejected_candidates,
        )

    def _persist_trend_analysis(self, pid: str, result) -> None:
        self.persistence.persist_trend_analysis(pid, result)

    def _persist_value_evaluation(self, pid: str, result) -> None:
        self.persistence.persist_value_evaluation(pid, result)

    def _persist_asset_generation(self, pid: str, result) -> None:
        self.persistence.persist_asset_generation(pid, result)

    def _persist_campaign(self, pid: str, result) -> None:
        self.persistence.persist_campaign(pid, result)

    def _persist_report(self, pid: str, report) -> None:
        self.persistence.persist_report(pid, report)

    def _write_markdown(self, pid: str, markdown: str) -> None:
        self.persistence.write_report_markdown(markdown)

    def _save_state(self, state: PipelineState) -> None:
        self.persistence.save_state(state)
