"""
Worker 2a: Value Evaluator
Input:  TrendAnalysisResult + List[NailStyleStoreItem]
Output: ValueEvaluationResult

Scores each top-trend on three independent dimensions, then combines them
into a launch priority score. See docs/scoring_formulas.md for full details.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from typing import List

from nails_agent.models.schemas import (
    TrendAnalysisResult,
    TrendSignal,
    MetricSnapshot,
    ValueEvaluationResult,
    NailStyleStoreItem,
)
from nails_agent.services.trend_presentation import (
    generate_display_label,
    sample_label,
    signal_image_url,
    tag_summary,
)


_TZ8 = timezone(timedelta(hours=8))


# ── Dimension 1: External Heat ─────────────────────────────────────────────────


def _heat_score(sig: TrendSignal, all_signals: List[TrendSignal]) -> float:
    """
    Normalised composite engagement across all signals in this batch,
    capped at 100. Uses log-scale to prevent a single viral post from
    dominating the entire range.

    composite = likes + collects * 1.5 + shares * 2 + comments * 0.5
    heat = log1p(composite) / log1p(max_composite) * 100
    """

    def _raw(s: TrendSignal) -> float:
        return s.likes + s.collects * 1.5 + s.shares * 2 + s.comments * 0.5

    raw = _raw(sig)
    max_raw = max((_raw(s) for s in all_signals), default=1.0)
    if max_raw <= 0:
        return 50.0
    score = math.log1p(raw) / math.log1p(max_raw) * 100
    return round(min(score, 100.0), 1)


# ── Dimension 2: Freshness / Recency ──────────────────────────────────────────


def _freshness_score(sig: TrendSignal, all_signals: List[TrendSignal]) -> float:
    """
    Two-component freshness score (0-100):

    A) Publish-time recency (weight 0.6)
       Linear decay from 100 at t=0 to 0 at t=7 days.
       Missing publish_time → median of other signals' ages (not 50 flat).

    B) Rank-based novelty (weight 0.4)
       Signals with high engagement but LOW historical rank are newer entrants.
       Approximated as: 1 - (rank_in_batch / batch_size).
       This distinguishes a suddenly trending post from a consistently popular one.

    Combined: freshness = 0.6 * recency + 0.4 * novelty
    """
    # A) recency
    recency = _recency(sig.publish_time, all_signals)

    # B) novelty: rank within the batch sorted by composite engagement
    def _raw(s: TrendSignal) -> float:
        return s.likes + s.collects * 1.5 + s.shares * 2 + s.comments * 0.5

    sorted_ids = sorted(all_signals, key=_raw, reverse=True)
    rank = next((i for i, s in enumerate(sorted_ids) if s.trend_id == sig.trend_id), 0)
    novelty = max(0.0, (1 - rank / max(len(all_signals) - 1, 1)) * 100)

    return round(0.6 * recency + 0.4 * novelty, 1)


def _recency(publish_time: str, all_signals: List[TrendSignal]) -> float:
    if not publish_time:
        # Use median age of signals that do have a publish_time
        ages = []
        for s in all_signals:
            if s.publish_time:
                try:
                    pub = datetime.fromisoformat(s.publish_time)
                    if pub.tzinfo is None:
                        pub = pub.replace(tzinfo=_TZ8)
                    ages.append((datetime.now(_TZ8) - pub).total_seconds() / 3600)
                except Exception:
                    pass
        median_age = sorted(ages)[len(ages) // 2] if ages else 84  # default 3.5 days
        return max(0.0, round((1 - median_age / 168) * 100, 1))
    try:
        pub = datetime.fromisoformat(publish_time)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=_TZ8)
        hours_old = (datetime.now(_TZ8) - pub).total_seconds() / 3600
        if hours_old < 0:
            return 100.0
        return max(0.0, round((1 - hours_old / 168) * 100, 1))
    except Exception:
        return 50.0


# ── Dimension 3: Style Gap ─────────────────────────────────────────────────────


_SUPPLY_STATUSES = {"enhanced", "listed"}


def _style_gap_score(sig: TrendSignal, library: List[NailStyleStoreItem]) -> float:
    """
    Market saturation gap score (0-100). High = low competition / large opportunity.

    Formula:
        coverage  = number of library items that share ≥1 tag with this trend
        max_overlap = best tag-overlap fraction across all library items (0-1)

        gap = (1 - saturation_weight) * 100

        saturation_weight = 0.5 * (coverage / len(library))
                          + 0.5 * max_overlap

    Interpretation:
        100 → no library item covers any trend tag  (pure white-space)
        0   → multiple library items cover all tags  (fully saturated)

    Why two sub-terms?
        coverage_ratio  — how MANY styles compete in this space
        max_overlap     — how WELL the best competitor covers this trend
    """
    sig_tags = set(sig.style_tags or [])
    if not sig_tags:
        return 50.0  # unknown tags: neutral
    library = [item for item in library if item.status in _SUPPLY_STATUSES]
    if not library:
        return 100.0

    coverage = sum(1 for item in library if sig_tags & set(item.style_tags or []))
    max_overlap = max(
        (len(sig_tags & set(item.style_tags or [])) / len(sig_tags) for item in library),
        default=0.0,
    )

    saturation = 0.5 * (coverage / len(library)) + 0.5 * max_overlap
    return round((1 - saturation) * 100, 1)


# ── Priority combiner ──────────────────────────────────────────────────────────


def _priority_score(heat: float, freshness: float, gap: float) -> float:
    """
    Weighted combination → launch priority (0-100).

    Weights reflect business intent:
      heat      0.45  — signals real consumer demand right now
      freshness 0.30  — prefer acting on emerging trends before they peak
      gap       0.25  — reward under-served niches, but not over-indexed vs demand

    See docs/scoring_formulas.md § Priority for rationale.
    """
    return round(heat * 0.45 + freshness * 0.30 + gap * 0.25, 1)


# ── Public entry point ─────────────────────────────────────────────────────────


def evaluate(
    analysis: TrendAnalysisResult,
    library: List[NailStyleStoreItem],
) -> ValueEvaluationResult:
    all_signals = list(analysis.top_10)  # already ranked by composite score
    snapshots: List[MetricSnapshot] = []

    for sig in all_signals:
        heat = _heat_score(sig, all_signals)
        freshness = _freshness_score(sig, all_signals)
        gap = _style_gap_score(sig, library)
        priority = _priority_score(heat, freshness, gap)

        snapshots.append(
            MetricSnapshot(
                trend_id=sig.trend_id,
                keyword=sig.keyword,
                display_label=generate_display_label(sig)
                or sig.display_label
                or sample_label(sig, sig.rank, with_tags=False),
                tag_summary=tag_summary(sig),
                image_url=signal_image_url(sig),
                external_heat_score=heat,
                trend_growth_score=freshness,
                style_gap_score=gap,
                launch_priority_score=priority,
                rank=sig.rank,
            )
        )

    # Re-rank by priority score
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
        library = [NailStyleStoreItem(**item) for item in json.load(f)]
    return evaluate(analysis, library)
