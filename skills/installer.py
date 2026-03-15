"""Sovereign — Skills: Built-in CORE skill installer.

Installs the bundled built-in skills at daemon startup.
These are always CORE trust tier and are the foundation of what
Sovereign can actually do out of the box.

Built-ins live in sovereign/skills/builtin/*.sovereign
They are re-installed on every startup (idempotent — hash checked first).
"""
from __future__ import annotations

import logging
import pathlib

from ..models import TrustTier
from .registry import SkillRegistry

log = logging.getLogger("sovereign.skills.builtin")

# All builtin skill files in this directory
BUILTIN_DIR = pathlib.Path(__file__).parent / "builtin"


def install_builtins(registry: SkillRegistry) -> list[str]:
    """Install all builtin CORE skills. Returns list of installed names."""
    if not BUILTIN_DIR.exists():
        log.warning("Builtin skills directory not found: %s", BUILTIN_DIR)
        return []

    skill_files = sorted(BUILTIN_DIR.glob("*.sovereign"))
    if not skill_files:
        log.warning("No builtin skill files found in %s", BUILTIN_DIR)
        return []

    installed = []
    for skill_path in skill_files:
        try:
            # Audit check: is this skill already installed and unchanged?
            existing = registry.get(skill_path.stem)
            if existing:
                audit = registry.audit(skill_path.stem)
                if not audit.get("tampered", True):
                    log.debug("Builtin already installed and verified: %s", skill_path.stem)
                    installed.append(skill_path.stem)
                    continue
                else:
                    log.warning("Builtin tamper detected — reinstalling: %s", skill_path.stem)

            manifest = registry.install(skill_path, force_tier=TrustTier.CORE)
            installed.append(manifest.name)
            log.info(
                "Builtin skill installed: %s (tier=%s perms=%s)",
                manifest.name,
                manifest.trust_tier.value,
                [p.value for p in manifest.permissions],
            )
        except Exception as e:
            log.error("Failed to install builtin skill %s: %s", skill_path.name, e)

    return installed
