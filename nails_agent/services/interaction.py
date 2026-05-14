"""
Behavior tracking + real try-on (via ComfyUIClient).

Replaces demo_v1/src/interaction.py — the mock try-on is gone; this service
uploads the user's hand image + the style image to ComfyUI Cloud, runs the
nail try-on workflow, and stores the CDN URL of the result.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from nails_agent.memory.store import MemoryStore
from nails_agent.services.style_library import StyleLibrary
from nails_agent.tools.comfyui_client import ComfyUIClient


EVENT_WEIGHTS = {
    "click": 1,
    "try_on_start": 3,
    "try_on_success": 4,
}

ROOT_DIR = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = Path(
    os.environ.get(
        "NAILS_TRYON_WORKFLOW",
        str(ROOT_DIR / "workflows" / "nail_tryon_klein_9b.json"),
    )
)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class InteractionService:
    def __init__(
        self,
        store: MemoryStore,
        library: StyleLibrary | None = None,
        client: ComfyUIClient | None = None,
    ):
        self.store = store
        self.library = library or StyleLibrary(store)
        self.client = client or ComfyUIClient()

    # ── Behavior tracking ────────────────────────────────────────────────────

    def record_behavior(
        self,
        session_id: str,
        style_id: str,
        event_type: str,
        source_snapshot_id: str | None = None,
    ) -> Dict[str, Any]:
        if event_type not in EVENT_WEIGHTS:
            raise ValueError(f"Unknown event_type: {event_type}")
        event = {
            "event_id": self.store.next_id("behavior_events", "SBE"),
            "session_id": session_id,
            "style_id": style_id,
            "event_type": event_type,
            "source_snapshot_id": source_snapshot_id,
            "event_weight": EVENT_WEIGHTS[event_type],
            "created_at": _now_iso(),
        }
        self.store.put_behavior_event(event)
        return event

    def session_events(self, session_id: str) -> list[Dict[str, Any]]:
        return self.store.list_session_events(session_id)

    def latest_try_on_job(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.store.latest_tryon_job(session_id)

    # ── Try-on (real, via ComfyUI) ───────────────────────────────────────────

    def run_tryon(
        self,
        session_id: str,
        style: Dict[str, Any],
        user_image: Dict[str, Any],
        source_snapshot_id: str | None = None,
        workflow_path: Path | None = None,
    ) -> Dict[str, Any]:
        """Run a real ComfyUI try-on for (style, user_image) and persist the result."""
        self.record_behavior(session_id, style["style_id"], "try_on_start", source_snapshot_id)

        job_id = self.store.next_id("tryon_jobs", "TOJ")
        created_at = _now_iso()
        wf_path = Path(workflow_path) if workflow_path else WORKFLOW_PATH

        # Persist a 'pending' row up-front so the UI can see in-flight state.
        job: Dict[str, Any] = {
            "try_on_job_id": job_id,
            "session_id": session_id,
            "style_id": style["style_id"],
            "user_hand_image_id": user_image["user_hand_image_id"],
            "nail_image_url": style.get("image_url", ""),
            "status": "pending",
            "comfyui_prompt_id": None,
            "request_payload": {"workflow": wf_path.name},
            "result_image_url": None,
            "error_message": None,
            "duration_s": 0.0,
            "created_at": created_at,
            "completed_at": None,
        }
        self.store.put_tryon_job(job)

        t0 = time.time()
        try:
            if not wf_path.exists():
                raise FileNotFoundError(f"Workflow not found: {wf_path}")

            with open(wf_path, encoding="utf-8") as f:
                workflow = json.load(f)

            hand_path = user_image["image_url"]
            style_path = self._resolve_style_image_path(style)
            if not Path(hand_path).exists():
                raise FileNotFoundError(f"Hand image not found: {hand_path}")
            if not style_path or not Path(style_path).exists():
                raise FileNotFoundError(f"Style image not found: {style_path}")

            result = self.client.run_tryon(
                workflow=workflow,
                hand_image_path=str(hand_path),
                style_image_path=str(style_path),
            )

            if result.get("success"):
                job.update(
                    {
                        "status": "success",
                        "result_image_url": result.get("image_url"),
                        "duration_s": result.get("duration_s", round(time.time() - t0, 1)),
                        "completed_at": _now_iso(),
                    }
                )
                self.store.put_tryon_job(job)
                self.record_behavior(
                    session_id, style["style_id"], "try_on_success", source_snapshot_id
                )
            else:
                job.update(
                    {
                        "status": "failed",
                        "error_message": str(result.get("error", "unknown error")),
                        "duration_s": round(time.time() - t0, 1),
                        "completed_at": _now_iso(),
                    }
                )
                self.store.put_tryon_job(job)
        except Exception as exc:
            job.update(
                {
                    "status": "failed",
                    "error_message": f"{type(exc).__name__}: {exc}",
                    "duration_s": round(time.time() - t0, 1),
                    "completed_at": _now_iso(),
                }
            )
            self.store.put_tryon_job(job)

        return job

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _resolve_style_image_path(self, style: Dict[str, Any]) -> str:
        """Resolve relative image_url under repo root or demo_v1/."""
        raw = style.get("image_url", "")
        if not raw:
            return ""
        p = Path(raw)
        if p.is_absolute() and p.exists():
            return str(p)
        # Try a few well-known locations the seed data tends to use.
        for candidate in (
            ROOT_DIR / raw,
            ROOT_DIR / "demo_v1" / raw,
            ROOT_DIR / "demo" / raw,
        ):
            if candidate.exists():
                return str(candidate)
        return raw
