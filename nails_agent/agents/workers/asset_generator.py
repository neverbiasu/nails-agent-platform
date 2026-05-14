"""
Worker 2b: Asset Generator
Input:  TrendAnalysisResult
Output: AssetGenerationResult

Generates style card drafts with platform-specific captions + pricing.
Rule-based (no LLM call required for demo).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import List

from nails_agent.models.schemas import (
    TrendAnalysisResult,
    TrendSignal,
    StyleCardDraft,
    PlatformVariant,
    PricingInfo,
    AssetGenerationResult,
)

_TZ8 = timezone(timedelta(hours=8))

# ── Caption templates ─────────────────────────────────────────────────────────

_XHS_TEMPLATES = [
    "{keyword}绝了！{tags_str}，低调有魅力，通勤约会都能驾驭～ ✨",
    "最近爱上{keyword}，{tags_str}质感超绝，看一眼就心动 💅",
    "{keyword}拍照超出片！{tags_str}，美到不像话 🌸",
]
_DOUYIN_TEMPLATES = [
    "{keyword}，{tags_str}✨ 你值得拥有",
    "种草{keyword}！{tags_str}，这是今年最美的款式没有之一",
    "{keyword}实拍，{tags_str}，效果惊艳全场",
]
_IG_TEMPLATES = [
    "{keyword_en} nails with {tags_en} vibes — effortlessly chic ✨",
    "Obsessed with this {keyword_en} nail look! {tags_en} energy only 💅",
    "Spring/Summer must-have: {keyword_en} nails featuring {tags_en} elements 🌸",
]


def _hashtags(sig: TrendSignal, platform: str) -> List[str]:
    base = ["#美甲", f"#{sig.keyword}"]
    for tag in sig.style_tags[:2]:
        base.append(f"#{tag}美甲")
    if platform == "xiaohongshu":
        base += ["#美甲推荐", "#美甲日记"]
    elif platform == "douyin":
        base += ["#美甲教程", "#美甲分享"]
    elif platform == "instagram":
        return [
            f"#{sig.keyword.replace(' ', '')}",
            "#nailart",
            "#nails",
            "#naildesign",
            "#nailinspo",
        ]
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


def generate(analysis: TrendAnalysisResult) -> AssetGenerationResult:
    drafts: List[StyleCardDraft] = []

    for i, sig in enumerate(analysis.top_10):
        tags_str = "、".join(sig.style_tags[:3]) if sig.style_tags else sig.keyword
        tags_en = " & ".join(sig.style_tags[:2]) if sig.style_tags else "aesthetic"
        keyword_en = sig.keyword  # simplified; no translation service needed

        tmpl_idx = i % len(_XHS_TEMPLATES)
        xhs_caption = _XHS_TEMPLATES[tmpl_idx].format(keyword=sig.keyword, tags_str=tags_str)
        dy_caption = _DOUYIN_TEMPLATES[tmpl_idx].format(keyword=sig.keyword, tags_str=tags_str)
        ig_caption = _IG_TEMPLATES[tmpl_idx].format(keyword_en=keyword_en, tags_en=tags_en)

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
            style_name=sig.keyword,
            style_tags=sig.style_tags,
            image_url="",  # filled by try-on or style library lookup
            platform_variants=variants,
            pricing=_pricing(sig),
        )
        drafts.append(draft)

    return AssetGenerationResult(
        drafts=drafts,
        timestamp=datetime.now(_TZ8).isoformat(),
    )


def from_file(analysis_path: str) -> AssetGenerationResult:
    with open(analysis_path, encoding="utf-8") as f:
        analysis = TrendAnalysisResult(**json.load(f))
    return generate(analysis)
