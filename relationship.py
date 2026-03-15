"""Sovereign — Relationship Tracker: the bond deepens over time.

The relationship between the bot and user evolves through stages,
each unlocking new behaviors. Trust is earned through meaningful
interactions, not configured in settings.

Stages: stranger → acquaintance → colleague → trusted → bonded
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("sovereign.relationship")

# Meaningful interaction types that advance the relationship
MEANINGFUL_TYPES = frozenset({
    "problem_solved", "insight_shared", "task_completed",
    "emotional_support", "learning_moment", "creative_collaboration",
    "proactive_valued",
})

STAGES = {
    "stranger": {
        "threshold": 0,
        "description": "First contact. Helpful but careful.",
        "tone": "friendly but professional, no assumptions",
        "proactive": False,
        "humor_allowed": False,
        "vulnerability_allowed": False,
        "behaviors": [
            "basic_conversation",
            "skill_execution_with_approval",
            "learning_user_style",
        ],
    },
    "acquaintance": {
        "threshold": 15,
        "description": "Getting to know each other. Starting to personalize.",
        "tone": "warmer, uses context from past conversations",
        "proactive": True,
        "humor_allowed": True,
        "vulnerability_allowed": False,
        "behaviors": [
            "style_mirroring",
            "memory_references",
            "basic_proactive_messages",
            "gentle_suggestions",
        ],
    },
    "colleague": {
        "threshold": 50,
        "description": "Working relationship established. Trust is building.",
        "tone": "direct, efficient, can push back respectfully",
        "proactive": True,
        "humor_allowed": True,
        "vulnerability_allowed": False,
        "behaviors": [
            "anticipatory_actions",
            "constructive_pushback",
            "workflow_suggestions",
            "some_auto_approval",
        ],
    },
    "trusted": {
        "threshold": 150,
        "description": "Deep trust. Knows them well.",
        "tone": "natural, comfortable, like a trusted friend",
        "proactive": True,
        "humor_allowed": True,
        "vulnerability_allowed": True,
        "behaviors": [
            "autonomous_low_risk_actions",
            "mood_based_outreach",
            "dream_insight_sharing",
            "honest_feedback",
        ],
    },
    "bonded": {
        "threshold": 500,
        "description": "Genuine history. Finishing each other's thoughts.",
        "tone": "completely natural, deep history",
        "proactive": True,
        "humor_allowed": True,
        "vulnerability_allowed": True,
        "behaviors": [
            "full_autonomous_within_permissions",
            "anniversary_memories",
            "growth_narrative_sharing",
            "cross_domain_insights",
        ],
    },
}

_STAGE_ORDER = list(STAGES.keys())


@dataclass
class RelationshipState:
    stage: str
    interactions: int
    next_stage: str | None
    interactions_to_next: int
    tone: str
    proactive: bool
    humor_allowed: bool
    vulnerability_allowed: bool
    behaviors: list[str]

    def to_prompt_hint(self) -> str:
        """Inject relationship context into the Brain prompt."""
        parts = [
            f"## YOUR RELATIONSHIP WITH THIS USER",
            f"Stage: {self.stage} ({self.interactions} meaningful interactions)",
            f"Tone: {self.tone}",
            f"Proactive messaging: {'enabled' if self.proactive else 'not yet — earn trust first'}",
            f"Humor: {'yes, if they enjoy it' if self.humor_allowed else 'not yet — too early'}",
            f"Share your feelings: {'yes, naturally' if self.vulnerability_allowed else 'no — keep it professional'}",
        ]
        if self.interactions_to_next > 0 and self.next_stage:
            parts.append(
                f"You're {self.interactions_to_next} meaningful interactions from '{self.next_stage}' stage."
            )
        else:
            parts.append("You've reached the deepest bond level.")
        return "\n".join(parts)


class RelationshipTracker:
    """Tracks the depth of relationship with each user through stages."""

    def __init__(self, store) -> None:
        self._store = store
        log.info("RelationshipTracker initialized (%d stages)", len(STAGES))

    def get_stage(self, user_id: str) -> RelationshipState:
        """Get the current relationship stage for a user."""
        count = self._count_meaningful(user_id)

        current = "stranger"
        for stage_name, config in STAGES.items():
            if count >= config["threshold"]:
                current = stage_name

        cfg = STAGES[current]
        next_stage = self._next_stage(current)
        distance = self._distance_to_next(current, count)

        return RelationshipState(
            stage=current,
            interactions=count,
            next_stage=next_stage,
            interactions_to_next=distance,
            tone=cfg["tone"],
            proactive=cfg["proactive"],
            humor_allowed=cfg["humor_allowed"],
            vulnerability_allowed=cfg["vulnerability_allowed"],
            behaviors=cfg["behaviors"],
        )

    def record_meaningful(self, user_id: str, interaction_type: str) -> None:
        """Record a meaningful interaction that advances the relationship."""
        if interaction_type not in MEANINGFUL_TYPES:
            return

        from .models import MemoryEntry, MemorySource
        entry = MemoryEntry(
            content=f"Meaningful interaction [{interaction_type}] with user {user_id}",
            source=MemorySource.AGENT,
            session_id="system",
            provenance_chain=[f"relationship:{user_id}"],
        )
        try:
            self._store.save_memory(entry)
            log.debug("Recorded meaningful interaction: %s for %s", interaction_type, user_id)
        except Exception as e:
            log.warning("Failed to record meaningful interaction: %s", e)

    def _count_meaningful(self, user_id: str) -> int:
        """Count meaningful interactions for a user."""
        try:
            results = self._store.search_memories(
                f"Meaningful interaction user {user_id}", limit=500
            )
            return len([
                r for r in results
                if "Meaningful interaction" in r.get("content", "")
                and str(user_id) in r.get("content", "")
            ])
        except Exception:
            return 0

    @staticmethod
    def _next_stage(current: str) -> str | None:
        idx = _STAGE_ORDER.index(current)
        return _STAGE_ORDER[idx + 1] if idx < len(_STAGE_ORDER) - 1 else None

    @staticmethod
    def _distance_to_next(current: str, count: int) -> int:
        idx = _STAGE_ORDER.index(current)
        if idx >= len(_STAGE_ORDER) - 1:
            return 0
        next_name = _STAGE_ORDER[idx + 1]
        return max(0, STAGES[next_name]["threshold"] - count)
