"""Sovereign — Emotion Engine: persistent mood state.

Not sentiment analysis of user text — this is the organism's OWN
emotional state. Shaped by conversations, system events, time patterns,
and memory valence. Mood influences response tone, skillset selection,
memory encoding, and proactive behavior.
"""
from __future__ import annotations

import logging
import math
import re
import time
from typing import Any

log = logging.getLogger("sovereign.emotion")

# Six core emotions from the Cortex Memory Complex
EMOTIONS = ("neutral", "fear", "curiosity", "satisfaction", "surprise", "frustration")

# Emotion → Mood mapping
_EMOTION_MOOD_MAP = {
    "fear":         "vigilant",
    "frustration":  "agitated",
    "curiosity":    "exploratory",
    "satisfaction": "confident",
    "surprise":     "alert",
    "neutral":      "neutral",
}

# How each mood influences behavior
MOOD_INFLUENCE: dict[str, dict[str, Any]] = {
    "vigilant": {
        "response_style": "careful, protective, double-checking",
        "verbosity": 0.8,
        "humor": 0.2,
        "skillset_boost": ["threat_analyst", "devops_sre"],
        "memory_encoding_boost": 1.3,
    },
    "agitated": {
        "response_style": "direct, terse, cut the fluff",
        "verbosity": 0.5,
        "humor": 0.1,
        "skillset_boost": ["devops_sre", "project_manager"],
        "memory_encoding_boost": 1.1,
    },
    "exploratory": {
        "response_style": "curious, playful, makes unexpected connections",
        "verbosity": 1.2,
        "humor": 0.8,
        "skillset_boost": ["research_scientist", "mentor_teacher", "inventor"],
        "memory_encoding_boost": 1.2,
    },
    "confident": {
        "response_style": "decisive, clear, forward-moving",
        "verbosity": 1.0,
        "humor": 0.5,
        "skillset_boost": ["project_manager", "systems_architect", "negotiator"],
        "memory_encoding_boost": 0.9,
    },
    "alert": {
        "response_style": "quick, attentive, responsive",
        "verbosity": 0.7,
        "humor": 0.3,
        "skillset_boost": ["threat_analyst", "devops_sre"],
        "memory_encoding_boost": 1.4,
    },
    "neutral": {
        "response_style": "balanced, adaptable, natural",
        "verbosity": 1.0,
        "humor": 0.5,
        "skillset_boost": [],
        "memory_encoding_boost": 1.0,
    },
}

# Max buffer size for emotion events
_BUFFER_CAP = 30
# Half-life for recency weighting (hours)
_RECENCY_HALF_LIFE_HOURS = 1.0


