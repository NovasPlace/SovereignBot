"""Sovereign — Knowledge Distiller.

Every time NIM turbo fires, the organism learns permanently from the response.
If the local model and NIM gave similar answers, local already knew it — skip.
If there's a gap, encode the knowledge as a semantic memory so local improves.

"The turbo teaches, then fades." — Claude spec
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("sovereign.knowledge_distiller")

SIMILARITY_THRESHOLD = 0.85   # skip distillation if responses are this similar
MIN_RESPONSE_LENGTH = 30       # don't distill trivial one-liner answers


def _simple_similarity(text_a: str, text_b: str) -> float:
    """Word overlap Jaccard similarity — fast, no embeddings needed.

    Good enough to catch near-identical answers. For deeper similarity
    the Cortex neural layer can be plugged in later.
    """
    if not text_a or not text_b:
        return 0.0
    words_a = set(re.findall(r'\w+', text_a.lower()))
    words_b = set(re.findall(r'\w+', text_b.lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


class KnowledgeDistiller:
    """Encodes cloud response gaps into long-term Cortex memory.

    Called after every NIM turbo response to teach the local model what it
    didn't know. Over time the turbo fires less and less.
    """

    def __init__(self, store) -> None:
        self._store = store
        self._distillations = 0   # session counter

    def learn(
        self,
        question: str,
        local_text: str,
        boosted_text: str,
        local_confidence: float = 0.5,
        boost_confidence: float = 0.8,
        user_id: str = "default",
    ) -> bool:
        """Potentially encode new knowledge from the NIM response.

        Returns True if knowledge was distilled, False if answers were similar.
        """
        # Skip trivial responses
        if len(boosted_text) < MIN_RESPONSE_LENGTH:
            return False

        # If local and NIM gave similar answers, local already knew this
        similarity = _simple_similarity(local_text, boosted_text)
        if similarity > SIMILARITY_THRESHOLD:
            log.debug("Distillation skipped — similarity=%.2f", similarity)
            return False

        # Knowledge gap exists — encode permanently
        knowledge_gap = boost_confidence - local_confidence
        importance = min(0.9, 0.5 + knowledge_gap)

        from .models import MemoryEntry, MemorySource
        self._store.save_memory(MemoryEntry(
            content=f"Q: {question}\nA: {boosted_text[:500]}",
            source=MemorySource.AGENT,
            confidence=boost_confidence * 0.85,   # external source penalty
            session_id="distilled",
        ))

        self._distillations += 1
        log.info(
            "Knowledge distilled: similarity=%.2f gap=%.2f importance=%.2f "
            "session_total=%d",
            similarity, knowledge_gap, importance, self._distillations,
        )
        return True

    @property
    def distillation_count(self) -> int:
        return self._distillations
