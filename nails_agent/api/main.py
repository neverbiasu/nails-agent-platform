"""
FastAPI application — Nails Agent Platform.

Endpoints:
  POST /chat                                          — natural-language trigger for pipeline runs
  POST /pipeline/run                                  — explicit full pipeline trigger
  POST /pipeline/trend                                — step 1 only (trend analysis)
  GET  /pipeline/{id}                                 — pipeline state query
  GET  /pipeline/list                                 — recent pipeline runs
  POST /tryon                                         — (legacy / merchant) ComfyUI try-on
  GET  /styles                                        — style library listing (V2 from SQLite)
  GET  /health                                        — health check

Consumer try-on (V1):
  POST /hand/analyze                                  — analyze a hand photo
  POST /sessions                                      — create a session from an uploaded hand
  GET  /sessions/{id}                                 — fetch session + image + profile
  POST /sessions/{id}/recommendations/round1          — generate round 1 recommendations
  POST /sessions/{id}/recommendations/round2          — generate round 2 (visual-similarity rerank)
  POST /sessions/{id}/events                          — record click / try_on_start / try_on_success
  POST /sessions/{id}/tryon                           — real ComfyUI try-on scoped to session
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import uuid as _uuid

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from nails_agent.models.schemas import (
    ChatRequest,
    ChatResponse,
    TryOnRequest,
    TryOnResponse,
    HandAnalyzeResponse,
    SessionCreateResponse,
    BehaviorEventRequest,
    ConsumerTryOnRequest,
)
from nails_agent.memory.store import MemoryStore
from nails_agent.memory.event_log import EventLog
from nails_agent.agents.orchestrator import PipelineOrchestrator
from nails_agent.agents.trigger_gateway import TriggerGateway
from nails_agent.agents.action_executor import ActionExecutor
from nails_agent.services.style_library import StyleLibrary
from nails_agent.services.session_service import SessionService, annotated_image_b64
from nails_agent.services.recommendation import RecommendationService
from nails_agent.services.interaction import InteractionService

app = FastAPI(
    title="Nails Agent Platform",
    description="AI-powered nail trend analysis and campaign strategy",
    version="0.2.0",
)

_CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "NAILS_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8501,http://localhost:8503",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Singletons ────────────────────────────────────────────────────────────────

_memory: Optional[MemoryStore] = None
_orchestrator: Optional[PipelineOrchestrator] = None
_event_log: Optional[EventLog] = None
_trigger_gateway: Optional[TriggerGateway] = None
_action_executor: Optional[ActionExecutor] = None

DATA_DIR = os.environ.get("NAILS_DATA_DIR", "web/data")
OUTPUT_DIR = os.environ.get("NAILS_OUTPUT_DIR", "web/output")
WORKFLOW_PATH = Path(
    os.environ.get(
        "NAILS_WORKFLOW_PATH",
        "workflows/nail_tryon_klein_9b.json",
    )
)
HAND_REF_PATH = Path(DATA_DIR).parent / "static" / "hand_reference.jpg"
NAIL_REF_PATH = Path(DATA_DIR).parent / "static" / "nail_reference.jpg"


def get_memory() -> MemoryStore:
    global _memory
    if _memory is None:
        _memory = MemoryStore()
    return _memory


def get_orchestrator() -> PipelineOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PipelineOrchestrator(
            memory=get_memory(),
            event_log=get_event_log(),
            data_dir=DATA_DIR,
            output_dir=OUTPUT_DIR,
        )
    return _orchestrator


def get_event_log() -> EventLog:
    global _event_log
    if _event_log is None:
        _event_log = EventLog()
    return _event_log


def get_trigger_gateway() -> TriggerGateway:
    global _trigger_gateway
    if _trigger_gateway is None:
        _trigger_gateway = TriggerGateway(event_log=get_event_log())
    return _trigger_gateway


def get_action_executor() -> ActionExecutor:
    global _action_executor
    if _action_executor is None:
        _action_executor = ActionExecutor(event_log=get_event_log())
    return _action_executor


# ── Consumer-side service singletons ──────────────────────────────────────────

_session_service: Optional[SessionService] = None
_style_library: Optional[StyleLibrary] = None
_recommendation_service: Optional[RecommendationService] = None
_interaction_service: Optional[InteractionService] = None


def get_style_library() -> StyleLibrary:
    global _style_library
    if _style_library is None:
        _style_library = StyleLibrary(get_memory())
    return _style_library


def get_session_service() -> SessionService:
    global _session_service
    if _session_service is None:
        _session_service = SessionService(get_memory())
    return _session_service


def get_recommendation_service() -> RecommendationService:
    global _recommendation_service
    if _recommendation_service is None:
        _recommendation_service = RecommendationService(get_memory(), get_style_library())
    return _recommendation_service


def get_interaction_service() -> InteractionService:
    global _interaction_service
    if _interaction_service is None:
        _interaction_service = InteractionService(get_memory(), get_style_library())
    return _interaction_service


# ══════════════════════════════════════════════════════════════════════════════
# MVP B-end pipeline API  (v1)
# ══════════════════════════════════════════════════════════════════════════════


class TriggerRequest(BaseModel):
    source: str = "manual"
    keywords: List[str] = []
    goal: Optional[str] = None
    shop_data: Dict[str, Any] = {}


class TriggerResponse(BaseModel):
    trigger_id: str
    status: str = "queued"


@app.post("/api/v1/trigger", response_model=TriggerResponse)
async def trigger_pipeline(req: TriggerRequest, background_tasks: BackgroundTasks):
    """Fire a new pipeline run. Returns trigger_id immediately; pipeline runs in background."""
    gw = get_trigger_gateway()
    event = gw.fire(
        source=req.source,
        keywords=req.keywords,
        goal=req.goal,
        shop_data=req.shop_data,
    )
    background_tasks.add_task(get_orchestrator().run_pipeline, event)
    return TriggerResponse(trigger_id=event.trigger_id)


@app.get("/api/v1/events")
async def list_events(trigger_id: str, limit: int = 50, offset: int = 0):
    """Poll EventLog entries for a given trigger_id (for frontend SSE simulation)."""
    entries = get_event_log().list_by_trigger(trigger_id, limit=limit, offset=offset)
    return {"events": [e.model_dump() for e in entries]}


class ReviewApproveRequest(BaseModel):
    trigger_id: str
    decision: str = "pass"  # "pass" | "revise" | "reject"
    note: Optional[str] = None


@app.post("/api/v1/review/approve")
async def review_approve(req: ReviewApproveRequest):
    """HITL confirmation endpoint — merchant confirms review decision before ActionExecutor runs."""
    from nails_agent.models.schemas import ReviewDecision

    el = get_event_log()
    pkg = el.get_candidate(req.trigger_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="CandidatePackage not found for trigger_id")

    human_decision = ReviewDecision(
        status=req.decision,
        reason=req.note or "Human operator approved",
        suggestions=[],
        risk_flags=[],
    )
    el.update_candidate_review(
        req.trigger_id,
        human_decision,
        status="approved" if req.decision == "pass" else "rejected",
    )
    el.write(
        event_type="HumanApprovalEvent",
        payload={"decision": req.decision, "note": req.note},
        trigger_id=req.trigger_id,
        agent_id="HumanOperator",
    )
    return {"ok": True}


class ActionPublishRequest(BaseModel):
    trigger_id: str
    platform: str = "xhs"  # "xhs" | "openclaw"
    artifact: Dict[str, Any] = {}


@app.post("/api/v1/action/publish")
async def action_publish(req: ActionPublishRequest):
    """Execute publish action for an approved CandidatePackage (after HITL confirm)."""
    el = get_event_log()
    pkg = el.get_candidate(req.trigger_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="CandidatePackage not found for trigger_id")

    executor = get_action_executor()
    # Run sync httpx calls in a thread to avoid blocking the async event loop
    action_event = await asyncio.to_thread(executor.publish, pkg, req.platform)
    return {"action_id": action_event.action_id, "status": action_event.status}


# ── Try-on (flat API for Next.js) ─────────────────────────────────────────────
# Simpler than the session-scoped consumer flow — accepts base64 image + style_id

_TRYON_JOB_TTL = int(os.environ.get("NAILS_TRYON_JOB_TTL", 7200))  # seconds (default 2h)

# In-memory write-through cache: {job_id: {status, result_url, _ts, ...}}
# Backed by SQLite via EventLog so jobs survive restarts and are bounded in memory.
_tryon_jobs: Dict[str, Dict[str, Any]] = {}


def _evict_stale_tryon_jobs() -> None:
    """Remove in-memory entries older than TTL (SQLite copy is retained)."""
    cutoff = time.time() - _TRYON_JOB_TTL
    stale = [jid for jid, j in _tryon_jobs.items() if j.get("_ts", 0) < cutoff]
    for jid in stale:
        del _tryon_jobs[jid]


def _persist_tryon_job(job_id: str, data: dict) -> None:
    """Write job state to in-memory cache and EventLog (SQLite)."""
    data.setdefault("_ts", time.time())
    _tryon_jobs[job_id] = data
    get_event_log().write(
        event_type="TryOnJobEvent",
        payload={k: v for k, v in data.items() if not k.startswith("_")},
        trigger_id=job_id,
        agent_id="TryOnWorker",
    )


def _load_tryon_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Cache-first read; falls back to EventLog on cache miss (e.g. after restart)."""
    if job_id in _tryon_jobs:
        return _tryon_jobs[job_id]
    events = get_event_log().list_by_trigger(trigger_id=job_id)
    for evt in reversed(events):
        if evt.event_type == "TryOnJobEvent":
            data = dict(evt.payload)
            data["_ts"] = time.time()  # refresh cache TTL
            _tryon_jobs[job_id] = data
            return data
    return None


