"""
Recommendation scoring (Round 1 + Round 2).

Originally `demo_v1/src/recommendation.py`. The scoring logic is unchanged —
data access now goes through StyleLibrary (SQLite) and MemoryStore instead
of JSON files.
"""

from __future__ import annotations

from collections import defaultdict
from math import sqrt
from typing import Any, Dict, List, Optional, Tuple

from nails_agent.memory.store import MemoryStore
from nails_agent.services.labels import (
    HAND_SHAPE_LABELS,
    SKIN_TONE_LABELS,
)
from nails_agent.services.style_library import StyleLibrary


SIMILAR_HAND_SHAPES = {
    "slender_long": {"narrow_palm"},
    "narrow_palm": {"slender_long"},
    "short_wide": {"square_palm"},
    "square_palm": {"short_wide"},
}

ADJACENT_SKIN_TONES = {
    "cool_fair": {"warm_fair", "natural"},
    "warm_fair": {"cool_fair", "natural", "warm_yellow"},
    "natural": {"cool_fair", "warm_fair", "warm_yellow", "wheat"},
    "warm_yellow": {"warm_fair", "natural", "wheat"},
    "wheat": {"natural", "warm_yellow", "deep"},
    "deep": {"wheat"},
}

COLOR_TEMP_LABELS = {
    "warm": "暖色",
    "cool": "冷色",
    "neutral": "中性色",
    "mixed": "混合色",
    "unknown": "未知",
}

COLOR_FAMILY_LABELS = {
    "red": "红色系",
    "pink": "粉色系",
    "nude": "裸色系",
    "white": "白色系",
    "black": "黑色系",
    "green": "绿色系",
    "blue": "蓝色系",
    "purple": "紫色系",
    "gold_silver": "金银色系",
    "multi": "多色系",
    "unknown": "未知色系",
}

LEVEL_LABELS = {
    "light": "浅明度",
    "medium": "中等",
    "dark": "深明度",
    "low": "低",
    "high": "高",
    "mixed": "混合",
    "unknown": "未知",
}

ADJACENT_COLOR_FAMILIES = {
    "red": {"pink", "nude", "black"},
    "pink": {"red", "nude", "white"},
    "nude": {"pink", "red", "white", "gold_silver"},
    "white": {"nude", "pink", "gold_silver"},
    "black": {"red", "green", "gold_silver"},
    "green": {"black", "nude"},
    "gold_silver": {"white", "nude", "black"},
}

ADJACENT_COLOR_TEMPERATURES = {
    "warm": {"mixed", "neutral"},
    "cool": {"mixed", "neutral"},
    "neutral": {"warm", "cool", "mixed"},
    "mixed": {"warm", "cool", "neutral"},
}

ADJACENT_LEVELS = {
    "light": {"medium"},
    "medium": {"light", "dark", "low", "high"},
    "dark": {"medium"},
    "low": {"medium"},
    "high": {"medium"},
}


# ── Pure helpers (unchanged from V1) ────────────────────────────────────────


def feature_color_name(feature: Dict[str, Any]) -> str:
    return feature.get("primary_color_name") or feature.get("main_color_name") or "未知"


def feature_color_family(feature: Dict[str, Any]) -> str:
    return feature.get("primary_color_family") or "unknown"


def _normalized_vector(vector: Optional[List[Any]]) -> List[float]:
    if not vector:
        return []
    result: List[float] = []
    for raw_value in vector:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            value = 0.0
        result.append(value / 255.0 if abs(value) > 1 else value)
    return result


def _weighted_average_vector(vectors: List[Tuple[List[Any], float]]) -> List[float]:
    usable = [(_normalized_vector(v), w) for v, w in vectors if v and w > 0]
    if not usable:
        return []
    max_len = max(len(v) for v, _ in usable)
    totals = [0.0] * max_len
    total_weight = 0.0
    for vector, weight in usable:
        padded = vector + [0.0] * (max_len - len(vector))
        for index, value in enumerate(padded):
            totals[index] += value * weight
        total_weight += weight
    return [round(value / total_weight, 4) for value in totals]


