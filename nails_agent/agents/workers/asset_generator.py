"""
Worker 2b: Asset Generator
Input:  TrendAnalysisResult
Output: AssetGenerationResult

Generates style card drafts with platform-specific captions + pricing.
Rule-based (no LLM call required for demo).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional

import requests

from nails_agent.models.schemas import (
    TrendAnalysisResult,
    TrendSignal,
    StyleCardDraft,
    PlatformVariant,
    PricingInfo,
    AssetGenerationResult,
)
from nails_agent.services.trend_presentation import sample_label, signal_image_url, tag_summary

_TZ8 = timezone(timedelta(hours=8))
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENHANCE_SRC_DIR = _PROJECT_ROOT / "web" / "output" / "images" / "enhance_src"
_CONTENT_TYPE_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_log = logging.getLogger(__name__)

# ── Caption templates ─────────────────────────────────────────────────────────

_XHS_TEMPLATES = [
    "这组{style_desc}绝了！低调有魅力，通勤约会都能驾驭～ ✨",
    "最近爱上这种{style_desc}，质感超绝，看一眼就心动 💅",
    "{style_desc}拍照超出片，美到不像话 🌸",
]
_DOUYIN_TEMPLATES = [
    "{style_desc}✨ 你值得拥有",
    "种草这组{style_desc}，这是今年很值得试的款式",
    "{style_desc}实拍，效果惊艳全场",
]
_IG_TEMPLATES = [
    "Nail look with {tags_en} vibes — effortlessly chic ✨",
    "Obsessed with this nail look! {tags_en} energy only 💅",
    "Spring/Summer must-have nails featuring {tags_en} elements 🌸",
]


def _hashtags(sig: TrendSignal, platform: str) -> List[str]:
    base = ["#美甲"]
    for tag in (sig.style_tags + sig.color_tags + sig.scene_tags)[:4]:
        if tag in {"美甲", "nail"}:
            continue
        base.append(f"#{tag}美甲")
    if platform == "xiaohongshu":
        base += ["#美甲推荐", "#美甲日记"]
    elif platform == "douyin":
        base += ["#美甲教程", "#美甲分享"]
    elif platform == "instagram":
        return ["#nailart", "#nails", "#naildesign", "#nailinspo"]
    return base[:6]


def _pricing(sig: TrendSignal) -> PricingInfo:
    # Price tiers based on material complexity
    if any(t in sig.material_tags for t in ["3D雕花", "硬胶", "镶钻"]):
        return PricingInfo(
            base_price="¥128",
            premium_price="¥268",
            promo_price="¥88",
            premium_reason="高端材料+手工雕花+拍照服务",
        )
    if any(t in sig.material_tags for t in ["猫眼", "磁铁石"]):
        return PricingInfo(
            base_price="¥89",
            premium_price="¥168",
            promo_price="¥59",
            premium_reason="限定磁铁石材料+延长设计+拍照服务",
        )
    return PricingInfo(
        base_price="¥69",
        premium_price="¥128",
        promo_price="¥49",
        premium_reason="精工制作+拍照服务",
    )


def _download_remote(url: str) -> Optional[str]:
    """Download a remote image to a local cache file; return its path or None."""
    if not url.startswith(("http://", "https://")):
        return None
    try:
        resp = requests.get(url, timeout=30, headers={"Referer": "https://www.xiaohongshu.com/"})
        resp.raise_for_status()
    except Exception as exc:
        _log.warning("Failed to download source image %s: %s", url[:60], exc)
        return None
    ext = _CONTENT_TYPE_EXT.get(resp.headers.get("Content-Type", "").split(";")[0].strip(), ".jpg")
    _ENHANCE_SRC_DIR.mkdir(parents=True, exist_ok=True)
    out = _ENHANCE_SRC_DIR / (hashlib.md5(url.encode()).hexdigest()[:16] + ext)
    out.write_bytes(resp.content)
    return str(out)


def _resolve_source_image(sig: TrendSignal) -> Optional[str]:
    """Resolve a draft's source image to a local file path the client can upload.

    Prefers an existing local scraped file; otherwise downloads a remote image URL.
    ComfyUI upload needs a local file, so a card counts as "having an image" if either
    a local path exists or a remote URL can be fetched.
    """
    for p in getattr(sig, "local_image_paths", None) or []:
        path = Path(p)
        if path.exists():
            return str(path)
        alt = _PROJECT_ROOT / p
        if alt.exists():
            return str(alt)
    for url in getattr(sig, "image_urls", None) or []:
        local = _download_remote(url)
        if local:
            return local
    return None


def _enhance_drafts(drafts: List[StyleCardDraft], signals: List[TrendSignal], top_n: int) -> int:
    """Generate ComfyUI cover images for the top-N drafts in place.

    Bounded by top_n to cap Cloud latency. Never raises — on any failure the draft
    keeps its original image_url and enhanced_image_url stays empty. Returns the
    number of drafts successfully enhanced.
    """
    if top_n <= 0:
        return 0
    try:
        from nails_agent.tools.comfyui_client import ComfyUIClient
    except Exception as exc:  # pragma: no cover - import guard
        _log.warning("ComfyUI client unavailable, skipping enhancement: %s", exc)
        return 0

    client = ComfyUIClient()
    if not client.api_key:
        _log.info("COMFYUI_API_KEY missing, skipping image enhancement")
        return 0

    enhanced = 0
    for draft, sig in list(zip(drafts, signals))[:top_n]:
        src = _resolve_source_image(sig)
        if not src:
            _log.info("No source image for %s, skipping enhancement", draft.style_name)
            continue
        try:
            result = client.enhance(src, workflow="product_showcase")
        except Exception as exc:
            _log.warning("Enhancement raised for %s: %s", draft.style_name, exc)
            continue
        if result.get("success") and result.get("image_url"):
            draft.enhanced_image_url = result["image_url"]
            enhanced += 1
        else:
            _log.warning("Enhancement failed for %s: %s", draft.style_name, result.get("error"))
    return enhanced


def generate(analysis: TrendAnalysisResult, enhance_top_n: int = 0) -> AssetGenerationResult:
    drafts: List[StyleCardDraft] = []

    for i, sig in enumerate(analysis.top_10):
        style_name = sample_label(sig, i + 1, with_tags=True)
        style_desc = tag_summary(sig, max_tags=4, empty="趋势美甲")
        tags_en = " & ".join(sig.style_tags[:2]) if sig.style_tags else "aesthetic"

        tmpl_idx = i % len(_XHS_TEMPLATES)
        xhs_caption = _XHS_TEMPLATES[tmpl_idx].format(style_desc=style_desc)
        dy_caption = _DOUYIN_TEMPLATES[tmpl_idx].format(style_desc=style_desc)
        ig_caption = _IG_TEMPLATES[tmpl_idx].format(tags_en=tags_en)

        variants = {
            "xiaohongshu": PlatformVariant(
                caption=xhs_caption,
                hashtags=_hashtags(sig, "xiaohongshu"),
            ),
            "douyin": PlatformVariant(
                caption=dy_caption,
                hashtags=_hashtags(sig, "douyin"),
            ),
            "instagram": PlatformVariant(
                caption=ig_caption,
                hashtags=_hashtags(sig, "instagram"),
            ),
        }

        draft = StyleCardDraft(
            trend_id=sig.trend_id,
            style_name=style_name,
            style_tags=sig.style_tags,
            image_url=signal_image_url(sig),
            platform_variants=variants,
            pricing=_pricing(sig),
        )
        drafts.append(draft)

    _enhance_drafts(drafts, list(analysis.top_10), enhance_top_n)

    return AssetGenerationResult(
        drafts=drafts,
        timestamp=datetime.now(_TZ8).isoformat(),
    )


def from_file(analysis_path: str) -> AssetGenerationResult:
    with open(analysis_path, encoding="utf-8") as f:
        analysis = TrendAnalysisResult(**json.load(f))
    return generate(analysis)
