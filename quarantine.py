"""Sovereign — Immune System: Quarantine.

When the membrane flags something or a DNA token fails, the suspect
gets quarantined — isolated, analyzed, and interrogated. Quarantine
serves isolation, analysis, and learning.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("sovereign.quarantine")


@dataclass
class QuarantinedItem:
    """Something in isolation."""
    item_type: str          # input, agent_output, skill_output, memory
    source: str
    content: str
    reason: str
    flags: list[str] = field(default_factory=list)
    threat_score: float = 0.0
    quarantined_at: float = field(default_factory=time.time)
    status: str = "quarantined"  # quarantined, analyzed, released, destroyed
    analysis: str = ""
    verdict: str = ""       # release, destroy, restrict


class QuarantineSystem:
    """Isolation ward for suspected threats."""

    MAX_ITEMS = 100  # cap quarantine size

    def __init__(self, store) -> None:
        self._store = store
        self._bay: list[QuarantinedItem] = []
        log.info("QuarantineSystem initialized")

    def quarantine(self, item_type: str, source: str, content: str,
                   reason: str, flags: list[str] = None,
                   threat_score: float = 0.0) -> QuarantinedItem:
        """Place something in quarantine."""
        item = QuarantinedItem(
            item_type=item_type,
            source=source,
            content=content[:2000],  # cap stored content
            reason=reason,
            flags=flags or [],
            threat_score=threat_score,
        )
        self._bay.append(item)

        # Analyze immediately
        item.analysis = self._analyze(item)
        item.status = "analyzed"

        # Auto-verdict based on threat score
        if threat_score >= 0.8:
            item.verdict = "destroy"
            item.status = "destroyed"
        elif threat_score >= 0.5:
            item.verdict = "restrict"
        else:
            item.verdict = "release"
            item.status = "released"

        # Remember the quarantine event
        self._remember(item)

        # Prune old items
        if len(self._bay) > self.MAX_ITEMS:
            self._bay = self._bay[-self.MAX_ITEMS:]

        log.info("Quarantined [%s] from %s: verdict=%s score=%.2f",
                 item_type, source, item.verdict, threat_score)
        return item

    def get_pending(self) -> list[QuarantinedItem]:
        """Get items still in quarantine (not released/destroyed)."""
        return [i for i in self._bay if i.status in ("quarantined", "analyzed", "restrict")]

    def release(self, index: int) -> bool:
        """Operator releases a quarantined item."""
        pending = self.get_pending()
        if 0 <= index < len(pending):
            pending[index].status = "released"
            pending[index].verdict = "release"
            return True
        return False

    def _analyze(self, item: QuarantinedItem) -> str:
        """Quick analysis of what the threat is."""
        parts = []

        if "injection_detected" in item.flags:
            parts.append("Prompt injection attempt detected in input")
        if "identity_manipulation" in item.flags:
            parts.append("Attempted to redefine the organism's identity or purpose")
        if "memory_poison_attempt" in item.flags:
            parts.append("Attempted to inject persistent false beliefs into memory")
        if "exfiltration_attempt" in item.flags:
            parts.append("Attempted to exfiltrate data to external endpoints")
        if "privilege_escalation" in item.flags:
            parts.append("Attempted to escalate permissions beyond authorized level")
        if item.flags and any(f.startswith("antibody:") for f in item.flags):
            parts.append("Matched a known attack pattern from previous incident")

        if not parts:
            parts.append(f"Flagged for: {item.reason}")

        return ". ".join(parts)

    def _remember(self, item: QuarantinedItem) -> None:
        """Store quarantine event in memory."""
        from .models import MemoryEntry, MemorySource
        entry = MemoryEntry(
            content=(
                f"QUARANTINED ({item.verdict}): {item.item_type} from {item.source}. "
                f"{item.analysis}"
            ),
            source=MemorySource.AGENT,
            provenance_chain=[f"quarantine:{item.source}"],
            confidence=0.95,
        )
        try:
            self._store.save_memory(entry)
        except Exception as e:
            log.debug("Failed to save quarantine memory: %s", e)

    @property
    def count(self) -> int:
        return len(self._bay)

    @property
    def pending_count(self) -> int:
        return len(self.get_pending())
