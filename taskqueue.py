"""Sovereign — Autonomous Task Queue: the bot gets a job.

Turns Sovereign from a reactive chatbot into a proactive worker.
Tasks are multi-step projects that execute over time across heartbeat
cycles. The organism breaks work into steps, executes them autonomously,
reports progress, and delivers results.

"Build me a landing page" becomes:
1. Plan the layout → 2. Write HTML → 3. Write CSS → 4. Write JS →
5. Self-review → 6. Deliver to user

Each step runs during a heartbeat pulse when the organism is idle.
The user can check progress, reprioritize, or cancel at any time.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Awaitable

log = logging.getLogger("sovereign.taskqueue")


class TaskStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    BLOCKED = "blocked"         # waiting on user input
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskStep:
    """A single step in a multi-step task."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str = ""
    action: str = ""            # skill to invoke or "llm" for brain work
    action_payload: dict = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    output: str = ""
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0

    @property
    def elapsed_ms(self) -> float:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at) * 1000
        return 0.0


@dataclass
class Task:
    """A multi-step autonomous task."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    user_id: str = ""
    steps: list[TaskStep] = field(default_factory=list)
    status: TaskStatus = TaskStatus.QUEUED
    priority: int = 50          # 0-100, higher = more urgent
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    result: str = ""
    error: str = ""

    @property
    def progress(self) -> float:
        """0.0 to 1.0 progress based on completed steps."""
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED))
        return done / len(self.steps)

    @property
    def current_step(self) -> Optional[TaskStep]:
        """Get the next pending step."""
        for step in self.steps:
            if step.status == StepStatus.PENDING:
                return step
        return None

    @property
    def progress_str(self) -> str:
        pct = int(self.progress * 100)
        done = sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)
        return f"{pct}% ({done}/{len(self.steps)} steps)"

    def summary(self) -> str:
        """Human-readable status summary."""
        lines = [f"📋 **{self.title}** — {self.status.value} ({self.progress_str})"]
        for i, step in enumerate(self.steps, 1):
            icon = {"pending": "⬜", "running": "🔄", "completed": "✅",
                     "failed": "❌", "skipped": "⏭️"}.get(step.status.value, "⬜")
            lines.append(f"  {icon} {i}. {step.description}")
        if self.result:
            lines.append(f"\n📦 Result: {self.result[:200]}")
        return "\n".join(lines)


class TaskQueue:
    """Manages autonomous multi-step tasks."""

    MAX_CONCURRENT = 1          # one task at a time for now
    MAX_STEP_RETRIES = 2        # retry failed steps

    def __init__(
        self,
        llm_fn: Optional[Callable] = None,
        send_fn: Optional[Callable] = None,
        skill_executor: Optional[Callable] = None,
    ) -> None:
        self._tasks: list[Task] = []
        self._llm_fn = llm_fn
        self._send_fn = send_fn
        self._skill_executor = skill_executor
        self._step_retries: dict[str, int] = {}
        log.info("TaskQueue initialized")

    # ── Task Management ──────────────────────────────────────────────────────

    def create_task(
        self,
        title: str,
        description: str,
        user_id: str,
        steps: list[dict] | None = None,
        priority: int = 50,
    ) -> Task:
        """Create a new task. Steps can be provided or auto-generated."""
        task = Task(
            title=title,
            description=description,
            user_id=user_id,
            priority=priority,
        )

        if steps:
            for step_data in steps:
                task.steps.append(TaskStep(
                    description=step_data.get("description", ""),
                    action=step_data.get("action", "llm"),
                    action_payload=step_data.get("payload", {}),
                ))
        else:
            # Auto-generate steps from description
            task.steps = self._auto_plan(description)
            task.status = TaskStatus.PLANNING

        self._tasks.append(task)
        log.info("Task created: %s (%d steps) for user %s",
                 task.title, len(task.steps), user_id)
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        for t in self._tasks:
            if t.id == task_id:
                return t
        return None

    def get_active_tasks(self, user_id: str | None = None) -> list[Task]:
        """Get all non-terminal tasks, optionally filtered by user."""
        active = [
            t for t in self._tasks
            if t.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        ]
        if user_id:
            active = [t for t in active if t.user_id == user_id]
        return sorted(active, key=lambda t: t.priority, reverse=True)

    def cancel_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if task and task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            task.status = TaskStatus.CANCELLED
            log.info("Task cancelled: %s", task.title)
            return True
        return False

    def list_tasks(self, user_id: str) -> str:
        """Human-readable task list."""
        active = self.get_active_tasks(user_id)
        if not active:
            return "No active tasks."
        return "\n\n".join(t.summary() for t in active)

    # ── Execution (called by heartbeat) ──────────────────────────────────────

    async def tick(self, state: str) -> None:
        """Process one step of the highest-priority active task.

        Called by heartbeat. Only runs when organism is idle or awake.
        """
        if state in ("dreaming", "deep_sleep"):
            return  # don't work while dreaming

        active = [
            t for t in self._tasks
            if t.status in (TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.PLANNING)
        ]
        if not active:
            return

        task = active[0]  # highest priority (already sorted at creation)

        if task.status == TaskStatus.QUEUED:
            task.status = TaskStatus.IN_PROGRESS
            task.started_at = time.time()
            log.info("Task started: %s", task.title)

            # Notify user
            if self._send_fn:
                try:
                    await self._send_fn(
                        task.user_id,
                        f"🚀 Starting task: **{task.title}**\n{task.progress_str}"
                    )
                except Exception:
                    pass

        # Get next step
        step = task.current_step
        if not step:
            # All steps done
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            task.result = self._compile_results(task)
            log.info("Task completed: %s", task.title)

            if self._send_fn:
                try:
                    await self._send_fn(
                        task.user_id,
                        f"✅ Task complete: **{task.title}**\n\n{task.result[:500]}"
                    )
                except Exception:
                    pass
            return

        # Execute the step
        await self._execute_step(task, step)

    async def _execute_step(self, task: Task, step: TaskStep) -> None:
        """Execute a single task step."""
        step.status = StepStatus.RUNNING
        step.started_at = time.time()
        log.info("Step running: %s (task=%s)", step.description, task.title)

        try:
            if step.action == "llm" and self._llm_fn:
                # Use the LLM brain for this step
                system = (
                    f"You are executing step {step.description} of task '{task.title}'.\n"
                    f"Task description: {task.description}\n"
                    f"Previous step outputs: {self._get_previous_outputs(task, step)}\n"
                    "Produce the output for this step. Be thorough but concise."
                )
                step.output = await self._llm_fn(
                    system=system,
                    user=step.description,
                )
            elif step.action and self._skill_executor:
                # Use a skill for this step
                result = await self._skill_executor(
                    step.action, step.action_payload
                )
                step.output = str(result)
            else:
                step.output = f"Step acknowledged: {step.description}"

            step.status = StepStatus.COMPLETED
            step.completed_at = time.time()
            log.info("Step completed: %s (%.0fms)",
                     step.description, step.elapsed_ms)

        except Exception as e:
            retry_key = f"{task.id}:{step.id}"
            retries = self._step_retries.get(retry_key, 0)

            if retries < self.MAX_STEP_RETRIES:
                self._step_retries[retry_key] = retries + 1
                step.status = StepStatus.PENDING  # retry next tick
                log.warning("Step failed (retry %d/%d): %s — %s",
                            retries + 1, self.MAX_STEP_RETRIES,
                            step.description, e)
            else:
                step.status = StepStatus.FAILED
                step.error = str(e)
                step.completed_at = time.time()
                task.status = TaskStatus.FAILED
                task.error = f"Step '{step.description}' failed: {e}"
                log.error("Step permanently failed: %s — %s",
                          step.description, e)

                if self._send_fn:
                    try:
                        await self._send_fn(
                            task.user_id,
                            f"❌ Task failed: **{task.title}**\n"
                            f"Step: {step.description}\n"
                            f"Error: {step.error}"
                        )
                    except Exception:
                        pass

    def _get_previous_outputs(self, task: Task, current: TaskStep) -> str:
        """Get outputs from completed previous steps for context chaining."""
        outputs = []
        for step in task.steps:
            if step.id == current.id:
                break
            if step.status == StepStatus.COMPLETED and step.output:
                outputs.append(f"[{step.description}]: {step.output[:200]}")
        return "\n".join(outputs[-3:]) if outputs else "None yet."

    def _compile_results(self, task: Task) -> str:
        """Compile all step outputs into a final result."""
        parts = []
        for step in task.steps:
            if step.status == StepStatus.COMPLETED and step.output:
                parts.append(f"**{step.description}**\n{step.output}")
        return "\n\n---\n\n".join(parts) if parts else "Task completed with no output."

    def _auto_plan(self, description: str) -> list[TaskStep]:
        """Generate default steps from a task description."""
        # Simple default plan — the LLM will refine during execution
        return [
            TaskStep(description="Analyze requirements", action="llm"),
            TaskStep(description="Plan approach", action="llm"),
            TaskStep(description="Execute primary work", action="llm"),
            TaskStep(description="Review and verify", action="llm"),
            TaskStep(description="Compile deliverable", action="llm"),
        ]

    @property
    def active_count(self) -> int:
        return len(self.get_active_tasks())

    @property
    def total_completed(self) -> int:
        return sum(1 for t in self._tasks if t.status == TaskStatus.COMPLETED)
