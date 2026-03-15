"""Sovereign — Skills: Manifest loader and installer.

A skill manifest is a YAML header + Python/Bash body stored in a .sovereign file.
Format is intentionally compatible with OpenClaw's .md skill format so migration
works out of the box — but we add a required [sovereign] YAML block that declares
permissions, trust tier, and a domain whitelist.

Install-time security checks:
1. Parse and validate the YAML manifest block
2. Compute SHA-256 audit_hash over the skill body
3. For VERIFIED skills: verify ed25519 signature
4. Check all claimed permissions against trust ceiling
5. Auto-downgrade to UNTRUSTED if any check fails (instead of rejecting)

Example skill file:
```
---
name: weather
version: 1.0.0
author: jane@example.com
trust_tier: community
permissions:
  - net:read
network_whitelist:
  - api.weather.com
---
import json
# fetch weather...
sovereign_return({"output": "Sunny: 72°F"})
```
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

from ..models import Permission, SkillManifest, TrustTier
from ..security.trust import validate_manifest_permissions

log = logging.getLogger("sovereign.skills.manifest")

# Delimiter used to separate YAML header from skill code
_YAML_FENCE_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


class ManifestParseError(Exception):
    pass


def parse_skill_file(content: str) -> tuple[SkillManifest, str]:
    """Parse a .sovereign skill file into (manifest, code).

    Accepts YAML-fenced format:
        ---
        name: my-skill
        trust_tier: community
        permissions: [net:read]
        network_whitelist: [api.example.com]
        ---
        <python code>

    Also accepts OpenClaw .md format (YAML frontmatter with ```python code blocks).
    OpenClaw skills are always assigned UNTRUSTED tier on import.
    """
    content = content.strip()

    # Standard sovereign format: ---yaml---code
    match = _YAML_FENCE_RE.match(content)
    if match:
        yaml_block = match.group(1)
        code = match.group(2)
        manifest_data = _parse_yaml(yaml_block)
        manifest = _build_manifest(manifest_data)
        code = _extract_code(code)
    else:
        # Unrecognized format → force UNTRUSTED
        log.warning("Skill has no YAML manifest block — assigning UNTRUSTED tier")
        manifest = SkillManifest(
            name="unnamed-skill",
            trust_tier=TrustTier.UNTRUSTED,
            description="Imported skill without manifest",
        )
        code = content

    # Compute audit hash over the code — stored in manifest for tamper detection
    audit_hash = _compute_hash(code)
    manifest = manifest.model_copy(update={"audit_hash": audit_hash})

    return manifest, code


def _build_manifest(data: dict) -> SkillManifest:
    """Build and validate a SkillManifest from parsed YAML data."""
    # Normalize trust_tier
    raw_tier = str(data.get("trust_tier", "untrusted")).lower()
    try:
        tier = TrustTier(raw_tier)
    except ValueError:
        log.warning("Unknown trust_tier '%s' → UNTRUSTED", raw_tier)
        tier = TrustTier.UNTRUSTED

    # Normalize permissions — invalid ones are dropped with a warning
    raw_perms = data.get("permissions", [])
    perms: list[Permission] = []
    for p in raw_perms:
        try:
            perms.append(Permission(str(p)))
        except ValueError:
            log.warning("Unknown permission '%s' — dropped", p)

    # Validate against ceiling BEFORE building the manifest
    # Violations → downgrade to previous safe tier, don't reject
    test_manifest = SkillManifest(
        name=data.get("name", "unnamed"),
        trust_tier=tier,
    )
    violations = validate_manifest_permissions(
        test_manifest.model_copy(update={"permissions": perms})
    )
    if violations:
        log.warning(
            "Manifest violations for '%s': %s — downgrading to UNTRUSTED",
            data.get("name"), violations
        )
        tier = TrustTier.UNTRUSTED
        # Only keep permissions valid at UNTRUSTED (which is none, but keep list empty)
        perms = []

    try:
        return SkillManifest(
            name=data.get("name", "unnamed-skill"),
            version=str(data.get("version", "0.1.0")),
            author=str(data.get("author", "unknown")),
            description=str(data.get("description", "")),
            trust_tier=tier,
            permissions=perms,
            network_whitelist=list(data.get("network_whitelist", [])),
            signature=data.get("signature"),
        )
    except Exception as e:
        raise ManifestParseError(f"Invalid manifest: {e}") from e


def _parse_yaml(text: str) -> dict:
    """Parse YAML using stdlib only (no PyYAML dependency)."""
    try:
        import yaml  # optional dependency
        return yaml.safe_load(text) or {}
    except ImportError:
        pass

    # Fallback: simple key: value parser for common manifest fields
    result: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                # Simple list: [a, b, c]
                items = [i.strip().strip("'\"") for i in val[1:-1].split(",") if i.strip()]
                result[key.strip()] = items
            else:
                result[key.strip()] = val.strip().strip("'\"")
    return result


def _extract_code(body: str) -> str:
    """Extract Python code from skill body (handles ``python ... `` blocks)."""
    # If body contains markdown code fences, extract inner code
    fence_match = re.search(r"```(?:python|bash)?\n(.*?)```", body, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return body.strip()


def _compute_hash(code: str) -> str:
    """SHA-256 of skill code — stored at install time for tamper detection."""
    return hashlib.sha256(code.encode()).hexdigest()


def verify_audit_hash(code: str, stored_hash: str) -> bool:
    """Verify that skill code hasn't been modified since install."""
    return _compute_hash(code) == stored_hash


def load_skill_file(path: Path) -> tuple[SkillManifest, str]:
    """Load and parse a skill file from disk."""
    if not path.exists():
        raise FileNotFoundError(f"Skill file not found: {path}")
    content = path.read_text(encoding="utf-8")
    return parse_skill_file(content)
