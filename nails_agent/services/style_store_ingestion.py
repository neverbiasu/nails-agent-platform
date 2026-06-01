"""Persist campaign P0/P1 styles into the unified nail style store.

This is the bridge from B-end operation strategy to the C-end nail plaza:
TrendSignal + StyleCard -> nail_styles_store -> visual/reference profiles -> memory.db.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable

from nails_agent.memory.store import MemoryStore
from nails_agent.models.schemas import (
    CampaignStrategyResult,
    HandProfile,
    NailStyleStoreItem,
    TrendAnalysisResult,
    TrendSignal,
)
from nails_agent.services import storage
from nails_agent.services.trend_presentation import signal_image_url, source_title

logger = logging.getLogger(__name__)

LISTING_PRIORITIES = {"P0", "P1"}


def _safe_id(value: str, prefix: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
    normalized = normalized or "UNKNOWN"
    return f"{prefix}_{normalized[:48]}"


def _now() -> str:
    return storage.now_iso()


def _table_path(data_dir: Path, table_name: str) -> Path:
    return data_dir / f"{table_name}.json"


def _read_table(data_dir: Path, table_name: str) -> list[dict[str, Any]]:
    path = _table_path(data_dir, table_name)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    data = json.loads(text)
    return data if isinstance(data, list) else []


def _write_table(data_dir: Path, table_name: str, rows: list[dict[str, Any]]) -> None:
    storage.write_json(_table_path(data_dir, table_name), rows)


def _upsert_table_row(
    data_dir: Path,
    table_name: str,
    key: str,
    item: dict[str, Any],
    *,
    preserve_created_at: bool = True,
) -> None:
    rows = _read_table(data_dir, table_name)
    replaced = False
    for index, row in enumerate(rows):
        if row.get(key) == item.get(key):
            merged = dict(item)
            if preserve_created_at:
                merged["created_at"] = row.get("created_at") or item.get("created_at")
            rows[index] = merged
            replaced = True
            break
    if not replaced:
        rows.append(item)
    _write_table(data_dir, table_name, rows)


def _tags(signal: TrendSignal | None, field: str, fallback: Iterable[str] = ()) -> list[str]:
    values = list(getattr(signal, field, []) or [])
    if values:
        return values
    return [value for value in fallback if value]


def _trend_map(analysis: TrendAnalysisResult) -> dict[str, TrendSignal]:
    return {signal.trend_id: signal for signal in analysis.top_10}


def _priority(card: Any) -> str:
    schedule = getattr(card, "schedule", None)
    return getattr(schedule, "priority", "") or "P2"


def _initial_style_item(card: Any, signal: TrendSignal | None, now: str) -> dict[str, Any]:
    style_id = getattr(card, "style_id", "") or _safe_id(getattr(card, "trend_id", ""), "STYLE")
    image_url = getattr(card, "image_url", "") or (signal_image_url(signal) if signal else "")
    return {
        "style_id": style_id,
        "source_trend_id": getattr(card, "trend_id", "") or (signal.trend_id if signal else None),
        "source_title": source_title(signal, max_len=80)
        if signal
        else getattr(card, "style_name", ""),
        "image_url": image_url,
        "enhanced_image_url": "",
        "source_platform": signal.platform if signal else "trend_generated",
        "is_available_for_try_on": True,
        "reference_hand_profile_id": None,
        "visual_feature_id": None,
        "style_tags": _tags(signal, "style_tags", getattr(card, "style_tags", []) or []),
        "color_tags": _tags(signal, "color_tags"),
        "material_tags": _tags(signal, "material_tags"),
        "scene_tags": _tags(signal, "scene_tags"),
        "shape_tags": [],
        "is_trend_generated": True,
        "status": "candidate",
        "created_at": getattr(card, "created_at", "") or now,
        "updated_at": now,
    }


def _resolve_existing_image(image_url: str) -> Path | None:
    if not image_url:
        return None
    if image_url.startswith(("http://", "https://")):
        return None
    path = storage.image_path(image_url)
    return path if path.exists() else None


def _unknown_reference_profile(style_id: str, hand_profile_id: str, now: str) -> dict[str, Any]:
    return HandProfile(
        hand_profile_id=hand_profile_id,
        owner_type="nail_reference",
        owner_id=style_id,
        hand_shape="unknown",
        hand_shape_confidence=0.0,
        skin_tone="unknown",
        undertone="unknown",
        skin_rgb=[],
        skin_confidence=0.0,
        undertone_confidence=0.0,
        analysis_method="image_unavailable",
        hand_metrics={},
        color_metrics={},
        created_at=now,
    ).model_dump()


def _reference_profile_from_image(
    style_id: str, image_path: Path, hand_profile_id: str, now: str
) -> dict[str, Any]:
    from nails_agent.services.hand_analyzer import analyze_hand_image

    result = analyze_hand_image(image_path)
    if not result.get("ok"):
        profile = _unknown_reference_profile(style_id, hand_profile_id, now)
        profile["analysis_method"] = "mediapipe_opencv_failed"
        profile["hand_metrics"] = {"error": result.get("error", "hand_not_detected")}
        return profile

    return HandProfile(
        hand_profile_id=hand_profile_id,
        owner_type="nail_reference",
        owner_id=style_id,
        hand_shape=result.get("hand_shape", "unknown"),
        hand_shape_confidence=float(result.get("hand_shape_confidence", 0.0) or 0.0),
        skin_tone=result.get("skin_tone", "unknown"),
        undertone=result.get("undertone", "unknown"),
        skin_rgb=list(result.get("median_rgb", []) or []),
        skin_confidence=float(result.get("skin_confidence", 0.0) or 0.0),
        undertone_confidence=float(result.get("undertone_confidence", 0.0) or 0.0),
        analysis_method="mediapipe_opencv",
        hand_metrics=dict(result.get("metrics", {}) or {}),
        color_metrics=dict(result.get("color_metrics", {}) or {}),
        created_at=now,
    ).model_dump()


def _result_summary(result: dict[str, Any]) -> str:
    listed = sum(1 for item in result["styles"] if item["status"] == "listed")
    candidate = sum(1 for item in result["styles"] if item["status"] == "candidate")
    return (
        f"入库 {len(result['styles'])} 款：listed {listed}，candidate {candidate}；"
        f"视觉特征 {result['visual_feature_count']} 条，参考手画像 {result['reference_profile_count']} 条"
    )


def format_ingestion_markdown(result: dict[str, Any]) -> str:
    lines = [
        _result_summary(result),
        "",
        "| 优先级 | style_id | 状态 | 视觉特征 | 参考手画像 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in result["styles"]:
        lines.append(
            "| {priority} | {style_id} | {status} | {visual} | {reference} |".format(
                priority=item["priority"],
                style_id=item["style_id"],
                status=item["status"],
                visual=item.get("visual_feature_id") or "-",
                reference=item.get("reference_hand_profile_id") or "-",
            )
        )
    if result.get("warnings"):
        lines.extend(["", "注意："] + [f"- {warning}" for warning in result["warnings"]])
    return "\n".join(lines)


def ingest_campaign_styles(
    analysis: TrendAnalysisResult,
    campaign: CampaignStrategyResult,
    *,
    memory: MemoryStore | None = None,
    data_dir: str | Path | None = None,
    priorities: set[str] | None = None,
    extract_visual_features: bool = True,
    analyze_reference_hand: bool = True,
) -> dict[str, Any]:
    """Sync P0/P1 campaign cards into JSON stores and memory.db.

    The current demo does not call an image enhancement service yet, so
    enhanced_image_url remains empty and downstream display falls back to image_url.
    """

    data_path = Path(data_dir) if data_dir else storage.DATA_DIR
    data_path.mkdir(parents=True, exist_ok=True)
    memory_store = memory or MemoryStore()
    allowed_priorities = priorities or LISTING_PRIORITIES
    signals = _trend_map(analysis)

    ingested: list[dict[str, Any]] = []
    warnings: list[str] = []
    visual_feature_count = 0
    reference_profile_count = 0
    now = _now()

    logger.info(
        "ingest_campaign_styles: %d cards total, allowed_priorities=%s, data_dir=%s",
        len(campaign.style_cards),
        allowed_priorities,
        data_path,
    )

    for card in campaign.style_cards:
        priority = _priority(card)
        if priority not in allowed_priorities:
            logger.debug(
                "Skipping card %s with priority=%s", getattr(card, "trend_id", "?"), priority
            )
            continue

        signal = signals.get(card.trend_id)
        if signal is None:
            logger.warning(
                "Card trend_id=%s not found in analysis signals (available: %s…)",
                card.trend_id,
                list(signals.keys())[:3],
            )
        style_item = _initial_style_item(card, signal, now)
        style_id = style_item["style_id"]

        logger.info(
            "Ingesting style_id=%s priority=%s image_url=%s",
            style_id,
            priority,
            style_item.get("image_url", ""),
        )

        # Phase 1: write the candidate style as soon as the strategy says P0/P1.
        _upsert_table_row(data_path, "nail_styles_store", "style_id", style_item)

        image_path = _resolve_existing_image(style_item["image_url"])
        visual_feature_id: str | None = None
        reference_hand_profile_id: str | None = None

        if extract_visual_features and image_path:
            try:
                from nails_agent.services.nail_feature_extractor import (  # noqa: PLC0415
                    extract_nail_visual_features,
                )

                visual_feature_id = _safe_id(style_id, "NVF")
                feature = extract_nail_visual_features(
                    image_path,
                    style_id,
                    visual_feature_id=visual_feature_id,
                )
                _upsert_table_row(data_path, "nail_visual_features", "visual_feature_id", feature)
                memory_store.put_visual_feature(feature)
                visual_feature_count += 1

                # Use nail_shape_tag already computed inside extract_nail_visual_features
                # (same Roboflow crop — no extra API call needed)
                shape_tag = feature.get("nail_shape_tag", "")
                if shape_tag and shape_tag not in (style_item.get("shape_tags") or []):
                    style_item.setdefault("shape_tags", []).append(shape_tag)
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                warnings.append(f"{style_id}: 视觉特征提取失败，原因：{exc}")
        elif extract_visual_features:
            warnings.append(f"{style_id}: 未找到本地图片，暂未生成视觉特征")

        if analyze_reference_hand:
            reference_hand_profile_id = _safe_id(style_id, "RHP")
            try:
                if image_path:
                    profile = _reference_profile_from_image(
                        style_id,
                        image_path,
                        reference_hand_profile_id,
                        now,
                    )
                else:
                    profile = _unknown_reference_profile(style_id, reference_hand_profile_id, now)
                _upsert_table_row(data_path, "reference_hand_profiles", "hand_profile_id", profile)
                memory_store.put_reference_hand(profile)
                reference_profile_count += 1
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                warnings.append(f"{style_id}: 参考手画像生成失败，原因：{exc}")
                reference_hand_profile_id = None

        # Phase 2: fill the remaining linkage fields and make the style C-end visible
        # once at least the nail visual feature is available.
        style_item.update(
            {
                "visual_feature_id": visual_feature_id,
                "reference_hand_profile_id": reference_hand_profile_id,
                "status": "listed" if visual_feature_id else "candidate",
                "updated_at": _now(),
            }
        )
        try:
            style_item = NailStyleStoreItem(**style_item).model_dump()
        except Exception as exc:
            logger.warning("NailStyleStoreItem validation failed for %s: %s", style_id, exc)
            # keep the raw dict so we still write back updated linkage fields
        _upsert_table_row(data_path, "nail_styles_store", "style_id", style_item)
        memory_store.put_style(style_item)

        ingested.append(
            {
                "style_id": style_id,
                "source_trend_id": style_item.get("source_trend_id"),
                "priority": priority,
                "status": style_item["status"],
                "image_url": style_item.get("image_url", ""),
                "visual_feature_id": visual_feature_id,
                "reference_hand_profile_id": reference_hand_profile_id,
            }
        )

    result = {
        "summary": "",
        "styles": ingested,
        "visual_feature_count": visual_feature_count,
        "reference_profile_count": reference_profile_count,
        "warnings": warnings,
        "data_dir": str(data_path),
    }
    result["summary"] = _result_summary(result)
    return result
