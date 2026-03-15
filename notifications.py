"""Sovereign — Proactive Notification System.

The organism reaches out when it has something to say — not waiting
to be spoken to. Notifications are driven by the heartbeat and can be:
- Scheduled reminders ("remind me at 5pm")
- System alerts ("disk space is low")
- Spontaneous thoughts ("I've been thinking about X")
- Mood-based outreach ("you seemed stressed earlier, how's it going?")

The system queues notifications and dispatches them during heartbeat
pulses, respecting quiet hours and rate limits.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, Awaitable

log = logging.getLogger("sovereign.notifications")

# Quiet hours — don't bother the user during these times
QUIET_START = 23  # 11 PM
QUIET_END = 7     # 7 AM

# Rate limit — max proactive messages per hour
MAX_PER_HOUR = 3

# Minimum gap between proactive messages (seconds)
MIN_GAP = 300  # 5 minutes


@dataclass
class Notification:
    """A queued proactive message."""
    user_id: str
    text: str
    priority: int = 50          # 0-100, higher = more urgent
    category: str = "general"   # reminder, alert, thought, outreach
    fire_at: float = 0.0        # unix timestamp, 0 = ASAP
    created_at: float = field(default_factory=time.time)
    fired: bool = False

    @property
    def is_due(self) -> bool:
        if self.fire_at <= 0:
            return True
        return time.time() >= self.fire_at


class NotificationSystem:
    """Queues and dispatches proactive messages to users."""

    def __init__(self, send_fn: Optional[Callable] = None) -> None:
        self._queue: list[Notification] = []
        self._send_fn = send_fn  # async fn(user_id, text)
        self._last_sent: dict[str, float] = {}  # user_id → last send timestamp
        self._sent_count: dict[str, list[float]] = {}  # user_id → timestamps this hour
        log.info("NotificationSystem initialized")

    def set_send_fn(self, fn: Callable[[str, str], Awaitable[None]]) -> None:
        """Set the send function (from channel adapter)."""
        self._send_fn = fn

    # ── Queueing ─────────────────────────────────────────────────────────────

    def schedule_reminder(self, user_id: str, text: str, fire_at: float) -> None:
        """Schedule a reminder at a specific time."""
        self._queue.append(Notification(
            user_id=user_id,
            text=f"⏰ Reminder: {text}",
            priority=70,
            category="reminder",
            fire_at=fire_at,
        ))
        dt = datetime.fromtimestamp(fire_at)
        log.info("Reminder queued for %s at %s", user_id, dt.strftime("%H:%M"))

    def queue_alert(self, user_id: str, text: str, priority: int = 80) -> None:
        """Queue an urgent system alert."""
        self._queue.append(Notification(
            user_id=user_id,
            text=f"🚨 {text}",
            priority=priority,
            category="alert",
        ))

    def queue_thought(self, user_id: str, text: str) -> None:
        """Queue a spontaneous thought the organism wants to share."""
        self._queue.append(Notification(
            user_id=user_id,
            text=text,
            priority=20,
            category="thought",
        ))

    def queue_outreach(self, user_id: str, text: str) -> None:
        """Queue a mood-based check-in."""
        self._queue.append(Notification(
            user_id=user_id,
            text=text,
            priority=30,
            category="outreach",
        ))

    # ── Dispatch (called by heartbeat) ───────────────────────────────────────

    async def dispatch(self) -> int:
        """Process the queue. Called every heartbeat pulse. Returns count sent."""
        if not self._send_fn:
            return 0

        now = time.time()
        hour = datetime.now().hour
        sent = 0

        # Sort by priority descending
        due = [n for n in self._queue if n.is_due and not n.fired]
        due.sort(key=lambda n: n.priority, reverse=True)

        for notif in due:
            # Skip non-numeric user IDs (Telegram needs integer chat IDs)
            if not notif.user_id.lstrip("-").isdigit():
                notif.fired = True  # discard undeliverable
                continue

            # Quiet hours — only alerts break through
            if QUIET_START <= hour or hour < QUIET_END:
                if notif.category != "alert":
                    continue

            # Rate limit per user
            if not self._can_send(notif.user_id, now):
                continue

            # Min gap between messages
            last = self._last_sent.get(notif.user_id, 0)
            if now - last < MIN_GAP and notif.category != "alert":
                continue

            # Send it
            try:
                await self._send_fn(notif.user_id, notif.text)
                notif.fired = True
                self._last_sent[notif.user_id] = now
                self._record_send(notif.user_id, now)
                sent += 1
                log.info("Proactive [%s] sent to %s: %s",
                         notif.category, notif.user_id, notif.text[:50])
            except Exception as e:
                log.warning("Failed to send notification to %s: %s", notif.user_id, e)
                notif.fired = True  # don't retry failed sends forever

        # Clean up fired notifications
        self._queue = [n for n in self._queue if not n.fired]

        return sent

    def _can_send(self, user_id: str, now: float) -> bool:
        """Check rate limit — max N messages per hour."""
        if user_id not in self._sent_count:
            return True
        hour_ago = now - 3600
        recent = [t for t in self._sent_count[user_id] if t > hour_ago]
        self._sent_count[user_id] = recent
        return len(recent) < MAX_PER_HOUR

    def _record_send(self, user_id: str, now: float) -> None:
        if user_id not in self._sent_count:
            self._sent_count[user_id] = []
        self._sent_count[user_id].append(now)

    @property
    def pending_count(self) -> int:
        return len([n for n in self._queue if not n.fired])
