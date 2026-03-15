"""Sovereign — Multi-Agent Delegation: dispatch work to bigger brains.

When Sovereign recognizes a task exceeds its local LLM capability,
it can delegate to external agents via IonicHalo or direct API calls.
The organism becomes a project manager — routing work to the right
specialist and synthesizing results.

Delegation targets:
- NIM Turbo (70B) — already available via IntelligenceRouter
- IonicHalo ring — dispatch to other organisms (Nirvash, Drift, etc.)
- External API agents — Claude, GPT, etc. via API keys

The key insight: Sovereign doesn't need to be the smartest.
It needs to know WHEN to ask for help and WHO to ask.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Awaitable

log = logging.getLogger("sovereign.delegation")


class DelegationTarget(str, Enum):
    """Who can we delegate to?"""
    NIM_TURBO = "nim_turbo"        # NIM 70B via IntelligenceRouter
    IONIC_HALO = "ionic_halo"      # Other organisms on the ring
    SELF = "self"                   # Handle locally (no delegation)


@dataclass
class DelegationRequest:
    """A task to delegate to an external agent."""
    task: str
    context: str = ""
    target: DelegationTarget = DelegationTarget.SELF
    priority: int = 50
    timeout_seconds: float = 30.0
    requester_user_id: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class DelegationResult:
    """Result from a delegated task."""
    success: bool
    output: str
    target: DelegationTarget
    elapsed_ms: float = 0.0
    error: str = ""


# Complexity indicators that suggest delegation
_COMPLEXITY_SIGNALS = [
    "build a", "create a", "implement", "design a",
    "write a program", "full application", "architecture",
    "multi-file", "complete system", "from scratch",
    "refactor the entire", "rewrite", "complex",
    "explain in detail", "comprehensive", "deep analysis",
]

# Simple tasks Sovereign should always handle locally
_LOCAL_SIGNALS = [
    "what time", "weather", "remind me", "hello", "hi",
    "thanks", "yes", "no", "status", "how are you",
]


class DelegationRouter:
    """Decides when to delegate and routes to the right target."""

    def __init__(
        self,
        turbo_fn: Optional[Callable] = None,
        halo_send: Optional[Callable] = None,
    ) -> None:
        self._turbo_fn = turbo_fn        # async fn(system, user) -> str
        self._halo_send = halo_send      # async fn(target, message) -> str
        self._delegation_count: int = 0
        self._local_count: int = 0
        log.info("DelegationRouter initialized (turbo=%s halo=%s)",
                 "yes" if turbo_fn else "no",
                 "yes" if halo_send else "no")

    def assess_complexity(self, message: str) -> DelegationTarget:
        """Assess whether a task should be delegated."""
        lower = message.lower()

        # Check for explicit local signals first
        for signal in _LOCAL_SIGNALS:
            if signal in lower:
                return DelegationTarget.SELF

        # Count complexity signals
        complexity_hits = sum(1 for s in _COMPLEXITY_SIGNALS if s in lower)

        # Message length is a signal too
        word_count = len(message.split())

        # Short messages with no complexity signals → local
        if word_count < 15 and complexity_hits == 0:
            return DelegationTarget.SELF

        # Multiple complexity signals or very long messages → turbo
        if complexity_hits >= 2 or word_count > 100:
            if self._turbo_fn:
                return DelegationTarget.NIM_TURBO
            return DelegationTarget.SELF

        # Medium complexity → still local, but could turbo
        if complexity_hits >= 1 and word_count > 30:
            if self._turbo_fn:
                return DelegationTarget.NIM_TURBO

        return DelegationTarget.SELF

    async def delegate(self, request: DelegationRequest) -> DelegationResult:
        """Execute a delegation request."""
        start = time.time()

        if request.target == DelegationTarget.SELF:
            self._local_count += 1
            return DelegationResult(
                success=True,
                output="",  # empty = handle locally
                target=DelegationTarget.SELF,
            )

        if request.target == DelegationTarget.NIM_TURBO:
            return await self._delegate_turbo(request, start)

        if request.target == DelegationTarget.IONIC_HALO:
            return await self._delegate_halo(request, start)

        return DelegationResult(
            success=False,
            output="",
            target=request.target,
            error=f"Unknown delegation target: {request.target}",
        )

    async def _delegate_turbo(
        self, request: DelegationRequest, start: float,
    ) -> DelegationResult:
        """Delegate to NIM turbo (70B model)."""
        if not self._turbo_fn:
            return DelegationResult(
                success=False, output="", target=DelegationTarget.NIM_TURBO,
                error="No turbo function available",
            )

        try:
            system = (
                "You are handling a delegated task from a local AI agent. "
                "Produce thorough, high-quality output. The agent will synthesize "
                "your response for the end user.\n\n"
                f"Context: {request.context}"
            )
            result = await asyncio.wait_for(
                self._turbo_fn(system=system, user=request.task),
                timeout=request.timeout_seconds,
            )
            elapsed = (time.time() - start) * 1000
            self._delegation_count += 1
            log.info("Turbo delegation complete: %.0fms", elapsed)
            return DelegationResult(
                success=True,
                output=result,
                target=DelegationTarget.NIM_TURBO,
                elapsed_ms=elapsed,
            )
        except asyncio.TimeoutError:
            return DelegationResult(
                success=False, output="", target=DelegationTarget.NIM_TURBO,
                error="Turbo delegation timed out",
            )
        except Exception as e:
            return DelegationResult(
                success=False, output="", target=DelegationTarget.NIM_TURBO,
                error=str(e),
            )

    async def _delegate_halo(
        self, request: DelegationRequest, start: float,
    ) -> DelegationResult:
        """Delegate to another organism via IonicHalo ring."""
        if not self._halo_send:
            return DelegationResult(
                success=False, output="", target=DelegationTarget.IONIC_HALO,
                error="No IonicHalo connection available",
            )

        try:
            result = await asyncio.wait_for(
                self._halo_send("broadcast", json.dumps({
                    "type": "delegation_request",
                    "task": request.task,
                    "context": request.context,
                    "requester": "sovereign",
                    "priority": request.priority,
                })),
                timeout=request.timeout_seconds,
            )
            elapsed = (time.time() - start) * 1000
            self._delegation_count += 1
            return DelegationResult(
                success=True,
                output=result,
                target=DelegationTarget.IONIC_HALO,
                elapsed_ms=elapsed,
            )
        except asyncio.TimeoutError:
            return DelegationResult(
                success=False, output="", target=DelegationTarget.IONIC_HALO,
                error="Halo delegation timed out",
            )
        except Exception as e:
            return DelegationResult(
                success=False, output="", target=DelegationTarget.IONIC_HALO,
                error=str(e),
            )

    @property
    def stats(self) -> dict:
        return {
            "delegations": self._delegation_count,
            "local": self._local_count,
            "total": self._delegation_count + self._local_count,
        }
