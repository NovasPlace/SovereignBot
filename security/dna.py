"""Sovereign — Security: DNA integrity tokens.

Every agent session carries a DNA token. The token is a fragile HMAC
that dies if anything tampers with it. When it breaks, the agent enters
QUARANTINE — no further autonomous execution until a human clears it.

Lifecycle:
    1. ISSUE      — on session start
    2. CARRY      — embedded in every inter-module boundary crossing
    3. VERIFY     — before each action execution
    4. BROKEN     — HMAC mismatch → status = BROKEN → quarantine
    5. QUARANTINE — agent halts, notifies user
    6. CLEANSE    — human reviews tamper report and authorizes resume
    7. RE-ISSUE   — new token for resumed session
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Optional

from ..models import DNAToken, TokenStatus

log = logging.getLogger("sovereign.security.dna")

# Per-process session secret — not persisted, invalidates all tokens on restart
_SESSION_SECRET: str = os.urandom(32).hex()


class DNATokenManager:
    """Issues and verifies DNA integrity tokens for Sovereign sessions."""

    def __init__(self, secret: Optional[str] = None) -> None:
        self._secret = secret or _SESSION_SECRET
        self._tokens: dict[str, DNAToken] = {}  # session_id → token
        log.info("DNATokenManager initialized")

    def issue(self, session_id: str) -> DNAToken:
        """Issue a new token for a session. Replaces any existing token."""
        token = DNAToken.issue(session_id=session_id, secret=self._secret)
        self._tokens[session_id] = token
        log.info("DNA token issued: session=%s token=%s", session_id, token.token_id[:8])
        return token

    def verify(self, session_id: str) -> bool:
        """Verify the current token for a session.

        Returns True if valid. Returns False and enters QUARANTINE if tampered.
        """
        token = self._tokens.get(session_id)
        if token is None:
            log.error("DNA verify: no token for session=%s", session_id)
            return False

        if token.status == TokenStatus.QUARANTINE:
            log.error("DNA verify: session=%s is in QUARANTINE — no execution allowed", session_id)
            return False

        if token.status == TokenStatus.BROKEN:
            log.error("DNA verify: session=%s token already BROKEN", session_id)
            self._enter_quarantine(session_id, "Verify called on already-broken token")
            return False

        ok = token.verify(secret=self._secret)
        if not ok:
            log.critical(
                "DNA INTEGRITY FAILURE: session=%s | evidence=%s",
                session_id, token.tamper_evidence,
            )
            self._enter_quarantine(session_id, "HMAC mismatch — possible prompt injection or payload tamper")
            return False

        return True

    def _enter_quarantine(self, session_id: str, reason: str) -> None:
        """Put a session into quarantine. No execution until cleansed."""
        token = self._tokens.get(session_id)
        if token:
            token.quarantine(reason)
            log.critical(
                "SESSION QUARANTINED: session=%s reason=%s", session_id, reason
            )

    def cleanse(self, session_id: str, operator: str) -> DNAToken:
        """Human operator clears quarantine and re-issues a fresh token."""
        old = self._tokens.get(session_id)
        if old:
            old.cleanse(operator)

        # Re-issue fresh token — clean slate with audit trail preserved
        new_token = self.issue(session_id)
        log.info(
            "Session cleansed + re-issued: session=%s operator=%s new_token=%s",
            session_id, operator, new_token.token_id[:8],
        )
        return new_token

    def status(self, session_id: str) -> Optional[TokenStatus]:
        token = self._tokens.get(session_id)
        return token.status if token else None

    def tamper_report(self, session_id: str) -> dict:
        """Return full tamper evidence for human review."""
        token = self._tokens.get(session_id)
        if not token:
            return {"session_id": session_id, "error": "no token found"}
        return {
            "session_id": session_id,
            "token_id": token.token_id,
            "status": token.status.value,
            "issued_at": token.issued_at,
            "verified_count": token.verified_count,
            "tamper_evidence": token.tamper_evidence,
        }


# Module-level singleton
_manager: Optional[DNATokenManager] = None


def get_dna_manager() -> DNATokenManager:
    global _manager
    if _manager is None:
        _manager = DNATokenManager()
    return _manager
