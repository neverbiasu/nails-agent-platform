"""
XHS-MCP fetcher — talks to the Go xiaohongshu-mcp HTTP server.

The Go server (xpzouying/xiaohongshu-mcp) exposes REST endpoints in
addition to the MCP protocol. We hit `/api/v1/feeds/search` and
`/api/v1/feeds/list` directly — simpler than MCP handshake, same data.

Server must be running:
    cd /tmp/xiaohongshu-mcp && go run .

And the account must be logged in:
    cd /tmp/xiaohongshu-mcp && go run cmd/login/main.go
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from nails_agent.models.schemas import TrendSignal

logger = logging.getLogger(__name__)

_TZ8 = timezone(timedelta(hours=8))

# Tag vocabulary, reused from XHS Skills fetcher
_NAIL_KWS = {
    # styles
    "猫眼": "style",
    "法式": "style",
    "渐变": "style",
    "奶油": "style",
    "3D": "style",
    "贴片": "style",
    "冰透": "style",
    "暗黑": "style",
    "日式": "style",
    "韩式": "style",
    "ins风": "style",
    "极简": "style",
    "波点": "style",
    "格纹": "style",
    "花朵": "style",
    "蝴蝶": "style",
    "爱心": "style",
    "星月": "style",
    "手绘": "style",
    "光疗": "style",
    "美甲": "style",
    "nail": "style",
    # colors
    "白色": "color",
    "黑色": "color",
    "粉色": "color",
    "红色": "color",
    "蓝色": "color",
    "紫色": "color",
    "绿色": "color",
    "裸色": "color",
    "香芋": "color",
    "薄荷": "color",
    "莫兰迪": "color",
    "多巴胺": "color",
    # materials
    "甲油胶": "material",
    "钻": "material",
    "锡箔": "material",
    "贝壳": "material",
    "磁铁石": "material",
    "镭射": "material",
    "亮片": "material",
    # scenes
    "新娘": "scene",
    "日常": "scene",
    "约会": "scene",
    "通勤": "scene",
    "夏日": "scene",
    "秋冬": "scene",
    "圣诞": "scene",
    "新年": "scene",
}

_NAIL_CORE = ("美甲", "nail art", "nailart", "甲油胶", "指甲", "美甲师", "nail design")


def _make_trend_id(uid: str) -> str:
    today = datetime.now(_TZ8).strftime("%Y%m%d")
    short = hashlib.md5(uid.encode()).hexdigest()[:6].upper()
    return f"TREND_{today}_XHS_{short}"


def _safe_int(val) -> int:
    if val is None:
        return 0
    s = str(val).strip().replace(",", "")
    if not s or s == "0":
        return 0
    # Handle "1.2万" / "2.5w"
    m = re.match(r"^([\d.]+)\s*(万|w|W|千|k|K)?$", s)
    if m:
        num = float(m.group(1))
        unit = m.group(2)
        if unit in ("万", "w", "W"):
            return int(num * 10000)
        if unit in ("千", "k", "K"):
            return int(num * 1000)
        return int(num)
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _classify(text: str) -> dict:
    """Extract style/color/material/scene tags from title."""
    style, color, material, scene = [], [], [], []
    tl = text.lower()
    for kw, cat in _NAIL_KWS.items():
        if kw.lower() in tl:
            if cat == "style" and kw not in style:
                style.append(kw)
            elif cat == "color" and kw not in color:
                color.append(kw)
            elif cat == "material" and kw not in material:
                material.append(kw)
            elif cat == "scene" and kw not in scene:
                scene.append(kw)
    return {
        "style_tags": style[:5],
        "color_tags": color[:3],
        "material_tags": material[:3],
        "scene_tags": scene[:3],
    }


def _is_nail_related(text: str) -> bool:
    t = text.lower()
    if any(k in t for k in _NAIL_CORE):
        return True
    if "nail" in t:
        idx = t.find("nail")
        before = t[max(0, idx - 2) : idx]
        if not any(pre in before for pre in ("ck", "em", "de", "ai", "co", "di", "fi")):
            return True
    return False


def _feed_to_signal(feed: dict, keyword: str) -> Optional[TrendSignal]:
    """Convert one Go xhs-mcp feed item → TrendSignal."""
    try:
        nc = feed.get("noteCard", {})
        title = nc.get("displayTitle", "") or ""
        desc = nc.get("desc", "") or ""
        caption = f"{title} {desc}".strip()[:200]

        ii = nc.get("interactInfo", {})
        likes = _safe_int(ii.get("likedCount"))
        collects = _safe_int(ii.get("collectedCount"))
        comments = _safe_int(ii.get("commentCount"))
        shares = _safe_int(ii.get("sharedCount"))

        uid = feed.get("id") or nc.get("noteId") or ""
        if not uid:
            return None

        cover = nc.get("cover", {}) or {}
        cover_url = cover.get("urlDefault") or cover.get("url") or cover.get("urlPre") or ""

        classified = _classify(title + " " + desc)
        now_iso = datetime.now(_TZ8).isoformat()

        return TrendSignal(
            trend_id=_make_trend_id(uid),
            platform="小红书",
            keyword=keyword,
            caption=caption,
            likes=likes,
            comments=comments,
            shares=shares,
            collects=collects,
            # XHS search-feeds payload doesn't include publish time; leave
            # empty (sentinel for "unknown" → neutral recency score).
            publish_time="",
            captured_at=now_iso,
            **classified,
            image_urls=[cover_url] if cover_url else [],
        )
    except Exception as e:
        logger.debug("XHS-MCP parse error: %s", e)
        return None


class XHSMCPFetcher:
    """
    Fetches XHS data via the local Go xiaohongshu-mcp HTTP server.

    Two strategies:
      - search(keywords): per-keyword search via /feeds/search
      - fetch_trending(): homepage list via /feeds/list + nail-keyword filter
    """

    def __init__(self, base_url: str = "http://localhost:18060", timeout: int = 75):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._available_cache: Optional[bool] = None

    def is_available(self) -> bool:
        """Server up AND logged in. Cached after first call (slow ~6s)."""
        if self._available_cache is not None:
            return self._available_cache
        try:
            # Quick health check first (server up?)
            r = requests.get(f"{self.base_url}/health", timeout=2)
            if not r.ok:
                self._available_cache = False
                return False
            # Full login check (slow — starts a browser)
            r = requests.get(f"{self.base_url}/api/v1/login/status", timeout=20)
            if not r.ok:
                self._available_cache = False
                return False
            data = r.json().get("data") or {}
            self._available_cache = bool(
                data.get("is_logged_in") or data.get("isLoggedIn") or data.get("logged_in")
            )
        except Exception as e:
            logger.debug("XHS-MCP availability check failed: %s", e)
            self._available_cache = False
        return self._available_cache

    def search(self, keywords: List[str], limit_per_kw: int = 15) -> List[TrendSignal]:
        signals: List[TrendSignal] = []
        for kw in keywords:
            try:
                logger.info("XHS-MCP: searching '%s'…", kw)
                r = requests.get(
                    f"{self.base_url}/api/v1/feeds/search",
                    params={"keyword": kw},
                    timeout=self.timeout,
                )
                if not r.ok:
                    logger.warning("XHS-MCP search '%s' HTTP %d", kw, r.status_code)
                    continue
                body = r.json()
                if not body.get("success"):
                    logger.warning("XHS-MCP search '%s' failed: %s", kw, body.get("message"))
                    continue
                feeds = (body.get("data") or {}).get("feeds") or []
                taken = 0
                for f in feeds:
                    sig = _feed_to_signal(f, kw)
                    if sig:
                        signals.append(sig)
                        taken += 1
                        if taken >= limit_per_kw:
                            break
                logger.info("XHS-MCP: '%s' → %d signals", kw, taken)
            except requests.Timeout:
                logger.warning("XHS-MCP timeout for '%s'", kw)
            except Exception as e:
                logger.error("XHS-MCP error for '%s': %s", kw, e)
        return signals

    def fetch_trending(self, limit: int = 20) -> List[TrendSignal]:
        try:
            logger.info("XHS-MCP: fetching trending list…")
            r = requests.get(f"{self.base_url}/api/v1/feeds/list", timeout=self.timeout)
            if not r.ok:
                logger.warning("XHS-MCP list HTTP %d", r.status_code)
                return []
            body = r.json()
            feeds = (body.get("data") or {}).get("feeds") or []
            all_sigs = [_feed_to_signal(f, "美甲") for f in feeds]
            all_sigs = [s for s in all_sigs if s and _is_nail_related(s.caption)]
            logger.info("XHS-MCP trending: %d nail-related / %d total", len(all_sigs), len(feeds))
            return all_sigs[:limit]
        except Exception as e:
            logger.error("XHS-MCP trending error: %s", e)
            return []
