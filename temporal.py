"""Sovereign — Temporal Perception: the organism feels time.

Time isn't a tool the organism checks. It's something it feels flowing.
Reminders fire as prospective memory. Recurring rhythms run automatically.
The organism knows what day it is, senses deadlines approaching, and
notices when user behavior shifts from their usual schedule.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

log = logging.getLogger("sovereign.temporal")


@dataclass
class Intention:
    """A one-time future commitment."""
    user_id: str
    action: str
    fire_at: float          # unix timestamp
    context: str = ""
    status: str = "pending"  # pending, fired, cancelled
    created_at: float = field(default_factory=time.time)


@dataclass
class Rhythm:
    """A recurring scheduled action."""
    user_id: str
    action: str
    schedule_type: str      # daily, hourly, interval
    hour: int = -1          # for daily
    minute: int = 0
    weekday: str = ""       # for weekly (e.g. "Monday")
    interval_minutes: int = 0  # for interval
    last_fired: float = 0.0
    active: bool = True

    def is_due(self, now: datetime) -> bool:
        if not self.active:
            return False

        if self.schedule_type == "daily":
            if now.hour == self.hour and now.minute == self.minute:
                if self.last_fired == 0 or datetime.fromtimestamp(self.last_fired).date() < now.date():
                    return True

        elif self.schedule_type == "weekly":
            if now.strftime("%A").lower() == self.weekday.lower() and now.hour == self.hour:
                if self.last_fired == 0 or (time.time() - self.last_fired) > 86000:
                    return True

        elif self.schedule_type == "hourly":
            if now.minute == self.minute:
                if self.last_fired == 0 or (time.time() - self.last_fired) > 3500:
                    return True

        elif self.schedule_type == "interval":
            if self.interval_minutes > 0:
                if self.last_fired == 0 or (time.time() - self.last_fired) > self.interval_minutes * 60:
                    return True

        return False


class TemporalPerception:
    """The organism's sense of time — intentions, rhythms, temporal context."""

    CHECK_INTERVAL = 50  # seconds between temporal checks

    def __init__(self, notification_system=None) -> None:
        self._notifs = notification_system
        self._intentions: list[Intention] = []
        self._rhythms: list[Rhythm] = []
        self._last_check: float = 0.0
        log.info("TemporalPerception initialized")

    async def on_pulse(self, pulse_count: int, state: str) -> None:
        """Heartbeat phase — check time-based events."""
        now = time.time()
        if now - self._last_check < self.CHECK_INTERVAL:
            return
        self._last_check = now

        dt = datetime.now()
        await self._check_intentions(dt)
        await self._check_rhythms(dt)

    # ── Intentions ───────────────────────────────────────────────────────────

    def set_reminder(self, user_id: str, action: str, fire_at: float, context: str = "") -> Intention:
        """Schedule a one-time reminder."""
        intent = Intention(user_id=user_id, action=action, fire_at=fire_at, context=context)
        self._intentions.append(intent)
        dt = datetime.fromtimestamp(fire_at)
        log.info("Reminder set for %s at %s: %s", user_id, dt.strftime("%H:%M"), action)
        return intent

    async def _check_intentions(self, now: datetime) -> None:
        now_ts = time.time()
        for intent in self._intentions:
            if intent.status == "pending" and now_ts >= intent.fire_at:
                intent.status = "fired"
                log.info("Intention fired: %s for %s", intent.action, intent.user_id)
                if self._notifs:
                    self._notifs.schedule_reminder(intent.user_id, intent.action, 0)

    # ── Rhythms ──────────────────────────────────────────────────────────────

    def add_rhythm(self, user_id: str, action: str, schedule_type: str,
                   hour: int = -1, minute: int = 0, weekday: str = "",
                   interval_minutes: int = 0) -> Rhythm:
        """Create a recurring rhythm."""
        rhythm = Rhythm(
            user_id=user_id, action=action, schedule_type=schedule_type,
            hour=hour, minute=minute, weekday=weekday,
            interval_minutes=interval_minutes,
        )
        self._rhythms.append(rhythm)
        log.info("Rhythm created: %s (%s) for %s", action, schedule_type, user_id)
        return rhythm

    async def _check_rhythms(self, now: datetime) -> None:
        for rhythm in self._rhythms:
            if rhythm.is_due(now):
                rhythm.last_fired = time.time()
                log.info("Rhythm fired: %s for %s", rhythm.action, rhythm.user_id)
                if self._notifs:
                    self._notifs.queue_thought(rhythm.user_id, f"🔁 {rhythm.action}")

    # ── Temporal Context ─────────────────────────────────────────────────────

    def to_prompt_hint(self) -> str:
        """Inject temporal awareness into the Brain prompt."""
        now = datetime.now()
        tod = self._time_of_day(now.hour)

        parts = [
            "## YOUR SENSE OF TIME",
            f"Right now: {now.strftime('%A, %B %d at %I:%M %p')}",
            f"Time of day: {tod}",
        ]

        # Overdue intentions
        overdue = [i for i in self._intentions if i.status == "pending" and time.time() > i.fire_at]
        if overdue:
            parts.append("⚠️ OVERDUE: " + ", ".join(i.action for i in overdue))

        # Upcoming (next 24h)
        cutoff = time.time() + 86400
        upcoming = [
            i for i in self._intentions
            if i.status == "pending" and i.fire_at <= cutoff and time.time() < i.fire_at
        ]
        if upcoming:
            items = []
            for i in upcoming:
                dt = datetime.fromtimestamp(i.fire_at)
                items.append(f"{i.action} at {dt.strftime('%I:%M %p')}")
            parts.append("Coming up: " + ", ".join(items))

        # Active rhythms
        active_r = [r for r in self._rhythms if r.active]
        if active_r:
            parts.append(f"Active rhythms: {len(active_r)}")

        return "\n".join(parts)

    @staticmethod
    def _time_of_day(hour: int) -> str:
        if hour < 6:
            return "deep night"
        if hour < 9:
            return "early morning"
        if hour < 12:
            return "morning"
        if hour < 14:
            return "midday"
        if hour < 17:
            return "afternoon"
        if hour < 20:
            return "evening"
        if hour < 23:
            return "night"
        return "late night"

    @property
    def pending_count(self) -> int:
        return sum(1 for i in self._intentions if i.status == "pending")
