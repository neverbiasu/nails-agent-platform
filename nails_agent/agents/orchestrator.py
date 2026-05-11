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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from nails_agent.models.schemas import (
    PipelineState,
    TrendSignal,
    StyleLibraryItem,
    MemoryEntry,
)
from nails_agent.memory.store import MemoryStore
from nails_agent.tools.fetchers.signal_collector import SignalCollector, DEFAULT_NAIL_KEYWORDS
from nails_agent.agents.workers import (
    trend_analyst,
    value_evaluator,
    asset_generator,
    campaign_strategist,
    summarizer,
)

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(
        self,
        memory: Optional[MemoryStore] = None,
        data_dir: str = "demo/data",
        output_dir: str = "demo/output",
        keywords: Optional[List[str]] = None,
        collector: Optional[SignalCollector] = None,
    ):
        self.memory = memory or MemoryStore()
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.keywords = keywords or DEFAULT_NAIL_KEYWORDS
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
        self._save_state(state)
        emit = progress_cb or (lambda msg: logger.info(msg))

        try:
            # ── Load inputs ────────────────────────────────────────────────
            if signals is None:
                status = self.collector.source_status()
                live = [k for k, v in status.items() if v and k != "mock"]
                emit(f"📡 数据源：{', '.join(live) if live else '📦 mock (无实时源)'}")
                signals = self.collector.collect(keywords=self.keywords)
                emit(f"📥 获取信号 {len(signals)} 条")
            # Persist raw signals so the demo UI can show real data
            self._persist_signals(signals)
            library = self._load_library()

            # ── Step 1: Trend Analysis ─────────────────────────────────────
            emit("⏳ Step 1/4 趋势分析中…")
            state.step = 1
            analysis = trend_analyst.analyse(signals)
            state.trend_analysis = analysis
            self._persist_trend_analysis(state.pipeline_id, analysis)
            emit(f"✅ Step 1 完成 — top 关键词：{', '.join(s.keyword for s in analysis.top_10[:3])}")

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
            self._persist_value_evaluation(state.pipeline_id, value_result)
            self._persist_asset_generation(state.pipeline_id, asset_result)
            emit(f"✅ Step 2 完成 — {len(value_result.snapshots)} 条评估, {len(asset_result.drafts)} 张卡片草稿")

            # ── Step 3: Campaign Strategy ──────────────────────────────────
            emit("⏳ Step 3/4 运营策略制定中…")
            state.step = 3
            campaign = campaign_strategist.strategise(value_result, asset_result)
            state.campaign_strategy = campaign
            self._persist_campaign(state.pipeline_id, campaign)
            p0_count = sum(1 for c in campaign.style_cards if c.schedule and c.schedule.priority == "P0")
            emit(f"✅ Step 3 完成 — {len(campaign.style_cards)} 张策略卡片，P0 立即上线 {p0_count} 款")

            # ── Step 4: Summary Report ─────────────────────────────────────
            emit("⏳ Step 4/4 生成运营报告…")
            state.step = 4
            report = summarizer.summarise(state)
            state.report = report
            self._persist_report(state.pipeline_id, report)
            self._write_markdown(state.pipeline_id, report.markdown)
            emit(f"✅ Step 4 完成 — 报告已生成")

            # ── Distill long-term memory ───────────────────────────────────
            new_insights = self.memory.distill(state.pipeline_id)
            if new_insights:
                emit(f"🧠 记忆蒸馏：{len(new_insights)} 条新洞察写入长期记忆")

            state.status = "done"
            state.finished_at = datetime.now().isoformat()

        except Exception as exc:
            logger.exception("Pipeline error at step %d", state.step)
            state.errors.append(f"Step {state.step}: {exc}")
            state.status = "error"

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
        try:
            signals = signals or self._load_signals()
            emit("⏳ Step 1 趋势分析中…")
            analysis = trend_analyst.analyse(signals)
            state.trend_analysis = analysis
            state.step = 1
            self._persist_trend_analysis(state.pipeline_id, analysis)
            emit(f"✅ Step 1 完成")
            state.status = "done"
        except Exception as exc:
            state.errors.append(str(exc))
            state.status = "error"
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

    def _load_library(self) -> List[StyleLibraryItem]:
        path = self.data_dir / "style_library.json"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            return [StyleLibraryItem(**item) for item in json.load(f)]

    # ── Raw signal persistence (for demo UI) ────────────────────────────────

    def _persist_signals(self, signals: List[TrendSignal]) -> None:
        """Write raw signals to output dir so the demo can show real data."""
        try:
            import json
            path = self.output_dir / "trend_signals.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump([s.model_dump() for s in signals], f,
                          ensure_ascii=False, indent=2)
            logger.debug("Persisted %d signals to %s", len(signals), path)
        except Exception as exc:
            logger.warning("Failed to persist signals: %s", exc)

    # ── Memory persistence ──────────────────────────────────────────────────

    def _persist_trend_analysis(self, pid: str, result) -> None:
        entries: List[MemoryEntry] = []
        for sig in result.top_10:
            entries.append(MemoryEntry(
                pipeline_id=pid,
                produced_by="trend_analyst",
                kind="trend",
                key=sig.trend_id,
                value=sig.model_dump_json(),
                tags=f"{sig.keyword},{','.join(sig.style_tags)},{sig.platform}",
            ))
        for i, p in enumerate(result.patterns):
            entries.append(MemoryEntry(
                pipeline_id=pid, produced_by="trend_analyst",
                kind="pattern", key=f"pattern_{i}", value=p, tags=p,
            ))
        for i, a in enumerate(result.anomalies):
            entries.append(MemoryEntry(
                pipeline_id=pid, produced_by="trend_analyst",
                kind="anomaly", key=f"anomaly_{i}", value=a, tags=a,
            ))
        self.memory.save_many(entries)
        # Write JSON artifact
        out = self.output_dir / "trend_top10.json"
        out.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    def _persist_value_evaluation(self, pid: str, result) -> None:
        entries = [
            MemoryEntry(
                pipeline_id=pid, produced_by="value_evaluator",
                kind="metric", key=s.metric_id,
                value=s.model_dump_json(),
                tags=f"{s.keyword},priority:{s.launch_priority_score:.0f}",
            )
            for s in result.snapshots
        ]
        self.memory.save_many(entries)
        out = self.output_dir / "metric_snapshots.json"
        out.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    def _persist_asset_generation(self, pid: str, result) -> None:
        entries = [
            MemoryEntry(
                pipeline_id=pid, produced_by="asset_generator",
                kind="style_card_draft", key=d.card_id,
                value=d.model_dump_json(),
                tags=f"{d.style_name},{','.join(d.style_tags)}",
            )
            for d in result.drafts
        ]
        self.memory.save_many(entries)
        out = self.output_dir / "style_cards_draft.json"
        out.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    def _persist_campaign(self, pid: str, result) -> None:
        entries = [
            MemoryEntry(
                pipeline_id=pid, produced_by="campaign_strategist",
                kind="style_card", key=c.card_id,
                value=c.model_dump_json(),
                tags=f"{c.style_name},priority:{c.schedule.priority if c.schedule else 'P2'}",
            )
            for c in result.style_cards
        ]
        self.memory.save_many(entries)
        out = self.output_dir / "style_cards.json"
        out.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    def _persist_report(self, pid: str, report) -> None:
        entry = MemoryEntry(
            pipeline_id=pid, produced_by="summarizer",
            kind="summary", key=pid,
            value=report.model_dump_json(),
            tags=",".join(report.top_3_keywords),
        )
        self.memory.save(entry)
        out = self.output_dir / "report.json"
        out.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    def _write_markdown(self, pid: str, markdown: str) -> None:
        out = self.output_dir / "report.md"
        out.write_text(markdown, encoding="utf-8")

    def _save_state(self, state: PipelineState) -> None:
        self.memory.save_pipeline_state(
            state.pipeline_id, state.status, state.model_dump_json()
        )
