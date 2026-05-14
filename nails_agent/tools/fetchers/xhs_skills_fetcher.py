"""
Xiaohongshu Skills fetcher — browser-based XHS data collection.

Uses the xiaohongshu-skills project (autoclaw-cc/xiaohongshu-skills)
installed at ~/.hermes/skills/xiaohongshu-skills/

Two modes:
  1. search-feeds --keyword <kw>  (nail-specific, engagement counts often "0")
  2. list-feeds                   (homepage trending, real engagement counts,
                                   filtered by nail keyword match in title)

Falls back silently if not available or not logged in.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional

from nails_agent.models.schemas import TrendSignal

logger = logging.getLogger(__name__)

_TZ8 = timezone(timedelta(hours=8))

# Auto-detect the skills directory
_XHS_SKILLS_CANDIDATES = [
    Path.home() / ".hermes" / "skills" / "xiaohongshu-skills",
    Path("/opt/hermes/skills/xiaohongshu-skills"),
]

# Nail-related keywords for title-based tag extraction and trending filter
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

_NAIL_CORE = {"美甲", "nail art", "nailart", "甲油胶", "指甲", "美甲师", "nail design"}


def _find_skills_dir() -> Optional[Path]:
    env_path = os.environ.get("XHS_SKILLS_DIR")
    if env_path and Path(env_path).exists():
        return Path(env_path)
    for p in _XHS_SKILLS_CANDIDATES:
        if p.exists() and (p / "scripts" / "cli.py").exists():
            return p
    return None


def _make_trend_id(uid: str) -> str:
    """Stable ID based on post UID only — same post = same ID regardless of keyword."""
    today = datetime.now(_TZ8).strftime("%Y%m%d")
    short = hashlib.md5(uid.encode()).hexdigest()[:6].upper()
    return f"TREND_{today}_XHS_{short}"


def _extract_tags_from_title(title: str) -> dict:
    """Extract classified nail tags from a post title."""
    style_tags, color_tags, material_tags, scene_tags = [], [], [], []
    for kw, category in _NAIL_KWS.items():
        if kw.lower() in title.lower():
            if category == "style" and kw not in style_tags:
                style_tags.append(kw)
            elif category == "color" and kw not in color_tags:
                color_tags.append(kw)
            elif category == "material" and kw not in material_tags:
                material_tags.append(kw)
            elif category == "scene" and kw not in scene_tags:
                scene_tags.append(kw)
    return {
        "style_tags": style_tags[:5],
        "color_tags": color_tags[:3],
        "material_tags": material_tags[:3],
        "scene_tags": scene_tags[:3],
    }


def _is_nail_related(text: str) -> bool:
    """True if text explicitly mentions a nail-specific term."""
    t = text.lower()
    # Explicit nail terms (unambiguous)
    if any(
        kw in t for kw in ("美甲", "甲油胶", "指甲", "美甲师", "nail art", "nailart", "nail design")
    ):
        return True
    # "nail" only if not part of a non-nail compound (e.g. "cocktail", "email", "detail")
    if "nail" in t:
        idx = t.find("nail")
        before = t[max(0, idx - 2) : idx]
        if not any(pre in before for pre in ("ck", "em", "de", "ai", "co", "di", "fi")):
            return True
    return False


def _safe_int(val) -> int:
    """Convert string/int/None to int safely."""
    if val is None:
        return 0
    try:
        return int(str(val).replace(",", "").strip()) if str(val).strip() else 0
    except (ValueError, TypeError):
        return 0


class XHSSkillsFetcher:
    """
    Fetches XHS content via browser automation using xiaohongshu-skills CLI.

    Two complementary strategies:
    - search(keywords): nail-specific search via search-feeds
    - fetch_trending(): homepage list-feeds filtered by nail keywords (real engagement data)
    """

    def __init__(self, skills_dir: Optional[Path] = None):
        self.skills_dir = skills_dir or _find_skills_dir()

    def is_available(self) -> bool:
        """Returns True if skills are installed and Chrome is reachable."""
        if not self.skills_dir:
            return False
        try:
            result = self._run_cli(["check-login"], timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    def _run_cli(
        self,
        args: List[str],
        timeout: int = 45,
    ) -> subprocess.CompletedProcess:
        cmd = ["uv", "run", "python", "scripts/cli.py"] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.skills_dir),
            timeout=timeout,
        )

    def _parse_item(self, item: dict, keyword: str, index: int) -> Optional[TrendSignal]:
        """Parse one XHS feed item → TrendSignal."""
        try:
            note = item.get("note") or item.get("noteCard") or item
            uid = note.get("id") or note.get("noteId") or item.get("id") or ""
            stable_uid = uid if uid else hashlib.md5(f"{keyword}{index}".encode()).hexdigest()[:12]
            title = note.get("displayTitle") or note.get("title") or note.get("display_title") or ""
            desc = note.get("desc") or note.get("description") or note.get("content") or ""
            caption = f"{title} {desc}".strip()[:200]

            stats = (
                note.get("interactInfo")
                or note.get("interact_info")
                or note.get("statistics")
                or {}
            )
            likes = _safe_int(
                stats.get("likedCount") or stats.get("liked_count") or stats.get("like_count")
            )
            collects = _safe_int(
                stats.get("collectedCount")
                or stats.get("collected_count")
                or stats.get("collect_count")
            )
            comments = _safe_int(stats.get("commentCount") or stats.get("comment_count"))
            shares = _safe_int(stats.get("shareCount") or stats.get("share_count"))

            # Tag extraction: explicit tag_list → fallback to title keyword matching
            raw_tags = [
                t.get("name") or t.get("text") or t
                for t in (note.get("tagList") or note.get("tag_list") or [])
                if isinstance(t, (str, dict))
            ]
            raw_tags = [t for t in raw_tags if isinstance(t, str) and t]

            # Also extract from hashtags in caption
            hashtag_tags = re.findall(r"#(\w+)", caption)
            for ht in hashtag_tags:
                if ht not in raw_tags:
                    raw_tags.append(ht)

            # Title-based classification when we have no structured tags
            classified = _extract_tags_from_title(title + " " + desc)
            if raw_tags:
                # Use explicit tags but keep classified as supplement
                classified["style_tags"] = (raw_tags[:5] + classified["style_tags"])[:5]

            now_iso = datetime.now(_TZ8).isoformat()
            return TrendSignal(
                trend_id=_make_trend_id(stable_uid),
                platform="小红书",
                keyword=keyword,
                caption=caption,
                likes=likes,
                comments=comments,
                shares=shares,
                collects=collects,
                publish_time=now_iso,
                captured_at=now_iso,
                **classified,
                image_urls=[],
            )
        except Exception as e:
            logger.debug("XHS skills parse error item %d: %s", index, e)
            return None

    def _parse_output(self, raw_json: str, keyword: str) -> List[TrendSignal]:
        """Parse CLI JSON output → List[TrendSignal]."""
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("XHS skills: invalid JSON output")
            return []

        # Support both list output and {"feeds": [...]} / {"items": [...]}
        if isinstance(data, list):
            items = data
        else:
            items = data.get("feeds") or data.get("items") or []

        signals = []
        for i, item in enumerate(items):
            sig = self._parse_item(item, keyword, i)
            if sig:
                signals.append(sig)
        return signals

    def search(
        self,
        keywords: List[str],
        limit_per_kw: int = 10,
        sort_by: str = "最多点赞",
    ) -> List[TrendSignal]:
        """
        Search XHS feeds for each keyword via browser automation.
        Uses search-feeds; supplements with list-feeds when results are sparse.
        """
        if not self.skills_dir:
            logger.info("XHS skills: not installed, skipping")
            return []

        all_signals: List[TrendSignal] = []

        for kw in keywords:
            try:
                logger.info("XHS skills: searching '%s'...", kw)
                result = self._run_cli(
                    ["search-feeds", "--keyword", kw, "--sort-by", sort_by],
                )
                if result.returncode != 0:
                    logger.warning(
                        "XHS skills search-feeds failed for '%s': %s", kw, result.stderr[:200]
                    )
                    continue

                signals = self._parse_output(result.stdout, kw)
                logger.info("XHS skills: '%s' → %d signals", kw, len(signals))
                all_signals.extend(signals[:limit_per_kw])

            except subprocess.TimeoutExpired:
                logger.warning("XHS skills: timeout searching '%s'", kw)
            except Exception as exc:
                logger.error("XHS skills: error for '%s': %s", kw, exc)

        return all_signals

    def fetch_trending(self, limit: int = 20) -> List[TrendSignal]:
        """
        Fetch XHS homepage trending content (list-feeds) and filter for nail posts.
        Returns signals with REAL engagement counts (likedCount is populated here).
        """
        if not self.skills_dir:
            return []

        try:
            logger.info("XHS skills: fetching trending homepage feeds…")
            result = self._run_cli(["list-feeds"])
            if result.returncode != 0:
                logger.warning("XHS skills list-feeds failed: %s", result.stderr[:200])
                return []

            all_items = self._parse_output(result.stdout, "美甲")
            nail_items = [s for s in all_items if _is_nail_related(s.caption)]

            logger.info(
                "XHS skills trending: %d total → %d nail-related", len(all_items), len(nail_items)
            )
            return nail_items[:limit]

        except subprocess.TimeoutExpired:
            logger.warning("XHS skills: timeout fetching trending")
            return []
        except Exception as exc:
            logger.error("XHS skills trending error: %s", exc)
            return []
