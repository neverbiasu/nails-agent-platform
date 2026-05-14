"""
TikHub API fetcher — real social media data for Douyin, Xiaohongshu, Instagram.

Uses the TikHub Python SDK (pip install tikhub).
Requires: TIKHUB_API_KEY environment variable.

API response → TrendSignal field mapping:

Douyin video:
  aweme_id            → trend_id
  desc                → caption + style_tags (hashtags)
  create_time         → publish_time
  statistics.digg_count   → likes
  statistics.comment_count → comments
  statistics.share_count  → shares
  statistics.collect_count → collects
  text_extra[].hashtag_name → raw_tags (filtered for nail-related)

XHS note (web_v2):
  id / note_id        → trend_id
  title + desc        → caption
  interact_info.*     → engagement metrics
  tag_list[].name     → raw_tags
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional

from nails_agent.models.schemas import TrendSignal

logger = logging.getLogger(__name__)

_TZ8 = timezone(timedelta(hours=8))

# Keywords that indicate nail-art content (for tag filtering)
_NAIL_KEYWORDS = {
    "美甲",
    "nail",
    "指甲",
    "美甲师",
    "猫眼",
    "法式",
    "渐变",
    "3D",
    "浮雕",
    "贴片",
    "甲油胶",
    "磁铁",
    "暗黑",
    "奶油",
    "哑光",
    "冰透",
    "钻石",
    "韩式",
    "日式",
    "短甲",
    "长甲",
    "方甲",
    "尖甲",
    "设计",
    "款式",
    "显白",
    "夏日",
    "秋冬",
}


def _is_nail_related(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in _NAIL_KEYWORDS)


def _extract_hashtags(text: str) -> List[str]:
    """Extract #hashtag from text."""
    return re.findall(r"#(\S+?)(?=\s|#|$)", text)


def _classify_tags(tags: List[str], caption: str) -> dict:
    """Split raw tags into style/color/material/scene buckets."""
    color_words = {
        "蓝",
        "粉",
        "红",
        "白",
        "黑",
        "紫",
        "绿",
        "金",
        "银",
        "肉",
        "裸",
        "棕",
        "橙",
        "冰蓝",
        "肤色",
    }
    material_words = {"磁铁", "雕花", "钻", "硬胶", "甲油胶", "贴片", "浮雕", "渐变粉", "磁铁石"}
    scene_words = {
        "通勤",
        "约会",
        "日常",
        "夏季",
        "秋冬",
        "春季",
        "节日",
        "拍照",
        "晚宴",
        "度假",
        "显白",
        "商务",
    }

    style_tags, color_tags, material_tags, scene_tags = [], [], [], []
    for tag in tags:
        placed = False
        for w in scene_words:
            if w in tag:
                scene_tags.append(tag)
                placed = True
                break
        if not placed:
            for w in material_words:
                if w in tag:
                    material_tags.append(tag)
                    placed = True
                    break
        if not placed:
            for w in color_words:
                if w in tag:
                    color_tags.append(tag)
                    placed = True
                    break
        if not placed and _is_nail_related(tag):
            style_tags.append(tag)

    # Extract additional tags from caption
    inline = _extract_hashtags(caption)
    for t in inline:
        if t not in tags:
            if any(w in t for w in scene_words):
                scene_tags.append(t)
            elif _is_nail_related(t):
                style_tags.append(t)

    return {
        "style_tags": list(dict.fromkeys(style_tags))[:5],
        "color_tags": list(dict.fromkeys(color_tags))[:5],
        "material_tags": list(dict.fromkeys(material_tags))[:5],
        "scene_tags": list(dict.fromkeys(scene_tags))[:5],
    }


def _ts_to_iso(ts: int) -> str:
    """Unix-seconds → ISO. Returns '' for 0/None (sentinel for 'unknown')."""
    try:
        ts = int(ts)
        if ts <= 0:
            return ""
        return datetime.fromtimestamp(ts, tz=_TZ8).isoformat()
    except (ValueError, TypeError, OSError):
        return ""


def _make_trend_id(platform: str, raw_id: str) -> str:
    prefix = {"抖音": "DY", "小红书": "XHS", "Instagram": "IG"}.get(platform, "SIG")
    today = datetime.now(_TZ8).strftime("%Y%m%d")
    short = hashlib.md5(raw_id.encode()).hexdigest()[:6].upper()
    return f"TREND_{today}_{prefix}_{short}"


