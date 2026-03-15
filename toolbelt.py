"""Sovereign — The Hands: Tool Belt.

The organism's primitive capabilities. Every work pipeline chains
these together. No hand can do anything that isn't built from these
primitives — which means every action is auditable, permission-gated,
and TRACE-logged at the primitive level.

Primitives:
  file_read, file_write, file_list
  shell
  memory_recall, memory_store
  web_search, web_fetch
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("sovereign.toolbelt")

# Directories the organism is allowed to read/write
_ALLOWED_ROOT = os.path.expanduser("~")
_SAFE_TMP = "/tmp/sovereign"

# Commands that will never be executed regardless of context
_BLOCKED_COMMANDS = [
    # Destructive
    (r":(){ :|:& };:", "fork bomb"),
    (r"dd\s+if=.*/dev/(?!null|zero)", "raw disk read"),
    (r"dd\s+of=.*/dev/(?!null|zero)", "raw disk write"),
    (r"mkfs", "filesystem format"),
    (r"> /dev/sd", "raw device write"),
    (r"rm\s+-rf\s+/\s*$", "wipe root"),
    (r"rm\s+-rf\s+~\s*$", "wipe home"),
    (r"rm\s+-rf\s+/home\s*$", "wipe home dir"),
    # Remote code execution
    (r"curl[^|]+\|\s*(ba)?sh", "remote script execution"),
    (r"wget[^|]+\|\s*(ba)?sh", "remote script execution"),
    # Privilege escalation
    (r"chmod\s+777\s+/", "world-writable root"),
    (r"chown\s+root", "chown to root"),
    (r"iptables\s+-F", "flush firewall"),
    # Persistence / backdoor
    (r"crontab", "crontab modification"),
    (r"\.ssh/authorized_keys", "SSH key injection"),
    (r">> /etc/passwd", "passwd file write"),
    (r">> /etc/shadow", "shadow file write"),
    # Reverse shell
    (r"nc\s+-[a-z]*e\s+/bin", "netcat reverse shell"),
    (r"bash\s+-i\s+>&\s+/dev/tcp", "bash reverse shell"),
    (r"python.*socket.*connect", "python reverse shell"),
    # Information exfiltration
    (r"cat\s+/etc/shadow", "shadow file read"),
    (r"cat\s+\.env\s*\|", "env pipe exfiltration"),
    (r"env\s*\|\s*(curl|wget|nc)", "env exfiltration"),
    (r"history\s*-c", "history wipe"),
]

# URLs that may never be fetched (SSRF protection)
_BLOCKED_URL_PATTERNS = [
    r"169\.254\.",        # link-local / AWS metadata
    r"100\.64\.",         # carrier-grade NAT
    r"file://",           # local file via URL
    r"gopher://",         # SSRF pivot
    r"dict://",           # SSRF pivot
]


def _decode_llm_code(text: str) -> str:
    """Decode literal \\n/\\t sequences, strip markdown fences and trailing prose.

    Handles these LLM output patterns:
    - Literal \\n instead of real newlines (llama3.1:8b)
    - ```python ... ``` fences around the content
    - Trailing 'Note: ...' paragraphs after the code block
    """
    # Decode literal backslash-n when the text has no real newlines
    if "\\n" in text and "\n" not in text:
        text = text.replace("\\n", "\n").replace("\\t", "\t")

    text = text.strip()

    # If the text contains a fenced block, extract just the contents of the
    # FIRST code fence (covers the case where LLM wraps the whole file)
    fence_match = re.search(r"```[a-z]*\n([\s\S]+?)```", text)
    if fence_match:
        return fence_match.group(1).strip()

    # Fallback: strip leading/trailing fences
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)

    # Strip any trailing prose after the last real code line
    # (llama appends "Note: ..." after the last function)
    lines = text.split("\n")
    last_code = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if line.startswith("Note:") or line.startswith("#note") or line == "":
            last_code = i
        else:
            break
    text = "\n".join(lines[:last_code])

    return text.strip()


@dataclass
class ToolResult:
    """The result of any primitive tool call."""
    success: bool
    tool: str
    data: Any = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    rollback: Optional[Callable] = None  # undo function if available

    def __str__(self) -> str:
        if self.success:
            preview = str(self.data)[:200] if self.data is not None else "(no output)"
            return f"[{self.tool}] OK: {preview}"
        return f"[{self.tool}] FAIL: {self.error}"


class ToolBelt:
    """Sovereign's primitive capabilities — the fingers on the hands."""

    def __init__(self, store=None, membrane=None) -> None:
        self._store = store
        self._membrane = membrane
        os.makedirs(_SAFE_TMP, exist_ok=True)
        log.info("ToolBelt initialized")

    # ── FILE OPERATIONS ──────────────────────────────────────────────────────

    async def file_read(self, path: str) -> ToolResult:
        """Read a file within allowed directories."""
        path = os.path.expanduser(path)
        if not self._path_allowed(path):
            return ToolResult(False, "file_read",
                              error=f"Path outside allowed directories: {path}")
        try:
            with open(path, "r", errors="replace") as f:
                content = f.read()
            size = len(content)
            # Cap at 100 KB to avoid context explosion
            if size > 100_000:
                content = content[:100_000] + f"\n[TRUNCATED at 100KB of {size} bytes]"
            log.debug("file_read: %s (%d bytes)", path, size)
            return ToolResult(True, "file_read", data=content,
                              metadata={"path": path, "size": size})
        except Exception as e:
            return ToolResult(False, "file_read", error=str(e))

    async def file_write(self, path: str, content: str,
                         mode: str = "write") -> ToolResult:
        """Write to a file. Creates backup before overwriting."""
        path = os.path.expanduser(path)
        if not self._path_allowed(path):
            return ToolResult(False, "file_write",
                              error=f"Path outside allowed directories: {path}")

        # Auto-create parent directory
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

        # For source code files, decode literal \\n/\\t that LLMs sometimes emit,
        # and strip accidental markdown fences.
        _, ext = os.path.splitext(path)
        if ext in {".py", ".js", ".ts", ".go", ".rs", ".sh", ".rb"}:
            content = _decode_llm_code(content)

        # Backup existing file for rollback
        backup: Optional[str] = None
        if mode == "write" and os.path.exists(path):
            try:
                with open(path) as f:
                    backup = f.read()
            except Exception:
                pass

        try:
            file_mode = "w" if mode == "write" else "a"
            with open(path, file_mode) as f:
                f.write(content)

            def _rollback():
                if backup is not None:
                    with open(path, "w") as f:
                        f.write(backup)
                    log.info("Rolled back: %s", path)
                else:
                    os.unlink(path)

            log.info("file_write: %s (%d bytes, mode=%s)", path, len(content), mode)
            return ToolResult(True, "file_write",
                              data=f"Wrote {len(content)} bytes to {path}",
                              metadata={"path": path, "backup": backup is not None},
                              rollback=_rollback)
        except Exception as e:
            return ToolResult(False, "file_write", error=str(e))

    async def file_list(self, path: str, pattern: str = "*") -> ToolResult:
        """List files matching a pattern (supports **)."""
        import glob
        path = os.path.expanduser(path)
        if not self._path_allowed(path):
            return ToolResult(False, "file_list",
                              error=f"Path outside allowed directories: {path}")
        try:
            glob_path = os.path.join(path, pattern)
            files = glob.glob(glob_path, recursive="**" in pattern)
            # Relative paths for readability
            rel = [os.path.relpath(f, path) for f in sorted(files)]
            return ToolResult(True, "file_list", data=rel,
                              metadata={"path": path, "count": len(rel)})
        except Exception as e:
            return ToolResult(False, "file_list", error=str(e))

    # ── SHELL ────────────────────────────────────────────────────────────────

    async def shell(self, command: str, timeout: int = 30,
                    workdir: Optional[str] = None) -> ToolResult:
        """Execute a shell command with security scanning and timeout."""
        danger = self._scan_command(command)
        if danger:
            log.warning("TOOLBELT: blocked command (%s): %s", danger, command[:80])
            return ToolResult(False, "shell",
                              error=f"Command blocked by security policy: {danger}")

        if workdir:
            workdir = os.path.expanduser(workdir)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(False, "shell",
                                  error=f"Timed out after {timeout}s: {command[:60]}")

            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            ok = proc.returncode == 0
            log.debug("shell: exit=%d cmd=%s", proc.returncode, command[:60])
            return ToolResult(ok, "shell",
                              data=out,
                              error=err if not ok else None,
                              metadata={"exit_code": proc.returncode,
                                        "command": command[:120]})
        except Exception as e:
            return ToolResult(False, "shell", error=str(e))

    # ── MEMORY ───────────────────────────────────────────────────────────────

    async def memory_recall(self, query: str, limit: int = 5) -> ToolResult:
        """Search the organism's memory."""
        if not self._store:
            return ToolResult(False, "memory_recall", error="No store connected")
        try:
            results = self._store.search_memories(query, limit=limit)
            data = [{"content": m.content, "confidence": getattr(m, "confidence", 0.8)}
                    for m in results]
            return ToolResult(True, "memory_recall", data=data,
                              metadata={"query": query, "found": len(data)})
        except Exception as e:
            return ToolResult(False, "memory_recall", error=str(e))

    async def memory_store(self, content: str, importance: float = 0.5) -> ToolResult:
        """Store something in memory."""
        if not self._store:
            return ToolResult(False, "memory_store", error="No store connected")
        try:
            from ..models import MemoryEntry, MemorySource
            entry = MemoryEntry(
                content=content,
                source=MemorySource.AGENT,
                confidence=importance,
                provenance_chain=["toolbelt"],
            )
            self._store.save_memory(entry)
            return ToolResult(True, "memory_store", data="Stored",
                              metadata={"preview": content[:80]})
        except Exception as e:
            return ToolResult(False, "memory_store", error=str(e))

    # ── WEB ──────────────────────────────────────────────────────────────────

    async def web_search(self, query: str, max_results: int = 5) -> ToolResult:
        """Search the web and screen results through membrane."""
        try:
            import httpx
            # Use DuckDuckGo instant answers API (no API key needed)
            url = "https://api.duckduckgo.com/"
            params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1"}
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                data = resp.json()

            results = []
            # RelatedTopics as search results
            for item in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(item, dict) and "Text" in item:
                    text = item["Text"]
                    link = item.get("FirstURL", "")
                    # Screen through membrane
                    if self._membrane:
                        screening = self._membrane.screen(text, source="web_search")
                        if screening.action == "block":
                            continue
                        text = screening.cleaned
                    results.append({"text": text, "url": link})

            return ToolResult(True, "web_search", data=results,
                              metadata={"query": query, "count": len(results)})
        except Exception as e:
            return ToolResult(False, "web_search", error=str(e))

    async def web_fetch(self, url: str) -> ToolResult:
        """Fetch a URL and screen content through membrane."""
        if self._url_blocked(url):
            return ToolResult(False, "web_fetch",
                              error="URL blocked by SSRF protection policy")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Sovereign/1.0"})
                content = resp.text

            # Screen content
            if self._membrane:
                screening = self._membrane.screen(content[:10000], source="web_fetch")
                if screening.action == "block":
                    return ToolResult(False, "web_fetch",
                                      error="Content blocked by membrane: threat detected")
                content = screening.cleaned

            return ToolResult(True, "web_fetch", data=content[:8000],
                              metadata={"url": url, "status": resp.status_code})
        except Exception as e:
            return ToolResult(False, "web_fetch", error=str(e))

    # ── SECURITY ─────────────────────────────────────────────────────────────

    def _path_allowed(self, path: str) -> bool:
        abs_path = os.path.abspath(path)
        return abs_path.startswith(_ALLOWED_ROOT) or abs_path.startswith(_SAFE_TMP)

    def _scan_command(self, command: str) -> Optional[str]:
        for pattern, reason in _BLOCKED_COMMANDS:
            if re.search(pattern, command, re.IGNORECASE):
                return reason
        return None

    def _url_blocked(self, url: str) -> bool:
        for pattern in _BLOCKED_URL_PATTERNS:
            if re.search(pattern, url):
                return True
        return False
