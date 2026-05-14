"""
L2 Memory Store — SQLite + FTS5.

Stores structured outputs from each pipeline step with provenance tracking.
Supports full-text search across tags/values and pipeline-scoped queries.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from nails_agent.models.schemas import MemoryEntry


_DEFAULT_DB_PATH = Path.home() / ".nails_agent" / "memory.db"


class MemoryStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memory (
                    entry_id    TEXT PRIMARY KEY,
                    pipeline_id TEXT NOT NULL,
                    produced_by TEXT NOT NULL,
                    kind        TEXT NOT NULL,
                    key         TEXT NOT NULL,
                    value       TEXT NOT NULL,
                    tags        TEXT DEFAULT '',
                    created_at  TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_memory_pipeline
                    ON memory (pipeline_id);
                CREATE INDEX IF NOT EXISTS idx_memory_kind
                    ON memory (kind);
                CREATE INDEX IF NOT EXISTS idx_memory_produced_by
                    ON memory (produced_by);

                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                    USING fts5(entry_id UNINDEXED, key, value, tags, content=memory, content_rowid=rowid);

                CREATE TRIGGER IF NOT EXISTS memory_fts_insert
                    AFTER INSERT ON memory BEGIN
                        INSERT INTO memory_fts(rowid, entry_id, key, value, tags)
                        VALUES (new.rowid, new.entry_id, new.key, new.value, new.tags);
                    END;

                CREATE TRIGGER IF NOT EXISTS memory_fts_delete
                    AFTER DELETE ON memory BEGIN
                        INSERT INTO memory_fts(memory_fts, rowid, entry_id, key, value, tags)
                        VALUES ('delete', old.rowid, old.entry_id, old.key, old.value, old.tags);
                    END;

                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    pipeline_id TEXT PRIMARY KEY,
                    status      TEXT NOT NULL,
                    state_json  TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );

                -- ── Consumer-side tables (try-on session) ──────────────────

                CREATE TABLE IF NOT EXISTS nail_styles_v2 (
                    style_id   TEXT PRIMARY KEY,
                    data_json  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reference_hand_profiles (
                    hand_profile_id  TEXT PRIMARY KEY,
                    owner_id         TEXT,
                    data_json        TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS nail_visual_features (
                    visual_feature_id  TEXT PRIMARY KEY,
                    style_id           TEXT,
                    data_json          TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_sessions (
                    session_id  TEXT PRIMARY KEY,
                    status      TEXT NOT NULL,
                    data_json   TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    closed_at   TEXT
                );

                CREATE TABLE IF NOT EXISTS user_hand_images (
                    user_hand_image_id  TEXT PRIMARY KEY,
                    session_id          TEXT NOT NULL,
                    data_json           TEXT NOT NULL,
                    created_at          TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_uhi_session ON user_hand_images (session_id);

                CREATE TABLE IF NOT EXISTS user_hand_profiles (
                    hand_profile_id  TEXT PRIMARY KEY,
                    session_id       TEXT NOT NULL,
                    data_json        TEXT NOT NULL,
                    created_at       TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_uhp_session ON user_hand_profiles (session_id);

                CREATE TABLE IF NOT EXISTS recommendation_snapshots (
                    snapshot_id  TEXT PRIMARY KEY,
                    session_id   TEXT NOT NULL,
                    round_no     INTEGER NOT NULL,
                    data_json    TEXT NOT NULL,
                    created_at   TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rs_session
                    ON recommendation_snapshots (session_id, round_no);

                CREATE TABLE IF NOT EXISTS behavior_events (
                    event_id     TEXT PRIMARY KEY,
                    session_id   TEXT NOT NULL,
                    style_id     TEXT NOT NULL,
                    event_type   TEXT NOT NULL,
                    data_json    TEXT NOT NULL,
                    created_at   TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_be_session
                    ON behavior_events (session_id, created_at);

                CREATE TABLE IF NOT EXISTS session_preference_profiles (
                    preference_id  TEXT PRIMARY KEY,
                    session_id     TEXT NOT NULL,
                    data_json      TEXT NOT NULL,
                    created_at     TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_spp_session
                    ON session_preference_profiles (session_id);

                CREATE TABLE IF NOT EXISTS tryon_jobs (
                    try_on_job_id  TEXT PRIMARY KEY,
                    session_id     TEXT NOT NULL,
                    style_id       TEXT NOT NULL,
                    status         TEXT NOT NULL,
                    data_json      TEXT NOT NULL,
                    created_at     TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_toj_session
                    ON tryon_jobs (session_id, created_at);
            """)

    # ── Write ────────────────────────────────────────────────────────────────

    def save(self, entry: MemoryEntry) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO memory
                   (entry_id, pipeline_id, produced_by, kind, key, value, tags, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.entry_id,
                    entry.pipeline_id,
                    entry.produced_by,
                    entry.kind,
                    entry.key,
                    entry.value,
                    entry.tags,
                    entry.created_at,
                ),
            )

    def save_many(self, entries: List[MemoryEntry]) -> None:
        for e in entries:
            self.save(e)

    def save_pipeline_state(self, pipeline_id: str, status: str, state_json: str) -> None:
        from datetime import datetime

        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO pipeline_runs (pipeline_id, status, state_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(pipeline_id) DO UPDATE SET
                       status=excluded.status,
                       state_json=excluded.state_json,
                       updated_at=excluded.updated_at""",
                (pipeline_id, status, state_json, now, now),
            )

    # ── Read ─────────────────────────────────────────────────────────────────

    def get(self, entry_id: str) -> Optional[MemoryEntry]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM memory WHERE entry_id = ?", (entry_id,)).fetchone()
            return MemoryEntry(**dict(row)) if row else None

    def list_by_pipeline(self, pipeline_id: str, kind: Optional[str] = None) -> List[MemoryEntry]:
        with self._conn() as conn:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM memory WHERE pipeline_id = ? AND kind = ? ORDER BY created_at",
                    (pipeline_id, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memory WHERE pipeline_id = ? ORDER BY created_at",
                    (pipeline_id,),
                ).fetchall()
            return [MemoryEntry(**dict(r)) for r in rows]

    def list_recent(self, kind: str, limit: int = 20) -> List[MemoryEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memory WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
            return [MemoryEntry(**dict(r)) for r in rows]

    def search(self, query: str, kind: Optional[str] = None, limit: int = 20) -> List[MemoryEntry]:
        """Full-text search via FTS5."""
        with self._conn() as conn:
            if kind:
                rows = conn.execute(
                    """SELECT m.* FROM memory m
                       JOIN memory_fts f ON m.entry_id = f.entry_id
                       WHERE memory_fts MATCH ? AND m.kind = ?
                       ORDER BY rank LIMIT ?""",
                    (query, kind, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT m.* FROM memory m
                       JOIN memory_fts f ON m.entry_id = f.entry_id
                       WHERE memory_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (query, limit),
                ).fetchall()
            return [MemoryEntry(**dict(r)) for r in rows]

    def get_pipeline_state(self, pipeline_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_runs WHERE pipeline_id = ?", (pipeline_id,)
            ).fetchone()
            if not row:
                return None
            return {
                "pipeline_id": row["pipeline_id"],
                "status": row["status"],
                "state": json.loads(row["state_json"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    def list_pipeline_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT pipeline_id, status, created_at, updated_at FROM pipeline_runs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Consumer try-on tables (generic JSON CRUD) ───────────────────────────
    #
    # All consumer tables store one Pydantic model per row as JSON. These
    # helpers take/return dicts; service modules can wrap with Pydantic
    # validation as needed.

    def _put_json(
        self,
        table: str,
        pk_col: str,
        pk: str,
        data: Dict[str, Any],
        extra_cols: Optional[Dict[str, Any]] = None,
    ) -> None:
        cols = [pk_col, "data_json"]
        vals: List[Any] = [pk, json.dumps(data, ensure_ascii=False)]
        if extra_cols:
            for k, v in extra_cols.items():
                cols.append(k)
                vals.append(v)
        placeholders = ",".join("?" * len(cols))
        col_str = ",".join(cols)
        # Use INSERT OR REPLACE for idempotent upserts (seed loader, etc.)
        with self._conn() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({placeholders})",
                vals,
            )

    def _get_json(self, table: str, pk_col: str, pk: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT data_json FROM {table} WHERE {pk_col} = ?", (pk,)
            ).fetchone()
            return json.loads(row["data_json"]) if row else None

    def _list_all_json(self, table: str, order_by: str = "rowid") -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(f"SELECT data_json FROM {table} ORDER BY {order_by}").fetchall()
            return [json.loads(r["data_json"]) for r in rows]

    # ── Styles ───────────────────────────────────────────────────────────────

    def put_style(self, style: Dict[str, Any]) -> None:
        self._put_json("nail_styles_v2", "style_id", style["style_id"], style)

    def get_style(self, style_id: str) -> Optional[Dict[str, Any]]:
        return self._get_json("nail_styles_v2", "style_id", style_id)

    def list_styles(self) -> List[Dict[str, Any]]:
        return self._list_all_json("nail_styles_v2", order_by="style_id")

    # ── Reference hand profiles ──────────────────────────────────────────────

    def put_reference_hand(self, profile: Dict[str, Any]) -> None:
        self._put_json(
            "reference_hand_profiles",
            "hand_profile_id",
            profile["hand_profile_id"],
            profile,
            extra_cols={"owner_id": profile.get("owner_id")},
        )

    def get_reference_hand(self, hand_profile_id: str) -> Optional[Dict[str, Any]]:
        return self._get_json("reference_hand_profiles", "hand_profile_id", hand_profile_id)

    def list_reference_hands(self) -> List[Dict[str, Any]]:
        return self._list_all_json("reference_hand_profiles", order_by="hand_profile_id")

    # ── Nail visual features ─────────────────────────────────────────────────

    def put_visual_feature(self, feature: Dict[str, Any]) -> None:
        self._put_json(
            "nail_visual_features",
            "visual_feature_id",
            feature["visual_feature_id"],
            feature,
            extra_cols={"style_id": feature.get("style_id")},
        )

    def get_visual_feature(self, visual_feature_id: str) -> Optional[Dict[str, Any]]:
        return self._get_json("nail_visual_features", "visual_feature_id", visual_feature_id)

    def list_visual_features(self) -> List[Dict[str, Any]]:
        return self._list_all_json("nail_visual_features", order_by="visual_feature_id")

    # ── Sessions ─────────────────────────────────────────────────────────────

    def put_session(self, session: Dict[str, Any]) -> None:
        self._put_json(
            "user_sessions",
            "session_id",
            session["session_id"],
            session,
            extra_cols={
                "status": session.get("status", "active"),
                "created_at": session.get("created_at"),
                "closed_at": session.get("closed_at"),
            },
        )

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._get_json("user_sessions", "session_id", session_id)

    def list_sessions(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT data_json FROM user_sessions WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT data_json FROM user_sessions ORDER BY created_at DESC"
                ).fetchall()
            return [json.loads(r["data_json"]) for r in rows]

    def close_active_sessions(self, closed_at: str, reason: str = "new_upload") -> None:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT session_id, data_json FROM user_sessions WHERE status = 'active'"
            ).fetchall()
            for r in rows:
                data = json.loads(r["data_json"])
                data["status"] = "closed"
                data["closed_at"] = closed_at
                data["reset_reason"] = reason
                conn.execute(
                    "UPDATE user_sessions SET status=?, closed_at=?, data_json=? WHERE session_id=?",
                    ("closed", closed_at, json.dumps(data, ensure_ascii=False), r["session_id"]),
                )

    def latest_active_session(self) -> Optional[Dict[str, Any]]:
        sessions = self.list_sessions(status="active")
        return sessions[0] if sessions else None

    # ── User hand image & profile (per session) ──────────────────────────────

    def put_user_hand_image(self, img: Dict[str, Any]) -> None:
        self._put_json(
            "user_hand_images",
            "user_hand_image_id",
            img["user_hand_image_id"],
            img,
            extra_cols={
                "session_id": img["session_id"],
                "created_at": img.get("uploaded_at"),
            },
        )

    def get_session_user_image(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT data_json FROM user_hand_images
                   WHERE session_id = ? ORDER BY created_at DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
            return json.loads(row["data_json"]) if row else None

    def put_user_hand_profile(self, profile: Dict[str, Any]) -> None:
        self._put_json(
            "user_hand_profiles",
            "hand_profile_id",
            profile["hand_profile_id"],
            profile,
            extra_cols={
                "session_id": profile["session_id"],
                "created_at": profile.get("created_at"),
            },
        )

    def get_session_hand_profile(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT data_json FROM user_hand_profiles
                   WHERE session_id = ? ORDER BY created_at DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
            return json.loads(row["data_json"]) if row else None

    # ── Recommendations ──────────────────────────────────────────────────────

    def put_recommendation_snapshot(self, snap: Dict[str, Any]) -> None:
        self._put_json(
            "recommendation_snapshots",
            "snapshot_id",
            snap["snapshot_id"],
            snap,
            extra_cols={
                "session_id": snap["session_id"],
                "round_no": snap["round_no"],
                "created_at": snap.get("created_at"),
            },
        )

    def latest_snapshot(
        self, session_id: str, round_no: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            if round_no is not None:
                row = conn.execute(
                    """SELECT data_json FROM recommendation_snapshots
                       WHERE session_id = ? AND round_no = ?
                       ORDER BY created_at DESC LIMIT 1""",
                    (session_id, round_no),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT data_json FROM recommendation_snapshots
                       WHERE session_id = ?
                       ORDER BY created_at DESC LIMIT 1""",
                    (session_id,),
                ).fetchone()
            return json.loads(row["data_json"]) if row else None

    def list_session_snapshots(self, session_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT data_json FROM recommendation_snapshots
                   WHERE session_id = ? ORDER BY created_at""",
                (session_id,),
            ).fetchall()
            return [json.loads(r["data_json"]) for r in rows]

    # ── Behavior events ──────────────────────────────────────────────────────

    def put_behavior_event(self, event: Dict[str, Any]) -> None:
        self._put_json(
            "behavior_events",
            "event_id",
            event["event_id"],
            event,
            extra_cols={
                "session_id": event["session_id"],
                "style_id": event["style_id"],
                "event_type": event["event_type"],
                "created_at": event.get("created_at"),
            },
        )

    def list_session_events(self, session_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT data_json FROM behavior_events
                   WHERE session_id = ? ORDER BY created_at""",
                (session_id,),
            ).fetchall()
            return [json.loads(r["data_json"]) for r in rows]

    # ── Preference profiles ──────────────────────────────────────────────────

    def put_preference_profile(self, pref: Dict[str, Any]) -> None:
        self._put_json(
            "session_preference_profiles",
            "preference_id",
            pref["preference_id"],
            pref,
            extra_cols={
                "session_id": pref["session_id"],
                "created_at": pref.get("created_at"),
            },
        )

    def list_session_preferences(self, session_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT data_json FROM session_preference_profiles
                   WHERE session_id = ? ORDER BY created_at""",
                (session_id,),
            ).fetchall()
            return [json.loads(r["data_json"]) for r in rows]

    # ── Try-on jobs ──────────────────────────────────────────────────────────

    def put_tryon_job(self, job: Dict[str, Any]) -> None:
        self._put_json(
            "tryon_jobs",
            "try_on_job_id",
            job["try_on_job_id"],
            job,
            extra_cols={
                "session_id": job["session_id"],
                "style_id": job["style_id"],
                "status": job["status"],
                "created_at": job.get("created_at"),
            },
        )

    def latest_tryon_job(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT data_json FROM tryon_jobs
                   WHERE session_id = ? ORDER BY created_at DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
            return json.loads(row["data_json"]) if row else None

    # ── ID generation (sequence-based, replaces V1's next_id) ────────────────

    def next_id(self, table: str, prefix: str) -> str:
        with self._conn() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            n = (row["n"] if row else 0) + 1
            return f"{prefix}{n:03d}"

    # ── Distill (memory consolidation) ───────────────────────────────────────

    def distill(self, pipeline_id: str) -> List[MemoryEntry]:
        """
        Consolidate pipeline outputs into durable pattern/insight entries
        that survive across pipeline runs.  Returns newly created entries.
        """
        entries = self.list_by_pipeline(pipeline_id, kind="pattern")
        # Patterns are already stored during trend analysis.
        # Distill promotes them to kind="insight" with cross-run dedup.
        insights: List[MemoryEntry] = []
        with self._conn() as conn:
            for e in entries:
                # Skip if identical content already exists as insight
                existing = conn.execute(
                    "SELECT 1 FROM memory WHERE kind='insight' AND value=? LIMIT 1",
                    (e.value,),
                ).fetchone()
                if not existing:
                    insight = MemoryEntry(
                        pipeline_id=pipeline_id,
                        produced_by="distill",
                        kind="insight",
                        key=e.key,
                        value=e.value,
                        tags=e.tags,
                    )
                    conn.execute(
                        """INSERT INTO memory
                           (entry_id, pipeline_id, produced_by, kind, key, value, tags, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            insight.entry_id,
                            insight.pipeline_id,
                            insight.produced_by,
                            insight.kind,
                            insight.key,
                            insight.value,
                            insight.tags,
                            insight.created_at,
                        ),
                    )
                    insights.append(insight)
        return insights
