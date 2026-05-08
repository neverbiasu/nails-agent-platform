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
            row = conn.execute(
                "SELECT * FROM memory WHERE entry_id = ?", (entry_id,)
            ).fetchone()
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
