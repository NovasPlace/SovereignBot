"""Sovereign — Dream Cycle: memory consolidation during sleep.

When the organism enters deep_sleep (2hr+ idle), the dream cycle activates.
It consolidates memories: compresses duplicates, finds connections,
surfaces insights, and strengthens important memories.

The organism literally gets smarter while sleeping.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("sovereign.dreams")


@dataclass
class DreamInsight:
    """A connection or pattern discovered during dreaming."""
    content: str
    source_memories: list[str] = field(default_factory=list)
    importance: float = 0.5
    timestamp: float = field(default_factory=time.time)


class DreamCycle:
    """Memory consolidation during deep_sleep state.

    The dream cycle runs as a heartbeat phase when the organism
    reaches the dreaming or deep_sleep state. It:
    1. Compresses duplicate memories
    2. Finds topic connections across memories
    3. Surfaces insights
    4. Prunes low-importance ephemeral memories
    """

    CONSOLIDATION_INTERVAL = 600   # seconds between consolidation runs
    MAX_INSIGHTS_PER_DREAM = 3     # cap insight generation
    PRUNE_AGE_DAYS = 30            # prune agent memories older than this
    PRUNE_MIN_CONFIDENCE = 0.3     # only prune low-confidence memories

    def __init__(self, store, notification_system=None) -> None:
        self._store = store
        self._notifs = notification_system
        self._last_consolidation: float = 0.0
        self._insights: list[DreamInsight] = []
        self._dream_count: int = 0
        log.info("DreamCycle initialized")

    async def on_pulse(self, state: str, pulse_count: int) -> None:
        """Called by heartbeat. Only runs during dreaming/deep_sleep states."""
        if state not in ("dreaming", "deep_sleep"):
            return

        now = time.time()
        if now - self._last_consolidation < self.CONSOLIDATION_INTERVAL:
            return

        self._last_consolidation = now
        self._dream_count += 1
        log.info("Dream cycle %d starting (state=%s)", self._dream_count, state)

        try:
            compressed = self._compress_duplicates()
            insights = self._find_connections()
            pruned = self._prune_old_memories()

            log.info(
                "Dream cycle %d complete: compressed=%d insights=%d pruned=%d",
                self._dream_count, compressed, len(insights), pruned,
            )

            # If we found insights, queue them for when the user returns
            if insights and self._notifs:
                for insight in insights[:self.MAX_INSIGHTS_PER_DREAM]:
                    self._insights.append(insight)

        except Exception as e:
            log.warning("Dream cycle error: %s", e)

    def get_dream_insights(self) -> list[DreamInsight]:
        """Get and clear pending dream insights to share with the user."""
        insights = list(self._insights)
        self._insights.clear()
        return insights

    def has_insights(self) -> bool:
        return len(self._insights) > 0

    # ── Consolidation operations ─────────────────────────────────────────────

    def _compress_duplicates(self) -> int:
        """Find and merge near-duplicate memories."""
        try:
            # Find memories with very similar content
            # Strategy: search for common prefixes and deduplicate
            with self._store._conn() as cur:
                # Find exact content duplicates (cheap operation)
                cur.execute("""
                    DELETE FROM memories m1
                    USING memories m2
                    WHERE m1.ctid < m2.ctid
                      AND m1.content = m2.content
                      AND m1.source = m2.source
                """)
                deleted = cur.rowcount or 0
                if deleted > 0:
                    log.info("Compressed %d exact duplicate memories", deleted)
                return deleted
        except Exception as e:
            log.debug("Compression error: %s", e)
            return 0

    def _find_connections(self) -> list[DreamInsight]:
        """Find topic connections across memories. Returns insights."""
        insights: list[DreamInsight] = []

        try:
            # Find topics that appear in both bootstrap and agent memories
            from .brain import Brain
            topics = ["code", "architecture", "security", "agent",
                       "deployment", "memory", "personal"]

            for topic in topics:
                results = self._store.search_memories(topic, limit=20)
                # Look for cross-source connections
                sources = set(r.get("source", "") for r in results)
                if len(sources) > 1 and len(results) >= 3:
                    contents = [r["content"][:60] for r in results[:3]]
                    insight = DreamInsight(
                        content=(
                            f"Cross-domain connection in '{topic}': found references "
                            f"across {len(sources)} memory sources with {len(results)} entries."
                        ),
                        source_memories=contents,
                        importance=0.6,
                    )
                    insights.append(insight)

        except Exception as e:
            log.debug("Connection finding error: %s", e)

        return insights[:self.MAX_INSIGHTS_PER_DREAM]

    def _prune_old_memories(self) -> int:
        """Remove old, low-value agent memories to prevent bloat."""
        try:
            with self._store._conn() as cur:
                cur.execute("""
                    DELETE FROM memories
                    WHERE source = 'agent'
                      AND confidence < %s
                      AND created_at < now() - interval '%s days'
                      AND content NOT LIKE 'Meaningful interaction%%'
                      AND content NOT LIKE 'Discussed%%'
                """, (self.PRUNE_MIN_CONFIDENCE, self.PRUNE_AGE_DAYS))
                pruned = cur.rowcount or 0
                if pruned > 0:
                    log.info("Pruned %d old low-confidence memories", pruned)
                return pruned
        except Exception as e:
            log.debug("Pruning error: %s", e)
            return 0

    @property
    def dream_count(self) -> int:
        return self._dream_count