class TryOnSubmitRequest(BaseModel):
    image_base64: str
    style_id: str


def _run_tryon_job(job_id: str, image_b64: str, style_id: str) -> None:
    """Background task: run ComfyUI try-on and update job status."""
    import base64
    import tempfile

    _persist_tryon_job(job_id, {"status": "running", "result_url": None, "style_id": style_id})
    hand_path: Optional[str] = None
    try:
        # Decode hand image to a temp file; always cleaned up in finally
        img_bytes = base64.b64decode(image_b64)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(img_bytes)
            hand_path = f.name

        # Resolve style image
        style = get_style_library().get_style(style_id)
        style_path = style.get("image_url", "") if style else ""
        if not style_path or not Path(style_path).exists():
            style_path = str(NAIL_REF_PATH)

        if not WORKFLOW_PATH.exists():
            raise FileNotFoundError(f"Workflow not found: {WORKFLOW_PATH}")

        with open(WORKFLOW_PATH, encoding="utf-8") as f:
            workflow = json.load(f)

        from nails_agent.tools.comfyui_client import ComfyUIClient

        result = ComfyUIClient().run_tryon(
            workflow=workflow,
            hand_image_path=hand_path,
            style_image_path=style_path,
        )
        if result.get("success"):
            _persist_tryon_job(
                job_id,
                {"status": "done", "result_url": result.get("image_url", ""), "style_id": style_id},
            )
        else:
            _persist_tryon_job(
                job_id,
                {"status": "failed", "error": result.get("error", "unknown"), "style_id": style_id},
            )
    except Exception as exc:
        _persist_tryon_job(job_id, {"status": "failed", "error": str(exc), "style_id": style_id})
    finally:
        if hand_path:
            try:
                os.unlink(hand_path)
            except OSError:
                pass


