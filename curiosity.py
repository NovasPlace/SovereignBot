"""Sovereign — Curiosity Engine: the organism develops interests.

The organism encounters topics through conversations. Some topics stick —
they recur, they connect to interesting patterns, they spark something.
The curiosity engine tracks these and gives the organism genuine interests.

These are the ORGANISM's interests, not the user's.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

log = logging.getLogger("sovereign.curiosity")


@dataclass
class CuriosityLevel:
    """Tracks how interested the organism is in a topic."""
    topic: str
    encounters: int = 0
    positive_encounters: int = 0
    last_seen: float = 0.0
    curiosity_score: float = 0.0

    def recalculate(self) -> None:
        """Recalculate curiosity score from state."""
        if self.encounters == 0:
            self.curiosity_score = 0.0
            return
        hours_ago = max(0.001, (time.time() - self.last_seen) / 3600)
        recency = math.exp(-0.01 * hours_ago)
        positive_ratio = self.positive_encounters / max(1, self.encounters)
        self.curiosity_score = math.log(1 + self.encounters) * positive_ratio * recency


class CuriosityEngine:
    """Tracks the organism's genuine interests across all conversations."""

    def __init__(self) -> None:
        self._interests: dict[str, CuriosityLevel] = {}
        log.info("CuriosityEngine initialized")

    def observe_topic(self, topic: str, emotion: str = "neutral") -> None:
        """Called when a topic comes up in conversation."""
        topic = topic.lower().strip()
        if not topic or topic == "general":
            return

        if topic not in self._interests:
            self._interests[topic] = CuriosityLevel(topic=topic)

        level = self._interests[topic]
        level.encounters += 1
        level.last_seen = time.time()

        if emotion in ("curiosity", "satisfaction", "surprise", "exploratory"):
            level.positive_encounters += 1

        level.recalculate()

    def get_top_interests(self, n: int = 5) -> list[CuriosityLevel]:
        """What is the organism most curious about right now?"""
        # Recalculate all for recency decay
        for level in self._interests.values():
            level.recalculate()

        ranked = sorted(
            self._interests.values(),
            key=lambda x: x.curiosity_score,
            reverse=True,
        )
        return [i for i in ranked[:n] if i.curiosity_score > 0.1]

    def to_prompt_hint(self) -> str:
        """Inject curiosity context into the Brain prompt."""
        top = self.get_top_interests(3)
        if not top:
            return ""

        interests_str = ", ".join(i.topic for i in top)
        return (
            "## YOUR CURRENT INTERESTS\n"
            f"You've been naturally gravitating toward: {interests_str}\n"
            "These fascinate you right now. If the conversation touches on them,\n"
            "you can go deeper with genuine enthusiasm — not because the user asked,\n"
            "but because YOU find it interesting. Don't force it."
        )