def _vector_similarity(left: Optional[List[Any]], right: Optional[List[Any]]) -> float:
    lv = _normalized_vector(left)
    rv = _normalized_vector(right)
    if not lv or not rv:
        return 0.0
    max_len = max(len(lv), len(rv))
    lv += [0.0] * (max_len - len(lv))
    rv += [0.0] * (max_len - len(rv))
    distance = sqrt(sum((a - b) ** 2 for a, b in zip(lv, rv)) / max_len)
    return round(max(0.0, 100.0 * (1.0 - min(distance, 1.0))), 1)


def _weighted_category_score(
    value: str,
    weights: Dict[str, float],
    adjacent_values: Optional[Dict[str, set]] = None,
) -> float:
    if not weights:
        return 0.0
    max_weight = max(weights.values()) or 1.0
    exact = weights.get(value, 0.0) / max_weight * 100.0
    adjacent = 0.0
    if adjacent_values:
        adjacent = max(
            (weights.get(av, 0.0) / max_weight * 65.0 for av in adjacent_values.get(value, set())),
            default=0.0,
        )
    return round(max(exact, adjacent), 1)


def _top_label(weights: Dict[str, float], labels: Dict[str, str], limit: int = 2) -> str:
    values = [
        labels.get(v, v)
        for v, _ in sorted(weights.items(), key=lambda item: item[1], reverse=True)[:limit]
        if v and v != "unknown"
    ]
    return "、".join(values) if values else "暂不明确"


def hand_shape_score(user_shape: str, reference_shape: str) -> Tuple[int, str]:
    if user_shape == "unknown" or reference_shape == "unknown":
        return 50, "手型识别不完整，采用中性分"
    if user_shape == reference_shape:
        return 100, "手型完全一致"
    if reference_shape in SIMILAR_HAND_SHAPES.get(user_shape, set()):
        return 70, "手型相近"
    return 35, "手型差异较明显"


def skin_tone_score(
    user_profile: Dict[str, Any], reference_profile: Dict[str, Any]
) -> Tuple[int, str]:
    user_tone = user_profile.get("skin_tone", "unknown")
    ref_tone = reference_profile.get("skin_tone", "unknown")
    user_undertone = user_profile.get("undertone", "unknown")
    ref_undertone = reference_profile.get("undertone", "unknown")

    if user_tone == "unknown" or ref_tone == "unknown":
        return 50, "肤色识别不完整，采用中性分"
    if user_tone == ref_tone:
        return 100, "肤色类别一致"
    if ref_tone in ADJACENT_SKIN_TONES.get(user_tone, set()) and user_undertone == ref_undertone:
        return 75, "肤色相邻且冷暖调一致"
    if ref_tone in ADJACENT_SKIN_TONES.get(user_tone, set()):
        return 60, "肤色相邻"
    if user_undertone == ref_undertone and user_undertone != "unknown":
        return 55, "肤色类别不同但冷暖调一致"
    return 30, "肤色差异较明显"


def _reason_text(
    user_profile: Dict[str, Any],
    ref_profile: Dict[str, Any],
    shape_score: int,
    skin_score: int,
) -> Tuple[List[str], str]:
    tags: List[str] = []
    if shape_score >= 100:
        tags.append("手型一致")
    elif shape_score >= 70:
        tags.append("手型相近")
    if skin_score >= 100:
        tags.append("肤色一致")
    elif skin_score >= 75:
        tags.append("肤色相近")
    elif skin_score >= 55:
        tags.append("冷暖调接近")

    if not tags:
        tags = ["探索款"]

    user_shape = HAND_SHAPE_LABELS.get(user_profile.get("hand_shape", "unknown"), "未知")
    ref_shape = HAND_SHAPE_LABELS.get(ref_profile.get("hand_shape", "unknown"), "未知")
    user_tone = SKIN_TONE_LABELS.get(user_profile.get("skin_tone", "unknown"), "未知")
    ref_tone = SKIN_TONE_LABELS.get(ref_profile.get("skin_tone", "unknown"), "未知")
    return tags, f"你的手型/肤色为{user_shape}、{user_tone}；参考图为{ref_shape}、{ref_tone}。"


