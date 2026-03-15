"""Sovereign — Core: Action approval gate.

This is the single most important guard in Sovereign.
OpenClaw let the agent create a dating profile without user consent.
This gate prevents that from ever happening here.

HIGH-SENSITIVITY actions are paused. The agent describes exactly what it's
about to do. The user approves or rejects — in the same channel they used.
Timeout (5 minutes default) auto-rejects. Everything is logged.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

from ..models import Action, ActionType, TrustTier
from ..security.audit import AuditEvent, get_audit

log = logging.getLogger("sovereign.core.approver")

# Sensitivity classifications → approval requirement
# HIGH: always needs user confirmation regardless of trust tier
# MEDIUM: needs confirmation for COMMUNITY and below
# LOW: auto-approved
_ACTION_SENSITIVITY: dict[ActionType, str] = {
    ActionType.SEND_EMAIL:        "HIGH",
    ActionType.SEND_MESSAGE:      "HIGH",
    ActionType.CREATE_ACCOUNT:    "HIGH",
    ActionType.PURCHASE:          "HIGH",
    ActionType.DELETE_FILES_BULK: "HIGH",
    ActionType.ACCESS_FINANCIAL:  "HIGH",
    ActionType.SHARE_EXTERNAL:    "HIGH",
    ActionType.EXECUTE_CODE:      "MEDIUM",
    ActionType.WRITE_FILE:        "MEDIUM",
    ActionType.CALENDAR_EVENT:    "MEDIUM",
    ActionType.READ_FILE:         "LOW",
    ActionType.WEB_FETCH:         "LOW",
    ActionType.MEMORY_STORE:      "LOW",
    ActionType.CUSTOM:            "MEDIUM",
}

DEFAULT_TIMEOUT_S = 300.0  # 5 minutes


class ApprovalTimeout(Exception):
    """Raised when user doesn't respond to an approval prompt in time."""


class ApprovalGate:
    """Routes high-sensitivity actions through user confirmation.

    The gate receives an action and a send_prompt callback (which posts
    the approval request to the user's messaging channel). It then awaits
    their response. Timeout = auto-reject.

    Usage:
        gate = ApprovalGate(send_prompt_fn, session_id)
        action = await gate.check(action)  # approved Action returned, or exception
    """

    def __init__(
        self,
        send_prompt: Callable[[str], asyncio.Future],
        session_id: str = "",
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._send_prompt = send_prompt
        self._session_id = session_id
        self._timeout = timeout_s
        self._audit = get_audit()
        self._pending: dict[str, asyncio.Future] = {}  # action_id → future

    async def check(self, action: Action) -> Action:
        """Process an action through the approval gate.

        Returns the action (modified in-place with approved=True) if approved.
        Sets approved=False and raises if rejected or timed out.
        """
        sensitivity = _ACTION_SENSITIVITY.get(action.type, "MEDIUM")
        needs_approval = self._needs_user_approval(action, sensitivity)

        if not needs_approval:
            action.approved = True
            action.approved_by = "auto"
            self._audit.log(
                event_type=AuditEvent.ACTION_APPROVED,
                actor="auto",
                outcome="auto-approved",
                session_id=self._session_id,
                target=action.action_id,
                payload={
                    "type": action.type.value,
                    "sensitivity": sensitivity,
                    "tier": action.trust_tier.value,
                },
            )
            return action

        # Build approval prompt — clear, honest, specific
        prompt = self._build_prompt(action, sensitivity)
        self._audit.log(
            event_type=AuditEvent.ACTION_PROPOSED,
            actor=action.skill_id,
            outcome="awaiting-approval",
            session_id=self._session_id,
            target=action.action_id,
            payload={"type": action.type.value, "description": action.description},
        )

        # Post prompt to user's channel and await their response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[action.action_id] = future

        try:
            await self._send_prompt(prompt)
            response = await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError:
            action.approved = False
            action.approved_by = "timeout"
            self._audit.log(
                event_type=AuditEvent.ACTION_REJECTED,
                actor="timeout",
                outcome="auto-rejected (timeout)",
                session_id=self._session_id,
                target=action.action_id,
            )
            log.warning(
                "Action timed out: action_id=%s type=%s", action.action_id, action.type.value
            )
            raise ApprovalTimeout(
                f"Action {action.action_id} ({action.type.value}) timed out after {self._timeout}s"
            )
        finally:
            self._pending.pop(action.action_id, None)

        approved = response in ("y", "yes", "approve", "ok", "1", "✅")
        action.approved = approved
        action.approved_by = "user"

        event = AuditEvent.ACTION_APPROVED if approved else AuditEvent.ACTION_REJECTED
        self._audit.log(
            event_type=event,
            actor="user",
            outcome="approved" if approved else "rejected",
            session_id=self._session_id,
            target=action.action_id,
            payload={"user_response": response[:50]},
        )

        log.info(
            "Action %s: action_id=%s type=%s",
            "APPROVED" if approved else "REJECTED",
            action.action_id,
            action.type.value,
        )
        return action

    def resolve(self, action_id: str, user_response: str) -> None:
        """Call this when the user sends a response to an approval prompt."""
        future = self._pending.get(action_id)
        if future and not future.done():
            future.set_result(user_response.lower().strip())

    def _needs_user_approval(self, action: Action, sensitivity: str) -> bool:
        if sensitivity == "HIGH":
            return True
        if sensitivity == "MEDIUM":
            return action.trust_tier in (TrustTier.COMMUNITY, TrustTier.UNTRUSTED)
        return False  # LOW sensitivity → auto-approve

    @staticmethod
    def _build_prompt(action: Action, sensitivity: str) -> str:
        """Build the approval message that gets sent to the user."""
        tier_icons = {
            TrustTier.CORE: "🟢", TrustTier.VERIFIED: "🔵",
            TrustTier.COMMUNITY: "🟡", TrustTier.UNTRUSTED: "🔴",
        }
        icon = tier_icons.get(action.trust_tier, "⚪")
        lines = [
            f"⚠️ **Action requires your approval** [{sensitivity} sensitivity]",
            f"",
            f"**What:** {action.description}",
            f"**Type:** `{action.type.value}`",
            f"**Skill:** `{action.skill_id}` {icon} ({action.trust_tier.value})",
            f"**ID:** `{action.action_id}`",
            f"",
            f"Reply **Y** to approve or **N** to reject.",
            f"Auto-rejects in {int(action.approval_timeout_s // 60)} minutes.",
        ]
        return "\n".join(lines)
