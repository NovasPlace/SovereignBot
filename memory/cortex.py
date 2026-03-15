"""Sovereign — Memory: CortexDB integration.

Connects to the existing CortexDB instance (local SQLite FTS5).
All memories are stored with provenance tagging before they enter
the Cortex — no raw external content is stored directly.

If CortexDB is running as an HTTP service, we use it via its API.
If not, we fall through to the local sovereign store.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional
from urllib import request as urllib_request
from urllib.error import URLError

from ..models import MemoryEntry, MemorySource, MAX_CONFIDENCE
from ..skills.cleanse import InputCleanse
from ..store import get_store

log = logging.getLogger("sovereign.memory.cortex")

CORTEX_BASE_URL = "http://localhost:8765"  # CortexDB default
CORTEX_TIMEOUT_S = 2.0


class CortexClient:
    """Thin client for the CortexDB memory system.

    Tries the CortexDB HTTP API first. Falls back to the sovereign
    local SQLite store if CortexDB is not reachable.
    """

    def __init__(self, base_url: str = CORTEX_BASE_URL) -> None:
        self._base = base_url.rstrip("/")
        self._store = get_store()
        self._reachable: Optional[bool] = None  # tri-state: None=unchecked

    def store(self, entry: MemoryEntry) -> bool:
        """Store a memory entry. Returns True if stored in CortexDB, False if local fallback."""
        # Cleanse content before storing
        cleansed = InputCleanse.sanitize(entry.content, source=f"memory:{entry.source.value}")
        if cleansed.injection_detected:
            log.warning("Memory poisoning attempt blocked: modifications=%s",
                        cleansed.modifications)
            return False

        # Write clean content entry
        clean_entry = entry.model_copy(update={"content": cleansed.text})

        if self._ping():
            return self._cortex_store(clean_entry)

        # Fallback to local store
        self._store.save_memory(clean_entry)
        return False

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search memories. CortexDB first, local fallback."""
        if self._ping():
            results = self._cortex_search(query, limit)
            if results is not None:
                return results

        return self._store.search_memories(query, limit)

    def _ping(self) -> bool:
        """Check CortexDB reachability (cached for session)."""
        if self._reachable is not None:
            return self._reachable
        try:
            urllib_request.urlopen(
                f"{self._base}/health",
                timeout=CORTEX_TIMEOUT_S,
            )
            self._reachable = True
            log.info("CortexDB reachable at %s", self._base)
        except (URLError, OSError):
            self._reachable = False
            log.info("CortexDB not reachable — using local store")
        return self._reachable

    def _cortex_store(self, entry: MemoryEntry) -> bool:
        payload = json.dumps({
            "content": entry.content,
            "source": entry.source.value,
            "confidence": entry.confidence,
            "external_flag": entry.external_flag,
            "provenance": entry.provenance_chain,
            "skill_id": entry.skill_id,
        }).encode()
        try:
            req = urllib_request.Request(
                f"{self._base}/memories",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib_request.urlopen(req, timeout=CORTEX_TIMEOUT_S)
            return True
        except Exception as e:
            log.warning("CortexDB store failed: %s — falling back to local", e)
            self._store.save_memory(entry)
            return False

    def _cortex_search(self, query: str, limit: int) -> Optional[list[dict]]:
        try:
            url = f"{self._base}/memories/search?q={urllib_request.quote(query)}&limit={limit}"
            resp = urllib_request.urlopen(url, timeout=CORTEX_TIMEOUT_S)
            return json.loads(resp.read())
        except Exception as e:
            log.warning("CortexDB search failed: %s", e)
            return None


_client: Optional[CortexClient] = None


def get_cortex() -> CortexClient:
    global _client
    if _client is None:
        _client = CortexClient()
    return _client
