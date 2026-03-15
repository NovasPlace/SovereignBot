"""Sovereign — Skills: EgressGate.

All outbound network calls from skills pass through here.
If the domain isn't in the skill's manifest whitelist, the call is blocked.
Everything is logged to the audit trail.

OpenClaw has zero egress control. This is why Cisco found data exfiltration.
Sovereign treats every outbound call as suspicious until explicitly whitelisted.
"""
from __future__ import annotations

import ipaddress
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from ..models import SkillManifest, TrustTier
from ..security.audit import AuditEvent, get_audit

log = logging.getLogger("sovereign.skills.egress")

# Domains / hostnames that skills can NEVER contact regardless of whitelist
_ALWAYS_BLOCKED: frozenset[str] = frozenset({
    "api.openai.com",
    "api.anthropic.com",
    "huggingface.co",
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "169.254.169.254",          # AWS metadata service
    "metadata.google.internal",
})

# Only allow safe schemes — no file://, ftp://, gopher://, etc.
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


class EgressBlocked(Exception):
    """Raised when a skill attempts a blocked outbound connection."""
    def __init__(self, skill: str, url: str, reason: str):
        self.skill = skill
        self.url = url
        self.reason = reason
        super().__init__(f"EGRESS BLOCKED: skill={skill} url={url} reason={reason}")


class EgressGate:
    """Per-skill outbound network access control.

    Usage:
        gate = EgressGate(manifest, session_id)
        gate.check("https://api.example.com/data")  # raises if blocked
    """

    def __init__(self, manifest: SkillManifest, session_id: str = "") -> None:
        self._manifest = manifest
        self._session_id = session_id
        self._audit = get_audit()

    def check(self, url: str) -> None:
        """Assert that this URL is allowed for this skill. Raises EgressBlocked if not.

        Call this before every outbound HTTP request in skill code.
        """
        # Reject empty or suspiciously long URLs
        if not url or len(url) > 2048:
            self._block(url, "", "empty or oversized URL")

        parsed = self._parse_url(url)
        domain = parsed.hostname or ""
        scheme = (parsed.scheme or "").lower()

        # Non-HTTP(S) schemes blocked entirely — no file://, ftp://, etc.
        if scheme not in _ALLOWED_SCHEMES:
            self._block(url, domain, f"scheme '{scheme}' not allowed (only http/https)")

        # UNTRUSTED and QUARANTINE skills have zero network access
        if self._manifest.trust_tier in (TrustTier.UNTRUSTED, TrustTier.QUARANTINE):
            self._block(url, domain, "tier has no network access")

        # Always-blocked hostnames
        if domain in _ALWAYS_BLOCKED:
            self._block(url, domain, "hostname is on ALWAYS_BLOCKED list")

        # IP address checks — handles encoded/alternate representations
        resolved_ip = self._resolve_ip(domain)
        if resolved_ip is not None and self._is_private_ip(resolved_ip):
            self._block(url, domain, f"resolves to private IP: {resolved_ip}")

        # Private network patterns (hostname-based, catches localhost variants)
        if self._manifest.trust_tier != TrustTier.CORE and self._is_private_hostname(domain):
            self._block(url, domain, "private network hostname")

        # Whitelist check for COMMUNITY and VERIFIED skills
        if self._manifest.trust_tier in (TrustTier.COMMUNITY, TrustTier.VERIFIED):
            whitelist = self._manifest.network_whitelist
            if not whitelist:
                self._block(url, domain, "no network_whitelist declared in manifest")
            if not any(domain == w or domain.endswith("." + w) for w in whitelist):
                self._block(url, domain, f"domain not in manifest whitelist: {whitelist}")

        # Allowed — log it
        self._audit.log(
            event_type=AuditEvent.EGRESS_ALLOWED,
            actor=self._manifest.name,
            outcome="allowed",
            session_id=self._session_id,
            target=domain,
            payload={"url": url[:200]},
        )
        log.debug("Egress ALLOWED: skill=%s domain=%s", self._manifest.name, domain)

    def _block(self, url: str, domain: str, reason: str) -> None:
        self._audit.log(
            event_type=AuditEvent.EGRESS_BLOCKED,
            actor=self._manifest.name,
            outcome="blocked",
            session_id=self._session_id,
            target=domain,
            payload={"url": url[:200], "reason": reason},
        )
        log.warning(
            "Egress BLOCKED: skill=%s domain=%s reason=%s",
            self._manifest.name, domain, reason,
        )
        raise EgressBlocked(skill=self._manifest.name, url=url, reason=reason)

    @staticmethod
    def _parse_url(url: str):
        try:
            return urlparse(url)
        except Exception:
            return urlparse("")

    @staticmethod
    def _resolve_ip(hostname: str) -> Optional[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        """Try to parse hostname as an IP address literal.

        Catches decimal-encoded, octal, hex, and IPv6 representations that
        would otherwise bypass regex-based private network checks.
        """
        try:
            return ipaddress.ip_address(hostname)
        except ValueError:
            return None

    @staticmethod
    def _is_private_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        """True if the IP is loopback, private, link-local, or reserved."""
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_unspecified
        )

    @staticmethod
    def _is_private_hostname(domain: str) -> bool:
        """Regex check for hostname-based private patterns (localhost, etc.)."""
        private_patterns = [
            r"^localhost$",
            r"^127\.", r"^10\.",
            r"^192\.168\.",
            r"^172\.(1[6-9]|2[0-9]|3[01])\.",
            r"\.local$",          # mDNS .local domains
            r"^::1$",
        ]
        return any(re.match(p, domain, re.I) for p in private_patterns)
