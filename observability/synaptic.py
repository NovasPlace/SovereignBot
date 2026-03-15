"""Sovereign — Observability: Synaptic bridge.

Emits @emit_intent signals from the Planner and Executor to Synaptic —
the intent routing and pre-warm organ. When Sovereign plans a task that
involves code generation, Synaptic can pre-warm Blueprint Forge before
the action executes, reducing latency.

Falls back gracefully if Synaptic is not running.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Optional

log = logging.getLogger("sovereign.observability.synaptic")

SYNAPTIC_URL = "http://localhost:8740"  # Synaptic default port

# Map Sovereign action types to Synaptic intent tags
_ACTION_INTENT_MAP: dict[str, str] = {
    "execute_code":    "code.generation",
    "web_fetch":       "research.fetch",
    "read_file":       "file.read",
    "write_file":      "file.write",
    "send_email":      "communication.email",
    "memory_store":    "memory.write",
    "calendar_event":  "calendar.write",
    "custom":          "custom.action",
}


class SynapticBridge:
    """Emits intent signals to Synaptic for pre-warming downstream organs."""

    def __init__(self, base_url: str = SYNAPTIC_URL) -> None:
        self._base = base_url.rstrip("/")
        self._reachable: Optional[bool] = None

    def emit_intent(
        self,
        action_type: str,
        session_id: str,
        skill_id: str = "",
        payload_summary: str = "",
    ) -> None:
        """Emit an intent signal before an action executes.

        Synaptic uses this to pre-warm relevant organs (e.g. Blueprint Forge
        before code generation tasks).
        """
        intent_tag = _ACTION_INTENT_MAP.get(action_type, "unknown.action")
        self._post("/intents", {
            "organ_id":       "sovereign",
            "session_id":     session_id,
            "timestamp":      time.time(),
            "intent":         intent_tag,
            "action_type":    action_type,
            "skill_id":       skill_id,
            "payload_summary": payload_summary[:100],
        })

    def emit_plan_intent(
        self,
        session_id: str,
        user_message: str,
        action_types: list[str],
    ) -> None:
        """Emit the full plan's intent set before execution starts."""
        self._post("/intents/batch", {
            "organ_id":    "sovereign",
            "session_id":  session_id,
            "timestamp":   time.time(),
            "source":      "planner",
            "user_intent": user_message[:100],
            "action_types": action_types,
            "intent_tags": [_ACTION_INTENT_MAP.get(t, t) for t in action_types],
        })

    def _post(self, path: str, data: dict) -> None:
        try:
            body = json.dumps(data).encode()
            req = urllib.request.Request(
                f"{self._base}{path}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=0.5)  # half-second — never block agent
            if self._reachable is not True:
                log.info("Synaptic connected at %s", self._base)
            self._reachable = True
        except Exception:
            if self._reachable is not False:
                log.debug("Synaptic not reachable — intent signals dropped")
            self._reachable = False


_bridge: Optional[SynapticBridge] = None


def get_synaptic_bridge() -> SynapticBridge:
    global _bridge
    if _bridge is None:
        _bridge = SynapticBridge()
    return _bridge


def emit_intent(action_type: str, session_id: str, **kwargs) -> None:
    """Convenience function for decorator-style use."""
    get_synaptic_bridge().emit_intent(action_type, session_id, **kwargs)
