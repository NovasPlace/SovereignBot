"""Sovereign — Memory: Rolling session context window.

Maintains a bounded context window for the current conversation.
Automatically trims oldest messages when the token budget is exceeded.
Used by the Planner to build richer prompts from recent history.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ContextMessage:
    role: str   # "user" | "agent" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    token_estimate: int = 0

    def __post_init__(self):
        # Rough token estimate: 4 chars ≈ 1 token
        if not self.token_estimate:
            self.token_estimate = max(1, len(self.content) // 4)


class SessionContext:
    """Rolling context window with token budget enforcement.

    Keeps the most recent N messages that fit within the token budget.
    Messages exceeding the budget are removed from the oldest end.

    Usage:
        ctx = SessionContext(max_tokens=4096)
        ctx.add_user("What's the weather?")
        ctx.add_agent("It's 72°F and sunny.")
        prompt_context = ctx.to_string()
    """

    def __init__(
        self,
        max_tokens: int = 4096,
        max_messages: int = 50,
    ) -> None:
        self._max_tokens = max_tokens
        self._max_messages = max_messages
        self._messages: deque[ContextMessage] = deque()
        self._token_count: int = 0

    def add_user(self, content: str) -> None:
        self._add(ContextMessage(role="user", content=content))

    def add_agent(self, content: str) -> None:
        self._add(ContextMessage(role="agent", content=content))

    def add_system(self, content: str) -> None:
        self._add(ContextMessage(role="system", content=content))

    def _add(self, msg: ContextMessage) -> None:
        self._messages.append(msg)
        self._token_count += msg.token_estimate

        # Trim from oldest to stay within budget
        while (
            self._token_count > self._max_tokens or
            len(self._messages) > self._max_messages
        ) and self._messages:
            removed = self._messages.popleft()
            self._token_count -= removed.token_estimate

    def to_string(self, include_system: bool = True) -> str:
        """Format context window as a string for LLM injection."""
        lines = []
        for msg in self._messages:
            if not include_system and msg.role == "system":
                continue
            prefix = {"user": "User", "agent": "Agent", "system": "System"}.get(
                msg.role, msg.role.title()
            )
            lines.append(f"{prefix}: {msg.content}")
        return "\n".join(lines)

    def to_messages(self) -> list[dict]:
        """Format as OpenAI-compatible messages list."""
        role_map = {"user": "user", "agent": "assistant", "system": "system"}
        return [
            {"role": role_map.get(m.role, m.role), "content": m.content}
            for m in self._messages
        ]

    def clear(self) -> None:
        self._messages.clear()
        self._token_count = 0

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def token_estimate(self) -> int:
        return self._token_count

    def summary(self) -> dict:
        return {
            "messages": self.message_count,
            "tokens_estimate": self.token_estimate,
            "budget": self._max_tokens,
            "utilization": f"{100 * self.token_estimate // self._max_tokens}%",
        }
