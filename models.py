"""Sovereign — Core data models.

All Pydantic types used across the system. Single source of truth.
"""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ── Trust Tiers ───────────────────────────────────────────────────────────────

class TrustTier(str, Enum):
    CORE       = "core"       # built-in — full access
    VERIFIED   = "verified"   # signed by Sovereign Forge
    COMMUNITY  = "community"  # reviewed, 100+ installs
    UNTRUSTED  = "untrusted"  # new / unvetted — sandbox only
    QUARANTINE = "quarantine" # failed DNA check — blocked


# ── Permissions ───────────────────────────────────────────────────────────────

class Permission(str, Enum):
    FILE_READ    = "file:read"
    FILE_WRITE   = "file:write"
    NET_READ     = "net:read"      # HTTP GET only
    NET_WRITE    = "net:write"     # POST/PUT/DELETE — requires domain whitelist
    EMAIL_READ   = "email:read"
    EMAIL_SEND   = "email:send"    # always requires ApprovalGate
    CALENDAR     = "calendar:rw"
    EXEC         = "exec:subprocess"
    MEMORY_READ  = "memory:read"
    MEMORY_WRITE = "memory:write"

# Hard ceilings: skills cannot claim permissions above their tier ceiling
TRUST_CEILINGS: dict[TrustTier, set[Permission]] = {
    TrustTier.CORE:       set(Permission),
    TrustTier.VERIFIED:   {
        Permission.FILE_READ, Permission.NET_READ, Permission.NET_WRITE,
        Permission.EMAIL_READ, Permission.CALENDAR, Permission.MEMORY_READ,
    },
    TrustTier.COMMUNITY:  {Permission.FILE_READ, Permission.NET_READ},
    TrustTier.UNTRUSTED:  set(),   # sandbox only — zero data access
    TrustTier.QUARANTINE: set(),
}

# Actions that ALWAYS require explicit user ApprovalGate regardless of trust tier
ALWAYS_APPROVAL_REQUIRED: set[str] = {
    "send_email", "send_message", "create_account", "purchase",
    "delete_files_bulk", "access_financial", "share_data_external",
    "execute_code_external",
}


# ── Skill Manifest ────────────────────────────────────────────────────────────

class DataScope(str, Enum):
    """What user data a skill is allowed to see."""
    NONE         = "none"
    FILE_CURRENT = "file:current"  # only the file being worked on
    EMAIL_RECENT = "email:recent"  # last N emails
    CALENDAR_TODAY = "calendar:today"
    MEMORY_SESSION = "memory:session"  # in-session context only


class SkillManifest(BaseModel):
    name: str
    version: str = "0.1.0"
    author: str = "unknown"
    description: str = ""
    trust_tier: TrustTier = TrustTier.UNTRUSTED
    permissions: list[Permission] = Field(default_factory=list)
    data_access: list[DataScope] = Field(default_factory=list)
    network_whitelist: list[str] = Field(default_factory=list)  # domains only
    signature: Optional[str] = None   # ed25519 hex for VERIFIED tier
    audit_hash: str = ""              # sha256 of all skill code at install time

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, perms: list[Permission], info) -> list[Permission]:
        tier = info.data.get("trust_tier", TrustTier.UNTRUSTED)
        ceiling = TRUST_CEILINGS.get(tier, set())
        for p in perms:
            if p not in ceiling:
                raise ValueError(
                    f"Permission {p} exceeds ceiling for trust tier {tier}. "
                    f"Allowed: {[c.value for c in ceiling]}"
                )
        return perms


# ── Actions ───────────────────────────────────────────────────────────────────

class ActionType(str, Enum):
    SEND_EMAIL        = "send_email"
    SEND_MESSAGE      = "send_message"
    CREATE_ACCOUNT    = "create_account"
    PURCHASE          = "purchase"
    DELETE_FILES_BULK = "delete_files_bulk"
    ACCESS_FINANCIAL  = "access_financial"
    SHARE_EXTERNAL    = "share_data_external"
    READ_FILE         = "read_file"
    WRITE_FILE        = "write_file"
    WEB_FETCH         = "web_fetch"
    EXECUTE_CODE      = "execute_code"
    MEMORY_STORE      = "memory_store"
    CALENDAR_EVENT    = "calendar_event"
    CUSTOM            = "custom"


