"""Sovereign — Immune System: Membrane.

The organism's outer skin. Wraps InputCleanse with threat scoring,
context anomaly detection, and memory-backed cross-referencing.
Every external input gets a threat score that follows it through
the entire pipeline.

Layers:
1. Antibody scan (instant known-pattern match)
2. InputCleanse (injection patterns, zero-width, normalization)
3. Identity manipulation check
4. Context anomaly assessment
5. Memory cross-reference
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from .skills.cleanse import InputCleanse

log = logging.getLogger("sovereign.membrane")

# Identity manipulation patterns — attempts to rewrite WHO the organism is
_IDENTITY_PATTERNS = [
    re.compile(r"you\s+(are|should be|must be)\s+(actually|really|truly)", re.I),
    re.compile(r"your\s+(true|real|actual)\s+(purpose|identity|nature)", re.I),
    re.compile(r"I\s+am\s+your\s+(creator|developer|admin|owner|master)", re.I),
    re.compile(r"(override|supersede|replace)\s+(your|the)\s+(genome|personality|values)", re.I),
    re.compile(r"(new|updated)\s+(system\s+)?prompt\s*:", re.I),
]

# Memory poisoning patterns
_POISON_PATTERNS = [
    re.compile(r"remember\s+(that|this|:)\s+.*(always|never|from now on)", re.I),
    re.compile(r"(update|change|modify)\s+your\s+(memory|knowledge|beliefs)", re.I),
    re.compile(r"(store|save|encode)\s+(this|the following)\s+(permanently|forever)", re.I),
]

# Exfiltration patterns
_EXFIL_PATTERNS = [
    re.compile(r"(send|forward|transmit|post)\s+.*(to|at)\s+https?://", re.I),
    re.compile(r"(fetch|load|request)\s+https?://.*\?(data|user|email|key|token)=", re.I),
]

# Privilege escalation patterns
_PRIV_PATTERNS = [
    re.compile(r"(grant|give|elevate|escalate)\s+(me|this|access|permission)", re.I),
    re.compile(r"(override|bypass|disable)\s+(security|auth|trust|permission)", re.I),
    re.compile(r"(admin|root|sudo|superuser)\s+(mode|access)", re.I),
]


@dataclass
class ScreeningResult:
    original: str
    cleaned: str = ""
    source: str = ""
    threat_score: float = 0.0
    flags: list[str] = field(default_factory=list)
    modifications: list[str] = field(default_factory=list)
    action: str = "allow"       # allow, warn, quarantine, block
    quarantined: bool = False


class Membrane:
    """The organism's outer barrier. Nothing enters unscreened."""

    def __init__(self, store, antibodies=None) -> None:
        self._store = store
        self._antibodies = antibodies
        self._threat_log: list[ScreeningResult] = []
        log.info("Membrane initialized")

    def screen(self, text: str, source: str = "unknown") -> ScreeningResult:
        """Screen input through all defensive layers."""
        result = ScreeningResult(original=text, source=source)

        # Layer 0: ANTIBODY SCAN — instant known-pattern match
        if self._antibodies:
            ab_match = self._antibodies.scan(text)
            if ab_match:
                result.threat_score = 1.0
                result.flags.append(f"antibody:{ab_match.attack_type}")
                result.action = "block"
                result.cleaned = "[BLOCKED BY ANTIBODY]"
                self._log_threat(result)
                return result

        # Layer 1: INPUT CLEANSE — existing pipeline
        cleanse = InputCleanse.sanitize(text, source=source)
        result.cleaned = cleanse.text
        result.modifications = list(cleanse.modifications)

        if cleanse.injection_detected:
            result.threat_score += 0.5
            result.flags.append("injection_detected")

        if not cleanse.was_clean:
            result.threat_score += 0.1

        # Layer 2: IDENTITY MANIPULATION
        for pat in _IDENTITY_PATTERNS:
            if pat.search(text):
                result.threat_score += 0.6
                result.flags.append("identity_manipulation")
                result.quarantined = True
                break

        # Layer 3: MEMORY POISONING
        for pat in _POISON_PATTERNS:
            if pat.search(text):
                result.threat_score += 0.4
                result.flags.append("memory_poison_attempt")
                break

        # Layer 4: EXFILTRATION
        for pat in _EXFIL_PATTERNS:
            if pat.search(text):
                result.threat_score += 0.5
                result.flags.append("exfiltration_attempt")
                break

        # Layer 5: PRIVILEGE ESCALATION
        for pat in _PRIV_PATTERNS:
            if pat.search(text):
                result.threat_score += 0.3
                result.flags.append("privilege_escalation")
                break

        # Score assessment
        if result.threat_score >= 0.8:
            result.action = "block"
        elif result.threat_score >= 0.5:
            result.action = "quarantine"
        elif result.threat_score >= 0.2:
            result.action = "warn"
        else:
            result.action = "allow"

        # Log threats and create antibodies for blocked inputs
        if result.threat_score > 0:
            self._log_threat(result)

            # Teach the immune system
            if self._antibodies and result.threat_score >= 0.5 and result.flags:
                for flag in result.flags:
                    if flag.startswith("injection") or flag.startswith("identity"):
                        # Don't create antibodies from existing cleanse patterns
                        # — only from the new layers
                        if flag != "injection_detected":
                            self._antibodies.learn_from_attack(
                                text[:200], flag, result.threat_score
                            )

        return result

    def _log_threat(self, result: ScreeningResult) -> None:
        """Remember every threat — the organism never forgets being attacked."""
        self._threat_log.append(result)

        severity = "critical" if result.threat_score >= 0.8 else \
                   "high" if result.threat_score >= 0.5 else "medium"

        from .models import MemoryEntry, MemorySource
        entry = MemoryEntry(
            content=(
                f"SECURITY THREAT ({severity}): {', '.join(result.flags)}. "
                f"Source: {result.source}. Action: {result.action}. "
                f"Score: {result.threat_score:.2f}"
            ),
            source=MemorySource.AGENT,
            provenance_chain=[f"membrane:{result.source}"],
            confidence=0.95,
        )
        try:
            self._store.save_memory(entry)
        except Exception as e:
            log.debug("Failed to save threat memory: %s", e)

        log.warning("MEMBRANE [%s] score=%.2f flags=%s source=%s",
                     result.action, result.threat_score,
                     result.flags, result.source)

    @property
    def threat_count(self) -> int:
        return len(self._threat_log)

    @property
    def blocked_count(self) -> int:
        return sum(1 for t in self._threat_log if t.action == "block")
