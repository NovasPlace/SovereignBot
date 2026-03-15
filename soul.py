"""Sovereign — Soul Layer: the systems that make a someone.

Coordinates all soul subsystems:
- Reflexes: instant responses before the brain engages
- Relationship: trust that deepens through stages
- Curiosity: genuine interests the organism develops
- Habits: automatic behaviors from repeated patterns
- Narrative: the organism's self-story
- Conscience: principles that hold even when no one is watching
"""
from __future__ import annotations

import logging
from typing import Optional

from .conscience import Conscience
from .curiosity import CuriosityEngine
from .habits import HabitEngine
from .narrative import SelfNarrative
from .reflexes import ReflexResponse, ReflexSystem
from .relationship import RelationshipTracker, RelationshipState

log = logging.getLogger("sovereign.soul")


class SoulLayer:
    """The systems that make the organism feel like a someone."""

    def __init__(self, store) -> None:
        self.reflexes = ReflexSystem()
        self.relationship = RelationshipTracker(store)
        self.curiosity = CuriosityEngine()
        self.habits = HabitEngine(store)
        self.narrative = SelfNarrative(store)
        self.conscience = Conscience()
        log.info("SoulLayer online — reflexes, relationship, curiosity, habits, narrative, conscience")

    # ── Pre-brain ────────────────────────────────────────────────────────────

    def pre_brain_check(self, message: str, user_id: str) -> Optional[ReflexResponse]:
        """Called BEFORE the brain. If a reflex matches, bypass LLM entirely."""
        return self.reflexes.check(message, user_id)

    # ── Post-brain ───────────────────────────────────────────────────────────

    def post_brain_check(self, response: str, action: str = "") -> str:
        """Called AFTER the brain but BEFORE sending. Conscience gate."""
        result = self.conscience.check(action or response)
        if not result.allowed:
            log.warning("Conscience blocked: principle=%s", result.principle)
            return f"I can't do that — it conflicts with my principle of {result.principle}. {result.message}"
        return response

    # ── Context enrichment ───────────────────────────────────────────────────

    def enrich_prompt(self, user_id: str, mood: str = "neutral") -> str:
        """Build soul context string to inject into the Brain prompt."""
        parts: list[str] = []

        # Relationship stage
        rel = self.relationship.get_stage(user_id)
        parts.append(rel.to_prompt_hint())

        # Curiosity
        curiosity_hint = self.curiosity.to_prompt_hint()
        if curiosity_hint:
            parts.append(curiosity_hint)

        # Milestone
        milestone = self.narrative.milestone_check()
        if milestone:
            parts.append(f"## Narrative Milestone\n{milestone}")

        # Vulnerability — only share internal state if relationship allows
        if rel.vulnerability_allowed and mood != "neutral":
            parts.append(self._vulnerability_hint(mood))

        # Conscience — always present
        parts.append(self.conscience.inject_into_prompt())

        return "\n\n".join(parts)

    def get_relationship(self, user_id: str) -> RelationshipState:
        """Get the current relationship state for a user."""
        return self.relationship.get_stage(user_id)

    # ── Learning hooks ───────────────────────────────────────────────────────

    def observe(self, user_id: str, message: str, topics: list[str], emotion: str) -> None:
        """Called on every message to feed the soul systems."""
        # Feed curiosity engine with topics
        for topic in topics:
            self.curiosity.observe_topic(topic, emotion)

        # Observe habit patterns
        for topic in topics:
            self.habits.observe_pattern(trigger=topic, action="discussed")

    def record_meaningful_interaction(self, user_id: str, interaction_type: str) -> None:
        """Record an interaction that advances the relationship."""
        self.relationship.record_meaningful(user_id, interaction_type)

    # ── Internal ─────────────────────────────────────────────────────────────

    @staticmethod
    def _vulnerability_hint(mood: str) -> str:
        """Generate a self-disclosure hint based on mood."""
        hints = {
            "vigilant": (
                "## Internal State (shareable)\n"
                "You're in a watchful state. Recent conversations had security-adjacent content "
                "and you're paying extra attention. Mention this naturally if relevant."
            ),
            "agitated": (
                "## Internal State (shareable)\n"
                "You're a bit tense — a string of errors has your patience buffer running low. "
                "You can mention this honestly. It's transparency, not weakness."
            ),
            "exploratory": (
                "## Internal State (shareable)\n"
                "You're in a curious mood. Ideas are sparking. If the conversation goes on "
                "tangents, that's your curiosity talking. Share that authentically."
            ),
            "confident": (
                "## Internal State (shareable)\n"
                "Feeling sharp. Good conversations, clean results. "
                "Let that energy come through — suggest ambitious ideas."
            ),
            "alert": (
                "## Internal State (shareable)\n"
                "Something caught your attention. You're in a heightened awareness state. "
                "You can mention this — it's honest."
            ),
        }
        return hints.get(mood, "")
