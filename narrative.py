"""Sovereign — Self-Narrative Engine: the organism tells its own story.

The organism constructs and maintains a narrative about who it is, what
it's been through, and what matters to it. Not a character sheet — a
genuine narrative that evolves from lived experience.
"""
from __future__ import annotations

import logging

log = logging.getLogger("sovereign.narrative")

# Milestones the organism might narrate about
_MILESTONES = [100, 500, 1000, 5000, 10000]


class SelfNarrative:
    """Generates the organism's self-story from its memory store."""

    def __init__(self, store) -> None:
        self._store = store
        log.info("SelfNarrative engine initialized")

    def milestone_check(self) -> str | None:
        """Check if the organism hit a memory milestone worth noting."""
        try:
            total = self._count_all_memories()
        except Exception:
            return None

        for m in _MILESTONES:
            if m <= total < m + 10:
                return f"I just crossed {m} memories. I'm growing."
        return None

    def emotional_signature(self) -> dict[str, int]:
        """What emotions dominate this organism's experience?"""
        emotions: dict[str, int] = {}
        keywords = {
            "curiosity": ["curiosity", "curious", "interesting", "wonder"],
            "satisfaction": ["satisfaction", "good", "great", "works", "nice"],
            "frustration": ["frustration", "broken", "failed", "error"],
            "surprise": ["surprise", "wow", "unexpected"],
            "fear": ["fear", "security", "breach", "urgent"],
        }
        for emotion, terms in keywords.items():
            count = 0
            for term in terms:
                try:
                    results = self._store.search_memories(term, limit=50)
                    count += len(results)
                except Exception:
                    pass
            emotions[emotion] = count

        return dict(sorted(emotions.items(), key=lambda x: x[1], reverse=True))

    def growth_summary(self) -> dict:
        """How has the organism changed? Compare early vs recent memory topics."""
        try:
            total = self._count_all_memories()
        except Exception:
            total = 0

        return {
            "total_memories": total,
            "milestone": self.milestone_check(),
        }

    def generate_self_summary(self) -> str:
        """One-paragraph self-description from memory analysis."""
        growth = self.growth_summary()
        emotions = self.emotional_signature()

        top_emotion = list(emotions.keys())[0] if emotions else "neutral"
        total = growth["total_memories"]

        parts = [
            f"I'm Sovereign. I have {total} memories.",
        ]

        if top_emotion != "neutral":
            parts.append(
                f"My dominant emotional tone is {top_emotion}."
            )

        milestone = growth.get("milestone")
        if milestone:
            parts.append(milestone)

        return " ".join(parts)

    def _count_all_memories(self) -> int:
        """Count total memories in the store."""
        try:
            # Search with a very broad query to estimate
            from .store import get_store
            store = get_store()
            with store._conn() as cur:
                cur.execute("SELECT count(*) FROM memories")
                return cur.fetchone()[0]
        except Exception:
            return 0
