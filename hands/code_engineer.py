"""Sovereign — The Hands: Code Engineer.

A full autonomous software engineering pipeline. The flagship Hand.

State machine:
  UNDERSTAND → PLAN → IMPLEMENT → VERIFY → SHIP → COMPLETE
                          ↑            │
                          └──  DEBUG ←─┘  (max 3 cycles)

"Never touch a new codebase until you scan everything in order to
UNDERSTAND and MAKE REASON with it." — Frost
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("sovereign.hands.code_engineer")


def _decode_llm_code(text: str) -> str:
    """Decode literal \\n/\\t, strip fences and trailing prose.
    Kept in sync with toolbelt._decode_llm_code.
    """
    if "\\n" in text and "\n" not in text:
        text = text.replace("\\n", "\n").replace("\\t", "\t")
    text = text.strip()
    fence_match = re.search(r"```[a-z]*\n([\s\S]+?)```", text)
    if fence_match:
        return fence_match.group(1).strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    # Strip trailing Note: prose that llama3.1:8b appends
    lines = text.split("\n")
    last_code = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("Note:") or lines[i].strip() == "":
            last_code = i
        else:
            break
    return "\n".join(lines[:last_code]).strip()

# Priority files to read first when mapping a codebase


def _clean_path(raw: str) -> str:
    """Extract just the path from an LLM plan line.

    LLMs append descriptions like 'file.py (add tests)' — strip everything
    starting from the first '(' or whitespace after the filename portion.
    """
    m = re.match(r"([^\s(]+)", raw)
    return m.group(1) if m else raw


def _extract_file_content(raw: str, target_path: str) -> str:
    """Extract the code block for a specific file from a multi-file LLM response.

    The LLM often returns ALL requested files in one response, formatted as:
        /path/to/file.py
        ```python
        ...code...
        ```

        /path/to/other.py
        ```python
        ...code...
        ```

    We find the fence block that immediately follows a line containing target_path
    (or its basename). Falls back to _decode_llm_code for single-file responses.
    """
    fname = os.path.basename(target_path)

    # Decode literal \\n first
    if "\\n" in raw and "\n" not in raw:
        raw = raw.replace("\\n", "\n").replace("\\t", "\t")

    lines = raw.split("\n")

    # Find the line that mentions our target file
    target_idx = None
    for i, line in enumerate(lines):
        if fname in line or target_path in line:
            target_idx = i
            # Keep looking — take the LAST occurrence (most specific)

    if target_idx is not None:
        # Find the NEXT fence block starting after target_idx
        in_fence = False
        fence_lines = []
        for line in lines[target_idx + 1:]:
            stripped = line.strip()
            if stripped.startswith("```"):
                if not in_fence:
                    in_fence = True
                    continue  # skip opening fence
                else:
                    break  # hit closing fence — done
            if in_fence:
                fence_lines.append(line)
            elif stripped and not in_fence and fence_lines:
                # non-empty line between fence blocks = another file's header
                break
        if fence_lines:
            return "\n".join(fence_lines).strip()

    # Fallback: single-file response — use generic decoder
    return _decode_llm_code(raw)


_KEY_FILE_NAMES = {
    "README", "readme", "README.md", "setup.py", "setup.cfg",
    "pyproject.toml", "package.json", "Cargo.toml", "main.py",
    "app.py", "index.py", "server.py", "config.py", "settings.py",
    "Makefile", "Dockerfile", "requirements.txt", "poetry.lock",
}
_CODE_EXTS = {".py", ".js", ".ts", ".go", ".rs", ".cpp", ".c", ".java"}


@dataclass
class CodeRequest:
    description: str
    workdir: str
    user_id: str = ""
    test_command: str = ""   # run this to verify the implementation
    language: str = "python"


@dataclass
class CodeResult:
    task: str
    status: str              # success, failed, aborted
    phase_reached: str
    debug_cycles: int = 0
    files_modified: list = field(default_factory=list)
    abort_reason: str = ""
    summary: str = ""


class CodeEngineerHand:
    """Autonomous software engineering — from understanding to shipping."""

    MAX_ITERATIONS = 20
    MAX_DEBUG = 3
    MAX_REPLAN = 2
    MAX_FILES_TO_READ = 20

    def __init__(self, tools, work_planner, work_executor, llm_fn) -> None:
        self._tools = tools
        self._planner = work_planner
        self._executor = work_executor
        self._llm = llm_fn

    async def execute(self, request: CodeRequest) -> CodeResult:
        """Drive the request through the full engineering pipeline."""
        state = _CodeState(request=request)

        while state.phase not in ("complete", "abort") and state.iteration < self.MAX_ITERATIONS:
            state.iteration += 1
            log.info("[CodeEngineer] phase=%s iteration=%d", state.phase, state.iteration)

            if state.phase == "understand":
                await self._understand(state)
            elif state.phase == "plan":
                await self._plan(state)
            elif state.phase == "implement":
                await self._implement(state)
            elif state.phase == "verify":
                await self._verify(state)
            elif state.phase == "debug":
                await self._debug(state)
            elif state.phase == "ship":
                await self._ship(state)

        if state.iteration >= self.MAX_ITERATIONS:
            state.phase = "abort"
            state.abort_reason = "Maximum iterations exceeded"

        return CodeResult(
            task=request.description,
            status="success" if state.phase == "complete" else "failed",
            phase_reached=state.phase,
            debug_cycles=state.debug_count,
            files_modified=state.files_modified,
            abort_reason=state.abort_reason,
            summary=state.summary,
        )

    # ── PHASE 1: UNDERSTAND ─────────────────────────────────────────────────

    async def _understand(self, state: _CodeState) -> None:
        workdir = os.path.expanduser(state.request.workdir)

        # Map the codebase
        listing = await self._tools.file_list(workdir, "**/*")
        if not listing.success:
            state.phase = "abort"
            state.abort_reason = f"Cannot read workdir: {listing.error}"
            return

        all_files = listing.data or []
        state.codebase_files = all_files

        # Prioritize key files to read
        key = [f for f in all_files if os.path.basename(f) in _KEY_FILE_NAMES]
        code = [f for f in all_files if os.path.splitext(f)[1] in _CODE_EXTS
                and f not in key]
        to_read = (key + code)[:self.MAX_FILES_TO_READ]

        for rel_path in to_read:
            abs_path = os.path.join(workdir, rel_path)
            r = await self._tools.file_read(abs_path)
            if r.success:
                state.file_contents[rel_path] = r.data

        # Synthesize understanding
        files_summary = "\n".join(
            f"  {path}: {content[:300]}..."
            for path, content in list(state.file_contents.items())[:8]
        )
        all_paths = "\n".join(f"  {f}" for f in all_files[:60])

        understanding = await self._llm(
            system="You are a senior engineer analyzing a codebase.",
            user=(
                f"TASK: {state.request.description}\n\n"
                f"FILES:\n{all_paths}\n\n"
                f"KEY FILE CONTENTS:\n{files_summary}\n\n"
                "Provide a concise analysis covering:\n"
                "1. What this codebase does\n"
                "2. Architecture and structure\n"
                "3. Key entry points\n"
                "4. Testing infrastructure\n"
                "5. What needs to change for the task"
            )
        )
        state.understanding = understanding
        state.phase = "plan"

    # ── PHASE 2: PLAN ───────────────────────────────────────────────────────

    async def _plan(self, state: _CodeState) -> None:
        """Ask the LLM which files need to be created/modified."""
        response = await self._llm(
            system="You are a senior engineer decomposing a coding task.",
            user=(
                f"Task: {state.request.description}\n"
                f"Codebase: {state.request.workdir}\n"
                f"Understanding: {state.understanding[:500]}\n\n"
                "List the exact files that need to be CREATED or MODIFIED. "
                "Also list any shell commands to run (installs, tests, etc).\n"
                "Format: one item per line, prefix with:\n"
                "  CREATE: <path>\n"
                "  MODIFY: <path>\n"
                "  SHELL: <command>\n"
                "Nothing else. No prose."
            )
        )

        state.files_to_create = []
        state.files_to_modify = []
        state.shell_steps = []

        for line in response.strip().split("\n"):
            line = line.strip()
            if line.startswith("CREATE:"):
                path = _clean_path(line.replace("CREATE:", "").strip())
                if not os.path.isabs(path):
                    path = os.path.join(state.request.workdir, path)
                state.files_to_create.append(path)
            elif line.startswith("MODIFY:"):
                path = _clean_path(line.replace("MODIFY:", "").strip())
                if not os.path.isabs(path):
                    path = os.path.join(state.request.workdir, path)
                state.files_to_modify.append(path)
            elif line.startswith("SHELL:"):
                state.shell_steps.append(line.replace("SHELL:", "").strip())

        total = len(state.files_to_create) + len(state.files_to_modify)
        if total == 0:
            state.replan_count += 1
            if state.replan_count > self.MAX_REPLAN:
                state.phase = "abort"
                state.abort_reason = "Could not identify any files to create/modify"
            return  # retry plan

        log.info("[CodeEngineer] plan: create=%d modify=%d shell=%d",
                 len(state.files_to_create), len(state.files_to_modify),
                 len(state.shell_steps))
        state.phase = "implement"

    # ── PHASE 3: IMPLEMENT ──────────────────────────────────────────────────

    async def _implement(self, state: _CodeState) -> None:
        """Generate each file's COMPLETE content in one LLM call and write it."""
        # Demote MODIFY to CREATE for any file explicitly mentioned in the task
        # (the task says to "write" them, so existing content is stale)
        task_lower = state.request.description.lower()
        promoted = set()
        for path in list(state.files_to_modify):
            fname = os.path.basename(path).lower()
            if fname in task_lower or fname.replace(".py", "").replace("_", " ") in task_lower:
                state.files_to_create.append(path)
                promoted.add(path)
        state.files_to_modify = [p for p in state.files_to_modify if p not in promoted]
        if promoted:
            log.info("[CodeEngineer] promoted %d MODIFY→CREATE (task explicitly names them)",
                     len(promoted))

        all_files = [
            (path, "create") for path in state.files_to_create
        ] + [
            (path, "modify") for path in state.files_to_modify
        ]

        # Deduplicate by path — keep the first occurrence (CREATE wins over MODIFY)
        seen_paths: set[str] = set()
        deduped = []
        for path, action in all_files:
            if path not in seen_paths:
                seen_paths.add(path)
                deduped.append((path, action))
        if len(deduped) < len(all_files):
            log.info("[CodeEngineer] dedup: %d duplicate paths removed",
                     len(all_files) - len(deduped))
        all_files = deduped

        for path, action in all_files:
            existing = ""
            if action == "modify" and os.path.exists(path):
                r = await self._tools.file_read(path)
                existing = r.data if r.success else ""

            fname = os.path.basename(path)
            is_test_file = fname.startswith("test_") or fname.endswith("_test.py")

            if is_test_file:
                sys_prompt = (
                    "You are a senior QA engineer writing pytest tests.\n"
                    "CRITICAL: Write ONLY pytest test functions (def test_...). NO implementation code.\n"
                    "Do NOT write the actual functions being tested — only the tests.\n"
                    "No markdown fences. No explanation. ONLY the test file content."
                )
                user_prompt = (
                    f"Task: {state.request.description}\n"
                    f"Write the pytest test file: {fname}\n"
                    f"Language: {state.request.language}\n\n"
                    "Requirements:\n"
                    "- Import from the module under test\n"
                    "- Write def test_...() functions using assert\n"
                    "- Cover all functions and edge cases\n"
                    "- Use pytest.raises() for error cases\n\n"
                    "Write the complete test file now:"
                )
            else:
                sys_prompt = (
                    "You are a senior engineer. Write complete, production-quality code.\n"
                    "Rules: No markdown fences. No explanation. ONLY the file content.\n"
                    "The entire file — not just the changed parts."
                )
                user_prompt = (
                    f"Task: {state.request.description}\n"
                    f"File to {action}: {path}\n"
                    f"Language: {state.request.language}\n"
                    f"Codebase context: {state.understanding[:400]}\n\n"
                    + (f"Current content:\n{existing[:1000]}\n\n" if existing else "")
                    + "Write the complete updated file content:"
                )

            code = await self._llm(system=sys_prompt, user=user_prompt)

            # Extract just the code for THIS file from the response
            # (LLMs often dump all files in one response — find the right section)
            content = _extract_file_content(code, path)

            # ToolBelt.file_write handles decode internally for code files
            result = await self._tools.file_write(path, content)
            if result.success:
                state.files_modified.append(path)
                log.info("[CodeEngineer] wrote %s (%d bytes)", path, len(code))
            else:
                log.error("[CodeEngineer] failed to write %s: %s", path, result.error)

        # Run any shell steps from the plan (installs, pre-steps, etc)
        for cmd in state.shell_steps:
            r = await self._tools.shell(cmd, workdir=state.request.workdir, timeout=60)
            if not r.success:
                log.warning("[CodeEngineer] shell step failed: %s -> %s", cmd, r.error)

        if state.files_modified:
            state.phase = "verify"
        else:
            state.phase = "debug"
            state.debug_errors = ["No files were written successfully"]

    # ── PHASE 4: VERIFY ─────────────────────────────────────────────────────

    async def _verify(self, state: _CodeState) -> None:
        errors = []

        # Syntax check all modified Python files
        for path in state.files_modified:
            if path.endswith(".py"):
                r = await self._tools.shell(
                    f'python3 -c "import ast; ast.parse(open(\'{path}\').read())"',
                    timeout=10
                )
                if not r.success:
                    errors.append(f"Syntax error in {path}: {r.error}")

        # Run test suite if provided
        if state.request.test_command and not errors:
            r = await self._tools.shell(
                state.request.test_command, timeout=120,
                workdir=state.request.workdir
            )
            if not r.success:
                errors.append(f"Tests failed: {r.error or r.data}")

        if errors:
            state.debug_errors = errors
            # debug_count is incremented in _debug, not here — avoid double-increment
            if state.debug_count >= self.MAX_DEBUG:
                state.phase = "abort"
                state.abort_reason = f"Failed after {self.MAX_DEBUG} debug cycles"
            else:
                state.phase = "debug"
        else:
            state.phase = "ship"

    # ── PHASE 5: DEBUG ──────────────────────────────────────────────────────

    async def _debug(self, state: _CodeState) -> None:
        state.debug_count += 1  # single canonical increment
        if state.debug_count > self.MAX_DEBUG:
            state.phase = "abort"
            state.abort_reason = f"Max debug cycles ({self.MAX_DEBUG}) exceeded"
            return
        errors_text = "\n".join(state.debug_errors or ["unknown error"])

        # Read current versions of modified files
        current = {}
        for path in state.files_modified:
            r = await self._tools.file_read(path)
            if r.success:
                current[path] = r.data

        fix_response = await self._llm(
            system="You are a debugging expert. Fix errors in code. Be precise and complete.",
            user=(
                f"Task: {state.request.description}\n"
                f"Debug cycle: {state.debug_count}/{self.MAX_DEBUG}\n"
                f"Errors:\n{errors_text}\n\n"
                + "\n".join(f"--- {p} ---\n{c[:800]}" for p, c in current.items())
                + "\n\nFor each file needing a fix:\n"
                  "FILE: path/to/file.py\n```python\ncomplete fixed content\n```"
            )
        )

        # Parse and apply fixes
        fixes = self._parse_fixes(fix_response)
        for path, content in fixes.items():
            # Always decode literal \n sequences from LLM output
            await self._tools.file_write(path, _decode_llm_code(content))
            if path not in state.files_modified:
                state.files_modified.append(path)

        state.debug_errors = []
        state.phase = "verify"

    # ── PHASE 6: SHIP ───────────────────────────────────────────────────────

    async def _ship(self, state: _CodeState) -> None:
        workdir = state.request.workdir

        # Auto-format
        for path in state.files_modified:
            if path.endswith(".py"):
                await self._tools.shell(f"black {path} 2>/dev/null; isort {path} 2>/dev/null")

        # Git commit if in a repo
        git = await self._tools.shell("git status --short", workdir=workdir)
        if git.success and git.data.strip():
            await self._tools.shell("git add -A", workdir=workdir)
            msg_raw = await self._llm(
                system="Write a single-line git commit message, max 72 chars.",
                user=f"Task: {state.request.description}"
            )
            msg = re.sub(r'["`]', "'", msg_raw.strip())[:72]
            await self._tools.shell(f'git commit -m "{msg}"', workdir=workdir)

        state.summary = (
            f"Completed: {state.request.description}. "
            f"Modified {len(state.files_modified)} file(s). "
            f"Debug cycles: {state.debug_count}."
        )
        state.phase = "complete"

    def _parse_fixes(self, text: str) -> dict:
        """Extract FILE: path + code block pairs from LLM response."""
        fixes = {}
        current_path = None
        current_lines = []
        in_block = False

        for line in text.split("\n"):
            if line.startswith("FILE:"):
                if current_path and current_lines:
                    fixes[current_path] = "\n".join(current_lines)
                current_path = line.replace("FILE:", "").strip()
                current_lines = []
                in_block = False
            elif line.startswith("```"):
                in_block = not in_block
            elif in_block and current_path:
                current_lines.append(line)

        if current_path and current_lines:
            fixes[current_path] = "\n".join(current_lines)
        return fixes


@dataclass
class _CodeState:
    request: CodeRequest
    phase: str = "understand"
    iteration: int = 0
    codebase_files: list = field(default_factory=list)
    file_contents: dict = field(default_factory=dict)
    understanding: str = ""
    # Plan phase output (new structured plan)
    files_to_create: list = field(default_factory=list)
    files_to_modify: list = field(default_factory=list)
    shell_steps: list = field(default_factory=list)
    # Legacy plan (kept for compatibility)
    plan: Any = None
    execution_result: Any = None
    files_modified: list = field(default_factory=list)
    debug_errors: list = field(default_factory=list)
    debug_count: int = 0
    replan_count: int = 0
    abort_reason: str = ""
    summary: str = ""
