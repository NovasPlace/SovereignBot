"""Sovereign — Reflex System: faster than thought.

Hardwired stimulus-response patterns that bypass the brain entirely.
Like pulling your hand off a hot stove — the signal never reaches
conscious thought. The spinal cord handles it.

Reflexes are:
- Instant (no LLM call)
- Unconditional (always fire when triggered)
- Prioritized (override normal processing)
"""
from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger("sovereign.reflexes")


@dataclass
class ReflexResponse:
    """Result of a reflex firing."""
    text: str
    reflex_name: str
    follow_up_skillset: str | None = None  # hand off to this skillset
    bypass_brain: bool = True  # if True, don't run through LLM


@dataclass
class Reflex:
    """A single stimulus-response pattern."""
    name: str
    patterns: list[str]
    importance: float = 0.5
    emotion: str = "neutral"
    priority: int = 10
    response_template: str | None = None
    follow_up: str | None = None

    def matches(self, message: str) -> bool:
        """Check if any pattern matches the message."""
        for pattern in self.patterns:
            try:
                if re.search(pattern, message, re.IGNORECASE):
                    return True
            except re.error:
                if pattern.lower() in message.lower():
                    return True
        return False

    def respond(self, message: str) -> str:
        """Generate the response. Override in subclasses for dynamic responses."""
        return self.response_template or ""


class ReflexSystem:
    """Hardwired reflexes that fire before the brain engages."""

    def __init__(self) -> None:
        self._reflexes: list[Reflex] = []
        self._load_core_reflexes()
        log.info("ReflexSystem loaded: %d reflexes", len(self._reflexes))

    def check(self, message: str, user_id: str) -> ReflexResponse | None:
        """Called BEFORE the brain. Returns a response if a reflex matches."""
        # Sort by priority descending
        for reflex in sorted(self._reflexes, key=lambda r: r.priority, reverse=True):
            if reflex.matches(message):
                text = self._generate_response(reflex, message, user_id)
                if text:
                    log.info("Reflex fired: %s for user %s", reflex.name, user_id)
                    return ReflexResponse(
                        text=text,
                        reflex_name=reflex.name,
                        follow_up_skillset=reflex.follow_up,
                        bypass_brain=True,
                    )
        return None

    def _generate_response(self, reflex: Reflex, message: str, user_id: str) -> str:
        """Generate response based on reflex type."""
        if reflex.name == "greeting":
            return self._personalized_greeting(user_id)
        if reflex.name == "thanks":
            return random.choice(["anytime", "got you", "always", "of course"])
        if reflex.name == "affirmative":
            return "on it."
        if reflex.name == "negative":
            return "understood. cancelled."
        return reflex.respond(message)

    def _personalized_greeting(self, user_id: str) -> str:
        """Greetings are reflexive but time-aware."""
        hour = datetime.now().hour
        if hour < 12:
            time_str = "morning"
        elif hour < 17:
            time_str = "afternoon"
        else:
            time_str = "evening"

        return random.choice([
            f"hey! good {time_str}",
            "yo, what's up",
            f"good {time_str}. what are we getting into",
            "hey there",
        ])

    def _load_core_reflexes(self) -> None:
        """Hardwired reflexes that ship with the organism."""
        self._reflexes.extend([
            # EMERGENCY — instant acknowledgment
            Reflex(
                name="emergency_ack",
                patterns=[
                    r"(production|prod|live|server).*(down|crash|dead|broken|503|502)",
                    r"(everything|it('s| is)).*(down|broken|dead|crashed)",
                    r"URGENT",
                ],
                response_template="On it. Pulling diagnostics now.",
                follow_up="devops_sre",
                importance=0.95,
                emotion="fear",
                priority=100,
            ),

            # SECURITY ALERT
            Reflex(
                name="security_alert",
                patterns=[
                    r"(hacked|breached|compromised|unauthorized|injection)",
                    r"(leaked|exposed).*(key|password|token|secret|credential)",
                ],
                response_template=(
                    "Security alert acknowledged. Activating threat analysis mode. "
                    "Don't touch anything until I've assessed."
                ),
                follow_up="threat_analyst",
                importance=0.95,
                emotion="fear",
                priority=95,
            ),

            # GREETING — no brain needed
            Reflex(
                name="greeting",
                patterns=[
                    r"^(hey|hi|hello|yo|sup|morning|evening|gm|good morning|good evening)[\s!.\?]*$",
                ],
                importance=0.2,
                emotion="satisfaction",
                priority=10,
            ),

            # GRATITUDE
            Reflex(
                name="thanks",
                patterns=[
                    r"^(thanks|thank you|thx|ty|cheers|appreciated)[\s!.]*$",
                ],
                importance=0.1,
                emotion="satisfaction",
                priority=10,
            ),

            # QUICK AFFIRMATIVE
            Reflex(
                name="affirmative",
                patterns=[
                    r"^(yes|yeah|yep|yup|do it|go|approved|ship it|send it)[\s!.]*$",
                ],
                importance=0.3,
                emotion="satisfaction",
                priority=50,
            ),

            # QUICK NEGATIVE
            Reflex(
                name="negative",
                patterns=[
                    r"^(no|nah|nope|cancel|stop|don't|nevermind|never mind)[\s!.]*$",
                ],
                importance=0.3,
                emotion="neutral",
                priority=50,
            ),
        ])
