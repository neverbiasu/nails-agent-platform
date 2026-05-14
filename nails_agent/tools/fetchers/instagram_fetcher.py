"""
Instagram fetcher — two modes, both free:

Mode A (primary): playwright CDP — reuses the user's logged-in Chrome.
  Scrapes https://www.instagram.com/explore/tags/<hashtag>/
  Works when Chrome has Instagram logged in (same pattern as XHS + Douyin fetchers).

Mode B (fallback): instaloader — public hashtag scraping without login.
  pip install instaloader
  Instagram has tightened this; now requires login for top_posts.
  Only works if you provide a session file (see INSTAGRAM_SESSION_FILE).

Priority: CDP → instaloader → empty
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from nails_agent.models.schemas import TrendSignal

logger = logging.getLogger(__name__)

_TZ8 = timezone(timedelta(hours=8))

_NAIL_HASHTAGS_EN = [
    "nailart",
    "cateyenails",
    "frenchnails",
    "3dnailart",
    "gradientnails",
    "gelnails",
    "naildesign",
    "acrylicnails",
]

_HASHTAG_TO_KW = {
    "nailart": "nail art",
    "cateyenails": "猫眼美甲",
    "frenchnails": "法式美甲",
    "3dnailart": "3D美甲",
    "gradientnails": "渐变美甲",
    "gelnails": "甲油胶",
    "naildesign": "nail design",
    "acrylicnails": "贴片美甲",
}

_IG_TAG_URL = "https://www.instagram.com/explore/tags/{tag}/"
_IG_API_URL = "https://www.instagram.com/api/v1/tags/{tag}/sections/"


def _make_ig_id(shortcode: str) -> str:
    today = datetime.now(_TZ8).strftime("%Y%m%d")
    short = hashlib.md5(shortcode.encode()).hexdigest()[:6].upper()
    return f"TREND_{today}_IG_{short}"


def _parse_ig_edge(node: Dict[str, Any], keyword: str) -> Optional[TrendSignal]:
    """Parse one Instagram GraphQL node → TrendSignal."""
    try:
        now_iso = datetime.now(_TZ8).isoformat()
        shortcode = node.get("shortcode") or node.get("code") or ""
        caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
        caption = (
            caption_edges[0]["node"]["text"]
            if caption_edges
            else node.get("accessibility_caption", "")
        )
        hashtags = re.findall(r"#(\w+)", caption)

        # Real publish time — IG ships it as a unix-seconds int under several keys
        ts = (
            node.get("taken_at_timestamp")
            or node.get("taken_at")
            or node.get("device_timestamp")
            or 0
        )
        try:
            ts_int = int(ts)
            publish_iso = (
                datetime.fromtimestamp(ts_int, tz=timezone.utc).astimezone(_TZ8).isoformat()
                if ts_int > 0
                else ""
            )
        except (ValueError, TypeError, OSError):
            publish_iso = ""

        return TrendSignal(
            trend_id=_make_ig_id(shortcode or caption[:20]),
            platform="Instagram",
            keyword=keyword,
            caption=caption[:200],
            likes=node.get("edge_liked_by", {}).get("count", 0) or node.get("like_count", 0),
            comments=node.get("edge_media_to_comment", {}).get("count", 0)
            or node.get("comment_count", 0),
            shares=0,
            collects=0,
            publish_time=publish_iso,
            captured_at=now_iso,
            style_tags=hashtags[:5],
            color_tags=[],
            material_tags=[],
            scene_tags=[],
        )
    except Exception:
        return None


class InstagramFetcher:
    """
    Instagram scraper with two free modes.
    Tries CDP (logged-in Chrome) first, then instaloader with session file.
    """

    def __init__(
        self,
        cdp_url: str = "http://localhost:9222",
        session_file: Optional[str] = None,
        timeout_ms: int = 20_000,
    ):
        self.cdp_url = cdp_url
        self.session_file = session_file or os.environ.get("INSTAGRAM_SESSION_FILE", "")
        self.timeout_ms = timeout_ms

    def is_available(self) -> bool:
        """Available if Chrome with IG is reachable OR instaloader session exists."""
        return self._cdp_available() or self._instaloader_available()

    def _cdp_available(self) -> bool:
        try:
            import requests

            r = requests.get(f"{self.cdp_url}/json/version", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def _instaloader_available(self) -> bool:
        if not self.session_file or not os.path.exists(self.session_file):
            return False
        try:
            import instaloader  # noqa: F401

            return True
        except ImportError:
            return False

    # ── Mode A: playwright CDP ────────────────────────────────────────────────

    def _fetch_cdp(
        self,
        hashtags: List[str],
        limit_per_tag: int,
        max_scrolls: int = 3,
    ) -> List[TrendSignal]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return []

        if not self._cdp_available():
            return []

        all_signals: List[TrendSignal] = []

        with sync_playwright() as pw:
            try:
                browser = pw.chromium.connect_over_cdp(self.cdp_url)
            except Exception as e:
                logger.error("Instagram CDP: connect failed — %s", e)
                return []

            ctx = browser.contexts[0] if browser.contexts else browser.new_context()

            for tag in hashtags:
                captured_data: List[Dict] = []

                def _on_response(resp):
                    url = resp.url
                    if (
                        "graphql" in url or "api/v1/tags" in url or "sections" in url
                    ) and resp.status == 200:
                        try:
                            captured_data.append(resp.json())
                        except Exception:
                            pass

                page = ctx.new_page()
                page.on("response", _on_response)

                try:
                    url = _IG_TAG_URL.format(tag=tag)
                    logger.info("Instagram CDP: → #%s (target %d)", tag, limit_per_tag)
                    page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")

                    # Initial XHR wait
                    deadline = time.time() + 10
                    while not captured_data and time.time() < deadline:
                        page.wait_for_timeout(600)

                    # Fallback: embedded __initialData__ script
                    if not captured_data:
                        try:
                            raw = page.evaluate("""
                                (() => {
                                    const script = document.querySelector('script[type="application/json"]');
                                    return script ? script.textContent : null;
                                })()
                            """)
                            if raw:
                                captured_data.append(json.loads(raw))
                        except Exception:
                            pass

                    keyword = _HASHTAG_TO_KW.get(tag, tag)
                    signals = self._parse_ig_data(captured_data, keyword, limit_per_tag)

                    # Scroll-and-collect until target hit or max_scrolls exhausted
                    scrolls = 0
                    while len(signals) < limit_per_tag and scrolls < max_scrolls:
                        before = len(captured_data)
                        page.evaluate("window.scrollBy(0, window.innerHeight * 1.8)")
                        deadline = time.time() + 5
                        while len(captured_data) == before and time.time() < deadline:
                            page.wait_for_timeout(500)
                        page.wait_for_timeout(800)
                        signals = self._parse_ig_data(captured_data, keyword, limit_per_tag)
                        scrolls += 1
                        logger.debug(
                            "Instagram CDP: #%s scroll %d → %d signals", tag, scrolls, len(signals)
                        )

                    logger.info(
                        "Instagram CDP: #%s → %d signals (%d scrolls)", tag, len(signals), scrolls
                    )
                    all_signals.extend(signals[:limit_per_tag])

                except Exception as e:
                    logger.warning("Instagram CDP: #%s error — %s", tag, e)
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass

            try:
                browser.close()
            except Exception:
                pass

        return all_signals

    def _parse_ig_data(self, captured: List[Dict], keyword: str, limit: int) -> List[TrendSignal]:
        seen_ids: set = set()
        signals = []
        for body in captured:
            edges = (
                body.get("data", {})
                .get("hashtag", {})
                .get("edge_hashtag_to_top_posts", {})
                .get("edges")
                or body.get("data", {}).get("recent", {}).get("sections")
                or body.get("sections")
                or []
            )
            nodes = []
            for e in edges:
                node = e.get("node") or e.get("layout_content", {}).get("medias", [{}])[0].get(
                    "media"
                )
                if node:
                    nodes.append(node)

            for node in nodes:
                sig = _parse_ig_edge(node, keyword)
                if sig and sig.trend_id not in seen_ids:
                    seen_ids.add(sig.trend_id)
                    signals.append(sig)
                    if len(signals) >= limit:
                        return signals
        return signals

    # ── Mode B: instaloader (session required) ───────────────────────────────

    def _fetch_instaloader(self, hashtags: List[str], limit_per_tag: int) -> List[TrendSignal]:
        if not self._instaloader_available():
            return []
        import instaloader
        import time as _time

        L = instaloader.Instaloader(
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            quiet=True,
        )
        try:
            username = os.path.basename(self.session_file).replace(".session", "")
            L.load_session_from_file(username, self.session_file)
        except Exception as e:
            logger.warning("Instagram instaloader session error: %s", e)
            return []

        all_signals: List[TrendSignal] = []
        now_iso = datetime.now(_TZ8).isoformat()

        for i, tag in enumerate(hashtags):
            try:
                ht = instaloader.Hashtag.from_name(L.context, tag)
                keyword = _HASHTAG_TO_KW.get(tag, tag)
                for j, post in enumerate(ht.get_posts()):
                    if j >= limit_per_tag:
                        break
                    caption = post.caption or ""
                    all_signals.append(
                        TrendSignal(
                            trend_id=_make_ig_id(post.shortcode),
                            platform="Instagram",
                            keyword=keyword,
                            caption=caption[:200],
                            likes=post.likes,
                            comments=post.comments,
                            shares=0,
                            collects=0,
                            publish_time=post.date_utc.astimezone(_TZ8).isoformat(),
                            captured_at=now_iso,
                            style_tags=list(post.caption_hashtags)[:5],
                            color_tags=[],
                            material_tags=[],
                            scene_tags=[],
                        )
                    )
                logger.info("Instagram instaloader: #%s → %d signals", tag, j + 1)
                if i < len(hashtags) - 1:
                    _time.sleep(2.0)
            except Exception as e:
                logger.warning("Instagram instaloader #%s: %s", tag, e)

        return all_signals

    # ── Public API ────────────────────────────────────────────────────────────

    def fetch_all(
        self,
        hashtags: Optional[List[str]] = None,
        limit_per_tag: int = 8,
    ) -> List[TrendSignal]:
        tags = hashtags or _NAIL_HASHTAGS_EN[:5]

        # Try CDP first (faster, works with logged-in Chrome)
        if self._cdp_available():
            results = self._fetch_cdp(tags, limit_per_tag)
            if results:
                return results

        # Fallback: instaloader with session
        if self._instaloader_available():
            return self._fetch_instaloader(tags, limit_per_tag)

        logger.info("Instagram: neither CDP nor instaloader session available")
        return []
