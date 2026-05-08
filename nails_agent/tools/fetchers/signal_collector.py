"""
SignalCollector — unified entry point for trend signal collection.

All sources are FREE — no paid API keys required.

XHS source strategy:
  Primary:  XHSCDPFetcher  — scroll-based CDP scraper (up to 100+ per keyword)
            + Strategy A: seed "美甲" → auto-discover hot sub-keywords → drill down
  Fallback: XHSSkillsFetcher — CLI-based (44 per keyword, no scroll)

Other sources (all tried in parallel, results merged):
  2. Douyin CDP      抖音    browser CDP  (requires Chrome at localhost:9222)
  3. Instagram       IG      instaloader  (pip install instaloader, public hashtags)
  4. Mock            fallback             (demo/data/trend_signals.json)

TikHub (paid) is still supported as optional source if TIKHUB_API_KEY is set.

Usage:
    collector = SignalCollector()
    print(collector.source_status())       # which sources are live
    signals = collector.collect()          # auto-merge all available sources
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

# Strategy B: scene/intent keywords used as supplementary search terms
DEFAULT_NAIL_KEYWORDS = [
    "美甲",           # seed for Strategy A discovery
    "美甲推荐",
    "美甲灵感",
    "显白美甲",
    "夏日美甲",
    "美甲教程",
]

# Explicit style keywords (used when Strategy A discovery yields too few results)
_STYLE_KEYWORDS = [
    "猫眼美甲",
    "法式美甲",
    "渐变美甲",
    "奶油美甲",
    "3D美甲",
    "贴片美甲",
]

_IG_NAIL_TAGS = [
    "nailart", "cateyenails", "frenchnails",
    "3dnailart", "gradientnails", "gelnails",
]


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
        # Optional paid source
        tikhub_api_key: Optional[str] = None,
    ):
        self._mock_path = mock_data_path
        self._cdp_url = cdp_url
        self._xhs_dir = xhs_skills_dir
        self._ig_session = ig_session_file
        self._tikhub_key = tikhub_api_key or os.environ.get("TIKHUB_API_KEY", "")

        # Lazy instances
        self._xhs_cdp = None   # scroll-based CDP fetcher (primary)
        self._xhs = None        # CLI skills fetcher (fallback)
        self._douyin = None
        self._instagram = None
        self._tikhub = None

    # ── Lazy fetcher getters ──────────────────────────────────────────────────

    def _get_xhs_cdp(self):
        if self._xhs_cdp is None:
            from nails_agent.tools.fetchers.xhs_cdp_fetcher import XHSCDPFetcher
            self._xhs_cdp = XHSCDPFetcher(cdp_url=self._cdp_url)
        return self._xhs_cdp

    def _get_xhs(self):
        if self._xhs is None:
            from nails_agent.tools.fetchers.xhs_skills_fetcher import XHSSkillsFetcher
            self._xhs = XHSSkillsFetcher(skills_dir=self._xhs_dir)
        return self._xhs

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
            status["xhs_skills"] = self._get_xhs_cdp().is_available()
        except Exception:
            status["xhs_skills"] = False
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
        limit_per_kw: int = 8,
        use_xhs: bool = True,
        use_douyin: bool = True,
        use_instagram: bool = True,
        use_tikhub: bool = True,
        use_mock_fallback: bool = True,
        parallel: bool = True,
    ) -> List[TrendSignal]:
        """
        Collect from all available sources (parallel by default).

        Returns deduplicated List[TrendSignal] sorted by engagement score.
        Falls back to mock data only if all real sources produce nothing.
        """
        kws = keywords or DEFAULT_NAIL_KEYWORDS
        all_signals: List[TrendSignal] = []
        sources_used: List[str] = []

        # Build task list
        tasks: Dict[str, callable] = {}

        if use_xhs:
            cdp = self._get_xhs_cdp()
            if cdp.is_available():
                # Strategy A: seed "美甲" → discover hot sub-keywords → drill down
                # Each keyword also supports scroll-based 100-item fetch
                def _xhs_task(cdp=cdp, kws=kws, lim=limit_per_kw):
                    # Always run Strategy A from the seed keyword
                    results = cdp.discover_and_search(
                        seed_keyword="美甲",
                        target_total=min(150, lim * 15),
                        top_n_sub_keywords=5,
                        per_sub_keyword=min(80, lim * 8),
                    )
                    # Also run Strategy B keywords (scene/intent terms) if given
                    b_kws = [k for k in kws if k != "美甲"][:4]
                    if b_kws:
                        b_results = cdp.search_many(b_kws, target_per_kw=min(80, lim * 8))
                        seen = {s.trend_id for s in results}
                        for s in b_results:
                            if s.trend_id not in seen:
                                results.append(s)
                                seen.add(s.trend_id)
                    return results
                tasks["xhs"] = _xhs_task
            else:
                # Fallback: XHS Skills CLI (44 per keyword, no scroll)
                xhs = self._get_xhs()
                if xhs.is_available():
                    logger.info("XHS CDP: not available, falling back to XHS Skills CLI")
                    def _xhs_cli_task(xhs=xhs, kws=kws, lim=limit_per_kw):
                        return xhs.search(kws[:5], limit_per_kw=lim)
                    tasks["xhs"] = _xhs_cli_task
                else:
                    logger.debug("XHS: neither CDP nor Skills available")

        if use_douyin:
            dy = self._get_douyin()
            if dy.is_available():
                tasks["douyin"] = lambda: dy.search(kws[:4], limit_per_kw=limit_per_kw)
            else:
                logger.debug("Douyin CDP: Chrome not running with debug port")

        if use_instagram:
            ig = self._get_instagram()
            if ig.is_available():
                tasks["instagram"] = lambda: ig.fetch_all(_IG_NAIL_TAGS[:4], limit_per_tag=6)
            else:
                logger.debug("Instagram: instaloader not installed")

        if use_tikhub and self._tikhub_key:
            tasks["tikhub"] = lambda: self._get_tikhub().fetch_all(kws, limit_per_kw=limit_per_kw)

        # Execute tasks
        if parallel and len(tasks) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
                futures = {pool.submit(fn): name for name, fn in tasks.items()}
                for fut in as_completed(futures):
                    name = futures[fut]
                    try:
                        results = fut.result(timeout=45)
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

        if sources_used:
            logger.info("Sources: %s → %d total", ", ".join(sources_used), len(all_signals))
        else:
            logger.warning("No data sources available — returning empty")

        return self._dedup_and_sort(all_signals)

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
