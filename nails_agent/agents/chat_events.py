"""
Pydantic event types for the Agent Chat UI.

Single-direction event protocol: ChatPipelineRunner emits ChatEvent objects,
the Streamlit layer replays them. UserAction flows the opposite way for the
three interaction points (start / choose / interrupt).

All models are frozen to discourage accidental mutation after emission —
events are append-only history.
"""
from __future__ import annotations

import time
import uuid
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

# ── Phase ─────────────────────────────────────────────────────────────────────

Phase = Literal[
    "idle",
    "plan_review",
    "collecting",
    "trends_review",      # checkpoint after Step 1
    "evaluating",
    "eval_review",        # checkpoint after Step 2 (value eval + asset gen)
    "strategy_building",
    "strategy_review",    # checkpoint after Step 3 (campaign strategy)
    "reporting",
    "done",
    "interrupted",
    "error",
]


# ── Phase-output sub-models (discriminated by `kind`) ─────────────────────────

class TableOutput(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["table"] = "table"
    title: str
    columns: List[str]
    rows: List[List]                       # row-major


class ChartOutput(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["chart"] = "chart"
    title: str
    chart_type: Literal["bar", "radar", "line", "pie"]
    x: List
    y: List
    labels: Optional[List[str]] = None     # used by radar/pie


class MarkdownOutput(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["markdown"] = "markdown"
    title: str
    body: str


class GalleryItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    url: str
    caption: str
    badge: Optional[str] = None            # e.g. "P0", "热度 92"


class ImageGalleryOutput(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["image_gallery"] = "image_gallery"
    title: str
    items: List[GalleryItem]


PhaseOutputData = Union[TableOutput, ChartOutput, MarkdownOutput, ImageGalleryOutput]


# ── Checkpoint sub-models ─────────────────────────────────────────────────────

class FormField(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    label: str
    type: Literal["text", "number", "multiselect"]
    default: Optional[Union[str, int, List[str]]] = None
    options: Optional[List[str]] = None    # for multiselect


class CheckpointChoice(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    label: str
    style: Literal["primary", "secondary", "danger"] = "secondary"
    priority: Literal["P0", "P1"] = "P0"   # only P1 may be auto-approved
    form: Optional[List[FormField]] = None


# ── Top-level payload variants ────────────────────────────────────────────────

class MessagePayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    role: Literal["user", "assistant"]
    text: str
    icon: Optional[str] = None


class ToolCallPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    tool: str                              # e.g. "xhs-mcp.search_feeds"
    args: dict
    status: Literal["running", "ok", "error"]
    duration_ms: Optional[int] = None
    result_summary: Optional[str] = None
    result_data: Optional[dict] = None


class PhaseEnterPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    phase: Phase
    title: str
    elapsed_ms: int


class PhaseOutputPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    phase: Phase
    data: PhaseOutputData = Field(..., discriminator="kind")


class CheckpointPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    phase: Phase
    prompt: str
    choices: List[CheckpointChoice]
    auto_approve_after_s: Optional[int] = None
    auto_approve_choice_id: Optional[str] = None


class ProgressPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    phase: Phase
    text: str
    fraction: Optional[float] = None       # 0-1


class ErrorPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    phase: Phase
    message: str
    recoverable: bool = True
    traceback: Optional[str] = None        # dev-only display


EventPayload = Union[
    MessagePayload,
    ToolCallPayload,
    PhaseEnterPayload,
    PhaseOutputPayload,
    CheckpointPayload,
    ProgressPayload,
    ErrorPayload,
]


# ── Top-level ChatEvent ───────────────────────────────────────────────────────

EventType = Literal[
    "message",
    "tool_call",
    "phase_enter",
    "phase_output",
    "checkpoint",
    "progress",
    "error",
]


class ChatEvent(BaseModel):
    """Append-only history element. UI replays these on every rerun."""
    model_config = ConfigDict(frozen=True)

    type: EventType
    payload: EventPayload
    ts: float = Field(default_factory=time.time)
    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)


# ── User → runner actions ─────────────────────────────────────────────────────

class UserAction(BaseModel):
    """The only three things the UI can tell the runner."""
    model_config = ConfigDict(frozen=True)

    type: Literal["start", "choose", "interrupt"]
    payload: dict = Field(default_factory=dict)
    # start:     {"text": "..."}
    # choose:    {"checkpoint_id": phase, "choice_id": str, "form": dict}
    # interrupt: {}


# ── Convenience constructors ──────────────────────────────────────────────────
# These keep the runner code readable — instead of nesting two model
# constructors per event, the runner just calls `make_message(...)`.

def make_message(role: str, text: str, icon: Optional[str] = None) -> ChatEvent:
    return ChatEvent(
        type="message",
        payload=MessagePayload(role=role, text=text, icon=icon),
    )


def make_tool_call(
    tool: str,
    args: dict,
    status: str = "running",
    duration_ms: Optional[int] = None,
    result_summary: Optional[str] = None,
    result_data: Optional[dict] = None,
) -> ChatEvent:
    return ChatEvent(
        type="tool_call",
        payload=ToolCallPayload(
            tool=tool, args=args, status=status,
            duration_ms=duration_ms,
            result_summary=result_summary,
            result_data=result_data,
        ),
    )


def make_phase_enter(phase: Phase, title: str, elapsed_ms: int = 0) -> ChatEvent:
    return ChatEvent(
        type="phase_enter",
        payload=PhaseEnterPayload(phase=phase, title=title, elapsed_ms=elapsed_ms),
    )


def make_phase_output(phase: Phase, data: PhaseOutputData) -> ChatEvent:
    return ChatEvent(
        type="phase_output",
        payload=PhaseOutputPayload(phase=phase, data=data),
    )


def make_checkpoint(
    phase: Phase,
    prompt: str,
    choices: List[CheckpointChoice],
    auto_approve_after_s: Optional[int] = None,
    auto_approve_choice_id: Optional[str] = None,
) -> ChatEvent:
    return ChatEvent(
        type="checkpoint",
        payload=CheckpointPayload(
            phase=phase, prompt=prompt, choices=choices,
            auto_approve_after_s=auto_approve_after_s,
            auto_approve_choice_id=auto_approve_choice_id,
        ),
    )


def make_progress(phase: Phase, text: str, fraction: Optional[float] = None) -> ChatEvent:
    return ChatEvent(
        type="progress",
        payload=ProgressPayload(phase=phase, text=text, fraction=fraction),
    )


def make_error(
    phase: Phase,
    message: str,
    recoverable: bool = True,
    traceback_text: Optional[str] = None,
) -> ChatEvent:
    return ChatEvent(
        type="error",
        payload=ErrorPayload(
            phase=phase, message=message,
            recoverable=recoverable, traceback=traceback_text,
        ),
    )
