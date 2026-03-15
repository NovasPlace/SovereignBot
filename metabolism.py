"""Sovereign — Metabolism Phases: lifecycle operations on the heartbeat.

Registered as heartbeat phases. Each operation checks pulse number and
organism state to decide whether to fire.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .heartbeat import OrganismState
    from .emotion import EmotionEngine

log = logging.getLogger("sovereign.metabolism")


class MetabolismPhases:
    """Collection of lifecycle operations that run on the heartbeat pulse."""

    def __init__(self, emotion: EmotionEngine) -> None:
        self._emotion = emotion

    async def on_pulse(self, pulse: int, state: "OrganismState") -> None:
        """Main dispatch — called every heartbeat pulse (10s)."""
        from .heartbeat import OrganismState

        # ── EVERY 10th PULSE (100s) — emotional metabolism ──
        if pulse % 10 == 0:
            self._emotion.compute()
            log.debug("Emotion computed: mood=%s", self._emotion.mood)

        # ── EVERY 30th PULSE (300s / 5min) — log organism vitals ──
        if pulse % 30 == 0:
            mood = self._emotion.current()
            log.info(
                "Vitals: state=%s mood=%s(%.0f%%) buffer=%d pulse=%d",
                state.value,
                mood["state"],
                mood["confidence"] * 100,
                mood["buffer_size"],
                pulse,
            )

        # ── EVERY 360th PULSE (3600s / 1hr) — deep maintenance ──
        if pulse % 360 == 0:
            log.info("Hourly maintenance pulse (placeholder)")
