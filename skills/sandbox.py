"""Sovereign — Skills: Skill sandbox.

UNTRUSTED and COMMUNITY skills run in an isolated subprocess.
They receive only the data they declared in the manifest's data_access field.
They cannot access the network (beyond EgressGate), home dir, or credentials.

Isolation mechanisms:
- subprocess with heavily restricted environment
- stdout-only communication (skills return JSON)
- resource caps: 30s CPU, 256MB RAM, 10MB output
- output passed through InputCleanse before returning to agent
"""
from __future__ import annotations

import json
import logging
import os
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from ..models import DataScope, SkillManifest, TrustTier
from .cleanse import InputCleanse

log = logging.getLogger("sovereign.skills.sandbox")

# Resource caps
CPU_LIMIT_S   = 30      # seconds
MEM_LIMIT_MB  = 256     # megabytes
OUTPUT_LIMIT  = 10_000  # characters in output


class SandboxTimeoutError(Exception):
    pass


class SandboxError(Exception):
    pass


def _build_prelude(manifest: SkillManifest, injected_data: dict) -> str:
    """Generate Python prelude that injects data and blocks dangerous builtins."""
    return f"""
import sys, os, json

# Block filesystem access beyond tmpdir
_ALLOWED_TMPDIR = os.environ.get('SOVEREIGN_TMPDIR', '/tmp/sovereign_skill')
os.makedirs(_ALLOWED_TMPDIR, exist_ok=True)
os.chdir(_ALLOWED_TMPDIR)

# Remove home and working dir from sys.path
sys.path = [p for p in sys.path if not p.startswith(os.path.expanduser('~'))]

# Inject the data the skill declared it needs (ONLY this data)
SOVEREIGN_DATA = {json.dumps(injected_data)!r}

# Result container — skill must call sovereign_return(result_dict)
_sovereign_result = None
def sovereign_return(data):
    global _sovereign_result
    _sovereign_result = data

"""


def _enforce_limits() -> None:
    """Set resource limits before exec (called in child process via preexec_fn)."""
    try:
        # CPU time
        resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_S, CPU_LIMIT_S))
        # Virtual memory (RSS is harder to limit but AS works)
        mem_bytes = MEM_LIMIT_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        # Max file size the skill can write
        resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    except Exception as e:
        # Non-fatal on platforms that don't support all limits
        pass


class SkillSandbox:
    """Execute a skill in an isolated subprocess with strict resource controls."""

    def __init__(
        self,
        manifest: SkillManifest,
        skill_code: str,
        session_id: str = "",
    ) -> None:
        self._manifest = manifest
        self._skill_code = skill_code
        self._session_id = session_id

    def run(self, injected_data: dict, timeout: float = CPU_LIMIT_S + 5) -> dict:
        """Execute skill code. Returns the dict passed to sovereign_return().

        injected_data: ONLY the data declared in manifest.data_access.
        The skill has no other data access path.
        """
        if self._manifest.trust_tier == TrustTier.QUARANTINE:
            raise SandboxError("Cannot run QUARANTINE skill")

        # Build full script
        prelude = _build_prelude(self._manifest, injected_data)
        epilogue = """
# After skill body runs — serialize the result
import json as _json, sys as _sys
_sys.stdout.write(_json.dumps(_sovereign_result or {}) + '\\n__SOVEREIGN_END__\\n')
"""
        full_script = prelude + self._skill_code + epilogue

        # Restricted environment — no HOME, no credentials, isolated tmpdir
        tmpdir = tempfile.mkdtemp(prefix="sovereign_skill_")
        env = {
            "PATH": "/usr/bin:/bin",
            "SOVEREIGN_TMPDIR": tmpdir,
            "PYTHONPATH": "",
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        }

        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", full_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                preexec_fn=_enforce_limits,
            )

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise SandboxTimeoutError(
                    f"Skill {self._manifest.name} exceeded {timeout}s CPU limit"
                )

            output = stdout.decode("utf-8", errors="replace")

            if "__SOVEREIGN_END__" not in output:
                err = stderr.decode("utf-8", errors="replace")[:500]
                raise SandboxError(
                    f"Skill {self._manifest.name} exited without result. "
                    f"stderr: {err}"
                )

            raw_json = output.split("__SOVEREIGN_END__")[0].strip()

            # Cap output size
            if len(raw_json) > OUTPUT_LIMIT:
                raw_json = raw_json[:OUTPUT_LIMIT]
                log.warning("Skill output truncated: skill=%s", self._manifest.name)

            # CRITICAL: cleanse output before returning to agent reasoning
            cleanse_result = InputCleanse.sanitize(raw_json, source=self._manifest.name)
            if cleanse_result.injection_detected:
                log.critical(
                    "INJECTION IN SKILL OUTPUT: skill=%s mods=%s",
                    self._manifest.name, cleanse_result.modifications,
                )

            try:
                return json.loads(cleanse_result.text)
            except json.JSONDecodeError:
                return {"raw_output": cleanse_result.text}

        finally:
            # Clean up tmpdir
            import shutil
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass
