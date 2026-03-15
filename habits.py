"""Sovereign — Habit Engine: repeated patterns become automatic.

When the organism performs the same action in the same context repeatedly,
it becomes a habit. Like human muscle memory — first time you tie shoes
needs full concentration, after 1000 times your fingers do it automatically.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger("sovereign.habits")

FORMATION_THRESHOLD = 5     # repetitions to form a habit
DECAY_DAYS = 14             # days without reinforcement before weakening


@dataclass
class Habit:
    """A single automatic behavior pattern."""
    name: str
    trigger: str
    action: str
    strength: float = 0.5       # 0=forming, 1=automatic
    last_performed: float = 0.0
    formation_count: int = 0

    def matches_trigger(self, message: str) -> bool:
        """Check if the current message matches this habit's trigger."""
        return self.trigger.lower() in message.lower()


class HabitEngine:
    """Forms and tracks automatic behaviors from repeated patterns."""

    def __init__(self, store) -> None:
        self._store = store
        self._habits: list[Habit] = []
        self._pattern_buffer: dict[str, list[float]] = {}  # trigger → timestamps
        log.info("HabitEngine initialized")

    def check_habits(self, message: str) -> list[Habit]:
        """Check if any habits should fire for this message."""
        fired = []
        now = time.time()

        for habit in self._habits:
            if habit.matches_trigger(message):
                # Check decay
                days_since = (now - habit.last_performed) / 86400
                if days_since > DECAY_DAYS:
                    habit.strength *= 0.8

                if habit.strength > 0.3:
                    fired.append(habit)
                    habit.last_performed = now
                    habit.formation_count += 1
                    habit.strength = min(1.0, habit.strength * 1.05)

        return fired

    def observe_pattern(self, trigger: str, action: str) -> None:
        """Track a repeated pattern. Forms a habit at threshold."""
        key = f"{trigger}::{action}"
        now = time.time()

        if key not in self._pattern_buffer:
            self._pattern_buffer[key] = []

        self._pattern_buffer[key].append(now)

        # Clean old observations (> 30 days)
        cutoff = now - (30 * 86400)
        self._pattern_buffer[key] = [
            t for t in self._pattern_buffer[key] if t > cutoff
        ]

        if len(self._pattern_buffer[key]) >= FORMATION_THRESHOLD:
            # Check if habit already exists
            existing = [h for h in self._habits if h.name == key]
            if existing:
                existing[0].strength = min(1.0, existing[0].strength + 0.1)
            else:
                habit = Habit(
                    name=key,
                    trigger=trigger,
                    action=action,
                    strength=0.5,
                    last_performed=now,
                    formation_count=len(self._pattern_buffer[key]),
                )
                self._habits.append(habit)
                log.info("New habit formed: %s → %s (after %d observations)",
                         trigger, action, len(self._pattern_buffer[key]))

    @property
    def active_habits(self) -> list[Habit]:
        """Return habits strong enough to be considered active."""
        return [h for h in self._habits if h.strength > 0.3]