class Action(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    action_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: ActionType
    description: str                    # human-readable for approval prompt
    skill_id: str
    trust_tier: TrustTier
    payload: dict[str, Any] = Field(default_factory=dict)

    requires_approval: bool = False     # set in model_post_init
    approved: Optional[bool] = None     # None=pending, True=approved, False=rejected
    approved_by: Optional[str] = None   # "user" | "auto"
    approval_timeout_s: float = 300.0

    created_at: float = Field(default_factory=time.time)
    executed_at: Optional[float] = None

    def model_post_init(self, __context: Any) -> None:
        # Auto-determine if approval is required — runs after Pydantic validation
        if self.type.value in ALWAYS_APPROVAL_REQUIRED:
            self.requires_approval = True
        elif self.trust_tier in (TrustTier.UNTRUSTED, TrustTier.COMMUNITY):
            if self.type in (ActionType.WRITE_FILE, ActionType.SHARE_EXTERNAL):
                self.requires_approval = True

    @property
    def is_pending(self) -> bool:
        return self.requires_approval and self.approved is None

    @property
    def is_approved(self) -> bool:
        return not self.requires_approval or self.approved is True


# ── DNA Integrity Token ───────────────────────────────────────────────────────

class TokenStatus(str, Enum):
    VALID      = "valid"
    BROKEN     = "broken"      # HMAC mismatch detected
    QUARANTINE = "quarantine"  # agent halted pending human review
    CLEANSED   = "cleansed"    # user reviewed and cleared


class DNAToken(BaseModel):
    """Fragile HMAC integrity token. The manager holds the secret — this only holds the HMAC.
    If the HMAC doesn't match on re-computation, the session is quarantined.
    """
    model_config = {"arbitrary_types_allowed": True}

    token_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    hmac_hex: str = ""              # computed by DNATokenManager.issue()
    status: TokenStatus = TokenStatus.VALID
    issued_at: float = Field(default_factory=time.time)
    tamper_evidence: list[str] = Field(default_factory=list)
    verified_count: int = 0

    @classmethod
    def issue(cls, session_id: str, secret: str) -> "DNAToken":
        """Create and sign a new token. Secret stays in the manager — never on the token."""
        token = cls(session_id=session_id)
        token.hmac_hex = token._compute_hmac(secret)
        return token

    def _compute_hmac(self, secret: str) -> str:
        """Deterministically compute HMAC from immutable token fields."""
        payload = f"{self.token_id}:{self.session_id}:{self.issued_at}"
        return hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()

    def verify(self, secret: str) -> bool:
        """Verify token integrity. Returns False if tampered."""
        expected = self._compute_hmac(secret)
        valid = hmac.compare_digest(self.hmac_hex, expected)
        self.verified_count += 1
        if not valid:
            self.status = TokenStatus.BROKEN
            self.tamper_evidence.append(
                f"HMAC mismatch at {time.time():.3f} (verify #{self.verified_count})"
            )
        return valid

    def quarantine(self, reason: str) -> None:
        self.status = TokenStatus.QUARANTINE
        self.tamper_evidence.append(f"QUARANTINE: {reason} at {time.time():.3f}")

    def cleanse(self, operator: str) -> None:
        self.status = TokenStatus.CLEANSED
        self.tamper_evidence.append(f"CLEANSED by {operator} at {time.time():.3f}")


# ── Memory ────────────────────────────────────────────────────────────────────

class MemorySource(str, Enum):
    USER     = "user"      # directly stated by user
    AGENT    = "agent"     # agent concluded from experience
    SKILL    = "skill"     # reported by a skill
    EXTERNAL = "external"  # came from outside the device (API, email, web)
    INFERRED = "inferred"  # agent inferred without direct evidence
    IMPORTED = "imported"  # migrated from another system (e.g. OpenClaw)

# Max confidence by source — prevents memory poisoning
MAX_CONFIDENCE: dict[MemorySource, float] = {
    MemorySource.USER:     1.0,
    MemorySource.AGENT:    0.9,
    MemorySource.SKILL:    0.6,
    MemorySource.EXTERNAL: 0.3,
    MemorySource.INFERRED: 0.5,
    MemorySource.IMPORTED: 0.5,
}


class MemoryEntry(BaseModel):
    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    content: str
    source: MemorySource
    confidence: float = 1.0
    external_flag: bool = False
    formed_at: float = Field(default_factory=time.time)
    provenance_chain: list[str] = Field(default_factory=list)
    skill_id: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        # Enforce max confidence by source — the poisoning firewall
        # Runs after Pydantic validation so field values are guaranteed present
        max_conf = MAX_CONFIDENCE.get(self.source, 0.3)
        if self.confidence > max_conf:
            self.confidence = max_conf
        if self.source in (MemorySource.EXTERNAL, MemorySource.SKILL):
            self.external_flag = True


# ── Incoming Message ──────────────────────────────────────────────────────────

class IncomingMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    platform: str          # "telegram" | "discord" | "whatsapp" | "sms" | "web"
    user_id: str
    text: str              # already sanitized by ChannelAdapter.sanitize_incoming
    raw_text: str = ""     # original untouched text (for audit)
    attachments: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)    # channel-specific data (image_bytes, etc.)
    timestamp: float = Field(default_factory=time.time)
