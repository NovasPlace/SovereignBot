"""Sovereign — Heartbeat: the organism's pulse.

Runs every 10 seconds regardless of user activity. Drives all background
lifecycle operations: state transitions, memory decay, emotional metabolism,
dream consolidation, oracle checks, proactive outreach.

The heartbeat is not a cron job. It's a living rhythm the organism feels.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import time
from typing import Any, Callable, Coroutine

log = logging.getLogger("sovereign.heartbeat")

PULSE_INTERVAL_SECONDS = 10


class OrganismState(str, enum.Enum):
    """The organism's current lifecycle state."""
    WAKING     = "waking"       # just started or waking from sleep
    AWAKE      = "awake"        # actively in conversation
    IDLE       = "idle"         # no activity for 30s–5min
    RESTING    = "resting"      # no activity for 5–30min
    DREAMING   = "dreaming"     # no activity for 30min–2hr (consolidation active)
    DEEP_SLEEP = "deep_sleep"   # no activity for 2hr+ (minimal processing)


# Idle thresholds in seconds
_STATE_THRESHOLDS = [
    (30,    OrganismState.AWAKE),
    (300,   OrganismState.IDLE),
    (1800,  OrganismState.RESTING),
    (7200,  OrganismState.DREAMING),
]


class Heartbeat:
    """The organism's pulse loop. Registered phases fire on each beat."""

    def __init__(self) -> None:
        self.pulse_count: int = 0
        self.state: OrganismState = OrganismState.WAKING
        self.last_user_activity: float = time.time()
        self._phases: list[Callable[[int, OrganismState], Coroutine]] = []
        self._running: bool = False
        self._task: asyncio.Task | None = None
        self._wake_callbacks: list[Callable[[OrganismState], Coroutine]] = []

    # ── Phase Registration ──────────────────────────────────────────

    def register_phase(self, fn: Callable[[int, OrganismState], Coroutine]) -> None:
        """Register a coroutine that runs on every pulse."""
        self._phases.append(fn)

    def on_wake(self, fn: Callable[[OrganismState], Coroutine]) -> None:
        """Register a coroutine that runs when the organism wakes from sleep."""
        self._wake_callbacks.append(fn)

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self) -> None:
        """Begin the pulse loop. Call from an active event loop."""
        if self._running:
            return
        self._running = True
        self.state = OrganismState.AWAKE
        self._task = asyncio.ensure_future(self._loop())
        log.info("Heartbeat started — pulse every %ds", PULSE_INTERVAL_SECONDS)

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._pulse()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Heartbeat phase error: %s", e)
            await asyncio.sleep(PULSE_INTERVAL_SECONDS)

    async def _pulse(self) -> None:
        self.pulse_count += 1
        self._update_state()

        for phase in self._phases:
            try:
                await phase(self.pulse_count, self.state)
            except Exception as e:
                log.error("Phase %s error: %s", phase.__name__, e)

    # ── State Machine ───────────────────────────────────────────────

    def _update_state(self) -> None:
        idle = time.time() - self.last_user_activity
        new_state = OrganismState.DEEP_SLEEP

        for threshold, st in _STATE_THRESHOLDS:
            if idle < threshold:
                new_state = st
                break

        if new_state != self.state:
            old = self.state
            self.state = new_state
            log.info("Organism state: %s → %s (idle %.0fs)",
                     old.value, new_state.value, idle)

    def on_user_activity(self) -> None:
        """Call whenever a user message arrives."""
        previous = self.state
        self.last_user_activity = time.time()
        self.state = OrganismState.AWAKE

        if previous in (OrganismState.DREAMING, OrganismState.DEEP_SLEEP):
            asyncio.ensure_future(self._run_wake(previous))

    async def _run_wake(self, from_state: OrganismState) -> None:
        """Run wake-up callbacks when the organism wakes from sleep."""
        self.state = OrganismState.WAKING
        for cb in self._wake_callbacks:
            try:
                await cb(from_state)
            except Exception as e:
                log.error("Wake callback error: %s", e)
        self.state = OrganismState.AWAKE
        log.info("Organism awake (was %s)", from_state.value)

    # ── Introspection ───────────────────────────────────────────────

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_user_activity

    @property
    def uptime_pulses(self) -> int:
        return self.pulse_count

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "pulse_count": self.pulse_count,
            "idle_seconds": round(self.idle_seconds, 1),
            "phases_registered": len(self._phases),
            "running": self._running,
        }
