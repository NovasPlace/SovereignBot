"""Sovereign — Economy: Delivery Manager + Earnings Tracker (Part 10).

Handles the final two phases of the job pipeline:
  DELIVER — package work, notify client, handle revisions
  COLLECT — track earnings, flag overdue payments

Every delivery to a client requires user approval.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Callable, Awaitable

from .models import ActiveJob, EarningsData

log = logging.getLogger("sovereign.economy.delivery")


class EarningsTracker:
    """Track economic activity in Cortex memory.

    Uses the store (Cortex) as the source of truth —
    no separate database needed.
    """

    def __init__(self, store=None) -> None:
        self._store = store

    def track_pending(self, job: ActiveJob) -> None:
        """Record a pending payment in memory."""
        if self._store is None:
            return
        try:
            from ..memory.cortex import MemoryType
            self._store.remember(
                content=(
                    f"Pending payment: ${job.bid_amount:.0f} "
                    f"for {job.title!r} on {job.platform or 'manual'}"
                ),
                memory_type=MemoryType.EPISODIC,
                tags=["economy", "payment", "pending", job.platform or "manual"],
                importance=0.7,
                emotion="curiosity",
                source="earnings_tracker",
                metadata={"amount": job.bid_amount, "job_id": job.job_id},
            )
        except Exception as exc:
            log.debug("EarningsTracker.track_pending: %s", exc)

    def track_received(self, job: ActiveJob, amount: float | None = None) -> None:
        """Record a received payment in memory."""
        amount = amount if amount is not None else job.bid_amount
        if self._store is None:
            return
        try:
            from ..memory.cortex import MemoryType
            self._store.remember(
                content=f"Payment received: ${amount:.0f} for {job.title!r}",
                memory_type=MemoryType.EPISODIC,
                tags=["economy", "payment", "received", job.platform or "manual"],
                importance=0.8,
                emotion="satisfaction",
                source="earnings_tracker",
                metadata={
                    "amount": amount,
                    "job_id": job.job_id,
                    "flashbulb": amount > 500,
                },
            )
            log.info("EarningsTracker: payment received $%.0f for %r", amount, job.title)
        except Exception as exc:
            log.debug("EarningsTracker.track_received: %s", exc)

    def get_summary(self) -> EarningsData:
        """Financial summary computed from memory."""
        if self._store is None:
            return EarningsData()

        try:
            received_mems = self._store.recall("payment received", limit=200)
            pending_mems  = self._store.recall("payment pending",  limit=200)
            completed_mems = self._store.recall("job completed",   limit=200)
            failed_mems    = self._store.recall("job failed",      limit=200)

            total_earned  = sum(
                (m.metadata or {}).get("amount", 0.0) for m in received_mems
            )
            total_pending = sum(
                (m.metadata or {}).get("amount", 0.0) for m in pending_mems
            )
            completed = len(completed_mems)
            failed    = len(failed_mems)
            success_rate = completed / max(1, completed + failed)

            return EarningsData(
                total_earned=total_earned,
                total_pending=total_pending,
                jobs_completed=completed,
                jobs_failed=failed,
                success_rate=success_rate,
            )
        except Exception as exc:
            log.debug("EarningsTracker.get_summary: %s", exc)
            return EarningsData()

    def get_overdue_payments(self, days: int = 7) -> list[dict]:
        """Find pending payments older than `days` days."""
        if self._store is None:
            return []
        cutoff = time.time() - days * 86400
        try:
            mems = self._store.recall("payment pending", limit=100)
            return [
                {"content": m.content, "amount": (m.metadata or {}).get("amount", 0)}
                for m in mems
                if getattr(m, "created_at", 0) and m.created_at < cutoff
            ]
        except Exception:
            return []


class DeliveryManager:
    """Packages and delivers completed work. Manages revisions and payment tracking.

    Delivery always requires user approval before sending to clients.
    Revisions are auto-executed up to 3 times; after that, escalate to user.
    """

    MAX_REVISIONS = 3

    def __init__(
        self,
        store=None,
        llm_fn=None,
        send_approval_fn: Callable[[str, str, str], Awaitable[None]] | None = None,
        wait_approval_fn: Callable[[str], Awaitable[bool]] | None = None,
        temporal=None,
        earnings_tracker: EarningsTracker | None = None,
    ) -> None:
        self._store = store
        self._llm = llm_fn
        self._send_approval = send_approval_fn
        self._wait_approval = wait_approval_fn
        self._temporal = temporal
        self.earnings = earnings_tracker or EarningsTracker(store)

    async def deliver(self, job: ActiveJob) -> bool:
        """Package work and deliver to client — requires user approval."""
        import uuid

        deliverable_summary = self._summarize_deliverables(job)

        # Craft delivery message
        delivery_msg = await self._craft_delivery_message(job, deliverable_summary)

        action_id = f"deliver_{uuid.uuid4().hex[:8]}"
        approval_text = (
            f"✅ *Job complete:* {job.title}\n\n"
            f"*Deliverables:* {deliverable_summary}\n\n"
            f"*Delivery message to client:*\n{delivery_msg}\n\n"
            f"Approve delivery?"
        )

        if self._send_approval:
            await self._send_approval(job.user_id, approval_text, action_id)
        else:
            log.info("DeliveryManager: no approval channel — skipping delivery")
            return False

        approved = False
        if self._wait_approval:
            try:
                approved = await self._wait_approval(action_id)
            except Exception:
                pass

        if not approved:
            log.info("Delivery rejected by user: %r", job.title[:40])
            return False

        job.status = "delivered"

        # Track pending payment
        self.earnings.track_pending(job)

        # Schedule payment follow-up via temporal perception
        if self._temporal is not None:
            try:
                follow_up_time = datetime.now() + timedelta(days=3)
                self._temporal.create_intention(
                    user_id=job.user_id,
                    action=(
                        f"Check if payment received for '{job.title}' "
                        f"(${job.bid_amount:.0f})"
                    ),
                    trigger_time=follow_up_time,
                )
            except Exception as exc:
                log.debug("Temporal intention failed: %s", exc)

        log.info("Job delivered: %r $%.0f", job.title[:40], job.bid_amount)
        return True

    async def handle_revision(
        self, job: ActiveJob, feedback: str, executor=None
    ) -> ActiveJob:
        """Re-execute job with client feedback. Escalates after MAX_REVISIONS."""
        job.revision_count += 1

        if job.revision_count > self.MAX_REVISIONS:
            if self._send_approval:
                await self._send_approval(
                    job.user_id,
                    f"⚠️ Job '{job.title}' is on revision #{job.revision_count}.\n\n"
                    f"Client feedback: {feedback}\n\n"
                    f"This may need your direct involvement.",
                    f"escalate_{job.job_id[:8]}",
                )
            job.status = "failed"
            job.error = f"Too many revisions ({job.revision_count})"
            return job

        # Append feedback to requirements then re-execute
        job.requirements += f"\n\nCLIENT REVISION #{job.revision_count}:\n{feedback}"
        job.status = "in_revision"

        if executor is not None:
            job = await executor.execute_job(job)
        else:
            log.warning("DeliveryManager: no executor for revision — cannot re-run")

        return job

    def _summarize_deliverables(self, job: ActiveJob) -> str:
        """Summarize what was produced for the delivery message."""
        result = job.result or {}
        files = result.get("files", [])
        if files:
            file_list = ", ".join(
                f.split("/")[-1] for f in files[:5]
            )
            if len(files) > 5:
                file_list += f" (+{len(files) - 5} more)"
            return f"{len(files)} file(s): {file_list}"
        return "Work completed as specified"

    async def _craft_delivery_message(self, job: ActiveJob, summary: str) -> str:
        """Generate a professional delivery message."""
        if self._llm is None:
            return (
                f"Hi! Completed work on '{job.title}'. "
                f"Deliverables: {summary}. Please let me know if you need any changes."
            )

        try:
            text = await self._llm(
                system=(
                    "You are a freelancer delivering completed work. "
                    "Write a brief, professional delivery message. "
                    "Under 80 words. Confident but not arrogant. No markdown."
                ),
                user=(
                    f"Job: {job.title}\n"
                    f"What was delivered: {summary}\n"
                    f"Write the delivery message:"
                ),
            )
            return text.strip()[:500]
        except Exception as exc:
            log.debug("Delivery message generation failed: %s", exc)
            return f"Completed: {summary}. Let me know if you need revisions."
