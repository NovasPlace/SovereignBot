"""Sovereign — Primary PostgreSQL persistence store.

Replaces the previous SQLite implementation entirely.
Tables: skills, actions, memories (with FTS via pg_trgm / full-text), config.

Connection: reads SOVEREIGN_DATABASE_URL env var.
Default: postgresql://frost@localhost/sovereign (peer auth — no password).

All connections use a simple connection pool via psycopg2.pool.ThreadedConnectionPool.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Optional

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

log = logging.getLogger("sovereign.store")

_DATABASE_URL = os.environ.get(
    "SOVEREIGN_DATABASE_URL",
    "postgresql:///sovereign",  # Unix socket — peer auth, no password
)

_DDL = """
CREATE TABLE IF NOT EXISTS skills (
    id          TEXT PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    trust_tier  TEXT NOT NULL,
    manifest    JSONB NOT NULL DEFAULT '{}',
    code        TEXT NOT NULL DEFAULT '',
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    installed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS actions (
    action_id   TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    type        TEXT NOT NULL,
    skill_id    TEXT NOT NULL,
    trust_tier  TEXT NOT NULL,
    approved    BOOLEAN,
    approved_by TEXT,
    description TEXT,
    payload     JSONB NOT NULL DEFAULT '{}',
    executed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memories (
    id          SERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL DEFAULT 'default',
    content     TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'agent',
    confidence  REAL NOT NULL DEFAULT 1.0,
    external_flag BOOLEAN NOT NULL DEFAULT FALSE,
    provenance  JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    ts_vector   TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

CREATE INDEX IF NOT EXISTS memories_fts_idx ON memories USING GIN(ts_vector);
CREATE INDEX IF NOT EXISTS memories_session_idx ON memories (session_id);
CREATE INDEX IF NOT EXISTS actions_session_idx ON actions (session_id);

CREATE TABLE IF NOT EXISTS config (
    key     TEXT PRIMARY KEY,
    value   JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_pool: Optional[ThreadedConnectionPool] = None
_pool_lock = threading.Lock()


def _get_pool(dsn: str) -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=dsn)
    return _pool


class _CursorContext:
    """Context manager that yields a psycopg2 cursor, commits on success, rollbacks on error."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn = None
        self._cur = None

    def __enter__(self):
        pool = _get_pool(self._dsn)
        self._conn = pool.getconn()
        self._conn.autocommit = False
        self._cur = self._conn.cursor()
        return self._cur

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                self._conn.rollback()
            else:
                self._conn.commit()
        finally:
            self._cur.close()
            _get_pool(self._dsn).putconn(self._conn)


class SovereignStore:
    """PostgreSQL-backed persistence for Sovereign agent state."""

    def __init__(self, database_url: str = _DATABASE_URL) -> None:
        self._dsn = database_url
        self._init_schema()
        log.info("SovereignStore ready: %s", database_url)

    def _conn(self) -> _CursorContext:
        return _CursorContext(self._dsn)

    def _init_schema(self) -> None:
        with self._conn() as cur:
            cur.execute(_DDL)

    # ── Skills ────────────────────────────────────────────────────────────────

    def save_skill(self, skill_id: str, manifest: dict, code: str) -> None:
        with self._conn() as cur:
            cur.execute("""
                INSERT INTO skills (id, name, trust_tier, manifest, code)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    manifest    = EXCLUDED.manifest,
                    code        = EXCLUDED.code,
                    trust_tier  = EXCLUDED.trust_tier,
                    active      = TRUE,
                    installed_at = now()
            """, (
                skill_id,
                manifest["name"],
                manifest["trust_tier"],
                json.dumps(manifest),
                code,
            ))

    def get_skill(self, name: str) -> Optional[dict]:
        with self._conn() as cur:
            cur.execute(
                "SELECT * FROM skills WHERE name = %s AND active = TRUE",
                (name,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            d = dict(zip(cols, row))
            if isinstance(d["manifest"], str):
                d["manifest"] = json.loads(d["manifest"])
            d["installed_at"] = str(d.get("installed_at", ""))
            return d

    def list_skills(self) -> list[dict]:
        with self._conn() as cur:
            cur.execute(
                "SELECT name, trust_tier, installed_at FROM skills WHERE active = TRUE ORDER BY name"
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur]

    # ── Actions ───────────────────────────────────────────────────────────────

    def save_action(self, action) -> None:
        payload = action.payload if isinstance(action.payload, dict) else {}
        with self._conn() as cur:
            cur.execute("""
                INSERT INTO actions
                    (action_id, session_id, type, skill_id, trust_tier,
                     approved, approved_by, description, payload, executed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, to_timestamp(%s))
                ON CONFLICT (action_id) DO NOTHING
            """, (
                action.action_id,
                getattr(action, "session_id", "default"),
                action.type.value,
                action.skill_id,
                action.trust_tier.value,
                action.approved,
                getattr(action, "approved_by", None),
                action.description,
                json.dumps(payload),
                getattr(action, "executed_at", None),
            ))

    # ── Memories ──────────────────────────────────────────────────────────────

    def save_memory(self, entry) -> None:
        provenance = getattr(entry, "provenance_chain", [])
        with self._conn() as cur:
            cur.execute("""
                INSERT INTO memories
                    (session_id, content, source, confidence, external_flag, provenance)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                getattr(entry, "session_id", "default"),
                entry.content,
                entry.source.value if hasattr(entry.source, "value") else str(entry.source),
                float(getattr(entry, "confidence", 1.0)),
                bool(getattr(entry, "external_flag", False)),
                json.dumps(provenance),
            ))

    def search_memories(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search over memories using PostgreSQL tsvector."""
        with self._conn() as cur:
            cur.execute("""
                SELECT
                    content, source, confidence, external_flag, created_at,
                    ts_rank(ts_vector, plainto_tsquery('english', %s)) AS rank
                FROM memories
                WHERE ts_vector @@ plainto_tsquery('english', %s)
                   OR content ILIKE %s
                ORDER BY rank DESC, created_at DESC
                LIMIT %s
            """, (query, query, f"%{query}%", limit))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur]

    # ── Config ────────────────────────────────────────────────────────────────

    def set_config(self, key: str, value: Any) -> None:
        with self._conn() as cur:
            cur.execute("""
                INSERT INTO config (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """, (key, json.dumps(value)))

    def get_config(self, key: str, default=None) -> Any:
        with self._conn() as cur:
            cur.execute("SELECT value FROM config WHERE key = %s", (key,))
            row = cur.fetchone()
            return row[0] if row else default


_store: Optional[SovereignStore] = None
_store_lock = threading.Lock()


def get_store(database_url: str = _DATABASE_URL) -> SovereignStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SovereignStore(database_url)
    return _store
