"""Sovereign — Observability: TRACE reasoning audit bridge.

Emits every planning decision to TRACE — the reasoning audit organ.
TRACE receives: the user's intent, the plan produced, the reasoning,
what was approved/rejected, and the outcome.

This gives Sovereign a complete causal chain audit log that is
separate from the immutable SQLite log — TRACE adds counterfactual
analysis and reasoning quality scoring on top.

Falls back gracefully if TRACE is not running.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Any, Optional

log = logging.getLogger("sovereign.observability.trace")

TRACE_URL = "http://localhost:8720"  # TRACE daemon default port


class TraceEvent:
    """A single reasoning audit event."""
    __slots__ = ("event_type", "session_id", "timestamp", "payload")

    def __init__(self, event_type: str, session_id: str, payload: dict) -> None:
        self.event_type = event_type
        self.session_id = session_id
        self.timestamp  = time.time()
        self.payload    = payload

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "session_id": self.session_id,
            "timestamp":  self.timestamp,
            "organ":      "sovereign",
            "payload":    self.payload,
        }


class TraceBridge:
    """Emits Sovereign's reasoning decisions to the TRACE organ."""

    def __init__(self, base_url: str = TRACE_URL) -> None:
        self._base = base_url.rstrip("/")
        self._reachable: Optional[bool] = None

    def emit_plan(
        self,
        session_id: str,
        user_message: str,
        actions: list[dict],
        reasoning: str = "",
    ) -> None:
        """Emit a planning event — what the agent decided to do and why."""
        self._emit(TraceEvent(
            event_type="sovereign.plan",
            session_id=session_id,
            payload={
                "user_message": user_message[:200],
                "action_count": len(actions),
                "actions": [
                    {"type": a.get("type"), "skill": a.get("skill_id")}
                    for a in actions
                ],
                "reasoning": reasoning[:300],
            },
        ))

    def emit_action(
        self,
        session_id: str,
        action_id: str,
        action_type: str,
        outcome: str,
        elapsed_ms: int,
        approved_by: str = "",
    ) -> None:
        """Emit an action execution event with outcome and timing."""
        self._emit(TraceEvent(
            event_type="sovereign.action",
            session_id=session_id,
            payload={
                "action_id":   action_id,
                "action_type": action_type,
                "outcome":     outcome,
                "elapsed_ms":  elapsed_ms,
                "approved_by": approved_by,
            },
        ))

    def emit_trust_violation(
        self,
        session_id: str,
        skill_id: str,
        permission: str,
        tier: str,
    ) -> None:
        """Emit a trust violation event — skill exceeded its ceiling."""
        self._emit(TraceEvent(
            event_type="sovereign.trust_violation",
            session_id=session_id,
            payload={
                "skill_id":   skill_id,
                "permission": permission,
                "tier":       tier,
            },
        ))

    def emit_injection_detected(
        self,
        session_id: str,
        source: str,
        modifications: list[str],
    ) -> None:
        """Emit an injection detection event."""
        self._emit(TraceEvent(
            event_type="sovereign.injection_detected",
            session_id=session_id,
            payload={
                "source":        source,
                "modifications": modifications[:5],
            },
        ))

    def _emit(self, event: TraceEvent) -> None:
        """POST event to TRACE. Silent fail if not reachable."""
        try:
            body = json.dumps(event.to_dict()).encode()
            req = urllib.request.Request(
                f"{self._base}/events",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=1.0)  # 1s max — never block agent
            if self._reachable is not True:
                log.info("TRACE connected at %s", self._base)
            self._reachable = True
        except Exception:
            if self._reachable is not False:
                log.debug("TRACE not reachable — events buffered locally only")
            self._reachable = False


_bridge: Optional[TraceBridge] = None


def get_trace_bridge() -> TraceBridge:
    global _bridge
    if _bridge is None:
        _bridge = TraceBridge()
    return _bridge
