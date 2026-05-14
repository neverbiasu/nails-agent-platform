"""
SignalCollector — unified entry point for trend signal collection.

Active sources (all FREE):
  1. XHS-MCP      — local Go xiaohongshu-mcp server (port 18060, REST API)
  2. Douyin CDP   — reuses logged-in Chrome tab  (requires --remote-debugging-port=9222)
  3. Instagram    — playwright CDP or instaloader session
  4. Mock         — demo/data/trend_signals.json  (always available as fallback)

Disabled / suspended sources:
  - XHSCDPFetcher    — direct CDP scraping, suspended after automation warning
  - XHSSkillsFetcher — Node.js xhs-mcp wrapper; replaced by Go xhs-mcp
  - TikHub           — paid API; enable by setting TIKHUB_API_KEY

Usage:
    collector = SignalCollector()
    print(collector.source_status())
    signals = collector.collect()
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

from nails_agent.models.schemas import TrendSignal

logger = logging.getLogger(__name__)

# Per-platform keyword sets (5 each) — targets ≥100 signals/platform/round.

# Chinese terms work best on XHS (cover scene + intent + style).
# Empirically XHS de-dups across keywords at ~40%, so 7 kw × 22 ≈ 154 → ~95-100 unique.
XHS_KEYWORDS = [
    "美甲",  # broadest seed
    "美甲推荐",
    "夏日美甲",
    "显白美甲",
    "美甲灵感",
    "法式美甲",  # style-specific, lifts unique-rate
    "美甲教程",
]

# Douyin: keep similar but lean toward tutorial / show-off content
DOUYIN_KEYWORDS = [
    "美甲",
    "美甲教程",
    "美甲推荐",
    "夏日美甲",
    "高级美甲",
]

# Instagram hashtags (no #) — mix style + general nail tags
IG_NAIL_TAGS = [
    "nailart",
    "cateyenails",
    "frenchnails",
    "gradientnails",
    "3dnailart",
]

# Used by clients (orchestrator, etc.) that want a generic keyword set
DEFAULT_NAIL_KEYWORDS = XHS_KEYWORDS

# Per-platform per-keyword target (5 kw × 25 ≈ 125 → dedup to ~100)
_PER_KW_LIMIT = 25


class SignalCollector:
    """
    Aggregates trend signals from multiple FREE data sources with graceful fallback.
    All fetchers are lazy-loaded and fail-safe.
    """

    def __init__(
        self,
        mock_data_path: Optional[str] = None,
        cdp_url: str = "http://localhost:9222",
        xhs_skills_dir: Optional[Path] = None,
        ig_session_file: Optional[str] = None,
        xhs_mcp_url: str = "http://localhost:18060",
        # Optional paid source
        tikhub_api_key: Optional[str] = None,
    ):
        self._mock_path = mock_data_path
        self._cdp_url = cdp_url
        self._xhs_dir = xhs_skills_dir
        self._ig_session = ig_session_file
        self._xhs_mcp_url = xhs_mcp_url
        self._tikhub_key = tikhub_api_key or os.environ.get("TIKHUB_API_KEY", "")

        # Lazy instances
        self._xhs_mcp = None
        self._douyin = None
        self._instagram = None
        self._tikhub = None

    # ── Lazy fetcher getters ──────────────────────────────────────────────────

    def _get_xhs_mcp(self):
        if self._xhs_mcp is None:
            from nails_agent.tools.fetchers.xhs_mcp_fetcher import XHSMCPFetcher

            self._xhs_mcp = XHSMCPFetcher(base_url=self._xhs_mcp_url)
        return self._xhs_mcp

    def _get_douyin(self):
        if self._douyin is None:
            from nails_agent.tools.fetchers.douyin_cdp import DouyinCDPFetcher

            self._douyin = DouyinCDPFetcher(cdp_url=self._cdp_url)
        return self._douyin

    def _get_instagram(self):
        if self._instagram is None:
            from nails_agent.tools.fetchers.instagram_fetcher import InstagramFetcher

            self._instagram = InstagramFetcher(session_file=self._ig_session)
        return self._instagram

    def _get_tikhub(self):
        if self._tikhub is None:
            from nails_agent.tools.fetchers.tikhub_fetcher import TikHubFetcher

            self._tikhub = TikHubFetcher(api_key=self._tikhub_key)
        return self._tikhub

    # ── Status ────────────────────────────────────────────────────────────────

    def source_status(self) -> Dict[str, bool]:
        """Non-blocking check of which sources are ready."""
        status: Dict[str, bool] = {}
        try:
            status["xhs"] = self._get_xhs_mcp().is_available()
        except Exception:
            status["xhs"] = False
        try:
            status["douyin_cdp"] = self._get_douyin().is_available()
        except Exception:
            status["douyin_cdp"] = False
        try:
            status["instagram"] = self._get_instagram().is_available()
        except Exception:
            status["instagram"] = False
        status["tikhub"] = bool(self._tikhub_key)
        status["mock"] = self._mock_data_available()
        return status

    # ── Collection ────────────────────────────────────────────────────────────

    def collect(
        self,
        keywords: Optional[List[str]] = None,
        limit_per_kw: int = _PER_KW_LIMIT,
        since_days: Optional[int] = None,
        use_xhs: bool = True,
        use_douyin: bool = True,
        use_instagram: bool = True,
        use_tikhub: bool = True,
        use_mock_fallback: bool = True,
        parallel: bool = True,
    ) -> List[TrendSignal]:
        """
        Collect from all available sources (parallel by default).

        Each platform uses its own 5-keyword set targeting ~100 signals per
        platform per round. Pass `keywords` to override the union (used by
        XHS + Douyin; IG uses english hashtags regardless).

        Args:
            since_days: If set, drop signals whose publish_time is older
                than N days. Signals with empty/unknown publish_time
                (e.g. XHS search feeds) are kept regardless — they're
                marked unknown, not aged-out.

        Returns deduplicated List[TrendSignal] sorted by engagement score.
        Falls back to mock data only if all real sources produce nothing.
        """
        xhs_kws = keywords or XHS_KEYWORDS
        douyin_kws = keywords or DOUYIN_KEYWORDS
        ig_tags = IG_NAIL_TAGS  # english hashtags — not parametrised

        all_signals: List[TrendSignal] = []
        sources_used: List[str] = []
        tasks: Dict[str, callable] = {}

        if use_xhs:
            xhs = self._get_xhs_mcp()
            if xhs.is_available():
                tasks["xhs"] = lambda: xhs.search(xhs_kws, limit_per_kw=limit_per_kw)
            else:
                logger.debug("XHS-MCP: Go server not running or not logged in")

        if use_douyin:
            dy = self._get_douyin()
            if dy.is_available():
                tasks["douyin"] = lambda: dy.search(douyin_kws, limit_per_kw=limit_per_kw)
            else:
                logger.debug("Douyin CDP: Chrome not running with debug port")

        if use_instagram:
            ig = self._get_instagram()
            if ig.is_available():
                tasks["instagram"] = lambda: ig.fetch_all(ig_tags, limit_per_tag=limit_per_kw)
            else:
                logger.debug("Instagram: neither CDP nor instaloader available")

        if use_tikhub and self._tikhub_key:
            tasks["tikhub"] = lambda: self._get_tikhub().fetch_all(
                xhs_kws, limit_per_kw=limit_per_kw
            )

        # Execute tasks
        # 5 keywords × scroll/source is slow: XHS ~50s, Douyin ~120s, IG ~150s.
        # Cap at 4 min per source to bound total runtime when one platform stalls.
        if parallel and len(tasks) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
                futures = {pool.submit(fn): name for name, fn in tasks.items()}
                for fut in as_completed(futures):
                    name = futures[fut]
                    try:
                        results = fut.result(timeout=240)
                        if results:
                            all_signals.extend(results)
                            sources_used.append(f"{name}({len(results)})")
                            logger.info("Source %s: %d signals", name, len(results))
                    except Exception as e:
                        logger.error("Source %s failed: %s", name, e)
        else:
            for name, fn in tasks.items():
                try:
                    results = fn()
                    if results:
                        all_signals.extend(results)
                        sources_used.append(f"{name}({len(results)})")
                except Exception as e:
                    logger.error("Source %s failed: %s", name, e)

        # Fallback to mock only when zero real data
        if not all_signals and use_mock_fallback:
            mock = self._load_mock()
            if mock:
                all_signals = mock
                sources_used.append(f"mock({len(mock)})")
                logger.info("Fallback to mock: %d signals", len(mock))

        # Optional recency filter (publish_time known and within window)
        if since_days is not None and all_signals:
            before = len(all_signals)
            all_signals = self._filter_by_age(all_signals, since_days)
            dropped = before - len(all_signals)
            if dropped:
                logger.info(
                    "Recency filter (≤%dd): dropped %d/%d signals", since_days, dropped, before
                )

        if sources_used:
            logger.info("Sources: %s → %d total", ", ".join(sources_used), len(all_signals))
        else:
            logger.warning("No data sources available — returning empty")

        return self._dedup_and_sort(all_signals)

    @staticmethod
    def _filter_by_age(signals: List[TrendSignal], days: int) -> List[TrendSignal]:
        """Drop signals older than `days`. Empty publish_time → kept (unknown ≠ old)."""
        from datetime import datetime, timezone, timedelta

        tz8 = timezone(timedelta(hours=8))
        cutoff = datetime.now(tz8) - timedelta(days=days)
        kept = []
        for s in signals:
            if not s.publish_time:
                kept.append(s)  # unknown date → keep
                continue
            try:
                pub = datetime.fromisoformat(s.publish_time)
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=tz8)
                if pub >= cutoff:
                    kept.append(s)
            except Exception:
                kept.append(s)  # un-parseable → keep (don't silently drop)
        return kept

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _mock_data_available(self) -> bool:
        p = self._resolve_mock_path()
        return p is not None and p.exists()

    def _resolve_mock_path(self) -> Optional[Path]:
        if self._mock_path:
            p = Path(self._mock_path)
            return p if p.exists() else None
        for p in [
            Path("demo/data/trend_signals.json"),
            Path("demo/data/trend_signals_with_score.json"),
        ]:
            if p.exists():
                return p
        return None

    def _load_mock(self) -> List[TrendSignal]:
        path = self._resolve_mock_path()
        if not path:
            return []
        try:
            with open(path, encoding="utf-8") as f:
                return [TrendSignal(**item) for item in json.load(f)]
        except Exception as e:
            logger.error("Mock data load error: %s", e)
            return []

    def _dedup_and_sort(self, signals: List[TrendSignal]) -> List[TrendSignal]:
        seen: set = set()
        deduped = []
        for s in signals:
            if s.trend_id not in seen:
                seen.add(s.trend_id)
                deduped.append(s)
        deduped.sort(
            key=lambda s: s.likes + s.collects * 1.5 + s.shares * 2 + s.comments * 0.5,
            reverse=True,
        )
        return deduped
