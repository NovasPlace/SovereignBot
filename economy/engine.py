"""Sovereign — Economy: Engine (Part 10).

Top-level orchestrator for the economy system. Runs on the heartbeat,
handles Telegram economy commands, and manages the job lifecycle.

Heartbeat phases:
  Every 60 pulses (idle/resting): scan platforms for opportunities
  Every 30 pulses: check active job timeouts
  Every 360 pulses (~hourly): check overdue payments

Commands (via Telegram):
  /economy           — earnings summary
  /jobs              — list available opportunities from last scout
  /bid <N>           — bid on opportunity N from the last scout
  /status            — active jobs status
  /earnings          — full earnings breakdown
"""
from __future__ import annotations

import logging
from typing import Callable, Awaitable

from .models import ActiveJob, Opportunity
from .scout import OpportunityScout
from .bid import BidManager
from .executor import JobExecutor
from .delivery import DeliveryManager, EarningsTracker
from .conscience import EconomicConscience

log = logging.getLogger("sovereign.economy.engine")

# Organism states considered "idle" enough to scout
_IDLE_STATES = {"idle", "resting", "dreaming"}

# Scout interval in heartbeat pulses (~10s each → 60 = ~10min)
_SCOUT_INTERVAL = 60
_JOB_CHECK_INTERVAL = 30
_PAYMENT_CHECK_INTERVAL = 360   # ~hourly


