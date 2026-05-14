"""
Session, user image, and user hand-profile persistence — SQLite backed.

Originally `demo_v1/src/session_service.py` which wrote JSON files.
"""

from __future__ import annotations

import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

from nails_agent.memory.store import MemoryStore


# Uploaded images & their MediaPipe-annotated copies still need a place on
# disk (browsers/Streamlit need a URL, and ComfyUI needs a path to upload).
# We default to ~/.nails_agent/uploads/ to live alongside memory.db.
UPLOAD_DIR_DEFAULT = Path.home() / ".nails_agent" / "uploads"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_ext(source_name: str) -> str:
    ext = Path(source_name or "").suffix.lower()
    return ext if ext in {".png", ".jpg", ".jpeg", ".webp"} else ".png"


class SessionService:
    def __init__(self, store: MemoryStore, upload_dir: Path | None = None):
        self.store = store
        self.upload_dir = Path(upload_dir) if upload_dir else UPLOAD_DIR_DEFAULT
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    # ── Create ──────────────────────────────────────────────────────────────

    def create_session_from_analysis(
        self,
        analysis: Dict[str, Any],
        source_name: str,
    ) -> Dict[str, Any]:
        """
        Persist a new TryOnSession + user hand image + user HandProfile.

        `analysis` is the dict returned by hand_analyzer.analyze_hand_image().
        It must include `original_image` (PIL.Image) and `annotated_image`.
        """
        now = _now_iso()
        # Close any currently-active session first
        self.store.close_active_sessions(closed_at=now, reason="new_upload")

        session_id = self.store.next_id("user_sessions", "S")
        user_hand_image_id = self.store.next_id("user_hand_images", "UHI")
        hand_profile_id = self.store.next_id("user_hand_profiles", "UHP")

        ext = _safe_ext(source_name)
        image_path = self.upload_dir / f"{user_hand_image_id}{ext}"
        annotated_path = self.upload_dir / f"{user_hand_image_id}_annotated.png"
        analysis["original_image"].save(image_path)
        analysis["annotated_image"].save(annotated_path)

        session = {
            "session_id": session_id,
            "current_user_label": "guest",
            "status": "active",
            "created_at": now,
            "closed_at": None,
            "reset_reason": None,
        }
        user_image = {
            "user_hand_image_id": user_hand_image_id,
            "session_id": session_id,
            "image_url": str(image_path),
            "annotated_image_url": str(annotated_path),
            "image_width": analysis["original_image"].width,
            "image_height": analysis["original_image"].height,
            "uploaded_at": now,
            "analysis_status": "success",
            "source_name": source_name,
        }
        hand_profile = {
            "hand_profile_id": hand_profile_id,
            "owner_type": "user_upload",
            "owner_id": user_hand_image_id,
            "session_id": session_id,
            "hand_shape": analysis["hand_shape"],
            "hand_shape_confidence": analysis.get("hand_shape_confidence", 0.0),
            "skin_tone": analysis["skin_tone"],
            "undertone": analysis["undertone"],
            "skin_rgb": analysis.get("median_rgb", []),
            "skin_confidence": analysis.get("skin_confidence", 0.0),
            "undertone_confidence": analysis.get("undertone_confidence", 0.0),
            "analysis_method": "mediapipe_opencv",
            "hand_metrics": analysis.get("metrics", {}),
            "color_metrics": analysis.get("color_metrics", {}),
            "created_at": now,
        }

        self.store.put_session(session)
        self.store.put_user_hand_image(user_image)
        self.store.put_user_hand_profile(hand_profile)

        return {
            "session": session,
            "user_image": user_image,
            "hand_profile": hand_profile,
        }

    # ── Read ────────────────────────────────────────────────────────────────

    def active_session(self) -> Optional[Dict[str, Any]]:
        s = self.store.latest_active_session()
        if s:
            return s
        sessions = self.store.list_sessions()
        return sessions[0] if sessions else None

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get_session(session_id)

    def session_user_image(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get_session_user_image(session_id)

    def session_hand_profile(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get_session_hand_profile(session_id)


def annotated_image_b64(analysis: Dict[str, Any]) -> str:
    """Encode the MediaPipe-annotated overlay as a PNG-base64 string."""
    img: Image.Image = analysis.get("annotated_image") or analysis.get("original_image")
    if img is None:
        return ""
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
