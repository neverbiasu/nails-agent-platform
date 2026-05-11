"""
Worker 2a: Value Evaluator
Input:  TrendAnalysisResult + List[StyleLibraryItem]
Output: ValueEvaluationResult

Scores each top-trend on external heat, recency growth, and style-library gap.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import List

from nails_agent.models.schemas import (
    TrendAnalysisResult,
    TrendSignal,
    MetricSnapshot,
    ValueEvaluationResult,
    StyleLibraryItem,
)


_TZ8 = timezone(timedelta(hours=8))


def _recency_score(publish_time: str) -> float:
    """
    Real publish-time recency, 0-100.
      • 0 days old   → 100
      • 7 days old   → 0   (linear decay)
      • >7 days old  → 0
      • unknown ('') → 50  (neutral; common for XHS feeds)
    """
    if not publish_time:
        return 50.0
    try:
        pub = datetime.fromisoformat(publish_time)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=_TZ8)
        hours_old = (datetime.now(_TZ8) - pub).total_seconds() / 3600
        if hours_old < 0:
            return 100.0  # future-dated (clock skew); treat as fresh
        return max(0.0, round((1 - hours_old / 168) * 100, 1))
    except Exception:
        return 50.0


def _style_gap_score(sig: TrendSignal, library: List[StyleLibraryItem]) -> float:
    """
    100 if no style in library shares any style_tag with this trend.
    0   if a library item covers all style_tags perfectly.
    """
    sig_tags = set(sig.style_tags)
    if not sig_tags:
        return 50.0
    max_overlap = 0
    for item in library:
        overlap = len(sig_tags & set(item.style_tags))
        if overlap > max_overlap:
            max_overlap = overlap
    gap = 1 - max_overlap / len(sig_tags)
    return round(gap * 100, 1)


def evaluate(
    analysis: TrendAnalysisResult,
    library: List[StyleLibraryItem],
) -> ValueEvaluationResult:
    snapshots: List[MetricSnapshot] = []

    for sig in analysis.top_10:
        heat = sig.composite_score                        # already 0-100
        recency = _recency_score(sig.publish_time)
        gap = _style_gap_score(sig, library)
        priority = round(heat * 0.5 + recency * 0.3 + gap * 0.2, 1)

        snapshots.append(
            MetricSnapshot(
                trend_id=sig.trend_id,
                keyword=sig.keyword,
                external_heat_score=heat,
                trend_growth_score=recency,
                style_gap_score=gap,
                launch_priority_score=priority,
                rank=sig.rank,
            )
        )

    # re-rank by priority
    snapshots.sort(key=lambda s: s.launch_priority_score, reverse=True)
    for i, s in enumerate(snapshots, 1):
        s.rank = i

    return ValueEvaluationResult(
        snapshots=snapshots,
        timestamp=datetime.now(_TZ8).isoformat(),
    )


def from_files(analysis_path: str, library_path: str) -> ValueEvaluationResult:
    with open(analysis_path, encoding="utf-8") as f:
        analysis = TrendAnalysisResult(**json.load(f))
    with open(library_path, encoding="utf-8") as f:
        library = [StyleLibraryItem(**item) for item in json.load(f)]
    return evaluate(analysis, library)
