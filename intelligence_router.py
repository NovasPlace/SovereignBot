"""Sovereign — Intelligence Router.

Hybrid local/cloud routing. Always tries local Ollama first.
Turbo (NIM) fires based on:
  1. Onboarding phase turbo ratio (random chance — fades as bot learns)
  2. Confidence below threshold
  3. Message complexity above threshold

"Local first. Always. The turbo teaches, then fades." — Claude spec
"""
from __future__ import annotations

import asyncio
import logging
import random

log = logging.getLogger("sovereign.intelligence_router")

CONFIDENCE_THRESHOLD = 0.72    # below this → consider turbo
COMPLEXITY_THRESHOLD = 0.65    # above this → consider turbo


def _estimate_complexity(message: str) -> float:
    """Quick heuristic: longer + more technical words = higher complexity."""
    words = message.split()
    length_score = min(1.0, len(words) / 100)
    tech_words = sum(1 for w in words if len(w) > 10)
    tech_score = min(1.0, tech_words / 10)
    return (length_score + tech_score) / 2


class BrainResult:
    def __init__(self, text: str, source: str, confidence: float = 0.8):
        self.text = text
        self.source = source
        self.confidence = confidence


class IntelligenceRouter:
    """Routes each message to local Ollama or NIM turbo based on phase + confidence.

    Always calls local first — this is the sovereign brain.
    Turbo is a detachable boost that distills into local memory and fades.
    """

    def __init__(self, local_llm_fn, turbo_llm_fn, onboarding, distiller) -> None:
        self._local = local_llm_fn       # Ollama async fn(system, user) -> str
        self._turbo = turbo_llm_fn       # NIM async fn(system, user) -> str
        self._onboarding = onboarding
        self._distiller = distiller
        self._local_calls = 0
        self._turbo_calls = 0

    async def route(
        self,
        user_id: str,
        system: str,
        user: str,
    ) -> BrainResult:
        """Route a prompt through local or turbo. Always tries local first."""

        # Step 1 — Local attempt (always)
        try:
            local_text = await self._local(system=system, user=user)
            self._local_calls += 1
        except Exception as e:
            log.error("Local LLM failed: %s — forcing turbo", e)
            return await self._call_turbo(user_id, system, user, local_text="", local_conf=0.0)

        # Step 2 — Turbo decision
        turbo_ratio = self._onboarding.get_turbo_ratio(user_id)
        complexity = _estimate_complexity(user)

        # Estimate local confidence: longer, structured responses = higher confidence
        words = len(local_text.split())
        local_conf = min(0.95, 0.4 + (words / 200))

        should_turbo = self._should_turbo(local_conf, complexity, turbo_ratio)

        if not should_turbo:
            log.debug("Local handled it (conf=%.2f ratio=%.2f)", local_conf, turbo_ratio)
            return BrainResult(text=local_text, source="local", confidence=local_conf)

        # Step 3 — Turbo fires
        return await self._call_turbo(user_id, system, user, local_text, local_conf)

    async def _call_turbo(
        self,
        user_id: str,
        system: str,
        user: str,
        local_text: str,
        local_conf: float,
    ) -> BrainResult:
        try:
            turbo_text = await self._turbo(system=system, user=user)
            self._turbo_calls += 1
            boost_conf = 0.85

            # Strip any model watermarks from cloud output
            turbo_text = _strip_invisible(turbo_text)

            # Distill into memory — teach the local model what it didn't know
            if local_text:
                self._distiller.learn(
                    question=user,
                    local_text=local_text,
                    boosted_text=turbo_text,
                    local_confidence=local_conf,
                    boost_confidence=boost_conf,
                    user_id=user_id,
                )

            log.info(
                "Turbo fired (ratio=%.2f local_conf=%.2f) | "
                "local=%d turbo=%d session",
                self._onboarding.get_turbo_ratio(user_id), local_conf,
                self._local_calls, self._turbo_calls,
            )
            return BrainResult(text=turbo_text, source="nvidia_boost", confidence=boost_conf * 0.85)

        except Exception as e:
            log.error("Turbo failed: %s — falling back to local", e)
            return BrainResult(text=local_text or "I'm having trouble right now.",
                               source="local_fallback", confidence=0.3)

    def _should_turbo(self, local_conf: float, complexity: float, turbo_ratio: float) -> bool:
        # Phase-based random chance (fades as bot learns)
        if random.random() < turbo_ratio:
            return True
        # Low local confidence
        if local_conf < CONFIDENCE_THRESHOLD:
            return True
        # High complexity
        if complexity > COMPLEXITY_THRESHOLD:
            return True
        return False

    @property
    def stats(self) -> dict:
        total = self._local_calls + self._turbo_calls
        return {
            "local_calls": self._local_calls,
            "turbo_calls": self._turbo_calls,
            "turbo_rate": f"{100 * self._turbo_calls // total}%" if total else "0%",
        }


_INVISIBLE_CHARS = [
    "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",
    "\u2060", "\ufeff", "\u00ad", "\u034f", "\u180e",
]

def _strip_invisible(text: str) -> str:
    for ch in _INVISIBLE_CHARS:
        text = text.replace(ch, "")
    return text