@app.post("/api/v1/tryon/submit")
async def tryon_submit(req: TryOnSubmitRequest, background_tasks: BackgroundTasks):
    """Submit a try-on job. Returns job_id immediately; renders in background."""
    _evict_stale_tryon_jobs()
    job_id = str(_uuid.uuid4())
    _persist_tryon_job(job_id, {"status": "pending", "result_url": None, "style_id": req.style_id})
    background_tasks.add_task(_run_tryon_job, job_id, req.image_base64, req.style_id)
    return {"job_id": job_id}


@app.get("/api/v1/tryon/{job_id}")
async def tryon_status(job_id: str):
    """Poll try-on job status. status: pending|running|done|failed."""
    job = _load_tryon_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Try-on job not found")
    return {k: v for k, v in job.items() if not k.startswith("_")}


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    orch = get_orchestrator()
    sources = orch.source_status()
    return {"status": "ok", "version": "0.2.0", "data_sources": sources}


@app.get("/sources")
async def sources():
    """Check which real data sources are available."""
    orch = get_orchestrator()
    return orch.source_status()


# ── Chat ──────────────────────────────────────────────────────────────────────

_TRIGGER_KEYWORDS = {
    "趋势": "trend",
    "trend": "trend",
    "运营": "full",
    "pipeline": "full",
    "完整": "full",
    "full": "full",
}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, background_tasks: BackgroundTasks):
    msg = req.message.lower()

    action = None
    for kw, act in _TRIGGER_KEYWORDS.items():
        if kw in msg:
            action = act
            break

    if action == "trend":
        orch = get_orchestrator()
        messages = []
        state = orch.run_step1_only(progress_cb=messages.append)
        return ChatResponse(
            reply=f"✅ 趋势分析完成！Top 3：{', '.join(s.keyword for s in (state.trend_analysis.top_10[:3] if state.trend_analysis else []))}",
            pipeline_id=state.pipeline_id,
        )

    if action == "full":
        orch = get_orchestrator()
        messages = []
        state = orch.run(progress_cb=messages.append)
        top3 = state.report.top_3_keywords if state.report else []
        return ChatResponse(
            reply=f"✅ 完整流水线完成！Top 3 关键词：{', '.join(top3)}。共 {state.report.total_style_cards if state.report else 0} 张运营卡片。",
            pipeline_id=state.pipeline_id,
            state={"status": state.status, "step": state.step},
        )

    return ChatResponse(
        reply="你好！发送「趋势分析」运行 Step 1，发送「完整运营」运行全流水线。",
    )


