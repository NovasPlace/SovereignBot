"""Sovereign — Skills: CORE skill in-process executor.

CORE skills run in the main process (not subprocess sandbox) because
they need access to sovereign_store, sovereign_return, and other built-ins
that can't be serialized across subprocess boundaries.

Security model for CORE skills:
- They are pre-audited (SHA-256 hash verified at load time)
- They run with the same trust level as Sovereign itself
- They are authored by Sovereign team only — never from ClawHub
- Any violation still gets written to the immutable audit log

The execution context provides:
    sovereign_return(result: dict)  — return value from skill
    sovereign_store                 — read-only view of the store
    action_payload: dict            — the action's payload (inputs)
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("sovereign.skills.core_executor")


class SkillReturnValue(BaseException):
    """Control flow signal — exits skill execution without being caught by skill's own try/except.

    Inherits BaseException (not Exception) so that bare `except Exception` blocks
    inside skill code cannot accidentally swallow it. Only `except BaseException`
    or bare `except:` would catch it, which CORE skills must not use.
    """
    def __init__(self, result: dict) -> None:
        self.result = result


def run_core_skill(
    code: str,
    action_payload: dict,
    store=None,
    skill_name: str = "unknown",
) -> dict:
    """Execute a CORE skill in-process with a controlled namespace.

    Returns the dict passed to sovereign_return().
    If the skill never calls sovereign_return(), returns a generic success.
    """
    result_container: dict = {}

    def sovereign_return(result: dict) -> None:
        """Skills call this to return their output."""
        result_container.update(result)
        raise SkillReturnValue(result)

    # Build the execution namespace — skills can only see what's here
    namespace: dict[str, Any] = {
        "__builtins__": _safe_builtins(),
        "sovereign_return": sovereign_return,
        "sovereign_store": store,
        "action_payload": action_payload,
    }

    try:
        exec(compile(code, f"<skill:{skill_name}>", "exec"), namespace)
    except SkillReturnValue:
        pass  # normal exit path
    except Exception as e:
        log.error("CORE skill '%s' raised exception: %s", skill_name, e)
        return {"output": f"Skill error: {e}", "success": False}

    # If skill never called sovereign_return, return whatever's in the container
    if not result_container:
        return {"output": "Skill completed (no return value)", "success": True}

    return result_container


def _safe_builtins() -> dict:
    """Allow most Python builtins except truly dangerous ones."""
    import builtins
    safe = vars(builtins).copy()
    # These have no place in skill execution
    for blocked in ("__import__", "breakpoint", "input", "open", "compile", "exec", "eval"):
        safe.pop(blocked, None)
    # Allow import via __import__'s safe wrapper
    safe["__import__"] = _safe_import
    return safe


def _safe_import(name: str, globals=None, locals=None, fromlist=(), level=0):
    """Allow standard library imports only — no arbitrary code loading.

    This must mimic Python's built-in __import__ exactly:
    - 'import urllib.parse' calls __import__('urllib.parse', ..., fromlist=[])
      and expects the TOP-LEVEL module (urllib) to be returned, with .parse set
    - 'from urllib.parse import urlencode' calls __import__('urllib.parse',
      ..., fromlist=['urlencode']) and expects the SUBMODULE returned
    """
    # SECURITY: subprocess, os, sys are EXCLUDED — they allow sandbox escape.
    # Skills needing shell/filesystem access must use ToolBelt primitives
    # which are audited, permission-gated, and TRACE-logged.
    ALLOWED_MODULES = {
        "json", "re", "pathlib", "shlex",
        "urllib", "urllib.parse", "urllib.request", "urllib.error",
        "html", "hashlib", "hmac", "base64", "time", "datetime",
        "collections", "itertools", "functools", "math", "random",
        "string", "textwrap", "io", "struct", "typing",
        "dataclasses", "enum", "abc", "contextlib",
    }
    root = name.split(".")[0]
    if root not in ALLOWED_MODULES:
        raise ImportError(
            f"Skill import denied: '{name}'. Only stdlib modules allowed in CORE skills."
        )
    import importlib
    # Import the full dotted module
    module = importlib.import_module(name)
    # If fromlist is non-empty, return the leaf module (e.g. urllib.parse)
    # If fromlist is empty, return the root package (e.g. urllib)
    if fromlist:
        return module
    # Return root package with submodules attached (mirrors CPython behavior)
    import sys
    return sys.modules[root]
