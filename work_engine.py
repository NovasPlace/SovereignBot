"""Sovereign — The Hands: Work Execution Engine.

Two components:
  WorkPlanner  — asks the LLM to decompose a task into tool-chain steps
  WorkExecutor — runs those steps in dependency order with retry/rollback

This is DIFFERENT from the existing Planner (skill router) and TaskQueue
(heartbeat LLM scheduler). This engine is the substrate for the Hand
state machines — Code Engineer, Research, Deployment, etc.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .toolbelt import ToolBelt, ToolResult

log = logging.getLogger("sovereign.work_engine")

_PLANNER_SYSTEM = """You are a work decomposition engine. Break a task into concrete, sequenced steps.

Available tools:
  file_read(path)                     — read a file
  file_write(path, content)           — write a complete file (always overwrites)
  file_list(path, pattern)            — list directory contents
  shell(command, timeout, workdir)    — execute a shell command
  memory_recall(query, limit)         — search organism memory
  memory_store(content, importance)   — store in memory
  web_search(query, max_results)      — search the web
  web_fetch(url)                      — fetch a web page

Rules:
- Return ONLY valid JSON, no prose, no markdown.
- Each step has an id, description, tool, params dict, depends_on list, quality_gate string.
- quality_gate options: "none", "file_exists", "exit_code_zero", "no_errors_in_output",
  "tests_pass", "syntax_valid", "contains:<text>", or "brain_eval:<question>"
- depends_on lists step ids that MUST complete before this step runs.
- estimated_seconds is your best guess.
- risk_level: "low", "medium", or "high"
- requires_approval: true if any step does something destructive or irreversible.