# ── Service ─────────────────────────────────────────────────────────────────


class RecommendationService:
    def __init__(self, store: MemoryStore, library: StyleLibrary | None = None):
        self.store = store
        self.library = library or StyleLibrary(store)

    # ── Round 1 ─────────────────────────────────────────────────────────────

    def generate_round1(self, session_id: str, user_profile: Dict[str, Any]) -> Dict[str, Any]:
        styles = self.library.list_styles(try_on_only=True)
        reference_profiles = self.library.reference_profiles()
        features = self.library.features()

        items: List[Dict[str, Any]] = []
        for style in styles:
            ref_id = style.get("reference_hand_profile_id")
            if not ref_id:
                continue
            ref = reference_profiles.get(ref_id)
            if not ref:
                continue
            feature = features.get(style.get("visual_feature_id", ""), {}) or {}

            h_score, _ = hand_shape_score(
                user_profile.get("hand_shape", "unknown"),
                ref.get("hand_shape", "unknown"),
            )
            s_score, _ = skin_tone_score(user_profile, ref)
            total = round(h_score * 0.5 + s_score * 0.5, 1)
            tags, reason = _reason_text(user_profile, ref, h_score, s_score)
            items.append(
                {
                    "rank": 0,
                    "style_id": style["style_id"],
                    "total_score": total,
                    "hand_shape_score": h_score,
                    "skin_tone_score": s_score,
                    "visual_similarity_score": 0,
                    "color_preference_score": 0,
                    "behavior_boost_score": 0,
                    "reason_tags": tags,
                    "reason_text": reason,
                    "primary_color_family": feature_color_family(feature),
                    "primary_color_name": feature_color_name(feature),
                    "main_color_name": feature_color_name(feature),
                    "color_temperature": feature.get("color_temperature", "unknown"),
                    "brightness_level": feature.get("brightness_level", "unknown"),
                    "saturation_level": feature.get("saturation_level", "unknown"),
                }
            )

        items.sort(key=lambda row: row["total_score"], reverse=True)
        for index, item in enumerate(items, start=1):
            item["rank"] = index

        from datetime import datetime

        snapshot = {
            "snapshot_id": self.store.next_id("recommendation_snapshots", "RS"),
            "session_id": session_id,
            "round_no": 1,
            "strategy": "reference_hand_match",
            "items": items,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.store.put_recommendation_snapshot(snapshot)
        return snapshot

    def latest_snapshot(
        self, session_id: str, round_no: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        return self.store.latest_snapshot(session_id, round_no=round_no)

    # ── Round 2 ─────────────────────────────────────────────────────────────

    def _preference_from_events(self, session_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        events = self.store.list_session_events(session_id)
        features = self.library.feature_by_style_id()

        family_weights: Dict[str, float] = defaultdict(float)
        primary_color_weights: Dict[str, float] = defaultdict(float)
        temp_weights: Dict[str, float] = defaultdict(float)
        brightness_weights: Dict[str, float] = defaultdict(float)
        saturation_weights: Dict[str, float] = defaultdict(float)
        style_weights: Dict[str, float] = defaultdict(float)
        weighted_vectors: List[Tuple[List[Any], float]] = []
        source_event_ids: List[str] = []

        for event in events:
            feature = features.get(event["style_id"])
            if not feature:
                continue
            weight = float(event.get("event_weight", 1))
            family_weights[feature_color_family(feature)] += weight
            primary_color_weights[feature_color_name(feature)] += weight
            temp_weights[feature.get("color_temperature", "unknown")] += weight
            brightness_weights[feature.get("brightness_level", "unknown")] += weight
            saturation_weights[feature.get("saturation_level", "unknown")] += weight
            style_weights[event["style_id"]] += weight
            if feature.get("color_vector"):
                weighted_vectors.append((feature["color_vector"], weight))
            source_event_ids.append(event["event_id"])

        preference_vector = _weighted_average_vector(weighted_vectors)
        signals = {
            "family_weights": dict(family_weights),
            "primary_color_weights": dict(primary_color_weights),
            "temp_weights": dict(temp_weights),
            "brightness_weights": dict(brightness_weights),
            "saturation_weights": dict(saturation_weights),
            "style_weights": dict(style_weights),
            "preference_color_vector": preference_vector,
            "source_event_ids": source_event_ids,
        }
        if not source_event_ids:
            return {}, signals

        from datetime import datetime

        preference = {
            "preference_id": self.store.next_id("session_preference_profiles", "SPP"),
            "session_id": session_id,
            "preferred_color_families": [
                {"color_family": k, "weight": round(v, 2)}
                for k, v in sorted(family_weights.items(), key=lambda i: i[1], reverse=True)
            ],
            "preferred_primary_colors": [
                {"primary_color_name": k, "weight": round(v, 2)}
                for k, v in sorted(primary_color_weights.items(), key=lambda i: i[1], reverse=True)
            ],
            "preferred_color_temperatures": [
                {"color_temperature": k, "weight": round(v, 2)}
                for k, v in sorted(temp_weights.items(), key=lambda i: i[1], reverse=True)
            ],
            "preferred_brightness_levels": [
                {"brightness_level": k, "weight": round(v, 2)}
                for k, v in sorted(brightness_weights.items(), key=lambda i: i[1], reverse=True)
            ],
            "preferred_saturation_levels": [
                {"saturation_level": k, "weight": round(v, 2)}
                for k, v in sorted(saturation_weights.items(), key=lambda i: i[1], reverse=True)
            ],
            "preference_color_vector": preference_vector,
            "positive_style_ids": [
                style_id
                for style_id, _ in sorted(style_weights.items(), key=lambda i: i[1], reverse=True)
            ],
            "source_event_ids": source_event_ids,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.store.put_preference_profile(preference)
        return preference, signals

    @staticmethod
    def _visual_similarity_breakdown(
        feature: Dict[str, Any], signals: Dict[str, Any]
    ) -> Dict[str, float]:
        family_score = _weighted_category_score(
            feature_color_family(feature),
            signals["family_weights"],
            ADJACENT_COLOR_FAMILIES,
        )
        palette_score = _vector_similarity(
            feature.get("color_vector", []),
            signals.get("preference_color_vector", []),
        )
        temp_score = _weighted_category_score(
            feature.get("color_temperature", "unknown"),
            signals["temp_weights"],
            ADJACENT_COLOR_TEMPERATURES,
        )
        brightness_score = _weighted_category_score(
            feature.get("brightness_level", "unknown"),
            signals["brightness_weights"],
            ADJACENT_LEVELS,
        )
        saturation_score = _weighted_category_score(
            feature.get("saturation_level", "unknown"),
            signals["saturation_weights"],
            ADJACENT_LEVELS,
        )
        total = round(
            family_score * 0.30
            + palette_score * 0.35
            + temp_score * 0.15
            + brightness_score * 0.10
            + saturation_score * 0.10,
            1,
        )
        return {
            "visual_similarity_score": total,
            "color_family_score": family_score,
            "palette_similarity_score": palette_score,
            "color_temperature_score": temp_score,
            "brightness_score": brightness_score,
            "saturation_score": saturation_score,
        }

    def generate_round2(self, session_id: str) -> Optional[Dict[str, Any]]:
        round1 = self.latest_snapshot(session_id, round_no=1)
        if not round1:
            return None

        preference, signals = self._preference_from_events(session_id)
        if not signals["source_event_ids"]:
            return None

        features = self.library.feature_by_style_id()
        style_weights = signals["style_weights"]
        positive_style_ids = set(preference.get("positive_style_ids", []))
        family_summary = _top_label(signals["family_weights"], COLOR_FAMILY_LABELS)
        temp_summary = _top_label(signals["temp_weights"], COLOR_TEMP_LABELS)
        brightness_summary = _top_label(signals["brightness_weights"], LEVEL_LABELS, limit=1)

        items: List[Dict[str, Any]] = []
        for row in round1["items"]:
            feature = features.get(row["style_id"], {}) or {}
            breakdown = self._visual_similarity_breakdown(feature, signals)
            behavior_boost_score = min(8.0, style_weights.get(row["style_id"], 0.0) * 0.8)
            repeat_penalty_score = 5.0 if row["style_id"] in positive_style_ids else 0.0
            color_preference_score = round(
                breakdown["color_family_score"] * 0.65
                + breakdown["color_temperature_score"] * 0.35,
                1,
            )
            total = round(
                row["total_score"] * 0.40
                + breakdown["visual_similarity_score"] * 0.50
                + behavior_boost_score * 0.10
                - repeat_penalty_score,
                1,
            )
            reason_tags = list(row.get("reason_tags", []))
            if breakdown["visual_similarity_score"] >= 72:
                reason_tags.append("视觉相似")
            if breakdown["color_family_score"] >= 85:
                reason_tags.append("同色系")
            if breakdown["palette_similarity_score"] >= 76:
                reason_tags.append("相似调色板")
            if breakdown["color_temperature_score"] >= 75:
                reason_tags.append("冷暖接近")
            if behavior_boost_score > 0:
                reason_tags.append("偏好来源")
            reason_tags = list(dict.fromkeys(reason_tags))

            primary_name = feature_color_name(feature)
            family_label = COLOR_FAMILY_LABELS.get(feature_color_family(feature), "未知色系")
            temp_label = COLOR_TEMP_LABELS.get(feature.get("color_temperature", "unknown"), "未知")
            reason_text = (
                f"{row['reason_text']} 本轮行为显示你更关注{family_summary}/{temp_summary}/{brightness_summary}款式；"
                f"这款为{primary_name}（{family_label}、{temp_label}），视觉相似度 {breakdown['visual_similarity_score']}。"
            )
            items.append(
                {
                    **row,
                    "rank": 0,
                    "total_score": total,
                    "visual_similarity_score": breakdown["visual_similarity_score"],
                    "color_preference_score": round(color_preference_score, 1),
                    "behavior_boost_score": round(behavior_boost_score, 1),
                    "repeat_penalty_score": round(repeat_penalty_score, 1),
                    "color_family_score": breakdown["color_family_score"],
                    "palette_similarity_score": breakdown["palette_similarity_score"],
                    "color_temperature_score": breakdown["color_temperature_score"],
                    "brightness_score": breakdown["brightness_score"],
                    "saturation_score": breakdown["saturation_score"],
                    "primary_color_family": feature_color_family(feature),
                    "primary_color_name": primary_name,
                    "main_color_name": primary_name,
                    "color_temperature": feature.get("color_temperature", "unknown"),
                    "brightness_level": feature.get("brightness_level", "unknown"),
                    "saturation_level": feature.get("saturation_level", "unknown"),
                    "reason_tags": reason_tags,
                    "reason_text": reason_text,
                }
            )

        items.sort(key=lambda item: item["total_score"], reverse=True)
        for index, item in enumerate(items, start=1):
            item["rank"] = index

        from datetime import datetime

        snapshot = {
            "snapshot_id": self.store.next_id("recommendation_snapshots", "RS"),
            "session_id": session_id,
            "round_no": 2,
            "strategy": "session_visual_similarity_rerank",
            "preference_id": preference["preference_id"],
            "items": items,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.store.put_recommendation_snapshot(snapshot)
        return snapshot