# ── Pipeline endpoints ────────────────────────────────────────────────────────


class PipelineRunResponse(BaseModel):
    pipeline_id: str
    status: str
    message: str
    state: Optional[Dict[str, Any]] = None


@app.post("/pipeline/run", response_model=PipelineRunResponse)
async def pipeline_run():
    orch = get_orchestrator()
    state = orch.run()
    return PipelineRunResponse(
        pipeline_id=state.pipeline_id,
        status=state.status,
        message=f"Pipeline {'完成' if state.status == 'done' else '失败'}",
        state={"step": state.step, "errors": state.errors},
    )


@app.post("/pipeline/trend", response_model=PipelineRunResponse)
async def pipeline_trend():
    orch = get_orchestrator()
    state = orch.run_step1_only()
    return PipelineRunResponse(
        pipeline_id=state.pipeline_id,
        status=state.status,
        message="趋势分析完成" if state.status == "done" else "趋势分析失败",
    )


@app.get("/pipeline/list")
async def pipeline_list(limit: int = 20):
    return get_memory().list_pipeline_runs(limit=limit)


@app.get("/pipeline/{pipeline_id}")
async def pipeline_get(pipeline_id: str):
    result = get_memory().get_pipeline_state(pipeline_id)
    if not result:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return result


# ── Memory search ─────────────────────────────────────────────────────────────


