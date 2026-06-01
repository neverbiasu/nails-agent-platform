"""TASK-4: Hand shape fallback tests.

Verifies:
  1. /sessions returns 400 (not 500) for images without hands
  2. Recommendation scoring works with hand_shape="unknown"
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2", reason="cv2 required for hand analysis tests")
np = pytest.importorskip("numpy", reason="numpy required")
mediapipe = pytest.importorskip("mediapipe", reason="mediapipe required")

from PIL import Image
from fastapi.testclient import TestClient

from nails_agent.api.main import app
from nails_agent.memory.store import MemoryStore
from nails_agent.services.recommendation import RecommendationService, hand_shape_score
from nails_agent.services.style_library import StyleLibrary


# ── Unit: scoring with unknown hand shape ──────────────────────────────────


def test_hand_shape_score_unknown_returns_neutral():
    score, reason = hand_shape_score("unknown", "slender_long")
    assert score == 50
    assert "中性" in reason or "不完整" in reason


def test_hand_shape_score_both_unknown():
    score, _ = hand_shape_score("unknown", "unknown")
    assert score == 50


# ── Integration: recommendation with unknown profile ───────────────────────


def _seed_styles(store: MemoryStore, count: int = 5) -> None:
    for i in range(1, count + 1):
        sid = f"TEST_STYLE_{i:03d}"
        hpid = f"HP_REF_{i:03d}"
        vfid = f"VF_{i:03d}"
        store.put_style(
            {
                "style_id": sid,
                "status": "listed",
                "try_on_enabled": True,
                "reference_hand_profile_id": hpid,
                "visual_feature_id": vfid,
            }
        )
        store.put_reference_hand(
            {
                "hand_profile_id": hpid,
                "hand_shape": "slender_long",
                "skin_tone": "natural",
                "undertone": "neutral",
            }
        )
        store.put_visual_feature(
            {
                "visual_feature_id": vfid,
                "style_id": sid,
                "primary_color_family": "red",
                "primary_color_name": "酒红",
            }
        )


def test_round1_works_without_hand_shape(tmp_path: Path):
    store = MemoryStore(db_path=tmp_path / "mem.db")
    _seed_styles(store, count=5)
    svc = RecommendationService(store, StyleLibrary(store))
    result = svc.generate_round1(
        "SESSION_TEST",
        {
            "hand_shape": "unknown",
            "hand_shape_confidence": 0.0,
            "skin_tone": "natural",
            "undertone": "neutral",
        },
    )
    assert result is not None
    assert len(result.get("items", [])) >= 1


# ── API: blank image returns 400 ──────────────────────────────────────────


def test_upload_blank_image_returns_400():
    client = TestClient(app)
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), (255, 255, 255)).save(buf, "PNG")
    buf.seek(0)
    resp = client.post("/sessions", files={"image": ("blank.png", buf, "image/png")})
    assert resp.status_code == 400
    body = resp.json()
    assert "detail" in body


def test_hand_analyze_blank_returns_ok_false():
    client = TestClient(app)
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), (200, 200, 200)).save(buf, "PNG")
    buf.seek(0)
    resp = client.post("/hand/analyze", files={"image": ("blank.png", buf, "image/png")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["hand_shape"] == "unknown"