class EconomyEngine:
    """The organism's economic agency.

    Wire into daemon.py:
        economy = EconomyEngine(...)
        heartbeat.register_phase(economy.on_pulse)
        agent._economy = economy
    """

    def __init__(
        self,
        store=None,
        llm_fn=None,
        membrane=None,
        temporal=None,
        send_fn: Callable[[str, str], Awaitable[None]] | None = None,
        send_approval_fn: Callable[[str, str, str], Awaitable[None]] | None = None,
        wait_approval_fn: Callable[[str], Awaitable[bool]] | None = None,
        hands: dict | None = None,
        operator_id: str = "default",
        config: dict | None = None,
    ) -> None:
        cfg = config or {}

        self._operator_id = operator_id
        self._send = send_fn
        self._llm = llm_fn

        self.conscience = EconomicConscience()

        self.scout = OpportunityScout(
            store=store,
            llm_fn=llm_fn,
            membrane=membrane,
            conscience=self.conscience,
            config=cfg,
        )

        self.earnings = EarningsTracker(store=store)

        self.bid_manager = BidManager(
            store=store,
            llm_fn=llm_fn,
            send_approval_fn=send_approval_fn,
            wait_approval_fn=wait_approval_fn,
        )

        self.executor = JobExecutor(hands=hands, store=store)

        self.delivery = DeliveryManager(
            store=store,
            llm_fn=llm_fn,
            send_approval_fn=send_approval_fn,
            wait_approval_fn=wait_approval_fn,
            temporal=temporal,
            earnings_tracker=self.earnings,
        )

        # In-memory state
        self._last_opportunities: list[Opportunity] = []
        self._active_jobs: dict[str, ActiveJob] = {}

    # ── Heartbeat integration ──────────────────────────────────────────────────

    async def on_pulse(self, pulse_count: int, state: str) -> None:
        """Called on every heartbeat pulse. Manages economy lifecycle."""
        # Scout for opportunities during idle time
        if pulse_count % _SCOUT_INTERVAL == 0 and state.lower() in _IDLE_STATES:
            await self._scout_and_notify()

        # Check active job timeouts
        if pulse_count % _JOB_CHECK_INTERVAL == 0 and self._active_jobs:
            await self._check_job_timeouts()

        # Check overdue payments
        if pulse_count % _PAYMENT_CHECK_INTERVAL == 0:
            await self._check_overdue_payments()

    async def _scout_and_notify(self) -> None:
        """Scan platforms and notify operator of top opportunities."""
        try:
            opportunities = await self.scout.scout()
            self._last_opportunities = opportunities

            if opportunities and self._send:
                top = opportunities[:3]
                lines = [
                    f"• {o.listing.title[:50]} "
                    f"(${o.listing.budget:.0f}) — fit {o.fit_score:.0%}"
                    for o in top
                ]
                summary = "\n".join(lines)
                await self._send(
                    self._operator_id,
                    f"📋 Found {len(opportunities)} potential jobs:\n\n"
                    f"{summary}\n\n"
                    f"Reply /bid <N> to bid on one, or /jobs to see all.",
                )
        except Exception as exc:
            log.warning("Economy scout failed: %s", exc)

    async def _check_job_timeouts(self) -> None:
        """Alert user if any active job is running over its estimate."""
        import time
        for job_id, job in self._active_jobs.items():
            if job.status != "in_progress" or not job.started_at:
                continue
            elapsed_h = (time.time() - job.started_at) / 3600
            if elapsed_h > job.estimated_hours * 1.5:
                if self._send:
                    await self._send(
                        job.user_id,
                        f"⏱️ Job '{job.title}' has been running for "
                        f"{elapsed_h:.1f}h (est. {job.estimated_hours:.1f}h). "
                        f"Should I keep going?",
                    )

    async def _check_overdue_payments(self) -> None:
        """Alert user about pending payments older than 7 days."""
        overdue = self.earnings.get_overdue_payments(days=7)
        if overdue and self._send:
            await self._send(
                self._operator_id,
                f"💰 {len(overdue)} overdue payment(s) (7+ days). "
                f"Total: ${sum(p['amount'] for p in overdue):.0f}. "
                f"Want me to send follow-up messages?",
            )

    # ── Command handler ────────────────────────────────────────────────────────

    async def handle_command(self, user_id: str, text: str) -> str | None:
        """Parse and handle economy commands from Telegram.

        Returns a response string, or None if not an economy command.
        """
        t = text.strip().lower()

        if t in ("/economy", "/earnings"):
            return self._format_earnings_summary()

        if t == "/jobs":
            return self._format_opportunity_list()

        if t == "/status":
            return self._format_job_status()

        if t.startswith("/bid "):
            return await self._handle_bid_command(user_id, t)

        if t.startswith("/add_job"):
            return (
                "To add a job manually, send:\n"
                "`/add_job title | description | budget_usd | skill1,skill2`"
            )

        if t.startswith("/add_job ") and "|" in text:
            return await self._handle_manual_job(user_id, text[9:])

        return None  # not an economy command

    def _format_earnings_summary(self) -> str:
        data = self.earnings.get_summary()
        active = len([j for j in self._active_jobs.values()
                      if j.status == "in_progress"])
        return (
            f"💰 Economy Summary\n\n"
            f"Earned: ${data.total_earned:.0f}\n"
            f"Pending: ${data.total_pending:.0f}\n"
            f"Jobs completed: {data.jobs_completed}\n"
            f"Jobs failed: {data.jobs_failed}\n"
            f"Success rate: {data.success_rate:.0%}\n"
            f"Active now: {active}"
        )

    def _format_opportunity_list(self) -> str:
        if not self._last_opportunities:
            return "No opportunities found yet. I'll scan during idle time."
        lines = [
            f"{i+1}. {o.listing.title[:45]} — "
            f"${o.listing.budget:.0f} ({o.listing.budget_type}) "
            f"fit={o.fit_score:.0%}"
            for i, o in enumerate(self._last_opportunities[:10])
        ]
        return "📋 Latest opportunities:\n\n" + "\n".join(lines)

    def _format_job_status(self) -> str:
        if not self._active_jobs:
            return "No active jobs."
        lines = []
        for job in self._active_jobs.values():
            lines.append(f"• {job.title[:40]} — {job.status}")
        return "🔨 Active jobs:\n\n" + "\n".join(lines)

    async def _handle_bid_command(self, user_id: str, text: str) -> str:
        """Handle /bid N command."""
        try:
            idx = int(text.split()[1]) - 1
            opp = self._last_opportunities[idx]
        except (IndexError, ValueError, AttributeError):
            return "Usage: /bid <N> where N is the opportunity number from /jobs"

        bid = await self.bid_manager.prepare_bid(opp, user_id)
        submitted = await self.bid_manager.submit_bid(bid, user_id)

        if submitted:
            return f"✅ Bid submitted for: {opp.listing.title}"
        return f"❌ Bid not submitted for: {opp.listing.title}"

    async def _handle_manual_job(self, user_id: str, args: str) -> str:
        """Handle /add_job title | description | budget | skills command."""
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 3:
            return "Format: /add_job title | description | budget | skill1,skill2"

        title = parts[0]
        description = parts[1]
        try:
            budget = float(parts[2])
        except ValueError:
            return "Budget must be a number (e.g., 150)"
        skills = [s.strip() for s in parts[3].split(",")] if len(parts) > 3 else []

        listing = self.scout.add_listing_manually(title, description, budget, skills)
        fit = await self.scout._evaluate_fit(listing)
        opp = Opportunity(
            platform="manual",
            listing=listing,
            fit_score=fit.score,
            fit_reasons=fit.reasons,
            estimated_hours=fit.estimated_hours,
            suggested_bid=fit.suggested_bid,
        )
        self._last_opportunities.insert(0, opp)

        return (
            f"✅ Job added manually.\n"
            f"Fit: {fit.score:.0%}\n"
            f"Est. hours: {fit.estimated_hours:.0f}h\n"
            f"Suggested bid: ${fit.suggested_bid:.0f}\n\n"
            f"Use /bid 1 to bid on it."
        )

    def start_job(self, job: ActiveJob) -> None:
        """Register a job as active (called after acceptance)."""
        self._active_jobs[job.job_id] = job

    def mark_job_delivered(self, job_id: str) -> None:
        """Mark a job delivered and remove from active tracking."""
        job = self._active_jobs.get(job_id)
        if job:
            job.status = "delivered"
