"""Sovereign — Observability: Spectra health bridge.

Connects Sovereign to Spectra — the predictive health monitoring organ.
Emits: current health score, active threat signals, circuit breaker state.
Receives: predicted failure warnings from Spectra (via polling).

Falls back gracefully if Spectra is not running.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Optional

log = logging.getLogger("sovereign.observability.spectra")

SPECTRA_URL = "http://localhost:8730"  # Spectra default port


class SpectraBridge:
    """Publishes health signals to Spectra and reads predicted warnings."""

    def __init__(self, base_url: str = SPECTRA_URL, session_id: str = "default") -> None:
        self._base = base_url.rstrip("/")
        self._session_id = session_id
        self._reachable: Optional[bool] = None
        self._health_score: float = 1.0
        self._threat_signals: list[str] = []

    def report_health(
        self,
        score: float,
        signals: Optional[list[str]] = None,
    ) -> None:
        """Push a health report to Spectra (score 0.0-1.0, higher = healthier)."""
        payload = {
            "organ_id":     "sovereign",
            "session_id":   self._session_id,
            "timestamp":    time.time(),
            "health_score": max(0.0, min(1.0, score)),
            "signals":      signals or [],
        }
        self._post("/health", payload)

    def report_threat(self, threat_type: str, detail: str = "") -> None:
        """Report a detected threat to Spectra for pattern analysis."""
        self._threat_signals.append(threat_type)
        payload = {
            "organ_id":    "sovereign",
            "session_id":  self._session_id,
            "timestamp":   time.time(),
            "threat_type": threat_type,
            "detail":      detail[:200],
        }
        self._post("/threats", payload)

    def get_warnings(self) -> list[dict]:
        """Poll Spectra for any predicted failure warnings about this organ."""
        try:
            resp = urllib.request.urlopen(
                f"{self._base}/warnings/sovereign",
                timeout=1.0,
            )
            return json.loads(resp.read())
        except Exception:
            return []

    def _post(self, path: str, data: dict) -> None:
        try:
            body = json.dumps(data).encode()
            req = urllib.request.Request(
                f"{self._base}{path}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=1.0)
            if self._reachable is not True:
                log.info("Spectra connected at %s", self._base)
            self._reachable = True
        except Exception:
            if self._reachable is not False:
                log.debug("Spectra not reachable — health signals buffered locally")
            self._reachable = False


_bridge: Optional[SpectraBridge] = None


def get_spectra_bridge(session_id: str = "default") -> SpectraBridge:
    global _bridge
    if _bridge is None:
        _bridge = SpectraBridge(session_id=session_id)
    return _bridge
