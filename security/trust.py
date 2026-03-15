"""Sovereign — Security: Trust tier enforcement.

Central authority for permission checking. Never bypass this.
All skill execution goes through can_skill_do() before proceeding.
"""
from __future__ import annotations

import logging
from typing import Optional

from ..models import Permission, SkillManifest, TrustTier, TRUST_CEILINGS

log = logging.getLogger("sovereign.security.trust")


class TrustViolation(Exception):
    """Raised when a skill attempts an action beyond its trust ceiling."""
    def __init__(self, skill: str, tier: TrustTier, permission: Permission):
        self.skill = skill
        self.tier = tier
        self.permission = permission
        super().__init__(
            f"TRUST VIOLATION: skill '{skill}' (tier={tier.value}) "
            f"attempted {permission.value} — not in ceiling"
        )


def can_skill_do(manifest: SkillManifest, permission: Permission) -> bool:
    """Return True if this skill's trust tier allows this permission.

    CORE skills: ceiling check only — they are implicitly granted everything
    within their ceiling and do not need to declare each permission explicitly.
    This is by design: CORE skills are authored and audited by Sovereign team.

    Non-CORE skills: must pass BOTH the ceiling check AND have the permission
    explicitly declared in their manifest (principle of least privilege).
    """
    ceiling = TRUST_CEILINGS.get(manifest.trust_tier, set())

    if manifest.trust_tier == TrustTier.CORE:
        # CORE: ceiling is the only gate — no manifest declaration required
        allowed = permission in ceiling
    else:
        # COMMUNITY / VERIFIED / UNTRUSTED: explicit + within ceiling
        allowed = permission in ceiling and permission in manifest.permissions

    if not allowed:
        log.warning(
            "Trust check DENIED: skill=%s tier=%s permission=%s",
            manifest.name, manifest.trust_tier.value, permission.value,
        )
    return allowed


def assert_skill_can(manifest: SkillManifest, permission: Permission) -> None:
    """Like can_skill_do but raises TrustViolation if denied."""
    if not can_skill_do(manifest, permission):
        raise TrustViolation(manifest.name, manifest.trust_tier, permission)


def validate_manifest_permissions(manifest: SkillManifest) -> list[str]:
    """Return a list of permission claims that exceed the tier ceiling.

    Called at install time. Manifests with violations are rejected or
    downgraded to UNTRUSTED before installation.
    """
    ceiling = TRUST_CEILINGS.get(manifest.trust_tier, set())
    violations = []
    for p in manifest.permissions:
        if p not in ceiling:
            violations.append(
                f"{p.value} exceeds {manifest.trust_tier.value} ceiling"
            )
    return violations


def effective_permissions(manifest: SkillManifest) -> set[Permission]:
    """Return the intersection of declared permissions and tier ceiling.

    This is the actual runtime permission set — what the skill can do.
    """
    ceiling = TRUST_CEILINGS.get(manifest.trust_tier, set())
    return set(manifest.permissions) & ceiling


def tier_display(tier: TrustTier) -> str:
    """Human-readable trust tier with indicator."""
    icons = {
        TrustTier.CORE:       "🟢 CORE",
        TrustTier.VERIFIED:   "🔵 VERIFIED",
        TrustTier.COMMUNITY:  "🟡 COMMUNITY",
        TrustTier.UNTRUSTED:  "🔴 UNTRUSTED",
        TrustTier.QUARANTINE: "⛔ QUARANTINE",
    }
    return icons.get(tier, tier.value)
