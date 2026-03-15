"""Sovereign — Security: Immutable audit log (PostgreSQL).

Every action, approval, trust violation, and session event is recorded here.
The table is append-only: no UPDATE or DELETE via Sovereign code ever runs here.
PostgreSQL row-level security can be added to enforce this at the DB level.

Uses a separate connection (not the main pool) to ensure audit entries are
committed independently — even if the main transaction rolls back.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from enum import Enum
from typing import Any, Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("sovereign.security.audit")

_DATABASE_URL = os.environ.get(
    "SOVEREIGN_DATABASE_URL",
    "postgresql:///sovereign",  # Unix socket — peer auth
)

_DDL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    event_type  TEXT NOT NULL,
    actor       TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    session_id  TEXT NOT NULL DEFAULT 'default',
    target      TEXT,
    payload     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_log_session_idx   ON audit_log (session_id);
CREATE INDEX IF NOT EXISTS audit_log_event_idx     ON audit_log (event_type);
CREATE INDEX IF NOT EXISTS audit_log_created_idx   ON audit_log (created_at DESC);
"""


class AuditEvent(str, Enum):
    SESSION_START    = "session.start"
    SESSION_END      = "session.end"
    ACTION_PROPOSED  = "action.proposed"
    ACTION_APPROVED  = "action.approved"
    ACTION_REJECTED  = "action.rejected"
    ACTION_EXECUTED  = "action.executed"
    ACTION_FAILED    = "action.failed"
    TRUST_VIOLATION  = "trust.violation"
    DNA_ISSUED       = "dna.issued"
    DNA_VERIFIED     = "dna.verified"
    DNA_BROKEN       = "dna.broken"
    DNA_QUARANTINE   = "dna.quarantine"
    SKILL_INSTALLED  = "skill.installed"
    SKILL_REJECTED   = "skill.rejected"
    INJECTION_DETECT = "injection.detected"
    MEMORY_STORED    = "memory.stored"
    VAULT_UNLOCKED   = "vault.unlocked"
    VAULT_LOCKED     = "vault.locked"


class AuditLog:
    """Append-only audit log backed by PostgreSQL.

    Each log() call uses its own autocommit connection so audit entries
    are committed even if the calling transaction rolls back.
    """

    def __init__(self, database_url: str = _DATABASE_URL) -> None:
        self._dsn = database_url
        self._lock = threading.Lock()
        self._init_schema()
        log.info("AuditLog ready (PostgreSQL)")

    def _connect(self):
        conn = psycopg2.connect(self._dsn)
        conn.autocommit = True  # each write is immediately committed
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_DDL)

    def log(
        self,
        event_type: AuditEvent | str,
        actor: str,
        outcome: str,
        session_id: str = "default",
        target: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> None:
        """Append an immutable audit entry. Never raises — logs errors instead."""
        if isinstance(event_type, AuditEvent):
            event_type = event_type.value

        with self._lock:
            try:
                conn = self._connect()
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO audit_log
                            (event_type, actor, outcome, session_id, target, payload)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        event_type, actor, outcome, session_id,
                        target, json.dumps(payload or {}),
                    ))
                conn.close()
            except Exception as e:
                # Audit must never crash the caller
                log.error("AuditLog write failed: %s", e)

    def query(
        self,
        session_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Read audit entries (for review/reporting only)."""
        try:
            conn = self._connect()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                wheres = []
                params: list = []
                if session_id:
                    wheres.append("session_id = %s")
                    params.append(session_id)
                if event_type:
                    wheres.append("event_type = %s")
                    params.append(event_type)
                where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
                cur.execute(
                    f"SELECT * FROM audit_log {where_clause} ORDER BY created_at DESC LIMIT %s",
                    params + [limit],
                )
                rows = cur.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            log.error("AuditLog query failed: %s", e)
            return []


_audit: Optional[AuditLog] = None
_audit_lock = threading.Lock()


def get_audit() -> AuditLog:
    global _audit
    if _audit is None:
        with _audit_lock:
            if _audit is None:
                _audit = AuditLog()
    return _audit
