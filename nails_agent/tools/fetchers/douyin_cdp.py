"""
Douyin CDP fetcher — finds an existing logged-in Douyin tab in Chrome
and navigates it to the search page.

Unlike opening a new CDP page (which triggers captcha), reusing a real
browser tab that's already past authentication works reliably.

Setup (one-time):
  1. Launch Chrome with debug port:
       macOS: open -a "Google Chrome" --args --remote-debugging-port=9222
  2. Manually open douyin.com in that Chrome and log in
  3. Leave the tab open — our fetcher reuses it
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from nails_agent.models.schemas import TrendSignal
from nails_agent.tools.fetchers.tikhub_fetcher import (
    _classify_tags,
    _is_nail_related,
    _make_trend_id,
    _ts_to_iso,
)

logger = logging.getLogger(__name__)

_TZ8 = timezone(timedelta(hours=8))
_CDP_URL_DEFAULT = "http://localhost:9222"

_SEARCH_URL = "https://www.douyin.com/search/{kw}?type=video"

_API_PATTERNS = [
    "/aweme/v1/web/search/",
    "multiplatform/v1/search",
    "/api/search/",
    "aweme/v1/search",
]


def _parse_aweme(item: Dict[str, Any], keyword: str) -> Optional[TrendSignal]:
    if not isinstance(item, dict):
        return None
    info = item.get("aweme_info") or item
    if not isinstance(info, dict):
        return None
    stats = info.get("statistics") or {}
    caption = info.get("desc", "")
    raw_tags = [
        t.get("hashtag_name", "")
        for t in info.get("text_extra", [])
        if isinstance(t, dict) and t.get("type") == 1
    ]
    classified = _classify_tags([t for t in raw_tags if t], caption)
    aweme_id = info.get("aweme_id", "") or caption[:20]
    return TrendSignal(
        trend_id=_make_trend_id("抖音", aweme_id),
        platform="抖音",
        keyword=keyword,
        caption=caption[:200],
        likes=stats.get("digg_count", 0),
        comments=stats.get("comment_count", 0),
        shares=stats.get("share_count", 0),
        collects=stats.get("collect_count", 0),
        publish_time=_ts_to_iso(info.get("create_time", 0)),
        captured_at=datetime.now(_TZ8).isoformat(),
        **classified,
        image_urls=[],
    )


def _extract_items(body: Any) -> List[Dict]:
    """Recursively find aweme_list / item_list in arbitrary JSON."""
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return []
    for key in ("aweme_list", "item_list", "result"):
        val = body.get(key)
        if isinstance(val, list) and val:
            return val
    # recurse one level into 'data'
    data = body.get("data")
    if data:
        return _extract_items(data)
    return []


class DouyinCDPFetcher:
    """
    Scrapes Douyin by reusing an existing logged-in Douyin tab in the user's Chrome.
    Falls back gracefully if no Douyin tab is open.
    """

    def __init__(self, cdp_url: str = _CDP_URL_DEFAULT, timeout_ms: int = 20_000):
        self.cdp_url = cdp_url
        self.timeout_ms = timeout_ms

    def is_available(self) -> bool:
        """True if Chrome is reachable (Douyin tab is checked lazily during search)."""
        try:
            import requests

            return requests.get(f"{self.cdp_url}/json/version", timeout=2).status_code == 200
        except Exception:
            return False

    def _find_douyin_page(self, browser):
        """Find an existing open Douyin page in browser contexts."""
        for ctx in browser.contexts:
            for page in ctx.pages:
                if "douyin.com" in page.url:
                    return page
        return None

    def search(
        self,
        keywords: List[str],
        limit_per_kw: int = 25,
        max_scrolls: int = 3,
    ) -> List[TrendSignal]:
        """
        Search Douyin by reusing the user's logged-in tab.

        Scrolls the search result page up to `max_scrolls` times to gather
        more XHR batches, stopping early once `limit_per_kw` signals are in.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("playwright not installed")
            return []

        if not self.is_available():
            logger.info("Douyin CDP: Chrome not reachable at %s", self.cdp_url)
            return []

        all_signals: List[TrendSignal] = []

        with sync_playwright() as pw:
            try:
                browser = pw.chromium.connect_over_cdp(self.cdp_url)
            except Exception as e:
                logger.error("Douyin CDP: connect failed — %s", e)
                return []

            douyin_page = self._find_douyin_page(browser)
            if not douyin_page:
                logger.info(
                    "Douyin CDP: no Douyin tab found in Chrome.\n"
                    "  → Please open https://www.douyin.com in your Chrome browser and log in, "
                    "then re-run the pipeline."
                )
                try:
                    browser.close()
                except Exception:
                    pass
                return []

            logger.info("Douyin CDP: found Douyin tab at %s", douyin_page.url[:60])

            for kw in keywords:
                captured_bodies: List[tuple] = []
                seen_ids: set = set()

                def _on_response(resp):
                    if any(p in resp.url for p in _API_PATTERNS) and resp.status == 200:
                        try:
                            captured_bodies.append((resp.url, resp.json()))
                        except Exception:
                            pass

                douyin_page.on("response", _on_response)

                signals: List[TrendSignal] = []
                processed_idx = 0  # how many captured_bodies entries we've already drained

                try:
                    search_url = _SEARCH_URL.format(kw=urllib.parse.quote(kw))
                    logger.info("Douyin CDP: searching '%s' (target %d)", kw, limit_per_kw)
                    douyin_page.goto(
                        search_url, timeout=self.timeout_ms, wait_until="domcontentloaded"
                    )

                    # Initial XHR wait
                    deadline = time.time() + 10
                    while not captured_bodies and time.time() < deadline:
                        douyin_page.wait_for_timeout(500)

                    def _drain():
                        """Parse anything new in captured_bodies into signals."""
                        nonlocal processed_idx
                        for _url, body in captured_bodies[processed_idx:]:
                            for item in _extract_items(body):
                                try:
                                    sig = _parse_aweme(item, kw)
                                except Exception as e:
                                    logger.debug("Douyin parse: %s", e)
                                    continue
                                if not sig:
                                    continue
                                if sig.trend_id in seen_ids:
                                    continue
                                if not (_is_nail_related(sig.caption) or _is_nail_related(kw)):
                                    continue
                                seen_ids.add(sig.trend_id)
                                signals.append(sig)
                        processed_idx = len(captured_bodies)

                    _drain()

                    # Scroll-and-drain until target hit or max_scrolls exhausted
                    scrolls = 0
                    while len(signals) < limit_per_kw and scrolls < max_scrolls:
                        before = len(captured_bodies)
                        douyin_page.evaluate("window.scrollBy(0, window.innerHeight * 1.8)")
                        # Wait for new XHR
                        deadline = time.time() + 5
                        while len(captured_bodies) == before and time.time() < deadline:
                            douyin_page.wait_for_timeout(400)
                        douyin_page.wait_for_timeout(800)  # settle
                        _drain()
                        scrolls += 1
                        logger.debug(
                            "Douyin CDP: '%s' scroll %d → %d signals", kw, scrolls, len(signals)
                        )

                    logger.info(
                        "Douyin CDP: '%s' → %d signals (%d scrolls)", kw, len(signals), scrolls
                    )
                    all_signals.extend(signals[:limit_per_kw])

                except Exception as e:
                    logger.warning("Douyin CDP: '%s' error — %s", kw, e)
                finally:
                    douyin_page.remove_listener("response", _on_response)

            try:
                browser.close()
            except Exception:
                pass

        return all_signals