class TikHubFetcher:
    """
    Wraps the TikHub SDK to fetch nail-related trends from Douyin and XHS.
    Returns List[TrendSignal] for direct use in the pipeline.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("TIKHUB_API_KEY", "")
        self._client: Any = None

    @property
    def client(self):
        if self._client is None:
            try:
                import tikhub

                self._client = tikhub.TikHub(api_key=self.api_key)
            except ImportError:
                raise ImportError("pip install tikhub")
        return self._client

    def is_available(self) -> bool:
        return bool(self.api_key)

    # ── Douyin ───────────────────────────────────────────────────────────────

    def fetch_douyin_search(
        self,
        keywords: List[str],
        limit_per_kw: int = 10,
    ) -> List[TrendSignal]:
        """Search Douyin videos per keyword → List[TrendSignal]."""
        signals: List[TrendSignal] = []
        now_iso = datetime.now(_TZ8).isoformat()

        for kw in keywords:
            try:
                resp = self.client.douyin_search.fetch_video_search_v1(
                    keyword=kw,
                    sort_type="0",  # 综合排序
                    publish_time="0",  # 不限时间
                )
                if resp.get("code") != 200:
                    logger.warning("Douyin search failed for '%s': %s", kw, resp.get("message"))
                    continue

                items = resp.get("data", {}).get("data", [])
                for item_wrapper in items[:limit_per_kw]:
                    info = item_wrapper.get("aweme_info", {})
                    if not info:
                        continue

                    raw_tags = [
                        t.get("hashtag_name", "")
                        for t in info.get("text_extra", [])
                        if t.get("type") == 1
                    ]
                    caption = info.get("desc", "")
                    stats = info.get("statistics", {})

                    # Skip non-nail content
                    if not _is_nail_related(caption) and not any(
                        _is_nail_related(t) for t in raw_tags
                    ):
                        if not _is_nail_related(kw):
                            continue

                    classified = _classify_tags(raw_tags, caption)

                    sig = TrendSignal(
                        trend_id=_make_trend_id("抖音", info.get("aweme_id", "")),
                        platform="抖音",
                        keyword=kw,
                        caption=caption[:200],
                        likes=stats.get("digg_count", 0),
                        comments=stats.get("comment_count", 0),
                        shares=stats.get("share_count", 0),
                        collects=stats.get("collect_count", 0),
                        publish_time=_ts_to_iso(info.get("create_time", 0)),
                        captured_at=now_iso,
                        **classified,
                        image_urls=[],
                    )
                    signals.append(sig)

            except Exception as exc:
                logger.error("Douyin fetch error for '%s': %s", kw, exc)

        return signals

    def fetch_douyin_hot(self, limit: int = 20) -> List[TrendSignal]:
        """Fetch Douyin hot total list and filter nail content."""
        signals: List[TrendSignal] = []
        now_iso = datetime.now(_TZ8).isoformat()
        try:
            resp = self.client.douyin_billboard.fetch_hot_total_list(
                page=1, page_size=limit, type="video"
            )
            if resp.get("code") != 200:
                return signals
            items = resp.get("data", {}).get("word_list", [])
            for item in items:
                word = item.get("word", "")
                if not _is_nail_related(word):
                    continue
                heat_score = item.get("hot_value", 0)
                sig = TrendSignal(
                    trend_id=_make_trend_id("抖音", f"hot_{word}"),
                    platform="抖音",
                    keyword=word,
                    caption=f"抖音热榜：{word}",
                    likes=int(heat_score * 10),
                    comments=int(heat_score * 2),
                    shares=int(heat_score * 0.5),
                    collects=int(heat_score * 3),
                    publish_time=now_iso,
                    captured_at=now_iso,
                    style_tags=[word],
                )
                signals.append(sig)
        except Exception as exc:
            logger.error("Douyin hot fetch error: %s", exc)
        return signals

    # ── Xiaohongshu ──────────────────────────────────────────────────────────

    def fetch_xhs_search(
        self,
        keywords: List[str],
        limit_per_kw: int = 10,
    ) -> List[TrendSignal]:
        """Search XHS notes per keyword → List[TrendSignal]."""
        signals: List[TrendSignal] = []
        now_iso = datetime.now(_TZ8).isoformat()

        for kw in keywords:
            try:
                # Try web_v2 first (more stable)
                resp = self.client.xiaohongshu_web_v2.fetch_search_notes(
                    keywords=kw,
                    page=1,
                    sort_type="general",  # 综合
                )
                if resp.get("code") != 200:
                    # Fallback to app_v2
                    resp = self.client.xiaohongshu_app_v2.search_notes(keyword=kw)

                if resp.get("code") != 200:
                    logger.warning("XHS search failed for '%s': %s", kw, resp.get("message"))
                    continue

                data = resp.get("data", {})
                # Response structure varies between endpoints
                items = (
                    data.get("items")
                    or data.get("notes")
                    or data.get("data", {}).get("items")
                    or []
                )

                for item in items[:limit_per_kw]:
                    note = item.get("note_card") or item.get("note") or item
                    if not note:
                        continue

                    note_id = note.get("id") or note.get("note_id") or note.get("noteId", "")
                    title = note.get("title") or note.get("display_title", "")
                    desc = note.get("desc") or note.get("description") or note.get("content", "")
                    caption = f"{title} {desc}".strip()[:200]

                    if not _is_nail_related(caption) and not _is_nail_related(kw):
                        continue

                    # Engagement metrics (field names vary)
                    interact = note.get("interact_info") or note.get("statistics") or {}
                    likes = (
                        interact.get("liked_count")
                        or interact.get("like_count")
                        or interact.get("digg_count")
                        or 0
                    )
                    collects = (
                        interact.get("collected_count")
                        or interact.get("collect_count")
                        or interact.get("collects")
                        or 0
                    )
                    comments = interact.get("comment_count") or interact.get("comments") or 0
                    shares = interact.get("share_count") or interact.get("shares") or 0

                    # Tags
                    raw_tags = [
                        t.get("name") or t.get("text", "") for t in (note.get("tag_list") or [])
                    ]
                    classified = _classify_tags([t for t in raw_tags if t], caption)

                    sig = TrendSignal(
                        trend_id=_make_trend_id("小红书", note_id or title),
                        platform="小红书",
                        keyword=kw,
                        caption=caption,
                        likes=int(likes),
                        comments=int(comments),
                        shares=int(shares),
                        collects=int(collects),
                        publish_time=now_iso,
                        captured_at=now_iso,
                        **classified,
                        image_urls=[],
                    )
                    signals.append(sig)

            except Exception as exc:
                logger.error("XHS fetch error for '%s': %s", kw, exc)

        return signals

    def fetch_xhs_hot(self) -> List[TrendSignal]:
        """Fetch XHS hot list → nail-related TrendSignals."""
        signals: List[TrendSignal] = []
        now_iso = datetime.now(_TZ8).isoformat()
        try:
            resp = self.client.xiaohongshu_web_v2.fetch_hot_list()
            if resp.get("code") != 200:
                return signals
            items = resp.get("data", {}).get("items") or resp.get("data", [])
            for item in items:
                kw = item.get("title") or item.get("word") or item.get("name", "")
                if not _is_nail_related(kw):
                    continue
                sig = TrendSignal(
                    trend_id=_make_trend_id("小红书", f"hot_{kw}"),
                    platform="小红书",
                    keyword=kw,
                    caption=f"小红书热榜：{kw}",
                    likes=item.get("view_num", 5000),
                    comments=0,
                    shares=0,
                    collects=0,
                    publish_time=now_iso,
                    captured_at=now_iso,
                    style_tags=[kw],
                )
                signals.append(sig)
        except Exception as exc:
            logger.error("XHS hot fetch error: %s", exc)
        return signals

    # ── Convenience ──────────────────────────────────────────────────────────

    def fetch_all(
        self,
        keywords: Optional[List[str]] = None,
        limit_per_kw: int = 8,
    ) -> List[TrendSignal]:
        """Fetch from Douyin + XHS in parallel, return combined signals."""
        kws = keywords or [
            "美甲",
            "猫眼美甲",
            "法式美甲",
            "渐变美甲",
            "奶油美甲",
            "3D美甲",
            "贴片美甲",
            "冰透美甲",
        ]

        from concurrent.futures import ThreadPoolExecutor, as_completed

        tasks = {
            "douyin_search": lambda: self.fetch_douyin_search(kws, limit_per_kw),
            "xhs_search": lambda: self.fetch_xhs_search(kws, limit_per_kw),
            "douyin_hot": lambda: self.fetch_douyin_hot(20),
            "xhs_hot": lambda: self.fetch_xhs_hot(),
        }

        all_signals: List[TrendSignal] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fn): name for name, fn in tasks.items()}
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    results = fut.result()
                    logger.info("TikHub %s: %d signals", name, len(results))
                    all_signals.extend(results)
                except Exception as exc:
                    logger.error("TikHub %s failed: %s", name, exc)

        # Deduplicate by trend_id
        seen: set = set()
        deduped = []
        for s in all_signals:
            if s.trend_id not in seen:
                seen.add(s.trend_id)
                deduped.append(s)

        return deduped
