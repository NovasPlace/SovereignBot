"""Sovereign — Economy: Bid Manager (Part 10).

Crafts and submits proposals for job opportunities.
EVERY submission requires explicit user approval — no auto-bidding.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Awaitable

from .models import Bid, Opportunity

log = logging.getLogger("sovereign.economy.bid")


class BidManager:
    """Prepares and submits bids with mandatory user approval.

    Usage:
        bid = await manager.prepare_bid(opportunity, user_id="123")
        submitted = await manager.submit_bid(bid, user_id="123")
    """

    def __init__(
        self,
        store=None,
        llm_fn=None,
        send_approval_fn: Callable[[str, str, str], Awaitable[None]] | None = None,
        wait_approval_fn: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self._store = store
        self._llm = llm_fn
        self._send_approval = send_approval_fn   # async (user_id, text, action_id)
        self._wait_approval = wait_approval_fn   # async (action_id) → bool

    async def prepare_bid(self, opportunity: Opportunity, user_id: str) -> Bid:
        """Craft a compelling, human-sounding proposal for the opportunity."""
        past_bids = self._recall_winning_bids(opportunity.platform, limit=2)

        past_context = ""
        if past_bids:
            past_context = (
                "\nPREVIOUS WINNING PROPOSALS (style reference):\n"
                + "\n---\n".join(pb[:200] for pb in past_bids)
            )

        prompt = (
            f"Write a freelance proposal for this job.\n\n"
            f"JOB: {opportunity.listing.title}\n"
            f"DESCRIPTION: {opportunity.listing.description[:300]}\n"
            f"MY FIT: {', '.join(opportunity.fit_reasons[:3])}\n"
            f"MY BID: ${opportunity.suggested_bid:.0f}\n"
            f"ESTIMATED HOURS: {opportunity.estimated_hours:.0f}h\n"
            f"{past_context}\n\n"
            f"RULES:\n"
            f"- 150-220 words maximum\n"
            f"- Start with understanding of THEIR specific problem\n"
            f"- Mention 1-2 concrete relevant experiences\n"
            f"- State bid and timeline clearly\n"
            f"- End with a specific, actionable next step\n"
            f"- Sound human, confident, and helpful — not robotic\n"
            f"- Do NOT start with 'I' or 'Hello'\n"
        )

        proposal_text = ""
        if self._llm:
            try:
                proposal_text = await self._llm(
                    system=(
                        "You are a skilled freelancer writing a winning proposal. "
                        "No markdown. No preamble. Output only the proposal text."
                    ),
                    user=prompt,
                )
                # Strip any accidental preamble
                proposal_text = proposal_text.strip()
            except Exception as exc:
                log.warning("Bid proposal generation failed: %s", exc)
                proposal_text = f"[Proposal generation failed — {exc}]"
        else:
            proposal_text = (
                f"I can complete '{opportunity.listing.title}' for "
                f"${opportunity.suggested_bid:.0f} in "
                f"{opportunity.estimated_hours:.0f} hours. "
                f"Reach out to discuss details."
            )

        bid = Bid(
            opportunity=opportunity,
            proposal_text=proposal_text,
            bid_amount=opportunity.suggested_bid,
            estimated_hours=opportunity.estimated_hours,
            status="draft",
        )

        log.info(
            "Bid prepared: %r $%.0f %.0fh",
            opportunity.listing.title[:40],
            bid.bid_amount,
            bid.estimated_hours,
        )
        return bid

    async def submit_bid(self, bid: Bid, user_id: str) -> bool:
        """Submit a bid — ALWAYS requires user approval first."""
        import uuid

        action_id = f"bid_{uuid.uuid4().hex[:8]}"

        approval_text = (
            f"📋 *Ready to bid:*\n\n"
            f"*Job:* {bid.opportunity.listing.title}\n"
            f"*Platform:* {bid.opportunity.platform or 'manual'}\n"
            f"*Bid:* ${bid.bid_amount:.0f}\n"
            f"*Est. hours:* {bid.estimated_hours:.0f}h\n\n"
            f"*Proposal:*\n{bid.proposal_text}\n\n"
            f"Approve this bid?"
        )

        if self._send_approval:
            await self._send_approval(user_id, approval_text, action_id)
        else:
            log.info("BidManager: no approval channel — auto-rejecting bid")
            bid.status = "rejected_by_user"
            return False

        approved = False
        if self._wait_approval:
            try:
                approved = await self._wait_approval(action_id)
            except Exception as exc:
                log.warning("Approval wait failed: %s", exc)

        if not approved:
            bid.status = "rejected_by_user"
            log.info("Bid rejected by user: %r", bid.opportunity.listing.title[:40])
            return False

        bid.status = "submitted"
        bid.submitted_at = time.time()

        # Record in memory
        if self._store is not None:
            try:
                from ..memory.cortex import MemoryType
                self._store.remember(
                    content=(
                        f"Bid submitted: {bid.opportunity.listing.title!r} "
                        f"for ${bid.bid_amount:.0f} on "
                        f"{bid.opportunity.platform or 'manual'}"
                    ),
                    memory_type=MemoryType.EPISODIC,
                    tags=["economy", "bid", "submitted"],
                    importance=0.6,
                    emotion="curiosity",
                    source="bid_manager",
                )
            except Exception:
                pass

        log.info(
            "Bid submitted: %r $%.0f",
            bid.opportunity.listing.title[:40], bid.bid_amount,
        )
        return True

    def _recall_winning_bids(self, platform: str, limit: int = 2) -> list[str]:
        """Retrieve text of past won bids for style reference."""
        if self._store is None:
            return []
        try:
            memories = self._store.recall(f"bid won {platform}", limit=limit)
            return [m.content for m in memories if hasattr(m, "content")]
        except Exception:
            return []
