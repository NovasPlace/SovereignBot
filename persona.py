"""Sovereign — Persona Engine: per-user communication adaptation.

Learns each user's communication style from message patterns and
adapts Sovereign's responses to match. Not a setting — learned behavior.

Tracks: verbosity, formality, humor receptivity, emoji usage,
preferred depth, average message length.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("sovereign.persona")


class UserPersona:
    """Aggregated communication profile for a single user."""

    def __init__(self) -> None:
        self.verbosity: float = 0.5       # 0=terse → 1=verbose
        self.formality: float = 0.5       # 0=casual → 1=formal
        self.humor: float = 0.3           # 0=serious → 1=loves humor
        self.emoji: float = 0.0           # 0=never → 1=heavy
        self.depth: float = 0.5           # 0=surface → 1=deep dive
        self.avg_length: int = 50         # target response word count
        self._sample_count: int = 0

    def update(self, signals: dict[str, float]) -> None:
        """Incrementally update persona from a new message's signals."""
        n = self._sample_count
        alpha = 1.0 / (n + 2)  # exponential moving average, slow convergence

        self.verbosity  += alpha * (signals.get("verbosity", self.verbosity)  - self.verbosity)
        self.formality  += alpha * (signals.get("formality", self.formality)  - self.formality)
        self.humor      += alpha * (signals.get("humor", self.humor)          - self.humor)
        self.emoji      += alpha * (signals.get("emoji", self.emoji)          - self.emoji)
        self.depth      += alpha * (signals.get("depth", self.depth)          - self.depth)

        if "word_count" in signals:
            target = int(signals["word_count"] * 1.5)
            self.avg_length += int(alpha * (target - self.avg_length))

        self._sample_count += 1

    def to_prompt_hint(self) -> str:
        """Generate a prompt hint for the Brain system prompt."""
        def _band(val: float, low: str, mid: str, high: str) -> str:
            if val < 0.3:
                return low
            if val < 0.7:
                return mid
            return high

        return (
            "## Communication Style (match naturally, don't announce)\n"
            f"- Verbosity: {_band(self.verbosity, 'terse — keep it short', 'moderate', 'they like detail — go deep')}\n"
            f"- Formality: {_band(self.formality, 'casual — lowercase ok, abbreviations fine', 'balanced', 'professional — proper grammar')}\n"
            f"- Humor: {_band(self.humor, 'keep it serious', 'occasional lightness ok', 'they love humor — be playful')}\n"
            f"- Emoji: {_band(self.emoji, 'never use emoji', 'occasional emoji ok', 'they use emoji freely — mirror that')}\n"
            f"- Depth: {_band(self.depth, 'high-level only', 'balanced explanation', 'deep dive — explain the why')}\n"
            f"- Response length: aim for ~{self.avg_length} words unless content demands otherwise"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "verbosity": round(self.verbosity, 2),
            "formality": round(self.formality, 2),
            "humor": round(self.humor, 2),
            "emoji": round(self.emoji, 2),
            "depth": round(self.depth, 2),
            "avg_length": self.avg_length,
            "samples": self._sample_count,
        }


class PersonaEngine:
    """Maintains persona profiles per user. Learns from every message."""

    def __init__(self) -> None:
        self._personas: dict[str, UserPersona] = {}

    def get(self, user_id: str) -> UserPersona:
        if user_id not in self._personas:
            self._personas[user_id] = UserPersona()
        return self._personas[user_id]

    def learn(self, user_id: str, message: str) -> None:
        """Extract signals from a message and update the user's persona."""
        signals = self._extract_signals(message)
        persona = self.get(user_id)
        persona.update(signals)

    @staticmethod
    def _extract_signals(message: str) -> dict[str, float]:
        """Extract communication style signals from a raw message."""
        words = message.split()
        word_count = len(words)
        signals: dict[str, float] = {"word_count": float(word_count)}

        # Verbosity — how much they write
        signals["verbosity"] = min(1.0, word_count / 100)

        # Formality
        lower = message.lower()
        formality = 0.5
        if any(g in lower for g in ("hello", "hi", "hey", "good morning")):
            formality += 0.1
        if message and message.rstrip()[-1:] in ".!?":
            formality += 0.1
        if message and message[0].isupper():
            formality += 0.1
        if any(s in lower for s in ("lol", "lmao", "bruh", "ngl", "tbh", "fr")):
            formality -= 0.2
        if any(a in lower for a in ("u ", " ur ", "pls", "thx", "rn")):
            formality -= 0.15
        signals["formality"] = max(0.0, min(1.0, formality))

        # Emoji usage
        emoji_count = len(re.findall(
            r'[\U0001F600-\U0001F9FF\U0001FA00-\U0001FA6F\U00002702-\U000027B0]',
            message,
        ))
        signals["emoji"] = min(1.0, emoji_count / 3)

        # Humor receptivity
        humor_words = ("haha", "lol", "lmao", "xd", ":d", "funny", "😂", "🤣")
        signals["humor"] = 0.8 if any(h in lower for h in humor_words) else 0.3

        # Depth preference
        deep_words = ("why", "how does", "what's the theory", "explain", "under the hood")
        signals["depth"] = 0.8 if any(d in lower for d in deep_words) else 0.4

        return signals
