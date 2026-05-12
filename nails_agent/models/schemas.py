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
    composite_score: float = 0.0
    rank: int = 0


# ──────────────────────────────────────────────
# Step 1 Output: Trend Analysis
# ──────────────────────────────────────────────

class StyleTrend(BaseModel):
    """A style/color/material/scene tag aggregated across all signals."""
    tag: str                                  # e.g. "猫眼", "法式", "粉色"
    category: str                             # "style" | "color" | "material" | "scene"
    post_count: int                           # how many posts carry this tag
    total_engagement: int                     # sum of likes+collects+shares+comments
    aggregated_score: float                   # 0-100, normalised across all tags
    sample_caption: str = ""                  # one representative post caption


class TrendAnalysisResult(BaseModel):
    top_10: List[TrendSignal]                 # individual posts (evidence)
    style_trends: List[StyleTrend] = []       # aggregated tag trends (the real signal)
    patterns: List[str]                       # e.g. "猫眼+暗黑 跨平台共振"
    anomalies: List[str]                      # e.g. "冰透蓝 近48h增速 +320%"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ──────────────────────────────────────────────
# Step 2a Output: Value Evaluation
# ──────────────────────────────────────────────

class MetricSnapshot(BaseModel):
    metric_id: str = Field(default_factory=lambda: f"M{uuid.uuid4().hex[:6].upper()}")
    trend_id: str
    keyword: str
    external_heat_score: float    # 0-100, from composite_score normalisation
    trend_growth_score: float     # 0-100, captured_at recency bonus
    style_gap_score: float        # 0-100, how underserved in style_library
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
    tier: str = "进阶款"   # 基础款 / 进阶款 / 高端款


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
    priority: str = "P1"                   # P0/P1/P2
    xiaohongshu_publish_at: str = ""
    douyin_publish_at: str = ""
    instagram_publish_at: str = ""


class StyleCard(StyleCardDraft):
    style_id: str = ""
    generation_status: str = "pending"     # pending/success/failed
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
    status: str = "idle"   # idle / running / done / error
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
    produced_by: str           # worker name, e.g. "trend_analyst"
    kind: str                  # "trend" | "metric" | "style_card" | "pattern" | "anomaly" | "summary"
    key: str                   # e.g. trend_id or card_id
    value: str                 # JSON-serialised content
    tags: str = ""             # comma-separated for FTS
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
    nail_shape_tags: List[str] = []
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
    hand_image_b64: Optional[str] = None   # base64 encoded hand image; None = use default


class TryOnResponse(BaseModel):
    success: bool
    image_url: Optional[str] = None
    fallback_url: Optional[str] = None
    error: Optional[str] = None
    duration_s: float = 0.0
