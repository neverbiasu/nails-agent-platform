"""
All Pydantic schemas for the Nails Agent Platform.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uuid


# ──────────────────────────────────────────────
# Input / Raw Signal
# ──────────────────────────────────────────────


class TrendSignal(BaseModel):
    trend_id: str
    platform: str
    keyword: str
    display_label: str = ""
    source_title: str = ""
    caption: str = ""
    likes: int = 0
    comments: int = 0
    shares: int = 0
    collects: int = 0
    publish_time: str = ""
    captured_at: str = ""
    style_tags: List[str] = []
    color_tags: List[str] = []
    material_tags: List[str] = []
    scene_tags: List[str] = []
    image_urls: List[str] = []
    local_image_paths: List[str] = []
    image_download_status: str = ""
    image_content_type: str = ""
    detail_enriched: bool = False
    source_note_id: str = ""
    tag_source: str = "rules"
    tag_confidence: float = 0.0
    composite_score: float = 0.0
    rank: int = 0


class RejectedTrendCandidate(BaseModel):
    rejection_id: str = Field(default_factory=lambda: f"RJ{uuid.uuid4().hex[:8].upper()}")
    pipeline_id: str = ""
    source_platform: str = "小红书"
    source_note_id: str = ""
    keyword: str = ""
    source_title: str = ""
    caption: str = ""
    style_tags: List[str] = []
    color_tags: List[str] = []
    material_tags: List[str] = []
    scene_tags: List[str] = []
    reason_code: str
    reason_text: str = ""
    interaction_score: float = 0.0
    tag_source: str = ""
    tag_confidence: float = 0.0
    captured_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ──────────────────────────────────────────────
# Step 1 Output: Trend Analysis
# ──────────────────────────────────────────────


class StyleTrend(BaseModel):
    """A style/color/material/scene tag aggregated across all signals."""

    tag: str  # e.g. "猫眼", "法式", "粉色"
    category: str  # "style" | "color" | "material" | "scene"
    post_count: int  # how many posts carry this tag
    total_engagement: int  # sum of likes+collects+shares+comments
    aggregated_score: float  # 0-100, normalised across all tags
    sample_caption: str = ""  # one representative post caption


class TrendAnalysisResult(BaseModel):
    top_10: List[TrendSignal]  # individual posts (evidence)
    style_trends: List[StyleTrend] = []  # aggregated tag trends (the real signal)
    patterns: List[str]  # e.g. "猫眼+暗黑 跨平台共振"
    anomalies: List[str]  # e.g. "冰透蓝 近48h增速 +320%"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ──────────────────────────────────────────────
# Step 2a Output: Value Evaluation
# ──────────────────────────────────────────────


class MetricSnapshot(BaseModel):
    metric_id: str = Field(default_factory=lambda: f"M{uuid.uuid4().hex[:6].upper()}")
    trend_id: str
    keyword: str
    display_label: str = ""
    tag_summary: str = ""
    image_url: str = ""
    external_heat_score: float  # 0-100, from composite_score normalisation
    trend_growth_score: float  # 0-100, captured_at recency bonus
    style_gap_score: float  # 0-100, how underserved in nail_styles_store
    launch_priority_score: float  # weighted average → final score
    rank: int
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ValueEvaluationResult(BaseModel):
    snapshots: List[MetricSnapshot]
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ──────────────────────────────────────────────
# Step 2b Output: Asset / Style Cards Draft
# ──────────────────────────────────────────────


class PlatformVariant(BaseModel):
    caption: str
    hashtags: List[str]


class PricingInfo(BaseModel):
    base_price: str
    premium_price: str = ""
    promo_price: str = ""
    premium_reason: str = ""
    tier: str = "进阶款"  # 基础款 / 进阶款 / 高端款


class StyleCardDraft(BaseModel):
    card_id: str = Field(default_factory=lambda: f"SC{uuid.uuid4().hex[:6].upper()}")
    trend_id: str
    style_name: str
    style_tags: List[str] = []
    image_url: str = ""
    launch_priority_score: float = 0.0
    platform_variants: Dict[str, PlatformVariant] = {}
    pricing: Optional[PricingInfo] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class AssetGenerationResult(BaseModel):
    drafts: List[StyleCardDraft]
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ──────────────────────────────────────────────
# Step 3 Output: Campaign Strategy (final style cards)
# ──────────────────────────────────────────────


class PublishSchedule(BaseModel):
    priority: str = "P1"  # P0/P1/P2
    xiaohongshu_publish_at: str = ""
    douyin_publish_at: str = ""
    instagram_publish_at: str = ""


class StyleCard(StyleCardDraft):
    style_id: str = ""
    generation_status: str = "pending"  # pending/success/failed
    schedule: Optional[PublishSchedule] = None


class CampaignStrategyResult(BaseModel):
    style_cards: List[StyleCard]
    executive_summary: str = ""
    top_3_styles: List[str] = []
    generated_at: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ──────────────────────────────────────────────
# Step 4 Output: Summary Report
# ──────────────────────────────────────────────


class ReportSection(BaseModel):
    title: str
    content: str


class SummaryReport(BaseModel):
    pipeline_id: str
    title: str = "美甲 AI 运营平台 — 智能运营报告"
    sections: List[ReportSection]
    top_3_keywords: List[str] = []
    total_trends_analyzed: int = 0
    total_style_cards: int = 0
    markdown: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ──────────────────────────────────────────────
# Pipeline State (in-memory L1 layer)
# ──────────────────────────────────────────────


class PipelineState(BaseModel):
    pipeline_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "idle"  # idle / running / done / error
    step: int = 0
    trend_analysis: Optional[TrendAnalysisResult] = None
    value_evaluation: Optional[ValueEvaluationResult] = None
    asset_generation: Optional[AssetGenerationResult] = None
    campaign_strategy: Optional[CampaignStrategyResult] = None
    report: Optional[SummaryReport] = None
    errors: List[str] = []
    started_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    finished_at: str = ""
    meta: Dict[str, Any] = {}


# ──────────────────────────────────────────────
# Memory Store Entry (L2 layer)
# ──────────────────────────────────────────────


class MemoryEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    pipeline_id: str
    produced_by: str  # worker name, e.g. "trend_analyst"
    kind: str  # "trend" | "metric" | "style_card" | "pattern" | "anomaly" | "summary"
    key: str  # e.g. trend_id or card_id
    value: str  # JSON-serialised content
    tags: str = ""  # comma-separated for FTS
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ──────────────────────────────────────────────
# Style Library Item
# ──────────────────────────────────────────────


class StyleLibraryItem(BaseModel):
    style_id: str
    style_name: str
    image_url: str = ""
    style_tags: List[str] = []
    color_tags: List[str] = []
    material_tags: List[str] = []
    scene_tags: List[str] = []
    is_trend_generated: bool = False
    created_from_trend_id: Optional[str] = None
    try_on_enabled: bool = True
    created_at: str = ""


# ──────────────────────────────────────────────
# API request/response
# ──────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    pipeline_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    pipeline_id: Optional[str] = None
    state: Optional[Dict[str, Any]] = None


class TryOnRequest(BaseModel):
    style_id: str
    hand_image_b64: Optional[str] = None  # base64 encoded hand image; None = use default


class TryOnResponse(BaseModel):
    success: bool
    image_url: Optional[str] = None
    fallback_url: Optional[str] = None
    error: Optional[str] = None
    duration_s: float = 0.0


# ══════════════════════════════════════════════════════════════════════════
# Consumer-side try-on (extracted from consumer)
# ══════════════════════════════════════════════════════════════════════════

# ── Hand & reference profiles ─────────────────────────────────────────────


class HandProfile(BaseModel):
    """Detected or reference hand profile (shape + skin tone + undertone)."""

    hand_profile_id: str
    owner_type: str  # "user_upload" | "nail_reference"
    owner_id: str  # session image id or reference style id
    session_id: Optional[str] = None
    hand_shape: str = "unknown"  # slender_long | short_wide | square_palm | narrow_palm | unknown
    hand_shape_confidence: float = 0.0
    skin_tone: str = (
        "unknown"  # cool_fair | warm_fair | natural | warm_yellow | wheat | deep | unknown
    )
    undertone: str = "unknown"  # warm | cool | neutral | unknown
    skin_rgb: List[int] = []
    skin_confidence: float = 0.0
    undertone_confidence: float = 0.0
    analysis_method: str = "mediapipe_opencv"  # or "manual_mock"
    hand_metrics: Dict[str, Any] = {}
    color_metrics: Dict[str, Any] = {}
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ── Nail visual feature & style v2 ────────────────────────────────────────


class PaletteEntry(BaseModel):
    color_family: str
    color_name: str
    rgb: List[int]
    ratio: float


class NailVisualFeature(BaseModel):
    visual_feature_id: str
    style_id: str
    primary_color_family: str = "unknown"
    primary_color_name: str = ""
    primary_color_rgb: List[int] = []
    dominant_palette: List[PaletteEntry] = []
    color_temperature: str = "unknown"  # warm | cool | neutral | mixed | unknown
    brightness_level: str = "unknown"  # light | medium | dark | unknown
    saturation_level: str = "unknown"  # low | medium | high | unknown
    contrast_level: str = "unknown"
    color_vector: List[float] = []
    extractor_version: str = "manual_mock_v1_1"
    feature_confidence: float = 0.0
    needs_manual_review: bool = False
    feature_source: str = "manual_seed"
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: Optional[str] = None


class NailStyleStoreItem(BaseModel):
    """Unified nail style store item shared by B-end evaluation and C-end display."""

    style_id: str
    source_trend_id: Optional[str] = None
    source_title: str = ""  # provenance only; not used as the primary display label
    image_url: str = ""  # original/base nail image
    enhanced_image_url: str = ""
    source_platform: str = "internal"  # mock_social | xhs | douyin | internal | trend_generated
    is_available_for_try_on: bool = True

    # V1 linkage
    reference_hand_profile_id: Optional[str] = None  # → HandProfile (owner_type=nail_reference)
    visual_feature_id: Optional[str] = None  # → NailVisualFeature

    # V0 tag fields (kept for backward compat with B-end pipeline)
    style_tags: List[str] = []
    color_tags: List[str] = []
    material_tags: List[str] = []
    scene_tags: List[str] = []
    shape_tags: List[str] = []
    is_trend_generated: bool = False
    status: str = "listed"  # candidate | enhanced | listed | archived

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: Optional[str] = None


# Backward-compatible alias for older imports/docs.
NailStyleV2 = NailStyleStoreItem


# ── Session, recommendations, behavior, jobs ─────────────────────────────


class TryOnSession(BaseModel):
    session_id: str
    current_user_label: str = "guest"
    status: str = "active"  # active | closed
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    closed_at: Optional[str] = None
    reset_reason: Optional[str] = None


class UserHandImage(BaseModel):
    user_hand_image_id: str
    session_id: str
    image_url: str
    annotated_image_url: str = ""
    image_width: int = 0
    image_height: int = 0
    uploaded_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    analysis_status: str = "success"
    source_name: str = ""


class RecommendationItem(BaseModel):
    rank: int
    style_id: str
    total_score: float
    hand_shape_score: float = 0.0
    skin_tone_score: float = 0.0
    visual_similarity_score: float = 0.0
    color_preference_score: float = 0.0
    behavior_boost_score: float = 0.0
    repeat_penalty_score: float = 0.0
    color_family_score: float = 0.0
    palette_similarity_score: float = 0.0
    color_temperature_score: float = 0.0
    brightness_score: float = 0.0
    saturation_score: float = 0.0
    reason_tags: List[str] = []
    reason_text: str = ""
    primary_color_family: str = "unknown"
    primary_color_name: str = ""
    main_color_name: str = ""
    color_temperature: str = "unknown"
    brightness_level: str = "unknown"
    saturation_level: str = "unknown"


class RecommendationSnapshot(BaseModel):
    snapshot_id: str
    session_id: str
    round_no: int  # 1 | 2
    strategy: str  # reference_hand_match | session_visual_similarity_rerank
    preference_id: Optional[str] = None
    items: List[RecommendationItem] = []
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class BehaviorEvent(BaseModel):
    event_id: str
    session_id: str
    style_id: str
    event_type: str  # click | try_on_start | try_on_success
    source_snapshot_id: Optional[str] = None
    event_weight: int = 1
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class SessionPreferenceProfile(BaseModel):
    preference_id: str
    session_id: str
    preferred_color_families: List[Dict[str, Any]] = []
    preferred_primary_colors: List[Dict[str, Any]] = []
    preferred_color_temperatures: List[Dict[str, Any]] = []
    preferred_brightness_levels: List[Dict[str, Any]] = []
    preferred_saturation_levels: List[Dict[str, Any]] = []
    preference_color_vector: List[float] = []
    positive_style_ids: List[str] = []
    source_event_ids: List[str] = []
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class TryOnJob(BaseModel):
    try_on_job_id: str
    session_id: str
    style_id: str
    user_hand_image_id: str
    nail_image_url: str = ""
    status: str = "pending"  # pending | success | failed
    comfyui_prompt_id: Optional[str] = None
    request_payload: Dict[str, Any] = {}
    result_image_url: Optional[str] = None
    error_message: Optional[str] = None
    duration_s: float = 0.0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None


# ── Consumer API request/response ────────────────────────────────────────


class HandAnalyzeResponse(BaseModel):
    ok: bool
    error: Optional[str] = None
    hand_shape: str = "unknown"
    hand_shape_label: str = ""
    hand_shape_confidence: float = 0.0
    skin_tone: str = "unknown"
    skin_tone_label: str = ""
    skin_confidence: float = 0.0
    undertone: str = "unknown"
    undertone_label: str = ""
    undertone_confidence: float = 0.0
    median_rgb: List[int] = []
    metrics: Dict[str, Any] = {}
    color_metrics: Dict[str, Any] = {}
    annotated_image_b64: str = ""  # PNG, base64


class SessionCreateResponse(BaseModel):
    session: TryOnSession
    user_image: UserHandImage
    hand_profile: HandProfile


class BehaviorEventRequest(BaseModel):
    style_id: str
    event_type: str  # click | try_on_start | try_on_success
    source_snapshot_id: Optional[str] = None


class ConsumerTryOnRequest(BaseModel):
    style_id: str
    source_snapshot_id: Optional[str] = None


# ──────────────────────────────────────────────
# MVP Agent Pipeline — Event Log & HITL Models
# ──────────────────────────────────────────────


class TriggerEvent(BaseModel):
    trigger_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str  # "manual" | "scheduled" | "signal"
    keywords: List[str] = []
    goal: Optional[str] = None
    shop_data: Dict[str, Any] = {}
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class EventLogEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str  # TriggerEvent|TrendEvent|StrategyEvent|ReviewEvent|ActionEvent|FeedbackEvent
    trigger_id: Optional[str] = None
    agent_id: Optional[str] = None
    payload: Dict[str, Any] = {}
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class TrendCluster(BaseModel):
    cluster_id: str
    keywords: List[str]
    signals: List[TrendSignal] = []
    top_tags: List[str] = []


class TrendEvent(BaseModel):
    trigger_id: str
    clusters: List[TrendCluster] = []
    top_keywords: List[str] = []
    confidence: float = 0.0


class StrategyEvent(BaseModel):
    trigger_id: str
    strategy_summary: str
    platform_variants: List[Dict[str, Any]] = []
    publish_schedule: Optional[Dict[str, Any]] = None


class CandidatePackage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trigger_id: str
    trend_summary: str
    strategy: str
    assets: List[str] = []
    review_score: float = 0.0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ReviewDecision(BaseModel):
    status: str  # "pass" | "revise" | "reject"
    reason: str
    suggestions: List[str] = []
    risk_flags: List[str] = []


class ActionEvent(BaseModel):
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trigger_id: str
    platform: str  # "xhs" | "openclaw"
    status: str  # "success" | "failed" | "pending"
    result_url: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
