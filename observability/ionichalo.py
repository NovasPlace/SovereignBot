"""Sovereign — Observability: IonicHalo bridge.

Publishes Sovereign health pulses to IonicHalo — the organism bus.
This makes Sovereign a full member of the Sovereign Forge organism
network, allowing other organs to observe and coordinate with it.

Pulse schema matches IonicHalo's standard organ heartbeat format.
Falls back gracefully if IonicHalo is not running.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from typing import Optional

log = logging.getLogger("sovereign.observability.ionichalo")

IONICHALO_URL  = "http://localhost:8710"  # IonicHalo default port
PULSE_INTERVAL = 30.0  # seconds between heartbeats
ORGAN_ID       = "sovereign"
ORGAN_VERSION  = "0.1.0"


class IonicHaloBridge:
    """Publishes Sovereign's health pulses to IonicHalo.

    Runs in a background daemon thread — never blocks the agent loop.
    """

    def __init__(
        self,
        base_url: str = IONICHALO_URL,
        session_id: str = "default",
    ) -> None:
        self._base = base_url.rstrip("/")
        self._session_id = session_id
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._reachable: Optional[bool] = None
        self._metrics: dict = {
            "messages_handled": 0,
            "actions_executed": 0,
            "trust_violations": 0,
            "dna_quarantines": 0,
            "skills_installed": 0,
        }

    def start(self) -> None:
        """Start the background heartbeat thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._pulse_loop,
            daemon=True,
            name="sovereign-ionichalo-bridge",
        )
        self._thread.start()
        log.info("IonicHalo bridge started (target=%s)", self._base)

    def stop(self) -> None:
        self._running = False
        self._send_offline_pulse()

    def increment(self, metric: str, by: int = 1) -> None:
        """Increment a runtime metric counter."""
        if metric in self._metrics:
            self._metrics[metric] += by

    def _pulse_loop(self) -> None:
        while self._running:
            self._send_pulse()
            time.sleep(PULSE_INTERVAL)

    def _send_pulse(self) -> None:
        payload = {
            "organ_id": ORGAN_ID,
            "version":  ORGAN_VERSION,
            "session_id": self._session_id,
            "status": "healthy",
            "timestamp": time.time(),
            "metrics": dict(self._metrics),
            "capabilities": [
                "telegram-channel",
                "llm-planning",
                "action-approval-gate",
                "trust-tier-enforcement",
                "dna-integrity-tokens",
                "credential-vault",
                "skill-registry",
            ],
        }
        self._post("/pulse", payload)

    def _send_offline_pulse(self) -> None:
        payload = {
            "organ_id": ORGAN_ID,
            "status": "offline",
            "timestamp": time.time(),
        }
        self._post("/pulse", payload, timeout=2)

    def _post(self, path: str, data: dict, timeout: float = 3.0) -> bool:
        """POST to IonicHalo. Returns True on success, silent fail otherwise."""
        try:
            body = json.dumps(data).encode()
            req = urllib.request.Request(
                f"{self._base}{path}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=timeout)
            if self._reachable is not True:
                log.info("IonicHalo connected at %s", self._base)
            self._reachable = True
            return True
        except Exception:
            if self._reachable is not False:
                log.info("IonicHalo not reachable at %s — running standalone", self._base)
            self._reachable = False
            return False


_bridge: Optional[IonicHaloBridge] = None


def get_halo_bridge(session_id: str = "default") -> IonicHaloBridge:
    global _bridge
    if _bridge is None:
        _bridge = IonicHaloBridge(session_id=session_id)
    return _bridge