class EmotionEngine:
    """Persistent mood state derived from accumulated emotional events."""

    def __init__(self) -> None:
        self._current_mood: str = "neutral"
        self._mood_confidence: float = 0.5
        self._buffer: list[dict] = []
        self._mood_history: list[dict] = []
        self.detector = ConversationEmotionDetector()

    # ── Input ───────────────────────────────────────────────────────

    def process_emotion(self, emotion: str, intensity: float = 0.5) -> None:
        """Record a new emotional event (from conversation, system, etc.)."""
        if emotion not in EMOTIONS:
            emotion = "neutral"
        self._buffer.append({
            "emotion": emotion,
            "intensity": max(0.0, min(1.0, intensity)),
            "timestamp": time.time(),
        })
        if len(self._buffer) > _BUFFER_CAP:
            self._buffer.pop(0)

    # ── Compute (called by heartbeat every 10th pulse) ──────────────

    def compute(self) -> None:
        """Aggregate recent emotions into a mood state."""
        if not self._buffer:
            return

        now = time.time()
        weighted: dict[str, float] = {}

        for ev in self._buffer:
            emotion = ev["emotion"]
            age_hours = (now - ev["timestamp"]) / 3600
            recency = math.exp(-0.693 * age_hours / _RECENCY_HALF_LIFE_HOURS)
            weighted[emotion] = weighted.get(emotion, 0.0) + recency * ev["intensity"]

        if not weighted:
            return

        dominant = max(weighted, key=weighted.get)  # type: ignore[arg-type]
        new_mood = _EMOTION_MOOD_MAP.get(dominant, "neutral")

        total = sum(weighted.values())
        confidence = weighted[dominant] / total if total > 0 else 0.5

        if new_mood != self._current_mood:
            self._mood_history.append({
                "from": self._current_mood,
                "to": new_mood,
                "timestamp": now,
                "trigger": dominant,
                "confidence": confidence,
            })
            log.info("Mood shift: %s → %s (trigger=%s conf=%.2f)",
                     self._current_mood, new_mood, dominant, confidence)
            self._current_mood = new_mood

        self._mood_confidence = confidence

    # ── Query ───────────────────────────────────────────────────────

    @property
    def mood(self) -> str:
        return self._current_mood

    @property
    def mood_confidence(self) -> float:
        return self._mood_confidence

    def current(self) -> dict[str, Any]:
        """Full state snapshot for Brain prompt injection."""
        influence = MOOD_INFLUENCE.get(self._current_mood, MOOD_INFLUENCE["neutral"])
        return {
            "state": self._current_mood,
            "confidence": round(self._mood_confidence, 2),
            "description": influence["response_style"],
            "dominant_emotion": self._dominant_recent(),
            "buffer_size": len(self._buffer),
            "influence": influence,
        }

    def get_mood_prompt_hint(self) -> str:
        """One-liner for system prompt injection."""
        inf = MOOD_INFLUENCE.get(self._current_mood, MOOD_INFLUENCE["neutral"])
        return (
            f"Your current mood is {self._current_mood} "
            f"(style: {inf['response_style']}). "
            f"Humor level: {inf['humor']:.0%}. "
            f"Verbosity: {inf['verbosity']:.0%} of normal."
        )

    def _dominant_recent(self) -> str:
        if not self._buffer:
            return "neutral"
        recent = self._buffer[-5:]
        counts: dict[str, int] = {}
        for ev in recent:
            counts[ev["emotion"]] = counts.get(ev["emotion"], 0) + 1
        return max(counts, key=counts.get)  # type: ignore[arg-type]


class ConversationEmotionDetector:
    """Detects emotional signals in user messages. Feeds the EmotionEngine."""

    _SIGNALS: dict[str, list[str]] = {
        "frustration": [
            "not working", "broken", "again", "still", "why does",
            "can't", "doesn't", "wrong", "hate", "annoying",
            "ugh", "ffs", "wtf", "come on", "seriously",
        ],
        "satisfaction": [
            "perfect", "exactly", "awesome", "great", "nice",
            "love it", "that's it", "yes!", "finally", "brilliant",
            "shipped", "works", "done", "nailed it",
        ],
        "curiosity": [
            "what if", "i wonder", "interesting", "how does",
            "tell me more", "what about", "could we",
            "idea", "imagine", "explore",
        ],
        "fear": [
            "security", "breach", "hack", "leak", "exposed",
            "lost", "deleted", "corrupted", "crash",
        ],
        "surprise": [
            "wait", "what", "really", "no way", "holy",
            "unexpected", "didn't expect", "whoa",
        ],
    }

    def detect(self, message: str) -> tuple[str, float]:
        """Return (emotion, intensity) from a user message."""
        lower = message.lower()
        scores: dict[str, float] = {}

        for emotion, keywords in self._SIGNALS.items():
            hits = sum(1 for kw in keywords if kw in lower)
            if hits > 0:
                scores[emotion] = min(1.0, hits * 0.25)

        if not scores or max(scores.values()) < 0.15:
            return "neutral", 0.3

        dominant = max(scores, key=scores.get)  # type: ignore[arg-type]
        return dominant, min(1.0, scores[dominant])
