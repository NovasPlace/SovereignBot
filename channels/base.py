"""Sovereign — Channels: Base adapter interface.

Every messaging platform (Telegram, Discord, WhatsApp, SMS, Web)
implements this interface. The agent only talks to this interface —
it never knows which platform it's running on.

Key contract:
- sanitize_incoming() MUST be called on all inbound text before
  it reaches the agent. This is the first line of defense.
- send_approval_prompt() must wait for the user's Y/N response
  and return it to the ApprovalGate via agent.resolve_approval().
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from ..models import IncomingMessage
from ..skills.cleanse import InputCleanse


class Button:
    def __init__(self, label: str, callback_data: str) -> None:
        self.label = label
        self.callback_data = callback_data


class ChannelAdapter(ABC):
    """Abstract base for all messaging platform adapters."""

    platform_name: str = "unknown"

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the platform."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    def receive(self) -> AsyncIterator[IncomingMessage]:
        """Yield sanitized incoming messages."""
        ...

    @abstractmethod
    async def send(
        self,
        user_id: str,
        text: str,
        buttons: Optional[list[Button]] = None,
    ) -> None:
        """Send a text response (with optional inline buttons) to a user."""
        ...

    def sanitize_incoming(self, raw_text: str, user_id: str = "") -> tuple[str, str]:
        """Sanitize user input before passing to agent.

        Returns (clean_text, raw_text). The raw_text is preserved for audit.
        Every adapter MUST call this before building IncomingMessage.
        """
        result = InputCleanse.sanitize(
            raw_text,
            source=f"{self.platform_name}:{user_id}",
        )
        return result.text, raw_text

    def build_message(
        self,
        platform_user_id: str,
        raw_text: str,
        attachments: Optional[list[str]] = None,
    ) -> IncomingMessage:
        """Build a sanitized IncomingMessage from platform-specific fields."""
        clean, raw = self.sanitize_incoming(raw_text, platform_user_id)
        return IncomingMessage(
            platform=self.platform_name,
            user_id=platform_user_id,
            text=clean,
            raw_text=raw,
            attachments=attachments or [],
        )
