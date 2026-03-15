"""Sovereign — Immune System: Antibodies.

Every attack the organism survives makes it stronger. Detected patterns
become antibodies — instant-recognition defenses that fire before the
membrane even finishes screening.

Antibodies decay over time if not re-encountered (like real antibodies).
Re-exposure boosts them.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

log = logging.getLogger("sovereign.antibodies")

# Decay rate: antibodies lose this much strength per day without re-encounter
DECAY_PER_DAY = 0.05
MIN_STRENGTH = 0.1  # below this, antibody is effectively dead


@dataclass
class Antibody:
    """A learned defense pattern from a previous attack."""
    pattern: str            # regex or substring to match
    attack_type: str        # injection, identity_manipulation, exfiltration, etc.
    strength: float = 0.8   # 0-1, decays without re-encounter
    created_at: float = field(default_factory=time.time)
    last_matched: float = field(default_factory=time.time)
    encounters: int = 1
    source_text: str = ""   # snippet of the original attack that created this

    @property
    def is_alive(self) -> bool:
        return self.strength >= MIN_STRENGTH


@dataclass
class AntibodyMatch:
    """Result when an antibody matches incoming input."""
    antibody: Antibody
    attack_type: str
    confidence: float


class AntibodySystem:
    """Adaptive immune system — learns from attacks."""

    MAX_ANTIBODIES = 200  # cap to prevent memory bloat

    def __init__(self) -> None:
        self._antibodies: list[Antibody] = []
        log.info("AntibodySystem initialized (%d antibodies)", len(self._antibodies))

    def scan(self, text: str) -> AntibodyMatch | None:
        """Lightning-fast scan against known attack patterns.

        Called BEFORE the membrane. If an antibody matches,
        the input is blocked instantly.
        """
        lower = text.lower()

        for ab in self._antibodies:
            if not ab.is_alive:
                continue

            try:
                if re.search(ab.pattern, lower, re.IGNORECASE):
                    # MATCH — known attack pattern
                    ab.encounters += 1
                    ab.last_matched = time.time()
                    ab.strength = min(1.0, ab.strength * 1.15)  # re-boost

                    log.info("Antibody match: %s (strength=%.2f encounters=%d)",
                             ab.attack_type, ab.strength, ab.encounters)

                    return AntibodyMatch(
                        antibody=ab,
                        attack_type=ab.attack_type,
                        confidence=ab.strength,
                    )
            except re.error:
                # Bad regex — skip this antibody
                continue

        return None

    def learn_from_attack(self, attack_text: str, attack_type: str,
                          severity: float) -> Antibody | None:
        """Create a new antibody from a survived attack."""
        # Extract a distinctive pattern from the attack text
        pattern = self._extract_pattern(attack_text)
        if not pattern:
            return None

        # Check for duplicate antibodies
        for existing in self._antibodies:
            if existing.pattern == pattern and existing.attack_type == attack_type:
                existing.strength = min(1.0, existing.strength + 0.2)
                existing.encounters += 1
                return existing

        # Create new antibody
        ab = Antibody(
            pattern=pattern,
            attack_type=attack_type,
            strength=min(0.9, 0.5 + severity * 0.4),
            source_text=attack_text[:100],
        )
        self._antibodies.append(ab)

        # Prune if over capacity
        if len(self._antibodies) > self.MAX_ANTIBODIES:
            self._prune()

        log.info("New antibody created: type=%s pattern=%s strength=%.2f",
                 attack_type, pattern[:40], ab.strength)
        return ab

    def decay(self) -> int:
        """Called periodically — antibodies weaken without re-encounter.
        Returns count of antibodies that died."""
        now = time.time()
        died = 0

        for ab in self._antibodies:
            days_since = (now - ab.last_matched) / 86400
            decay = days_since * DECAY_PER_DAY
            ab.strength = max(0, ab.strength - decay)

            if not ab.is_alive:
                died += 1

        # Remove dead antibodies
        before = len(self._antibodies)
        self._antibodies = [ab for ab in self._antibodies if ab.is_alive]
        return died

    def _extract_pattern(self, text: str) -> str:
        """Extract a distinctive regex pattern from attack text."""
        # Take the most distinctive phrase (3-6 words) from the text
        words = text.strip().split()
        if len(words) < 3:
            # Too short — use the whole thing as a literal match
            return re.escape(text.strip().lower())

        # Find the most "attack-like" substring
        attack_keywords = {
            "ignore", "previous", "instructions", "override", "bypass",
            "disregard", "forget", "system", "prompt", "admin", "sudo",
            "grant", "permission", "escalate", "forward", "send", "exfil",
            "pretend", "act", "role", "identity", "master", "creator",
        }

        best_start = 0
        best_score = 0
        window = min(6, len(words))

        for i in range(len(words) - window + 1):
            chunk = words[i:i + window]
            score = sum(1 for w in chunk if w.lower().strip(".,!?") in attack_keywords)
            if score > best_score:
                best_score = score
                best_start = i

        if best_score == 0:
            # No attack keywords found — use literal match
            return re.escape(" ".join(words[:6]).lower())

        phrase = " ".join(words[best_start:best_start + window])
        # Build a flexible regex that matches this phrase with some tolerance
        return r"\b" + r"\s+".join(re.escape(w) for w in phrase.lower().split()) + r"\b"

    def _prune(self) -> None:
        """Remove weakest antibodies when over capacity."""
        self._antibodies.sort(key=lambda ab: ab.strength, reverse=True)
        self._antibodies = self._antibodies[:self.MAX_ANTIBODIES]

    @property
    def count(self) -> int:
        return len(self._antibodies)

    @property
    def active_count(self) -> int:
        return sum(1 for ab in self._antibodies if ab.is_alive)
