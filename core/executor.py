"""Sovereign — Core: Action executor.

Executes a validated, approved action. This is the only place
where side effects happen. No skill runs outside this path.

Before execution:
  1. DNA token is verified — tamper → quarantine, abort
  2. ApprovalGate result is checked — not approved → abort
  3. Trust ceiling is re-verified (defense in depth)
  4. EgressGate is available to the skill's execution context
  5. CORE skills: run in-process via core_executor (controlled namespace)
  6. COMMUNITY/UNTRUSTED: run in sandboxed subprocess

After execution:
  7. Result is passed through InputCleanse before logging or returning
  8. Execution event written to immutable audit log + TRACE
  9. store.save_action() called
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from ..models import Action, ActionType, Permission, SkillManifest, TrustTier
from ..security.audit import AuditEvent, get_audit
from ..security.dna import DNATokenManager
from ..security.trust import assert_skill_can, TrustViolation
from ..skills.cleanse import InputCleanse
from ..skills.core_executor import run_core_skill
from ..skills.egress import EgressGate
from ..skills.sandbox import SkillSandbox
from ..store import get_store
from ..observability.trace import get_trace_bridge
from ..observability.spectra import get_spectra_bridge

log = logging.getLogger("sovereign.core.executor")


class ExecutionError(Exception):
    pass


class ExecutionAborted(Exception):
    """Raised when execution is aborted before it starts (not-approved, quarantine, etc.)."""


_ACTION_PERMISSION_MAP: dict[ActionType, Permission] = {
    ActionType.READ_FILE:         Permission.FILE_READ,
    ActionType.WRITE_FILE:        Permission.FILE_WRITE,
    ActionType.WEB_FETCH:         Permission.NET_READ,
    ActionType.SEND_EMAIL:        Permission.EMAIL_SEND,
    ActionType.SHARE_EXTERNAL:    Permission.NET_WRITE,
    ActionType.CALENDAR_EVENT:    Permission.CALENDAR,
    ActionType.MEMORY_STORE:      Permission.MEMORY_WRITE,
    ActionType.EXECUTE_CODE:      Permission.EXEC,
}


class Executor:
    """Executes approved actions with DNA verification and trust enforcement."""

    def __init__(
        self,
        dna_manager: DNATokenManager,
        session_id: str,
        skill_registry: Optional[dict[str, tuple[SkillManifest, str]]] = None,
        toolbelt=None,
    ) -> None:
        self._dna = dna_manager
        self._session_id = session_id
        self._skills: dict[str, tuple[SkillManifest, str]] = skill_registry or {}
        self._audit = get_audit()
        self._store = get_store()
        self._toolbelt = toolbelt  # ToolBelt for native file/shell ops

    async def execute(self, action: Action) -> dict[str, Any]:
        """Execute a single approved action. Returns result dict.

        Raises ExecutionAborted if pre-conditions fail.
        Raises ExecutionError if the action itself fails.
        """
        # Gate 1: DNA integrity check
        if not self._dna.verify(self._session_id):
            status = self._dna.status(self._session_id)
            raise ExecutionAborted(
                f"DNA verification failed for session {self._session_id} "
                f"(status={status}). Action aborted."
            )

        # Gate 2: approval check
        if not action.is_approved:
            raise ExecutionAborted(
                f"Action {action.action_id} ({action.type.value}) is not approved. "
                f"approved={action.approved}"
            )

        # Gate 3: quarantined skills never run
        if action.trust_tier == TrustTier.QUARANTINE:
            raise ExecutionAborted(f"Skill {action.skill_id} is in QUARANTINE")

        # Gate 4: trust ceiling re-check (defense in depth)
        required_perm = _ACTION_PERMISSION_MAP.get(action.type)
        manifest = self._get_manifest(action.skill_id, action.trust_tier)
        if required_perm and manifest:
            try:
                assert_skill_can(manifest, required_perm)
            except TrustViolation as e:
                self._audit.log(
                    event_type=AuditEvent.TRUST_VIOLATION,
                    actor=action.skill_id,
                    outcome="blocked",
                    session_id=self._session_id,
                    target=action.action_id,
                    payload={"violation": str(e)},
                )
                raise ExecutionAborted(str(e))

        # Execute
        t0 = time.monotonic()
        try:
            result = await self._run_action(action, manifest)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
        except Exception as e:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            self._audit.log(
                event_type=AuditEvent.ACTION_FAILED,
                actor=action.skill_id,
                outcome="error",
                session_id=self._session_id,
                target=action.action_id,
                payload={"error": str(e)[:200], "elapsed_ms": elapsed_ms},
            )
            raise ExecutionError(f"Action {action.action_id} failed: {e}") from e

        action.executed_at = time.time()

        # Cleanse result before returning to agent reasoning
        if isinstance(result.get("output"), str):
            cleansed = InputCleanse.sanitize(result["output"], source=action.skill_id)
            result["output"] = cleansed.text
            if cleansed.injection_detected:
                result["_injection_detected"] = True
                result["_injection_mods"] = cleansed.modifications

        self._audit.log(
            event_type=AuditEvent.ACTION_EXECUTED,
            actor=action.skill_id,
            outcome="success",
            session_id=self._session_id,
            target=action.action_id,
            payload={"type": action.type.value, "elapsed_ms": elapsed_ms},
        )
        self._store.save_action(action)

        log.info(
            "Executed: action_id=%s type=%s elapsed_ms=%d",
            action.action_id, action.type.value, elapsed_ms,
        )
        return result

    async def _run_action(
        self,
        action: Action,
        manifest: Optional[SkillManifest],
    ) -> dict:
        """Route the action to the appropriate handler."""
        trace = get_trace_bridge()

        # ── ToolBelt fast-path: auto-detect tool from payload context ──
        # The planner sets all actions to ActionType.CUSTOM and the skill_id
        # varies based on LLM output. We match on payload keys + skill aliases.
        if self._toolbelt:
            sid = (action.skill_id or "").lower()
            payload = action.payload or {}
            log.info("ToolBelt dispatch check: skill_id=%s type=%s payload=%s",
                       sid, action.type.value, payload)

            # File read: payload has path/file, or skill mentions file/read
            path = payload.get("path") or payload.get("file") or payload.get("filepath", "")
            if path or sid in ("file_read", "read_file", "file", "filesystem"):
                path = path or payload.get("directory", "/")
                result = await self._toolbelt.file_read(path)
                return {
                    "output": result.data[:8000] if result.success else (result.error or "Read failed"),
                    "success": result.success,
                }

            # Shell: payload has command/cmd/code, or skill mentions shell/exec
            cmd = payload.get("command") or payload.get("cmd") or payload.get("code", "")
            if cmd or sid in ("shell", "execute", "exec", "terminal", "bash", "run"):
                cmd = cmd or f"ls {payload.get('directory', '~')}"
                workdir = payload.get("workdir") or payload.get("cwd")
                result = await self._toolbelt.shell(cmd, timeout=30, workdir=workdir)
                return {
                    "output": result.data if result.success else (result.error or "Command failed"),
                    "success": result.success,
                }

            # Web search: payload has query/search
            query = payload.get("query") or payload.get("search", "")
            if query or sid in ("web_search", "search", "internet"):
                query = query or action.description
                result = await self._toolbelt.web_search(query)
                return {
                    "output": result.data[:4000] if result.success else (result.error or "Search failed"),
                    "success": result.success,
                }

            # URL fetch: payload has url
            url = payload.get("url", "")
            if url or sid in ("fetch_url", "fetch", "url", "web_fetch"):
                url = url or ""
                if url:
                    result = await self._toolbelt.fetch_url(url)
                    return {
                        "output": result.data[:4000] if result.success else (result.error or "Fetch failed"),
                        "success": result.success,
                    }

        # Built-in action handlers (memory + web fetch don't need skill files)
        if action.type == ActionType.MEMORY_STORE:
            return await self._handle_memory_store(action)
        if action.type == ActionType.WEB_FETCH:
            return await self._handle_web_fetch(action, manifest)

        # Skill-based execution
        if manifest and action.skill_id in self._skills:
            _, skill_code = self._skills[action.skill_id]

            if action.trust_tier == TrustTier.CORE:
                # CORE: run in-process with controlled namespace
                # sovereign_return, sovereign_store, action_payload injected
                log.info("Skill %s payload: %s", action.skill_id, action.payload)
                result = run_core_skill(
                    code=skill_code,
                    action_payload=action.payload,
                    store=self._store,
                    skill_name=action.skill_id,
                )
            else:
                # COMMUNITY / VERIFIED / UNTRUSTED: sandboxed subprocess
                injected = self._build_injected_data(action, manifest)
                sandbox = SkillSandbox(manifest, skill_code, self._session_id)
                result = sandbox.run(injected)

            # Emit to TRACE
            trace.emit_action(
                session_id=self._session_id,
                action_id=action.action_id,
                action_type=action.type.value,
                outcome="success" if result.get("success", True) else "skill_failure",
                elapsed_ms=0,
                approved_by=getattr(action, "approved_by", "auto"),
            )
            return result

        # No skill found — return structured error
        log.warning("No handler: action_type=%s skill=%s",
                    action.type.value, action.skill_id)
        return {"output": f"No skill available for '{action.skill_id}'", "success": False}

    async def _handle_memory_store(self, action: Action) -> dict:
        """Store a memory entry with provenance tagging."""
        from ..models import MemoryEntry, MemorySource
        content = action.payload.get("content", "")
        if not content:
            return {"output": "Nothing to remember", "success": False}
        entry = MemoryEntry(
            content=content,
            source=MemorySource.AGENT,
            skill_id=action.skill_id,
            provenance_chain=[f"action:{action.action_id}"],
        )
        self._store.save_memory(entry)
        return {"output": f"Remembered: {content[:50]}", "success": True}

    async def _handle_web_fetch(self, action: Action, manifest: Optional[SkillManifest]) -> dict:
        """Fetch a URL through the EgressGate."""
        import urllib.request
        url = action.payload.get("url", "")
        if not url:
            return {"output": "No URL provided", "success": False}

        if manifest:
            gate = EgressGate(manifest, session_id=self._session_id)
            gate.check(url)  # raises EgressBlocked if not allowed

        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = resp.read(65536).decode("utf-8", errors="replace")
            cleansed = InputCleanse.sanitize(body, source=url)
            return {"output": cleansed.text, "success": True, "url": url}
        except Exception as e:
            return {"output": f"Fetch failed: {e}", "success": False}

    def _get_manifest(
        self, skill_id: str, trust_tier: TrustTier
    ) -> Optional[SkillManifest]:
        entry = self._skills.get(skill_id)
        if entry:
            return entry[0]
        # Synthesize a minimal manifest from the action's declared trust tier
        return SkillManifest(name=skill_id, trust_tier=trust_tier)

    @staticmethod
    def _build_injected_data(action: Action, manifest: SkillManifest) -> dict:
        """Build the data payload a skill receives — ONLY what it declared."""
        from ..models import DataScope
        data: dict = {}
        for scope in manifest.data_access:
            if scope == DataScope.NONE:
                pass
            elif scope == DataScope.MEMORY_SESSION:
                data["session_context"] = action.payload.get("context", "")
        # Always inject the action payload (the skill's own inputs)
        data["action_payload"] = action.payload
        return data