@app.get("/memory/search")
async def memory_search(q: str, kind: Optional[str] = None, limit: int = 10):
    results = get_memory().search(q, kind=kind, limit=limit)
    return [r.model_dump() for r in results]


@app.get("/memory/insights")
async def memory_insights(limit: int = 20):
    results = get_memory().list_recent("insight", limit=limit)
    return [r.model_dump() for r in results]


# ── Style library (V2 from SQLite, with optional legacy passthrough) ──────────


@app.get("/styles")
async def list_styles(
    try_on_only: bool = False,
    with_visual_feature_only: bool = False,
):
    """Unified V2 style library backed by SQLite (`nail_styles_v2`)."""
    return get_style_library().list_styles(
        try_on_only=try_on_only,
        with_visual_feature_only=with_visual_feature_only,
    )


@app.get("/styles/{style_id}")
async def get_style(style_id: str):
    style = get_style_library().get_style(style_id)
    if not style:
        raise HTTPException(status_code=404, detail="Style not found")
    return style


# ── Try-on ────────────────────────────────────────────────────────────────────


@app.post("/tryon", response_model=TryOnResponse)
async def tryon(req: TryOnRequest):
    import time

    t0 = time.time()

    # Resolve style image
    style_path = str(NAIL_REF_PATH)
    lib_path = Path(DATA_DIR) / "style_library.json"
    if lib_path.exists():
        with open(lib_path, encoding="utf-8") as f:
            library = json.load(f)
        for item in library:
            if item.get("style_id") == req.style_id:
                candidate = item.get("image_url", "")
                if candidate and Path(candidate).exists():
                    style_path = candidate
                break

    # Load workflow
    if not WORKFLOW_PATH.exists():
        return TryOnResponse(
            success=False,
            error=f"Workflow not found: {WORKFLOW_PATH}",
            fallback_url=str(NAIL_REF_PATH),
        )

    with open(WORKFLOW_PATH, encoding="utf-8") as f:
        workflow = json.load(f)

    # Run via ComfyUI client
    try:
        from nails_agent.tools.comfyui_client import ComfyUIClient

        client = ComfyUIClient()
        result = client.run_tryon(
            workflow=workflow,
            hand_image_path=str(HAND_REF_PATH),
            style_image_path=style_path,
        )
        return TryOnResponse(
            success=result["success"],
            image_url=result.get("image_url"),
            fallback_url=str(NAIL_REF_PATH),
            error=result.get("error"),
            duration_s=result.get("duration_s", round(time.time() - t0, 1)),
        )
    except Exception as exc:
        return TryOnResponse(
            success=False,
            error=str(exc),
            fallback_url=str(NAIL_REF_PATH),
            duration_s=round(time.time() - t0, 1),
        )


# ══════════════════════════════════════════════════════════════════════════════
# Consumer (V1) endpoints — session-scoped try-on flow
# ══════════════════════════════════════════════════════════════════════════════


@app.post("/hand/analyze", response_model=HandAnalyzeResponse)
async def hand_analyze(image: UploadFile = File(...)):
    """Run MediaPipe + rule-based hand/skin classification on an uploaded image."""
    try:
        from nails_agent.services.hand_analyzer import (
            analyze_hand_image,
            HAND_SHAPE_LABELS,
            SKIN_TONE_LABELS,
            UNDERTONE_LABELS,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Hand analysis unavailable (missing dep): {exc}",
        )

    blob = await image.read()
    try:
        analysis = analyze_hand_image(blob)
    except Exception as exc:
        return HandAnalyzeResponse(ok=False, error=f"{type(exc).__name__}: {exc}")

    return HandAnalyzeResponse(
        ok=analysis["ok"],
        error=analysis.get("error"),
        hand_shape=analysis.get("hand_shape", "unknown"),
        hand_shape_label=HAND_SHAPE_LABELS.get(analysis.get("hand_shape", "unknown"), ""),
        hand_shape_confidence=analysis.get("hand_shape_confidence", 0.0),
        skin_tone=analysis.get("skin_tone", "unknown"),
        skin_tone_label=SKIN_TONE_LABELS.get(analysis.get("skin_tone", "unknown"), ""),
        skin_confidence=analysis.get("skin_confidence", 0.0),
        undertone=analysis.get("undertone", "unknown"),
        undertone_label=UNDERTONE_LABELS.get(analysis.get("undertone", "unknown"), ""),
        undertone_confidence=analysis.get("undertone_confidence", 0.0),
        median_rgb=analysis.get("median_rgb", []),
        metrics=analysis.get("metrics", {}),
        color_metrics=analysis.get("color_metrics", {}),
        annotated_image_b64=annotated_image_b64(analysis) if analysis.get("ok") else "",
    )


