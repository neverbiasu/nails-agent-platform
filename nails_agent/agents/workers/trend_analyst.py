"""
Worker 1: Trend Analyst
Input:  List[TrendSignal]
Output: TrendAnalysisResult

Computes composite_score, ranks top-10, detects cross-platform patterns,
flags anomalies with high recent growth.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from nails_agent.models.schemas import TrendSignal, TrendAnalysisResult, StyleTrend
from nails_agent.services.trend_presentation import generate_display_label, sample_label


_TZ8 = timezone(timedelta(hours=8))


def _composite(sig: TrendSignal) -> float:
    return sig.likes + sig.collects * 1.5 + sig.shares * 2 + sig.comments * 0.5


# Tokens that originate from OUR search queries, not from real post content.
# We strip these from aggregated style trends so the report doesn't echo back
# its own inputs ("美甲推荐" is a search term, not a style).
_SEARCH_NOISE_TAGS = {
    "美甲",
    "美甲推荐",
    "美甲灵感",
    "美甲教程",
    "夏日美甲",
    "显白美甲",
    "法式美甲",
    "高级美甲",
    "nail",
    "nailart",
    "naildesign",
    "美甲日记",
}


def _aggregate_style_trends(signals: List[TrendSignal]) -> List[StyleTrend]:
    """
    Aggregate engagement by tag across all signals → 'what styles are hot'.
    """
    bucket: Dict[str, Dict[str, Any]] = {}

    def _add(tag: str, category: str, sig: TrendSignal):
        if not tag or tag.lower() in _SEARCH_NOISE_TAGS:
            return
        b = bucket.setdefault(
            tag,
            {
                "category": category,
                "post_count": 0,
                "engagement": 0,
                "best": sig,
            },
        )
        b["post_count"] += 1
        b["engagement"] += int(_composite(sig))
        if _composite(sig) > _composite(b["best"]):
            b["best"] = sig

    for sig in signals:
        for t in sig.style_tags:
            _add(t, "style", sig)
        for t in sig.color_tags:
            _add(t, "color", sig)
        for t in sig.material_tags:
            _add(t, "material", sig)
        for t in sig.scene_tags:
            _add(t, "scene", sig)

    if not bucket:
        return []

    max_eng = max(b["engagement"] for b in bucket.values()) or 1
    trends: List[StyleTrend] = []
    for tag, b in bucket.items():
        score = round(b["engagement"] / max_eng * 100, 1)
        trends.append(
            StyleTrend(
                tag=tag,
                category=b["category"],
                post_count=b["post_count"],
                total_engagement=b["engagement"],
                aggregated_score=score,
                sample_caption=b["best"].caption[:80],
            )
        )

    # Filter single-post tags (too noisy) and sort
    trends = [t for t in trends if t.post_count >= 2]
    trends.sort(key=lambda t: t.aggregated_score, reverse=True)
    return trends


def _normalise(scores: List[float]) -> List[float]:
    mn, mx = min(scores), max(scores)
    if mx == mn:
        return [50.0] * len(scores)
    return [round((s - mn) / (mx - mn) * 100, 2) for s in scores]


def analyse(signals: List[TrendSignal]) -> TrendAnalysisResult:
    if not signals:
        return TrendAnalysisResult(
            top_10=[],
            patterns=[],
            anomalies=[],
            timestamp=datetime.now(_TZ8).isoformat(),
        )

    # 1. Composite scores
    raw_scores = [_composite(s) for s in signals]
    norm = _normalise(raw_scores)
    for sig, score in zip(signals, norm):
        sig.composite_score = score

    # 2. Sort + top-10
    ranked = sorted(signals, key=lambda s: s.composite_score, reverse=True)
    for i, sig in enumerate(ranked, 1):
        sig.rank = i
        # Always try generate_display_label first so meaningful tags override stale placeholders
        sig.display_label = (
            generate_display_label(sig)
            or sig.display_label
            or sample_label(sig, i, with_tags=False)
        )
    top_10 = ranked[:10]

    # 3. Aggregated style trends (the real signal, not echoed search keywords)
    style_trends = _aggregate_style_trends(signals)

    # 4. Cross-platform co-occurrence patterns (filtered to real style tags)
    def real_tag_filter(t: str) -> bool:
        return bool(t) and t.lower() not in _SEARCH_NOISE_TAGS

    tag_platform: Dict[str, set] = {}
    for sig in signals:
        for tag in sig.style_tags:
            if real_tag_filter(tag):
                tag_platform.setdefault(tag, set()).add(sig.platform)

    pair_counter: Counter = Counter()
    for sig in signals:
        tags = [t for t in sig.style_tags if real_tag_filter(t)]
        for i in range(len(tags)):
            for j in range(i + 1, len(tags)):
                key = tuple(sorted([tags[i], tags[j]]))
                pair_counter[key] += 1

    patterns: List[str] = []
    for (t1, t2), cnt in pair_counter.most_common(5):
        platforms_t1 = tag_platform.get(t1, set())
        platforms_t2 = tag_platform.get(t2, set())
        shared = platforms_t1 & platforms_t2
        if cnt >= 2:
            scope = "、".join(sorted(shared)) if shared else "单平台"
            patterns.append(f"{t1}+{t2} 组合（{scope}，{cnt} 帖共现）")

    if not patterns and style_trends:
        top_combo = "、".join(t.tag for t in style_trends[:3])
        patterns.append(f"主流风格：{top_combo}")

    # 5. Anomaly detection (style-trend bursts in last 48h)
    now = datetime.now(_TZ8)

    # Recent-only signals
    recent_signals = []
    for sig in signals:
        try:
            cap = datetime.fromisoformat(sig.captured_at)
            if cap.tzinfo is None:
                cap = cap.replace(tzinfo=_TZ8)
            if (now - cap).total_seconds() / 3600 <= 48:
                recent_signals.append(sig)
        except Exception:
            pass

    # Per-tag recent-engagement vs mean
    recent_tag_engagement: Dict[str, int] = {}
    for sig in recent_signals:
        for tag in sig.style_tags + sig.color_tags + sig.material_tags + sig.scene_tags:
            if real_tag_filter(tag):
                recent_tag_engagement[tag] = recent_tag_engagement.get(tag, 0) + int(
                    _composite(sig)
                )

    anomalies: List[str] = []
    if recent_tag_engagement:
        eng_values = list(recent_tag_engagement.values())
        mean_eng = sum(eng_values) / len(eng_values)
        for tag, eng in sorted(recent_tag_engagement.items(), key=lambda x: -x[1])[:5]:
            if eng > mean_eng * 1.8:
                pct = round((eng - mean_eng) / mean_eng * 100) if mean_eng else 0
                anomalies.append(f"「{tag}」近 48h 累计热度比平均高 {pct}%")

    return TrendAnalysisResult(
        top_10=top_10,
        style_trends=style_trends[:15],
        patterns=patterns[:5],
        anomalies=anomalies[:5],
        timestamp=datetime.now(_TZ8).isoformat(),
    )


def from_json_file(path: str) -> TrendAnalysisResult:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    signals = [TrendSignal(**item) for item in data]
    return analyse(signals)