Output format:
{
  "steps": [
    {
      "id": "step_1",
      "description": "what this step does",
      "tool": "tool_name",
      "params": {"param": "value"},
      "depends_on": [],
      "quality_gate": "none",
      "estimated_seconds": 5
    }
  ],
  "risk_level": "low",
  "requires_approval": false,
  "estimated_total_seconds": 30
}"""


@dataclass
class PlanStep:
    id: str
    description: str
    tool: str
    params: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    quality_gate: str = "none"
    estimated_seconds: int = 5
    # Runtime state
    status: str = "pending"   # pending, running, success, failed, blocked, rolled_back
    result: Optional[ToolResult] = None
    error: Optional[str] = None
    attempts: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass
class WorkPlan:
    task: str
    steps: list[PlanStep]
    risk_level: str = "medium"
    requires_approval: bool = True
    estimated_seconds: int = 60
    failed_to_generate: bool = False


@dataclass
class WorkResult:
    task: str
    status: str                    # success, partial, failed, aborted
    steps: list[dict]
    duration: float
    summary: str = ""


class WorkPlanner:
    """Decomposes a task description into a concrete ToolBelt step plan."""

    def __init__(self, llm_fn) -> None:
        self._llm = llm_fn

    async def plan(self, task: str, context: str = "") -> WorkPlan:
        """Ask the LLM to produce a step plan for the task."""
        user_prompt = f"TASK: {task}"
        if context:
            user_prompt = f"CONTEXT:\n{context}\n\n{user_prompt}"

        try:
            raw = await self._llm(system=_PLANNER_SYSTEM, user=user_prompt)
            data = self._parse(raw)

            steps = []
            for i, s in enumerate(data.get("steps", []), 1):
                steps.append(PlanStep(
                    id=s.get("id") or f"step_{i}",
                    description=s.get("description", ""),
                    tool=s.get("tool", "shell"),
                    params=s.get("params", {}),
                    depends_on=s.get("depends_on", []),
                    quality_gate=s.get("quality_gate", "none"),
                    estimated_seconds=s.get("estimated_seconds", 5),
                ))

            plan = WorkPlan(
                task=task,
                steps=self._deduplicate_steps(steps),
                risk_level=data.get("risk_level", "medium"),
                requires_approval=data.get("requires_approval", True),
                estimated_seconds=data.get("estimated_total_seconds", 60),
            )
            log.info("WorkPlanner: %d steps, risk=%s, approval=%s",
                     len(steps), plan.risk_level, plan.requires_approval)
            return plan

        except Exception as e:
            log.error("WorkPlanner failed: %s", e)
            return WorkPlan(task=task, steps=[], failed_to_generate=True)

    def _deduplicate_steps(self, steps: list[PlanStep]) -> list[PlanStep]:
        """Remove redundant file write steps.

        If the plan writes a file in 'write' mode and then appends to it in
        a later step, the append step is dropped. LLMs often plan this way
        for small files but it causes content corruption.
        """
        written_files: set[str] = set()
        cleaned: list[PlanStep] = []
        for step in steps:
            if step.tool == "file_write":
                path = step.params.get("path", "")
                mode = step.params.get("mode", "write")
                is_append = mode in ("append", "a")
                if is_append and path in written_files:
                    log.debug("Dedup: dropping append step for %s (already written)", path)
                    continue
                if not is_append:
                    written_files.add(path)
            cleaned.append(step)
        if len(cleaned) < len(steps):
            log.info("WorkPlanner dedup: removed %d redundant append steps",
                     len(steps) - len(cleaned))
        return cleaned

    def _parse(self, raw: str) -> dict:
        text = raw.strip()
        # Try raw JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Strip fences
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass
        # Find first { ... }
        m = re.search(r"(\{[\s\S]+\})", text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Could not parse plan from LLM response: {raw[:100]}")


class WorkExecutor:
    """Runs a WorkPlan step by step — dependency-aware, retry-capable, rollback-safe."""

    MAX_RETRIES = 2

    def __init__(self, tools: ToolBelt, llm_fn=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._tool_map = {
            "file_read": tools.file_read,
            "file_write": tools.file_write,
            "file_list": tools.file_list,
            "shell": tools.shell,
            "memory_recall": tools.memory_recall,
            "memory_store": tools.memory_store,
            "web_search": tools.web_search,
            "web_fetch": tools.web_fetch,
        }

    async def execute(self, plan: WorkPlan) -> WorkResult:
        """Execute a plan in dependency order. Returns full result with per-step audit."""
        t0 = time.time()
        step_map = {s.id: s for s in plan.steps}

        # Track completed and rollback stack
        rollback_stack: list[ToolResult] = []

        while True:
            ready = self._find_ready(plan.steps)

            if not ready:
                running = [s for s in plan.steps if s.status == "running"]
                pending = [s for s in plan.steps if s.status == "pending"]
                if not running and not pending:
                    break  # done
                if not running and pending:
                    # Deadlock — some pending steps have failed deps
                    for s in pending:
                        s.status = "blocked"
                        s.error = "Dependency failed"
                    break
                await asyncio.sleep(0.1)
                continue

            # Execute ready steps (parallel if no inter-deps)
            await asyncio.gather(*[self._run_step(s, rollback_stack) for s in ready])

        duration = time.time() - t0
        succeeded = sum(1 for s in plan.steps if s.status == "success")
        total = len(plan.steps)

        if succeeded == total:
            status = "success"
        elif succeeded > 0:
            status = "partial"
        else:
            status = "failed"

        return WorkResult(
            task=plan.task,
            status=status,
            steps=[{"id": s.id, "status": s.status, "error": s.error,
                    "description": s.description}
                   for s in plan.steps],
            duration=duration,
            summary=f"{succeeded}/{total} steps succeeded in {duration:.1f}s",
        )

    async def _run_step(self, step: PlanStep, rollback_stack: list) -> None:
        """Execute one step with retry logic."""
        step.status = "running"
        step.started_at = time.time()

        for attempt in range(self.MAX_RETRIES + 1):
            step.attempts = attempt + 1

            result = await self._invoke(step)

            if result.success:
                # Run quality gate
                passed, gate_error = await self._check_gate(step, result)
                if passed:
                    step.status = "success"
                    step.result = result
                    step.finished_at = time.time()
                    if result.rollback:
                        rollback_stack.append(result)
                    log.info("Step %s SUCCESS (attempt %d)", step.id, attempt + 1)
                    return
                else:
                    step.error = f"Quality gate failed: {gate_error}"
                    log.warning("Step %s gate failed: %s", step.id, gate_error)
            else:
                step.error = result.error
                log.warning("Step %s failed (attempt %d): %s",
                            step.id, attempt + 1, result.error)

            if attempt < self.MAX_RETRIES:
                # Try to get a fix from the LLM
                fixed_params = await self._get_fix(step, result)
                if fixed_params:
                    step.params = fixed_params
                else:
                    break  # LLM says unfixable
            else:
                break

        step.status = "failed"
        step.finished_at = time.time()

    async def _invoke(self, step: PlanStep) -> ToolResult:
        """Call the right tool with the step's params."""
        fn = self._tool_map.get(step.tool)
        if not fn:
            return ToolResult(False, step.tool,
                              error=f"Unknown tool: {step.tool}")
        try:
            return await fn(**step.params)
        except TypeError as e:
            return ToolResult(False, step.tool,
                              error=f"Bad params for {step.tool}: {e}")
        except Exception as e:
            return ToolResult(False, step.tool, error=str(e))

    async def _check_gate(self, step: PlanStep,
                           result: ToolResult) -> tuple[bool, str]:
        """Evaluate a quality gate. Returns (passed, reason if failed)."""
        gate = step.quality_gate or "none"

        if gate == "none":
            return True, ""
        if gate == "file_exists":
            path = step.params.get("path", "")
            exists = path and os.path.exists(os.path.expanduser(path))
            return exists, "" if exists else f"File not found: {path}"
        if gate == "exit_code_zero":
            code = result.metadata.get("exit_code", -1)
            return code == 0, "" if code == 0 else f"Exit code {code}"
        if gate == "no_errors_in_output":
            text = str(result.data or "").lower()
            bad = ["error", "exception", "traceback", "fatal", "failed"]
            hit = next((b for b in bad if b in text), None)
            return hit is None, "" if hit is None else f"Output contains '{hit}'"
        if gate == "syntax_valid":
            path = step.params.get("path", "")
            if path.endswith(".py"):
                check = await self._tools.shell(
                    f"python3 -c \"import ast; ast.parse(open('{path}').read())\"",
                    timeout=10)
                return check.success, check.error or ""
            return True, ""
        if gate.startswith("contains:"):
            needle = gate[len("contains:"):]
            ok = needle in str(result.data or "")
            return ok, "" if ok else f"Output missing '{needle}'"
        if gate.startswith("brain_eval:"):
            if not self._llm:
                return True, ""
            question = gate[len("brain_eval:"):]
            ans = await self._llm(
                system="Answer 'yes' or 'no' only.",
                user=f"{question}\n\nOutput:\n{str(result.data)[:400]}")
            ok = "yes" in ans.lower()
            return ok, "" if ok else f"Brain eval failed: {ans[:60]}"

        return True, ""  # unknown gate → pass

    async def _get_fix(self, step: PlanStep, result: ToolResult) -> Optional[dict]:
        """Ask the LLM to suggest fixed params for a failed step."""
        if not self._llm:
            return None
        prompt = (
            f"A step failed. Suggest corrected params (JSON only, no prose).\n"
            f"Tool: {step.tool}\nParams: {json.dumps(step.params)}\n"
            f"Error: {result.error}\n"
            f"If unfixable, respond exactly: UNFIXABLE"
        )
        try:
            raw = await self._llm(system="You are a debugging assistant.", user=prompt)
            if "UNFIXABLE" in raw.upper():
                return None
            m = re.search(r"\{[\s\S]+\}", raw)
            if m:
                return json.loads(m.group(0))
        except Exception:
            pass
        return None

    def _find_ready(self, steps: list[PlanStep]) -> list[PlanStep]:
        """Steps whose dependencies are all satisfied."""
        done = {s.id for s in steps if s.status == "success"}
        failed = {s.id for s in steps if s.status in ("failed", "blocked")}
        ready = []
        for s in steps:
            if s.status != "pending":
                continue
            # Block if any dep failed
            if any(d in failed for d in s.depends_on):
                s.status = "blocked"
                s.error = "Dependency failed"
                continue
            if all(d in done for d in s.depends_on):
                ready.append(s)
        return ready


# Import at bottom to avoid circular deps
import os