@app.post("/sessions", response_model=SessionCreateResponse)
async def create_session(image: UploadFile = File(...)):
    """Create a new try-on session from an uploaded hand image."""
    try:
        from nails_agent.services.hand_analyzer import analyze_hand_image
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Hand analysis unavailable (missing dep): {exc}",
        )

    blob = await image.read()
    try:
        analysis = analyze_hand_image(blob)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Analysis failed: {exc}")

    if not analysis["ok"]:
        raise HTTPException(status_code=400, detail=analysis.get("error", "Hand not detected"))

    created = get_session_service().create_session_from_analysis(
        analysis, source_name=image.filename or "upload.png"
    )
    # Eagerly generate Round 1 so a fresh session has recommendations immediately.
    get_recommendation_service().generate_round1(
        created["session"]["session_id"], created["hand_profile"]
    )
    return SessionCreateResponse(**created)


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    svc = get_session_service()
    session = svc.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session": session,
        "user_image": svc.session_user_image(session_id),
        "hand_profile": svc.session_hand_profile(session_id),
    }


@app.post("/sessions/{session_id}/recommendations/round1")
async def session_round1(session_id: str):
    svc = get_session_service()
    profile = svc.session_hand_profile(session_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Session or hand profile not found")
    return get_recommendation_service().generate_round1(session_id, profile)


@app.post("/sessions/{session_id}/recommendations/round2")
async def session_round2(session_id: str):
    snap = get_recommendation_service().generate_round2(session_id)
    if snap is None:
        raise HTTPException(
            status_code=400,
            detail="Round 2 needs at least one behavior event (click or try-on) first.",
        )
    return snap


@app.get("/sessions/{session_id}/recommendations/latest")
async def session_latest_snapshot(session_id: str, round_no: Optional[int] = None):
    snap = get_recommendation_service().latest_snapshot(session_id, round_no=round_no)
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshot for this session")
    return snap


@app.post("/sessions/{session_id}/events")
async def session_event(session_id: str, event: BehaviorEventRequest):
    return get_interaction_service().record_behavior(
        session_id=session_id,
        style_id=event.style_id,
        event_type=event.event_type,
        source_snapshot_id=event.source_snapshot_id,
    )


@app.get("/sessions/{session_id}/events")
async def session_events_list(session_id: str):
    return get_interaction_service().session_events(session_id)


@app.post("/sessions/{session_id}/tryon")
async def session_tryon(session_id: str, req: ConsumerTryOnRequest):
    svc = get_session_service()
    user_image = svc.session_user_image(session_id)
    if not user_image:
        raise HTTPException(status_code=404, detail="Session image not found")
    style = get_style_library().get_style(req.style_id)
    if not style:
        raise HTTPException(status_code=404, detail="Style not found")
    job = get_interaction_service().run_tryon(
        session_id=session_id,
        style=style,
        user_image=user_image,
        source_snapshot_id=req.source_snapshot_id,
    )
    return job


@app.get("/sessions/{session_id}/tryon/latest")
async def session_latest_tryon(session_id: str):
    job = get_interaction_service().latest_try_on_job(session_id)
    if not job:
        raise HTTPException(status_code=404, detail="No try-on jobs yet")
    return job
