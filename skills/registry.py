"""Sovereign — Skills: Local skill registry.

The registry manages installed skills on disk and in SQLite.
It is the single source of truth for what can execute.

Operations:
- install(path)   — parse, audit, hash, and store a skill
- remove(name)    — deactivate (never hard-delete for audit trail)
- get(name)       — retrieve manifest + code for execution
- list()          — all active skills with trust tier display
- audit(name)     — verify code hasn't been modified since install
- import_openclaw(path) — migrate an OpenClaw skill (forces UNTRUSTED)
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from pathlib import Path
from typing import Optional

from ..models import SkillManifest, TrustTier
from ..security.audit import AuditEvent, get_audit
from ..security.trust import validate_manifest_permissions, tier_display
from ..store import get_store
from .manifest import load_skill_file, parse_skill_file, verify_audit_hash

log = logging.getLogger("sovereign.skills.registry")

_SKILLS_DIR = Path.home() / ".local" / "share" / "sovereign" / "skills"


class RegistryError(Exception):
    pass


class SkillRegistry:
    """Manages installed skills — parse, validate, store, audit."""

    def __init__(self, skills_dir: Optional[Path] = None) -> None:
        self._dir = skills_dir or _SKILLS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._store = get_store()
        self._audit = get_audit()
        # In-memory cache: skill_name → (manifest, code)
        self._cache: dict[str, tuple[SkillManifest, str]] = {}
        self._load_all()

    def install(self, skill_path: Path, force_tier: Optional[TrustTier] = None) -> SkillManifest:
        """Install a skill from a .sovereign file.

        force_tier overrides the manifest's declared tier (used for CORE installs).
        Returns the installed manifest.
        """
        manifest, code = load_skill_file(skill_path)

        if force_tier:
            manifest = manifest.model_copy(update={"trust_tier": force_tier})

        # Reject if still has violations after potential downgrade
        violations = validate_manifest_permissions(manifest)
        if violations:
            self._audit.log(
                event_type=AuditEvent.SKILL_REJECTED,
                actor="registry",
                outcome="rejected",
                target=manifest.name,
                payload={"violations": violations},
            )
            raise RegistryError(
                f"Skill '{manifest.name}' rejected: {violations}"
            )

        # Copy to managed skills directory
        dest = self._dir / f"{manifest.name}.sovereign"
        shutil.copy2(skill_path, dest)

        skill_id = str(uuid.uuid4())[:8]
        manifest_dict = manifest.model_dump()
        manifest_dict["trust_tier"] = manifest.trust_tier.value

        self._store.save_skill(skill_id, manifest_dict, code)
        self._cache[manifest.name] = (manifest, code)

        self._audit.log(
            event_type=AuditEvent.SKILL_INSTALLED,
            actor="registry",
            outcome="installed",
            target=manifest.name,
            payload={
                "tier": manifest.trust_tier.value,
                "permissions": [p.value for p in manifest.permissions],
                "audit_hash": manifest.audit_hash[:16],
            },
        )
        log.info(
            "Skill installed: %s tier=%s perms=%s",
            manifest.name, tier_display(manifest.trust_tier),
            [p.value for p in manifest.permissions],
        )
        return manifest

    def install_from_text(
        self,
        content: str,
        force_tier: Optional[TrustTier] = None,
    ) -> SkillManifest:
        """Install a skill directly from its text content."""
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sovereign", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmp = Path(f.name)
        try:
            return self.install(tmp, force_tier=force_tier)
        finally:
            tmp.unlink(missing_ok=True)

    def remove(self, name: str) -> None:
        """Deactivate a skill. Never hard-deletes (audit trail)."""
        skill = self._store.get_skill(name)
        if not skill:
            raise RegistryError(f"Skill not found: {name}")

        with self._store._conn:
            self._store._conn.execute(
                "UPDATE skills SET active = 0 WHERE name = ?", (name,)
            )
        self._cache.pop(name, None)

        self._audit.log(
            event_type="skill.removed",
            actor="registry",
            outcome="deactivated",
            target=name,
        )
        log.info("Skill deactivated: %s", name)

    def get(self, name: str) -> Optional[tuple[SkillManifest, str]]:
        """Get (manifest, code) for an active skill. Returns None if not found."""
        if name in self._cache:
            return self._cache[name]

        row = self._store.get_skill(name)
        if not row:
            return None

        # Verify audit hash — detect tampering since install
        code = row["code"]
        stored_hash = row["manifest"].get("audit_hash", "")
        if stored_hash and not verify_audit_hash(code, stored_hash):
            log.critical(
                "AUDIT HASH MISMATCH for skill '%s' — possible tampering!", name
            )
            self._audit.log(
                event_type="skill.tamper_detected",
                actor="registry",
                outcome="WARNING",
                target=name,
                payload={"action": "skill blocked until re-audited"},
            )
            return None

        from ..models import Permission
        tier = TrustTier(row["trust_tier"])
        raw_perms = row["manifest"].get("permissions", [])
        perms = []
        for p in raw_perms:
            try:
                perms.append(Permission(p))
            except ValueError:
                pass

        manifest = SkillManifest(
            name=row["name"],
            version=row["manifest"].get("version", "0.1.0"),
            author=row["manifest"].get("author", "unknown"),
            trust_tier=tier,
            permissions=perms,
            network_whitelist=row["manifest"].get("network_whitelist", []),
            audit_hash=stored_hash,
        )
        self._cache[name] = (manifest, code)
        return manifest, code

    def list(self) -> list[dict]:
        """List all active skills with tier display."""
        skills = self._store.list_skills()
        for s in skills:
            try:
                s["tier_display"] = tier_display(TrustTier(s["trust_tier"]))
            except ValueError:
                s["tier_display"] = s["trust_tier"]
        return skills

    def audit(self, name: str) -> dict:
        """Verify a skill's code hash. Returns audit report."""
        row = self._store.get_skill(name)
        if not row:
            return {"name": name, "status": "not_found"}

        code = row["code"]
        stored_hash = row["manifest"].get("audit_hash", "")
        current_hash = hashlib.sha256(code.encode()).hexdigest()
        tampered = stored_hash and (current_hash != stored_hash)

        return {
            "name": name,
            "tier": row["trust_tier"],
            "installed_at": row["installed_at"],
            "stored_hash": stored_hash[:16] + "...",
            "current_hash": current_hash[:16] + "...",
            "tampered": tampered,
            "status": "TAMPERED ⚠️" if tampered else "OK ✅",
        }

    def import_openclaw(self, path: Path) -> SkillManifest:
        """Import an OpenClaw .md skill file.

        Always assigns UNTRUSTED tier — user must manually review and upgrade.
        Handles OpenClaw's markdown + YAML frontmatter + ```python code block format.
        """
        content = path.read_text(encoding="utf-8")

        # OpenClaw skills have YAML frontmatter but no sovereign permission block
        # inject minimal sovereign manifest and force UNTRUSTED
        sovereign_content = f"""---
name: {path.stem}
version: 0.1.0
author: openclaw-import
trust_tier: untrusted
description: Imported from OpenClaw — review before upgrading trust tier
permissions: []
network_whitelist: []
---
{content}
"""
        log.info("Importing OpenClaw skill: %s → UNTRUSTED", path.name)
        return self.install_from_text(sovereign_content, force_tier=TrustTier.UNTRUSTED)

    def _load_all(self) -> None:
        """Pre-warm cache from store on startup."""
        for row in self._store.list_skills():
            try:
                self.get(row["name"])
            except Exception as e:
                log.warning("Failed to load skill '%s': %s", row.get("name"), e)

    def as_skill_registry_dict(self) -> dict[str, tuple[SkillManifest, str]]:
        """Return the cache dict for passing to Executor."""
        return dict(self._cache)
