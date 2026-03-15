"""Sovereign — Onboarding: 4-phase adaptive learning system.

Tracks each user through discovery → learning → deepening → bonded.
Controls turbo ratio (how often NIM fires vs local), learning targets,
and first-contact flashbulb memory creation.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("sovereign.onboarding")

# ── Phase definitions ────────────────────────────────────────────────────────

PHASES: dict[str, dict] = {
    "discovery": {
        "memory_threshold": 0,
        "turbo_ratio": 0.90,
        "targets": [
            "name", "communication_style", "primary_need",
            "emotional_baseline", "timezone_hint",
        ],
        "behavior": "curious, attentive, mirroring style quickly",
    },
    "learning": {
        "memory_threshold": 10,
        "turbo_ratio": 0.50,
        "targets": [
            "interests", "work_context", "stress_patterns", "humor_style",
            "preferred_response_length", "topics_they_love", "topics_they_avoid",
        ],
        "behavior": "anticipating, referencing previous conversations",
    },
    "deepening": {
        "memory_threshold": 50,
        "turbo_ratio": 0.20,
        "targets": [
            "autobiographical_narrative", "relationship_depth",
            "predictive_need_model", "voice_fingerprint",
            "emotional_rhythm", "weekly_patterns",
        ],
        "behavior": "proactive, personal, references shared history naturally",
    },
    "bonded": {
        "memory_threshold": 200,
        "turbo_ratio": 0.05,
        "targets": [],
        "behavior": "feels like talking to a friend who knows you deeply",
    },
}


class OnboardingManager:
    """Tracks users through 4 onboarding phases based on memory count.

    Phase drives the turbo ratio — how often NIM fires vs local Ollama.
    As Cortex fills with distilled knowledge, turbo fades naturally.
    """

    def __init__(self, store) -> None:
        self._store = store

    def get_phase(self, user_id: str) -> str:
        """Return current phase based on memory count for this user."""
        try:
            memories = self._store.search_memories(f"user:{user_id}", limit=1000)
            count = len(memories)
        except Exception:
            count = 0

        if count >= 200:
            return "bonded"
        elif count >= 50:
            return "deepening"
        elif count >= 10:
            return "learning"
        else:
            return "discovery"

    def get_turbo_ratio(self, user_id: str) -> float:
        """Fraction of responses that should use NIM turbo (0.0–1.0)."""
        return PHASES[self.get_phase(user_id)]["turbo_ratio"]

    def get_behavior(self, user_id: str) -> str:
        return PHASES[self.get_phase(user_id)]["behavior"]

    def get_learning_targets(self, user_id: str, learned: set[str] | None = None) -> list[str]:
        """Return learning targets not yet captured for this user."""
        targets = PHASES[self.get_phase(user_id)]["targets"]
        if learned:
            return [t for t in targets if t not in learned]
        return targets

    def is_new_user(self, user_id: str) -> bool:
        try:
            results = self._store.search_memories(f"first_contact user:{user_id}", limit=1)
            return len(results) == 0
        except Exception:
            return True


class FirstContactHandler:
    """Creates a flashbulb memory on first contact and analyzes communication style."""

    def __init__(self, store) -> None:
        self._store = store

    def handle(self, user_id: str, first_message: str) -> dict:
        """Record first contact and analyze the opening message."""
        from .models import MemoryEntry, MemorySource

        signals = self._analyze_first_message(first_message)

        # Flashbulb — NEVER forget meeting them
        self._store.save_memory(MemoryEntry(
            content=(
                f"First contact with user {user_id}. "
                f"Opening message: '{first_message[:200]}'. "
                f"Style signals: {signals}"
            ),
            source=MemorySource.AGENT,
            confidence=1.0,
            session_id=user_id,
        ))

        # Initial style assessment
        self._store.save_memory(MemoryEntry(
            content=f"User {user_id} communication style: {signals}",
            source=MemorySource.AGENT,
            confidence=0.8,
            session_id=user_id,
        ))

        log.info("First contact for user=%s phase=discovery signals=%s", user_id, signals)
        return signals

    def _analyze_first_message(self, message: str) -> dict:
        signals: dict[str, Any] = {}
        words = message.split()

        signals["verbosity"] = (
            "terse" if len(words) < 5 else
            "moderate" if len(words) < 20 else
            "verbose"
        )

        has_greeting = any(g in message.lower() for g in
                          ["hello", "hi", "hey", "good morning", "yo", "sup"])
        signals["formality"] = "formal" if (message[:1].isupper() and
                                             message[-1:] in ".!?") else "casual"
        signals["uses_emoji"] = bool(re.search(r'[\U0001F600-\U0001F9FF]', message))
        signals["opener"] = (
            "question" if "?" in message else
            "seeking_help" if any(w in message.lower()
                                  for w in ["help", "need", "can you", "how"]) else
            "greeting" if has_greeting else
            "statement"
        )
        return signals


class UserLearningEncoder:
    """Encodes every interaction into memory with emotion and topic tagging."""

    EMOTION_KEYWORDS: dict[str, list[str]] = {
        "frustration": ["ugh", "annoying", "broken", "not working", "failed", "again"],
        "curiosity":   ["how", "why", "what if", "tell me", "curious", "wonder"],
        "satisfaction":["nice", "perfect", "great", "thanks", "awesome", "works"],
        "surprise":    ["wow", "whoa", "really", "seriously", "no way"],
        "fear":        ["worried", "scared", "concern", "risk", "problem", "urgent"],
    }

    def __init__(self, store) -> None:
        self._store = store

    def encode_interaction(
        self,
        user_id: str,
        user_message: str,
        bot_response: str,
        session_id: str = "default",
    ) -> None:
        """Store the interaction with detected emotion and importance."""
        from .models import MemoryEntry, MemorySource

        emotion = self._detect_emotion(user_message)
        importance = self._calculate_importance(user_message, emotion)

        self._store.save_memory(MemoryEntry(
            content=f"user:{user_id} | User: {user_message[:300]} | Bot: {bot_response[:300]}",
            source=MemorySource.AGENT,
            confidence=importance,
            session_id=session_id,
        ))

    def _detect_emotion(self, text: str) -> str:
        lower = text.lower()
        for emotion, keywords in self.EMOTION_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                return emotion
        return "neutral"

    def _calculate_importance(self, message: str, emotion: str) -> float:
        base = 0.4
        boosts = {"fear": 0.4, "surprise": 0.35, "frustration": 0.3,
                  "curiosity": 0.2, "satisfaction": 0.15}
        base += boosts.get(emotion, 0.0)
        if len(message.split()) > 50:
            base += 0.1
        if "?" in message:
            base += 0.1
        return min(0.95, base)
