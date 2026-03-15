"""Sovereign — Economy: Job Executor (Part 10).

Routes active jobs to the appropriate Hand and manages execution lifecycle.
Encodes results to memory for capability profile improvement.
"""
from __future__ import annotations

import logging
import os
import time
import uuid

from .models import ActiveJob

log = logging.getLogger("sovereign.economy.executor")

# Keyword → hand name mapping (ordered: more specific first)
_HAND_KEYWORDS: list[tuple[str, list[str]]] = [
    ("sysadmin",    ["devops", "linux", "docker", "kubernetes", "nginx",
                     "server", "deployment", "bash", "shell", "infra"]),
    ("research",    ["research", "analysis", "literature", "survey",
                     "market analysis", "competitive"]),
    ("writing",     ["documentation", "article", "blog", "copywriting",
                     "technical writing", "content"]),
    ("code_engineer", ["code", "python", "javascript", "typescript", "api",
                       "backend", "script", "automat", "web scraping",
                       "data processing", "bot", "integration"]),
]
_DEFAULT_HAND = "code_engineer"


class JobExecutor:
    """Executes accepted jobs using the most appropriate Hand.

    Requires `hands` dict of {name: HandInstance} from daemon.
    Every job execution is recorded in memory for future capability assessment.
    """

    def __init__(self, hands: dict | None = None, store=None) -> None:
        self._hands = hands or {}
        self._store = store

    async def execute_job(self, job: ActiveJob) -> ActiveJob:
        """Execute a job and return the updated ActiveJob record."""
        hand_name = self._select_hand(job)
        hand = self._hands.get(hand_name)

        if hand is None:
            job.status = "failed"
            job.error = f"Hand '{hand_name}' not available"
            log.error("JobExecutor: hand=%s unavailable for job=%r", hand_name, job.title)
            return job

        log.info(
            "JobExecutor: executing job=%r via hand=%s",
            job.title[:40], hand_name,
        )

        job.status = "in_progress"
        job.started_at = time.time()

        # Ensure workspace exists
        if not job.workspace:
            job.workspace = os.path.join(
                os.path.expanduser("~"), ".sovereign", "jobs", job.job_id
            )
        os.makedirs(job.workspace, exist_ok=True)

        try:
            result = await self._dispatch_to_hand(hand, hand_name, job)
            job.result = result
            success = result.get("status") == "success" if result else False
            job.status = "completed" if success else "failed"
            if not success:
                job.error = result.get("error", "Unknown failure") if result else "No result"

        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            log.exception("JobExecutor: hand=%s crashed on job=%r", hand_name, job.title)

        job.finished_at = time.time()
        job.actual_hours = (job.finished_at - job.started_at) / 3600

        self._encode_result(job)
        return job

    async def _dispatch_to_hand(
        self, hand, hand_name: str, job: ActiveJob
    ) -> dict:
        """Dispatch the job to the appropriate Hand type."""
        try:
            if hand_name == "code_engineer":
                from ..hands.code_engineer import CodeRequest
                req = CodeRequest(
                    description=job.requirements,
                    workdir=job.workspace,
                    user_id=job.user_id,
                    language="python",
                )
                state = await hand.execute(req)
                return {
                    "status": state.phase if state.phase == "complete" else "failed",
                    "error": getattr(state, "abort_reason", ""),
                    "files": getattr(state, "files_modified", []),
                }
            else:
                # Generic hand execution — all other hands accept a string
                result = await hand.execute(job.requirements)
                return {"status": "success", "result": str(result)[:500]}

        except Exception as exc:
            return {"status": "failed", "error": str(exc)}

    def _select_hand(self, job: ActiveJob) -> str:
        """Select the best hand for this job based on keyword matching."""
        combined = (job.title + " " + job.requirements).lower()

        for hand_name, keywords in _HAND_KEYWORDS:
            if any(kw in combined for kw in keywords):
                return hand_name

        return _DEFAULT_HAND

    def _encode_result(self, job: ActiveJob) -> None:
        """Record job completion in memory for future capability profiling."""
        if self._store is None:
            return

        success = job.status == "completed"
        emotion = "satisfaction" if success else "frustration"
        importance = 0.75 if job.bid_amount > 100 else 0.6

        try:
            from ..memory.cortex import MemoryType
            self._store.remember(
                content=(
                    f"Job {'completed' if success else 'failed'}: "
                    f"{job.title!r}. "
                    f"Duration: {job.actual_hours:.2f}h "
                    f"(estimated {job.estimated_hours:.1f}h). "
                    f"{'Earned' if success else 'Lost'}: ${job.bid_amount:.0f}"
                ),
                memory_type=MemoryType.EPISODIC,
                tags=[
                    "economy", "job", job.status, job.platform or "manual",
                    "task_execution",
                    "success" if success else "failure",
                ],
                importance=importance,
                emotion=emotion,
                source="job_executor",
                metadata={
                    "flashbulb": success and job.bid_amount > 100,
                    "amount": job.bid_amount,
                    "platform": job.platform,
                },
            )
        except Exception as exc:
            log.debug("JobExecutor: memory encode failed: %s", exc)

    def create_job(
        self,
        title: str,
        requirements: str,
        bid_amount: float,
        estimated_hours: float,
        user_id: str,
        platform: str = "manual",
    ) -> ActiveJob:
        """Factory: create an ActiveJob ready for execution."""
        return ActiveJob(
            job_id=uuid.uuid4().hex[:12],
            user_id=user_id,
            platform=platform,
            title=title,
            requirements=requirements,
            bid_amount=bid_amount,
            estimated_hours=estimated_hours,
            status="pending",
        )
