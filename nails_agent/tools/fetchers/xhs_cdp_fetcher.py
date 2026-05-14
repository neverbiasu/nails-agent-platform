"""
Xiaohongshu CDP fetcher — direct playwright-based scraper.

Unlike the XHS Skills CLI (which runs one subprocess per keyword and captures
only the initial 44-item page), this fetcher:

  1. Reuses the user's already-logged-in Chrome via CDP
  2. Scrolls the search results page to load up to `target` items
  3. Reads `window.__INITIAL_STATE__.search.feeds` after each scroll batch
  4. Implements Strategy A: seed search → discover hot sub-keywords →
     second-pass searches for those sub-keywords

Requires:
  - Chrome running with --remote-debugging-port=9222
  - Already logged in to xiaohongshu.com in that Chrome
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from nails_agent.models.schemas import TrendSignal

logger = logging.getLogger(__name__)

_TZ8 = timezone(timedelta(hours=8))
_CDP_DEFAULT = "http://localhost:9222"


# XHS search page URL (same as xhs-skills/urls.py)
def _search_url(keyword: str) -> str:
    params = urlencode({"keyword": keyword, "source": "web_explore_feed"})
    return f"https://www.xiaohongshu.com/search_result?{params}"


# JS to read current feeds from __INITIAL_STATE__
_READ_FEEDS_JS = """
(() => {
    try {
        const s = window.__INITIAL_STATE__;
        if (!s || !s.search || !s.search.feeds) return "";
        const feeds = s.search.feeds;
        const data = feeds.value !== undefined ? feeds.value : feeds._value;
        return data ? JSON.stringify(data) : "";
    } catch(e) { return ""; }
})()
"""

# Nail-related classification table for tag extraction from titles
_NAIL_STYLE_WORDS = {
    "猫眼",
    "法式",
    "渐变",
    "奶油",
    "3D",
    "贴片",
    "冰透",
    "暗黑",
    "日式",
    "韩式",
    "极简",
    "波点",
    "格纹",
    "花朵",
    "蝴蝶",
    "爱心",
    "星月",
    "手绘",
    "光疗",
    "玻璃",
    "镭射",
    "极光",
    "牛奶",
    "果冻",
    "奶酪",
    "蕾丝",
    "纯欲",
    "高级感",
    "清冷",
    "气质",
    "显白",
    "闪粉",
    "珠光",
    "金箔",
    "锡箔",
    "拿铁",
    "莫奈",
    "豹纹",
    "大理石",
    "珍珠",
    "水晶",
    "宝石",
    "钻石",
}
_NAIL_COLOR_WORDS = {
    "白色",
    "黑色",
    "粉色",
    "红色",
    "蓝色",
    "紫色",
    "绿色",
    "裸色",
    "香芋",
    "薄荷",
    "莫兰迪",
    "多巴胺",
    "奶茶",
    "杏色",
    "橘色",
    "黄色",
    "咖色",
    "灰色",
    "玫瑰",
    "珊瑚",
}
_NAIL_MATERIAL_WORDS = {"甲油胶", "钻", "贝壳", "磁铁", "亮片", "锡箔", "金箔"}
_NAIL_SCENE_WORDS = {
    "新娘",
    "日常",
    "约会",
    "通勤",
    "夏日",
    "秋冬",
    "圣诞",
    "新年",
    "春天",
    "夏天",
    "职场",
    "约会",
    "婚礼",
    "毕业",
}

# Words that make "美甲" compound search terms worth trying
_DISCOVER_CANDIDATE_WORDS = _NAIL_STYLE_WORDS | _NAIL_COLOR_WORDS | _NAIL_SCENE_WORDS


def _make_trend_id(uid: str) -> str:
    """Stable ID based on post UID only — same post = same ID regardless of search keyword."""
    today = datetime.now(_TZ8).strftime("%Y%m%d")
    short = hashlib.md5(uid.encode()).hexdigest()[:6].upper()
    return f"TREND_{today}_XHS_{short}"


def _safe_int(v: Any) -> int:
    if not v:
        return 0
    try:
        return int(str(v).replace(",", "").replace("万", "0000").strip())
    except (ValueError, TypeError):
        return 0


def _classify_title(title: str) -> Dict[str, List[str]]:
    style, color, material, scene = [], [], [], []
    for w in _NAIL_STYLE_WORDS:
        if w in title and w not in style:
            style.append(w)
    for w in _NAIL_COLOR_WORDS:
        if w in title and w not in color:
            color.append(w)
    for w in _NAIL_MATERIAL_WORDS:
        if w in title and w not in material:
            material.append(w)
    for w in _NAIL_SCENE_WORDS:
        if w in title and w not in scene:
            scene.append(w)
    return {
        "style_tags": style[:5],
        "color_tags": color[:3],
        "material_tags": material[:3],
        "scene_tags": scene[:3],
    }


def _parse_feed_dict(item: Dict, keyword: str) -> Optional[TrendSignal]:
    """Parse one __INITIAL_STATE__ feed dict → TrendSignal."""
    try:
        # XHS search feeds have noteCard nested structure
        note = item.get("noteCard") or item
        uid = item.get("id") or item.get("noteId") or item.get("note_id") or ""
        title = (
            note.get("displayTitle") or note.get("display_title") or item.get("displayTitle") or ""
        )
        desc = note.get("desc") or note.get("description") or ""
        caption = f"{title} {desc}".strip()[:200]

        interact = note.get("interactInfo") or note.get("interact_info") or {}
        likes = _safe_int(interact.get("likedCount") or interact.get("liked_count"))
        collects = _safe_int(interact.get("collectedCount") or interact.get("collected_count"))
        comments = _safe_int(interact.get("commentCount") or interact.get("comment_count"))
        shares = _safe_int(interact.get("sharedCount") or interact.get("shared_count"))

        classified = _classify_title(title + " " + desc)

        # Supplement with #hashtags from caption
        ht_tags = re.findall(r"#([^\s#]+)", caption)
        for ht in ht_tags:
            if ht not in classified["style_tags"] and len(classified["style_tags"]) < 5:
                classified["style_tags"].append(ht)

        # Use uid if available; fallback to hash of title (not keyword-dependent)
        stable_uid = uid if uid else hashlib.md5(title.encode()).hexdigest()[:12]
        return TrendSignal(
            trend_id=_make_trend_id(stable_uid),
            platform="小红书",
            keyword=keyword,
            caption=caption,
            likes=likes,
            comments=comments,
            shares=shares,
            collects=collects,
            publish_time=datetime.now(_TZ8).isoformat(),
            captured_at=datetime.now(_TZ8).isoformat(),
            image_urls=[],
            **classified,
        )
    except Exception as e:
        logger.debug("XHS CDP parse error: %s", e)
        return None


class XHSCDPFetcher:
    """
    Scrapes XHS by reusing the user's logged-in Chrome via CDP.

    Two key capabilities:
    - search(keyword, target=100): scroll-based fetch of up to `target` items
    - discover_and_search(seed, target=150): Strategy A — seed → hot sub-keywords → drill down
    """

    def __init__(self, cdp_url: str = _CDP_DEFAULT, timeout_ms: int = 20_000):
        self.cdp_url = cdp_url
        self.timeout_ms = timeout_ms

    def is_available(self) -> bool:
        try:
            import requests

            return requests.get(f"{self.cdp_url}/json/version", timeout=2).status_code == 200
        except Exception:
            return False

    # ── Core: scroll-based search ─────────────────────────────────────────────

    def search(
        self,
        keyword: str,
        target: int = 100,
        sort_by: str = "综合",
    ) -> List[TrendSignal]:
        """
        Search XHS for `keyword`, scrolling until `target` unique results are collected.

        sort_by: 综合 | 最新 | 最多点赞 | 最多评论 | 最多收藏
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("playwright not installed")
            return []

        if not self.is_available():
            logger.info("XHS CDP: Chrome not reachable at %s", self.cdp_url)
            return []

        with sync_playwright() as pw:
            try:
                browser = pw.chromium.connect_over_cdp(self.cdp_url)
            except Exception as e:
                logger.error("XHS CDP: connect failed — %s", e)
                return []

            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()

            try:
                url = _search_url(keyword)
                logger.info("XHS CDP: searching '%s' (target=%d)…", keyword, target)
                page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")

                # Apply sort filter if not default
                if sort_by and sort_by != "综合":
                    self._apply_sort(page, sort_by)

                # Scroll-and-collect loop
                seen_ids: set = set()
                signals: List[TrendSignal] = []
                stale_rounds = 0

                while len(signals) < target and stale_rounds < 3:
                    # Read current state
                    raw = page.evaluate(_READ_FEEDS_JS)
                    if raw:
                        try:
                            feeds = json.loads(raw)
                            before = len(signals)
                            for item in feeds:
                                uid = item.get("id") or ""
                                if uid and uid in seen_ids:
                                    continue
                                sig = _parse_feed_dict(item, keyword)
                                if sig:
                                    seen_ids.add(uid)
                                    signals.append(sig)
                            if len(signals) == before:
                                stale_rounds += 1
                            else:
                                stale_rounds = 0
                        except json.JSONDecodeError:
                            stale_rounds += 1
                    else:
                        stale_rounds += 1

                    if len(signals) >= target:
                        break

                    # Scroll down to load next batch
                    prev_height = page.evaluate("document.body.scrollHeight")
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)

                    # Wait for new content (height change or new feeds)
                    new_height = page.evaluate("document.body.scrollHeight")
                    if new_height == prev_height:
                        # Try scrolling a bit less (sometimes bottom has a footer)
                        page.evaluate("window.scrollBy(0, -200)")
                        page.wait_for_timeout(800)

                logger.info("XHS CDP: '%s' → %d signals (target=%d)", keyword, len(signals), target)
                return signals[:target]

            except Exception as e:
                logger.warning("XHS CDP: search '%s' error — %s", keyword, e)
                return []
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

    def _apply_sort(self, page, sort_by: str) -> None:
        """Click the sort filter on the XHS search page."""
        try:
            # Hover filter button to open panel
            filter_btn = page.query_selector("div.filter-button, .filter-btn, [class*='filterBtn']")
            if filter_btn:
                filter_btn.hover()
                page.wait_for_timeout(600)

            # Click the right sort option
            sort_map = {
                "最新": 2,
                "最多点赞": 3,
                "最多评论": 4,
                "最多收藏": 5,
            }
            idx = sort_map.get(sort_by, 1)
            page.wait_for_timeout(300)
            # Try the CSS selector pattern from xhs-skills
            sel = f"div.filter-panel div.filters:nth-child(1) div.tags:nth-child({idx})"
            el = page.query_selector(sel)
            if el:
                el.click()
                page.wait_for_timeout(1000)
        except Exception as e:
            logger.debug("XHS CDP: sort filter failed (%s), continuing with default", e)

    # ── Strategy A: seed → discover → drill down ─────────────────────────────

    def discover_and_search(
        self,
        seed_keyword: str = "美甲",
        target_total: int = 150,
        top_n_sub_keywords: int = 5,
        per_sub_keyword: int = 50,
    ) -> List[TrendSignal]:
        """
        Strategy A — two-pass discovery:

        Pass 1: Search `seed_keyword` (broad, e.g. "美甲") and collect up to
                `target_total // 3` items. Extract high-frequency style/scene
                compound words from titles.

        Pass 2: For the top N discovered sub-keywords, search each one and
                collect up to `per_sub_keyword` items each.

        Returns all unique signals sorted by engagement.
        """
        all_signals: List[TrendSignal] = []
        seen_ids: set = set()

        def _add(sigs: List[TrendSignal]) -> None:
            for s in sigs:
                if s.trend_id not in seen_ids:
                    seen_ids.add(s.trend_id)
                    all_signals.append(s)

        # ── Pass 1: broad seed search ─────────────────────────────────────
        seed_limit = max(44, target_total // 3)
        logger.info("XHS CDP Strategy A — Pass 1: seed='%s' (target=%d)", seed_keyword, seed_limit)
        seed_signals = self.search(seed_keyword, target=seed_limit)
        _add(seed_signals)

        # ── Discover sub-keywords from Pass 1 titles ──────────────────────
        sub_kws = self._discover_sub_keywords(seed_signals, top_n=top_n_sub_keywords)
        logger.info("XHS CDP Strategy A — discovered sub-keywords: %s", sub_kws)

        # ── Pass 2: drill into each sub-keyword ───────────────────────────
        for kw in sub_kws:
            if len(all_signals) >= target_total:
                break
            logger.info("XHS CDP Strategy A — Pass 2: sub-keyword='%s'", kw)
            sigs = self.search(kw, target=per_sub_keyword)
            _add(sigs)

        # Sort by engagement
        all_signals.sort(
            key=lambda s: s.likes + s.collects * 1.5 + s.shares * 2 + s.comments * 0.5,
            reverse=True,
        )
        logger.info("XHS CDP Strategy A — total unique signals: %d", len(all_signals))
        return all_signals[:target_total]

    def _discover_sub_keywords(
        self,
        signals: List[TrendSignal],
        top_n: int = 5,
    ) -> List[str]:
        """
        Extract high-frequency compound nail keywords from signal captions.

        E.g. if "猫眼" appears 15 times → candidate "猫眼美甲"
        If "法式" appears 8 times → candidate "法式美甲"
        """
        word_counts: Counter = Counter()

        for sig in signals:
            text = sig.caption
            for w in _DISCOVER_CANDIDATE_WORDS:
                if w in text:
                    word_counts[w] += 1

        # Build compound search terms: <word> + 美甲 (if word alone wouldn't be searched)
        sub_kws = []
        for word, count in word_counts.most_common(top_n * 2):
            if count < 2:
                break
            # Form the compound keyword
            kw = word if "美甲" in word else f"{word}美甲"
            if kw not in sub_kws:
                sub_kws.append(kw)
            if len(sub_kws) >= top_n:
                break

        return sub_kws

    # ── Multi-keyword batch ───────────────────────────────────────────────────

    def search_many(
        self,
        keywords: List[str],
        target_per_kw: int = 80,
    ) -> List[TrendSignal]:
        """Search multiple keywords (Strategy B: explicit intent/scene keywords)."""
        all_signals: List[TrendSignal] = []
        seen: set = set()
        for kw in keywords:
            for sig in self.search(kw, target=target_per_kw):
                if sig.trend_id not in seen:
                    seen.add(sig.trend_id)
                    all_signals.append(sig)
        all_signals.sort(
            key=lambda s: s.likes + s.collects * 1.5 + s.shares * 2 + s.comments * 0.5,
            reverse=True,
        )
        return all_signals
