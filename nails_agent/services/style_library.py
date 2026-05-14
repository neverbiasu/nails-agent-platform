"""
Style library access — reads merged nail_styles_v2 + reference_hand_profiles
+ nail_visual_features from SQLite.

Service-layer wrapper around MemoryStore: callers get plain dicts and don't
need to know which table holds what.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from nails_agent.memory.store import MemoryStore


class StyleLibrary:
    def __init__(self, store: MemoryStore):
        self.store = store

    # ── Styles ──────────────────────────────────────────────────────────────

    def list_styles(
        self,
        *,
        try_on_only: bool = False,
        with_visual_feature_only: bool = False,
    ) -> List[Dict[str, Any]]:
        styles = self.store.list_styles()
        if try_on_only:
            styles = [s for s in styles if s.get("is_available_for_try_on", True)]
        if with_visual_feature_only:
            styles = [s for s in styles if s.get("visual_feature_id")]
        return styles

    def get_style(self, style_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get_style(style_id)

    def style_by_id(self) -> Dict[str, Dict[str, Any]]:
        """Map of style_id → style dict (legacy V1 helper)."""
        return {s["style_id"]: s for s in self.store.list_styles()}

    # ── Reference hand profiles ─────────────────────────────────────────────

    def reference_profiles(self) -> Dict[str, Dict[str, Any]]:
        return {r["hand_profile_id"]: r for r in self.store.list_reference_hands()}

    # ── Visual features ─────────────────────────────────────────────────────

    def features(self) -> Dict[str, Dict[str, Any]]:
        return {f["visual_feature_id"]: f for f in self.store.list_visual_features()}

    def feature_by_style_id(self) -> Dict[str, Dict[str, Any]]:
        """Map style_id → visual_feature for styles that have a feature linked."""
        feats = self.features()
        return {
            s["style_id"]: feats[s["visual_feature_id"]]
            for s in self.store.list_styles()
            if s.get("visual_feature_id") and s["visual_feature_id"] in feats
        }
