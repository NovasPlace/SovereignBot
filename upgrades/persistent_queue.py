# sovereign/upgrades/persistent_queue.py
"""
UPGRADE 1: Persistent TaskQueue — PostgreSQL-backed task execution.

Replaces the in-memory TaskQueue. Tasks survive restarts.
On boot, any task with status='running' is resumed automatically.

Schema: tasks + task_steps tables (see schema.sql)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("sovereign.taskqueue")


@dataclass
class TaskStep:
    step_index: int
    description: str
    status: str = "pending"
    tools_allowed: list[str] = field(default_factory=list)
    depends_on: list[int] = field(default_factory=list)
    success_criteria: str = ""
    result: str | None = None
    error: str | None = None
    attempts: int = 0
    max_attempts: int = 3
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class Task:
    id: str
    goal: str
    status: str = "pending"
    created_by: str = ""
    parent_task_id: str | None = None
    priority: int = 0
    scratchpad: str = ""
    result: str | None = None
    error: str | None = None
    steps: list[TaskStep] = field(default_factory=list)
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PersistentTaskQueue:
    """
    PostgreSQL-backed task queue. Tasks and steps persist across restarts.
    
    Usage:
        queue = PersistentTaskQueue(dsn="dbname=sovereign")
        task = await queue.create_task("Deploy the new API", steps=[...])
        await queue.start_task(task.id)
        
        # On restart:
        resumed = await queue.resume_interrupted()
        # Returns list of tasks that were mid-execution
    """

    def __init__(self, dsn: str = "dbname=sovereign"):
        self.dsn = dsn
        self._conn: psycopg2.extensions.connection | None = None
        self._initialized = False

    def _init_db(self, conn) -> None:
        """Create the necessary schema if it does not exist."""
        sql = """
            CREATE TABLE IF NOT EXISTS tasks (
                id VARCHAR(64) PRIMARY KEY,
                goal TEXT NOT NULL,
                status VARCHAR(32) DEFAULT 'pending',
                created_by VARCHAR(128) DEFAULT '',
                parent_task_id VARCHAR(64),
                priority INT DEFAULT 0,
                scratchpad TEXT DEFAULT '',
                result TEXT,
                error TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                started_at TIMESTAMP WITH TIME ZONE,
                finished_at TIMESTAMP WITH TIME ZONE
            );
            
            CREATE TABLE IF NOT EXISTS task_steps (
                task_id VARCHAR(64) REFERENCES tasks(id) ON DELETE CASCADE,
                step_index INT NOT NULL,
                description TEXT NOT NULL,
                status VARCHAR(32) DEFAULT 'pending',
                tools_allowed JSONB DEFAULT '[]'::jsonb,
                depends_on JSONB DEFAULT '[]'::jsonb,
                success_criteria TEXT DEFAULT '',
                result TEXT,
                error TEXT,
                attempts INT DEFAULT 0,
                max_attempts INT DEFAULT 3,
                started_at TIMESTAMP WITH TIME ZONE,
                finished_at TIMESTAMP WITH TIME ZONE,
                PRIMARY KEY (task_id, step_index)
            );
        """
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.warning("TaskQueue schema init skipped or failed: %s", e)

    def _get_conn(self) -> psycopg2.extensions.connection:
        """Get or create connection. Class has close() for cleanup."""
        if self._conn is None or self._conn.closed:
            conn = psycopg2.connect(self.dsn)
            try:
                conn.autocommit = False
            except Exception:
                conn.close()
                raise
            self._conn = conn
            
            if not self._initialized:
                self._initialized = True
                self._init_db(self._conn)
                
        return self._conn

    def _execute(self, sql: str, params: tuple = ()) -> list[dict]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                if cur.description:
                    rows = cur.fetchall()
                else:
                    rows = []
            conn.commit()
            return [dict(r) for r in rows]
        except Exception:
            conn.rollback()
            raise

    # ── CREATE ──

    async def create_task(
        self,
        goal: str,
        steps: list[dict] | None = None,
        created_by: str = "",
        parent_task_id: str | None = None,
        priority: int = 0,
    ) -> Task:
        """Create a new task with optional pre-defined steps."""
        task_id = str(uuid.uuid4())[:12]

        self._execute(
            """INSERT INTO tasks (id, goal, status, created_by, parent_task_id, priority)
               VALUES (%s, %s, 'pending', %s, %s, %s)""",
            (task_id, goal, created_by, parent_task_id, priority),
        )

        task_steps = []
        if steps:
            for i, step_def in enumerate(steps):
                self._execute(
                    """INSERT INTO task_steps
                       (task_id, step_index, description, tools_allowed, depends_on,
                        success_criteria, max_attempts)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        task_id,
                        i,
                        step_def.get("description", ""),
                        json.dumps(step_def.get("tools_allowed", [])),
                        json.dumps(step_def.get("depends_on", [])),
                        step_def.get("success_criteria", ""),
                        step_def.get("max_attempts", 3),
                    ),
                )
                task_steps.append(TaskStep(
                    step_index=i,
                    description=step_def.get("description", ""),
                    tools_allowed=step_def.get("tools_allowed", []),
                    depends_on=step_def.get("depends_on", []),
                    success_criteria=step_def.get("success_criteria", ""),
                    max_attempts=step_def.get("max_attempts", 3),
                ))

        log.info("Task created: id=%s goal=%s steps=%d", task_id, goal[:60], len(task_steps))

        return Task(
            id=task_id,
            goal=goal,
            created_by=created_by,
            parent_task_id=parent_task_id,
            priority=priority,
            steps=task_steps,
        )

    # ── READ ──

    async def get_task(self, task_id: str) -> Task | None:
        """Load a task and its steps from the database."""
        rows = self._execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        if not rows:
            return None

        row = rows[0]
        step_rows = self._execute(
            "SELECT * FROM task_steps WHERE task_id = %s ORDER BY step_index",
            (task_id,),
        )

        steps = [
            TaskStep(
                step_index=s["step_index"],
                description=s["description"],
                status=s["status"],
                tools_allowed=s.get("tools_allowed") or [],
                depends_on=s.get("depends_on") or [],
                success_criteria=s.get("success_criteria", ""),
                result=s.get("result"),
                error=s.get("error"),
                attempts=s.get("attempts", 0),
                max_attempts=s.get("max_attempts", 3),
                started_at=s.get("started_at"),
                finished_at=s.get("finished_at"),
            )
            for s in step_rows
        ]

        return Task(
            id=row["id"],
            goal=row["goal"],
            status=row["status"],
            created_by=row.get("created_by", ""),
            parent_task_id=row.get("parent_task_id"),
            priority=row.get("priority", 0),
            scratchpad=row.get("scratchpad", ""),
            result=row.get("result"),
            error=row.get("error"),
            steps=steps,
            created_at=row.get("created_at"),
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
        )

    async def list_tasks(
        self,
        status: str | None = None,
        limit: int = 20,
    ) -> list[Task]:
        """List tasks, optionally filtered by status."""
        if status:
            rows = self._execute(
                "SELECT id FROM tasks WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                (status, limit),
            )
        else:
            rows = self._execute(
                "SELECT id FROM tasks ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )

        tasks = []
        for row in rows:
            task = await self.get_task(row["id"])
            if task:
                tasks.append(task)
        return tasks

    # ── UPDATE ──

    async def update_task_status(self, task_id: str, status: str,
                                   result: str | None = None,
                                   error: str | None = None):
        """Update task-level status."""
        extra_cols = ""
        params: list = [status]

        if status == "running":
            extra_cols += ", started_at = now()"
        elif status in ("done", "failed", "cancelled"):
            extra_cols += ", finished_at = now()"

        if result is not None:
            extra_cols += ", result = %s"
            params.append(result)
        if error is not None:
            extra_cols += ", error = %s"
            params.append(error)

        params.append(task_id)
        self._execute(
            f"UPDATE tasks SET status = %s{extra_cols} WHERE id = %s",
            tuple(params),
        )
        log.info("Task %s → %s", task_id, status)

    async def update_step_status(
        self,
        task_id: str,
        step_index: int,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ):
        """Update a single step's status."""
        extra_cols = ""
        params: list = [status]

        if status == "running":
            extra_cols += ", started_at = now(), attempts = attempts + 1"
        elif status in ("done", "failed", "skipped"):
            extra_cols += ", finished_at = now()"

        if result is not None:
            extra_cols += ", result = %s"
            params.append(result)
        if error is not None:
            extra_cols += ", error = %s"
            params.append(error)

        params.extend([task_id, step_index])
        self._execute(
            f"UPDATE task_steps SET status = %s{extra_cols} WHERE task_id = %s AND step_index = %s",
            tuple(params),
        )

    async def update_scratchpad(self, task_id: str, scratchpad: str):
        """Replace the task's scratchpad content."""
        self._execute(
            "UPDATE tasks SET scratchpad = %s WHERE id = %s",
            (scratchpad, task_id),
        )

    async def add_steps(self, task_id: str, steps: list[dict]):
        """Add new steps to an existing task (for replanning)."""
        # Get current max step_index
        rows = self._execute(
            "SELECT COALESCE(MAX(step_index), -1) as max_idx FROM task_steps WHERE task_id = %s",
            (task_id,),
        )
        start_idx = rows[0]["max_idx"] + 1

        for i, step_def in enumerate(steps):
            idx = start_idx + i
            self._execute(
                """INSERT INTO task_steps
                   (task_id, step_index, description, tools_allowed, depends_on,
                    success_criteria, max_attempts)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    task_id,
                    idx,
                    step_def.get("description", ""),
                    json.dumps(step_def.get("tools_allowed", [])),
                    json.dumps(step_def.get("depends_on", [])),
                    step_def.get("success_criteria", ""),
                    step_def.get("max_attempts", 3),
                ),
            )

        log.info("Added %d steps to task %s (starting at index %d)", len(steps), task_id, start_idx)

    # ── RESUME ──

    async def resume_interrupted(self) -> list[Task]:
        """
        Find tasks that were running when the bot last shut down.
        Reset their current running step to pending so they can retry.
        """
        rows = self._execute(
            "SELECT id FROM tasks WHERE status = 'running'"
        )

        resumed = []
        for row in rows:
            task_id = row["id"]

            # Reset any running steps to pending
            self._execute(
                """UPDATE task_steps SET status = 'pending'
                   WHERE task_id = %s AND status = 'running'""",
                (task_id,),
            )

            task = await self.get_task(task_id)
            if task:
                resumed.append(task)
                log.info("Resuming interrupted task: %s (%s)", task_id, task.goal[:40])

        return resumed

    # ── QUERY HELPERS ──

    async def next_pending_step(self, task_id: str) -> TaskStep | None:
        """Get the next step that's ready to execute (dependencies met)."""
        task = await self.get_task(task_id)
        if not task:
            return None

        done_indices = {
            s.step_index for s in task.steps
            if s.status in ("done", "skipped")
        }

        for step in task.steps:
            if step.status != "pending":
                continue
            # Check dependencies
            deps_met = all(d in done_indices for d in step.depends_on)
            if deps_met:
                return step

        return None

    async def all_steps_terminal(self, task_id: str) -> bool:
        """Check if all steps are in a terminal state."""
        rows = self._execute(
            """SELECT COUNT(*) as total,
                      COUNT(*) FILTER (WHERE status IN ('done','failed','skipped')) as terminal
               FROM task_steps WHERE task_id = %s""",
            (task_id,),
        )
        if not rows:
            return True
        return rows[0]["total"] == rows[0]["terminal"]

    async def get_step_count(self, task_id: str) -> dict:
        """Get step status counts."""
        rows = self._execute(
            """SELECT status, COUNT(*) as cnt
               FROM task_steps WHERE task_id = %s
               GROUP BY status""",
            (task_id,),
        )
        return {r["status"]: r["cnt"] for r in rows}

    # ── CLEANUP ──

    async def cancel_task(self, task_id: str, reason: str = ""):
        """Cancel a task and all its pending steps."""
        self._execute(
            "UPDATE task_steps SET status = 'skipped' WHERE task_id = %s AND status = 'pending'",
            (task_id,),
        )
        await self.update_task_status(task_id, "cancelled", error=reason)

    async def expire_stale(self, max_age_hours: int = 24):
        """Mark tasks that have been running too long as failed."""
        self._execute(
            """UPDATE tasks SET status = 'failed', error = 'Stale: exceeded max age'
               WHERE status = 'running'
               AND started_at < now() - interval '%s hours'""",
            (max_age_hours,),
        )

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
