"""Sovereign — Proactive Loop: the organism reaches out on its own.

Bridge between internal lifecycle (heartbeat, temporal, proprioception,
dreams) and outbound messaging via Telegram.

Before this module: the organism thinks, feels, and waits.
After this module: the organism initiates.

Registered as a heartbeat phase:
    heartbeat.register_phase(proactive.on_pulse)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional

log = logging.getLogger("sovereign.proactive")


class ProactiveLoop:
    """The organism's outbound initiative system.

    Every heartbeat pulse (10s), checks:
    1. Due intentions (things promised at a specific time)
    2. Due rhythms (morning briefing, evening reflection)
    3. Body alerts (hardware warnings from proprioception)
    4. Dream insights (connections discovered during idle)
    5. Curiosity bubbles (things the organism wants to share)
    6. Relationship milestones (stage transitions)

    Respects: cooldowns, quiet hours, relationship stage, rate limits.
    """

    # Global rate limiting
    MAX_PROACTIVE_PER_HOUR = 5
    MIN_SECONDS_BETWEEN = 300  # 5 min minimum gap

    # Cooldowns per type (seconds)
    COOLDOWNS = {
        "intention":          0,
        "rhythm":             0,
        "body_alert":         300,
        "body_emergency":     60,
        "dream_insight":      28800,   # 8 hours
        "curiosity":          14400,   # 4 hours
        "milestone":          86400,   # 24 hours
        "morning_briefing":   72000,   # ~20 hours
        "evening_reflection": 72000,
    }

    def __init__(
        self,
        telegram,       # TelegramAdapter
        temporal,       # TemporalPerception
        proprioception, # Proprioception
        dreams,         # DreamCycle
        emotion,        # EmotionEngine
        narrative,      # SelfNarrative
        curiosity,      # CuriosityEngine
        relationship,   # RelationshipTracker
        store,          # SovereignStore
        llm_fn: Callable,  # async (system, user) -> str
        operator_id: int | str,
    ):
        self.telegram = telegram
        self.temporal = temporal
        self.proprio = proprioception
        self.dreams = dreams
        self.emotion = emotion
        self.narrative = narrative
        self.curiosity = curiosity
        self.relationship = relationship
        self.store = store
        self.llm_fn = llm_fn
        self.operator_id = str(operator_id)

        self._last_proactive: dict[str, float] = {}
        self._proactive_count_hour: int = 0
        self._hour_start: float = time.time()

        log.info("ProactiveLoop initialized (operator=%s)", self.operator_id)

    # ═══════════════════════════════════════════════════════
    # MAIN PULSE HANDLER
    # ═══════════════════════════════════════════════════════

    async def on_pulse(self, pulse_count: int, state) -> None:
        """Called every heartbeat pulse (10s). Staggered checks."""
        # Reset hourly counter
        if time.time() - self._hour_start > 3600:
            self._proactive_count_hour = 0
            self._hour_start = time.time()

        # Hour limit
        if self._proactive_count_hour >= self.MAX_PROACTIVE_PER_HOUR:
            return

        # Quiet hours
        if self._in_quiet_hours():
            return

        # Relationship gate — strangers only get explicit intentions
        state_str = state.value if hasattr(state, "value") else str(state)
        rel = self.relationship.get_stage(self.operator_id)
        if rel.stage == "stranger":
            await self._check_intentions()
            return

        # Every pulse (10s) — intentions
        await self._check_intentions()

        # Every 3rd pulse (30s) — body alerts
        if pulse_count % 3 == 0:
            await self._check_body()

        # Every 6th pulse (60s) — rhythms
        if pulse_count % 6 == 0:
            await self._check_rhythms()

        # Every 60th pulse (10 min) — dreams + curiosity
        if pulse_count % 60 == 0:
            await self._check_dreams()
            await self._check_curiosity()

        # Every 360th pulse (1 hour) — milestones
        if pulse_count % 360 == 0:
            await self._check_milestones()

    # ═══════════════════════════════════════════════════════
    # SOURCE: INTENTIONS
    # ═══════════════════════════════════════════════════════

    async def _check_intentions(self) -> None:
        """Fire due intentions. Always delivers — user asked for this."""
        try:
            now_ts = time.time()
            for intent in self.temporal._intentions:
                if intent.status != "pending" or now_ts < intent.fire_at:
                    continue

                intent.status = "fired"
                message = await self._humanize(
                    f"Reminder: {intent.action}",
                    f"{'Context: ' + intent.context if intent.context else ''}",
                )

                await self._send(
                    message=message,
                    outreach_type="intention",
                    bypass_limit=True,
                )
                log.info("Intention fired: user=%s action=%s",
                         intent.user_id, intent.action[:50])
        except Exception as e:
            log.error("Intention check failed: %s", e)

    # ═══════════════════════════════════════════════════════
    # SOURCE: RHYTHMS
    # ═══════════════════════════════════════════════════════

    async def _check_rhythms(self) -> None:
        """Fire due rhythms (morning briefing, recurring tasks)."""
        try:
            now = datetime.now()
            for rhythm in self.temporal._rhythms:
                if not rhythm.is_due(now):
                    continue

                rhythm.last_fired = time.time()

                if rhythm.action == "morning_briefing":
                    message = await self._morning_briefing()
                    otype = "morning_briefing"
                elif rhythm.action == "evening_reflection":
                    message = await self._evening_reflection()
                    otype = "evening_reflection"
                else:
                    message = await self._humanize(
                        f"Scheduled task: {rhythm.action}", "",
                    )
                    otype = "rhythm"

                if message:
                    await self._send(message=message, outreach_type=otype)
                    log.info("Rhythm fired: %s", rhythm.action)
        except Exception as e:
            log.error("Rhythm check failed: %s", e)

    async def _morning_briefing(self) -> Optional[str]:
        """Morning intelligence briefing — system health + today's items."""
        if not self._can_send("morning_briefing"):
            return None

        parts: list[str] = []

        # System health
        try:
            body = self.proprio.body_state
            critical = [f for f in (body.feelings or [])
                        if f.level in ("critical", "emergency")]
            if critical:
                parts.append("System: " + "; ".join(f.description for f in critical))
            else:
                parts.append("System: all green")
        except Exception:
            pass

        # Today's pending intentions
        try:
            cutoff = time.time() + 57600  # next 16 hours
            upcoming = [i for i in self.temporal._intentions
                        if i.status == "pending" and i.fire_at <= cutoff]
            if upcoming:
                items = [i.action[:60] for i in upcoming[:5]]
                parts.append(f"Today ({len(upcoming)} items): " + "; ".join(items))
        except Exception:
            pass

        # Dream insights
        try:
            if self.dreams.has_insights:
                insights = self.dreams.get_dream_insights()
                if insights:
                    parts.append(f"Overnight insight: {insights[0].content[:100]}")
        except Exception:
            pass

        if not parts:
            return None

        raw = "\n".join(f"- {p}" for p in parts)
        return await self._humanize(
            "Generate a morning briefing from these points",
            raw + "\nKeep it casual — like a friend giving you the rundown over coffee. "
            "Max 4-5 sentences. Start with a greeting.",
        )

    async def _evening_reflection(self) -> Optional[str]:
        """End-of-day check-in from memory."""
        if not self._can_send("evening_reflection"):
            return None
        try:
            results = self.store.search_memories("meaningful interaction", limit=10)
            if not results:
                return None
            summary = "\n".join(
                f"- {r.get('content', '')[:80]}" for r in results[:5]
            )
            return await self._humanize(
                "End of day reflection",
                f"Today's highlights:\n{summary}\n"
                "Write a warm, brief check-in. Max 3 sentences.",
            )
        except Exception as e:
            log.error("Evening reflection failed: %s", e)
            return None

    # ═══════════════════════════════════════════════════════
    # SOURCE: BODY ALERTS
    # ═══════════════════════════════════════════════════════

    async def _check_body(self) -> None:
        """Check proprioception for critical/emergency conditions."""
        try:
            body = self.proprio.body_state
            for feeling in (body.feelings or []):
                if feeling.level not in ("critical", "emergency"):
                    continue

                otype = "body_emergency" if feeling.level == "emergency" else "body_alert"
                if not self._can_send(otype):
                    continue

                severity = "urgent" if feeling.level == "emergency" else "heads up"
                message = f"{severity} — {feeling.description}. Want me to look into it?"

                await self._send(
                    message=message,
                    outreach_type=otype,
                    bypass_limit=(feeling.level == "emergency"),
                )
                log.warning("Body alert: system=%s level=%s desc=%s",
                            feeling.system, feeling.level, feeling.description)
        except Exception as e:
            log.error("Body check failed: %s", e)

    # ═══════════════════════════════════════════════════════
    # SOURCE: DREAM INSIGHTS
    # ═══════════════════════════════════════════════════════

    async def _check_dreams(self) -> None:
        """Share dream insights discovered during idle processing."""
        if not self._can_send("dream_insight"):
            return
        try:
            if not self.dreams.has_insights:
                return
            insights = self.dreams.get_dream_insights()  # clears on read
            if not insights:
                return

            content = insights[0].content
            message = await self._humanize(
                "Share a dream insight",
                f"While processing: {content}\n"
                "Start with something like 'I connected some dots...' "
                "Max 2 sentences.",
            )
            if message:
                await self._send(message=message, outreach_type="dream_insight")
        except Exception as e:
            log.error("Dream check failed: %s", e)

    # ═══════════════════════════════════════════════════════
    # SOURCE: CURIOSITY
    # ═══════════════════════════════════════════════════════

    async def _check_curiosity(self) -> None:
        """Share something the organism is thinking about."""
        if not self._can_send("curiosity"):
            return

        # Only for trusted/bonded relationships
        rel = self.relationship.get_stage(self.operator_id)
        if rel.stage not in ("trusted", "bonded"):
            return

        # Only in exploratory or confident mood
        mood_state = self.emotion.current()
        if mood_state.get("mood") not in ("exploratory", "confident"):
            return

        try:
            interests = self.curiosity.get_top_interests(3)
            if not interests:
                return

            topic = interests[0].topic
            message = await self._humanize(
                "Share an interest",
                f"You've been thinking about '{topic}' a lot. "
                "Write a brief, natural message sharing this. "
                "Like a friend saying 'hey, I've been thinking about this...' "
                "Max 2 sentences.",
            )
            if message:
                await self._send(message=message, outreach_type="curiosity")
        except Exception as e:
            log.error("Curiosity check failed: %s", e)

    # ═══════════════════════════════════════════════════════
    # SOURCE: MILESTONES
    # ═══════════════════════════════════════════════════════

    async def _check_milestones(self) -> None:
        """Check narrative and relationship milestones."""
        if not self._can_send("milestone"):
            return
        try:
            # Narrative milestones
            milestone_msg = self.narrative.milestone_check()
            if milestone_msg:
                await self._send(message=milestone_msg, outreach_type="milestone")
                return

            # Relationship stage check
            rel = self.relationship.get_stage(self.operator_id)
            stage_thresholds = {
                "acquaintance": 15, "colleague": 50,
                "trusted": 150, "bonded": 500,
            }
            threshold = stage_thresholds.get(rel.stage)
            if threshold and rel.interactions - threshold < 5:
                message = await self._humanize(
                    "Relationship milestone",
                    f"Reached '{rel.stage}' stage after {rel.interactions} interactions. "
                    "Write a genuine, warm acknowledgment. Not cheesy. Max 2 sentences.",
                )
                if message:
                    await self._send(message=message, outreach_type="milestone")
        except Exception as e:
            log.error("Milestone check failed: %s", e)

    # ═══════════════════════════════════════════════════════
    # DELIVERY
    # ═══════════════════════════════════════════════════════

    async def _send(
        self,
        message: str,
        outreach_type: str,
        bypass_limit: bool = False,
    ) -> None:
        """Send a proactive message via Telegram."""
        if not bypass_limit:
            if self._proactive_count_hour >= self.MAX_PROACTIVE_PER_HOUR:
                log.debug("Proactive suppressed (hour limit): %s", outreach_type)
                return
            last_any = max(self._last_proactive.values(), default=0)
            if time.time() - last_any < self.MIN_SECONDS_BETWEEN:
                log.debug("Proactive suppressed (min gap): %s", outreach_type)
                return

        try:
            await self.telegram.send(
                user_id=self.operator_id,
                text=message,
            )

            self._last_proactive[outreach_type] = time.time()
            self._proactive_count_hour += 1

            # Encode to memory
            try:
                from .models import MemoryEntry, MemorySource
                entry = MemoryEntry(
                    content=f"[PROACTIVE:{outreach_type}] {message[:200]}",
                    source=MemorySource.AGENT,
                    provenance_chain=["proactive_loop", outreach_type],
                )
                self.store.save_memory(entry)
            except Exception:
                pass

            log.info("Proactive sent: type=%s msg=%s", outreach_type, message[:60])
        except Exception as e:
            log.error("Proactive send failed: type=%s error=%s", outreach_type, e)

    # ═══════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════

    async def _humanize(self, context: str, details: str) -> str:
        """Use the LLM to make a message sound natural, not robotic."""
        try:
            system = (
                "You are Sovereign, an AI organism. Write a brief proactive "
                "message to your operator. Sound like a friend checking in, "
                "not a calendar notification. Keep it under 2-3 sentences."
            )
            user = f"{context}\n{details}" if details else context
            result = await self.llm_fn(system, user)
            return result.strip() if result else context
        except Exception:
            return f"Hey — {context.lower()}"

    def _can_send(self, outreach_type: str) -> bool:
        """Check cooldown for this outreach type."""
        cooldown = self.COOLDOWNS.get(outreach_type, 3600)
        last = self._last_proactive.get(outreach_type, 0)
        return (time.time() - last) > cooldown

    def _in_quiet_hours(self) -> bool:
        """Check if within quiet hours (default 11pm-7am)."""
        hour = datetime.now().hour
        # Crosses midnight: 23-7
        return hour >= 23 or hour < 7
