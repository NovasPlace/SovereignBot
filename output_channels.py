"""Sovereign — Multi-Channel Output: the organism speaks through many mouths.

Telegram is the primary voice. But the organism can also reach users
via webhooks (Discord, Slack, custom), and email when configured.
Channel selection is automatic based on message priority and length.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional

log = logging.getLogger("sovereign.channels")


@dataclass
class ChannelConfig:
    """Configuration for an output channel."""
    name: str
    channel_type: str  # telegram, webhook, email
    url: str = ""
    token: str = ""
    enabled: bool = True


class OutputChannels:
    """Routes outbound messages to the appropriate channel."""

    def __init__(self, primary_send_fn: Optional[Callable] = None) -> None:
        self._primary = primary_send_fn  # Telegram send_fn
        self._webhooks: dict[str, str] = {}  # name → URL
        self._channels: list[ChannelConfig] = []
        log.info("OutputChannels initialized (primary=%s)", "yes" if primary_send_fn else "no")

    def register_webhook(self, name: str, url: str) -> None:
        """Add a webhook output channel."""
        self._webhooks[name] = url
        self._channels.append(ChannelConfig(name=name, channel_type="webhook", url=url))
        log.info("Webhook channel registered: %s", name)

    async def send(self, user_id: str, message: str,
                   channel: str = "auto", priority: str = "normal") -> bool:
        """Send a message through the appropriate channel."""
        if channel == "auto":
            channel = self._select_channel(message, priority)

        if channel == "telegram" and self._primary:
            try:
                await self._primary(user_id, message)
                return True
            except Exception as e:
                log.warning("Telegram send failed: %s", e)
                return False

        if channel in self._webhooks:
            return await self._send_webhook(channel, user_id, message)

        # Fallback to primary
        if self._primary:
            try:
                await self._primary(user_id, message)
                return True
            except Exception:
                return False

        return False

    async def broadcast(self, message: str, priority: str = "normal") -> int:
        """Send to ALL channels. Returns count of successful sends."""
        sent = 0
        if self._primary:
            try:
                await self._primary("broadcast", message)
                sent += 1
            except Exception:
                pass

        for name in self._webhooks:
            if await self._send_webhook(name, "broadcast", message):
                sent += 1

        return sent

    def _select_channel(self, message: str, priority: str) -> str:
        """Auto-select the best channel."""
        if priority == "emergency":
            return "telegram"  # fastest push notification
        if len(message) > 4000 and self._webhooks:
            # Long messages might work better on webhooks
            return list(self._webhooks.keys())[0]
        return "telegram"

    async def _send_webhook(self, name: str, user_id: str, message: str) -> bool:
        """Send via webhook."""
        url = self._webhooks.get(name)
        if not url:
            return False

        try:
            import httpx
            payload = {
                "source": "sovereign",
                "user_id": user_id,
                "content": message,
                "priority": "normal",
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                return resp.status_code < 400
        except Exception as e:
            log.warning("Webhook %s failed: %s", name, e)
            return False

    @property
    def available_channels(self) -> list[str]:
        channels = []
        if self._primary:
            channels.append("telegram")
        channels.extend(self._webhooks.keys())
        return channels
