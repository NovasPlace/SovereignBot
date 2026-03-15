"""Sovereign — Cross-Hand Chaining.

Enables multi-hand pipelines where one hand's output feeds into the
next hand's input. The organism doesn't just use one hand at a time —
it orchestrates sequences.

Example: Debugger finds a bug → TestEngineer writes regression test
         → CICDEngineer updates the pipeline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("sovereign.hand_chain")


@dataclass
class ChainStep:
    """A single step in a hand chain."""
    hand_name: str
    input_transform: Callable[[Any], dict] | None = None  # maps prev result → kwargs
    description: str = ""


@dataclass
class ChainResult:
    """Result of executing a full chain."""
    chain_name: str
    status: str  # success, partial, failed
    steps_completed: int = 0
    steps_total: int = 0
    step_results: list[Any] = field(default_factory=list)
    summary: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# BUILT-IN CHAINS
# ══════════════════════════════════════════════════════════════════════════════

CHAINS: dict[str, list[ChainStep]] = {
    "debug_and_test": [
        ChainStep(
            hand_name="debugger",
            description="Find and fix the bug",
        ),
        ChainStep(
            hand_name="test_engineer",
            input_transform=lambda r: {"workdir": getattr(r, "bug", ".")[:200]},
            description="Generate regression tests for the fix",
        ),
    ],
    "build_and_deploy": [
        ChainStep(
            hand_name="code_engineer",
            description="Implement the feature",
        ),
        ChainStep(
            hand_name="test_engineer",
            description="Generate and run tests",
        ),
        ChainStep(
            hand_name="cicd",
            description="Set up CI/CD pipeline",
        ),
        ChainStep(
            hand_name="deployment",
            description="Deploy to production",
        ),
    ],
    "doc_and_publish": [
        ChainStep(
            hand_name="documentation",
            description="Generate documentation",
        ),
        ChainStep(
            hand_name="social_media",
            input_transform=lambda r: {
                "topic": f"New docs published: {getattr(r, 'summary', '')[:100]}",
                "action": "create",
            },
            description="Create social posts about the update",
        ),
    ],
    "security_sweep": [
        ChainStep(
            hand_name="security",
            description="Full security audit",
        ),
        ChainStep(
            hand_name="debugger",
            input_transform=lambda r: {
                "bug_report": f"Security issues found: {getattr(r, 'summary', '')[:200]}",
            },
            description="Fix critical vulnerabilities",
        ),
        ChainStep(
            hand_name="test_engineer",
            description="Verify fixes with tests",
        ),
    ],
    "full_analysis": [
        ChainStep(
            hand_name="data_analyst",
            description="Analyze the data",
        ),
        ChainStep(
            hand_name="documentation",
            input_transform=lambda r: {
                "doc_type": "report",
                "workdir": "/tmp/sovereign/data_analysis",
            },
            description="Document the analysis",
        ),
    ],
}


class HandChainExecutor:
    """Execute a sequence of hands, piping output → input."""

    def __init__(self, hands: dict, send_fn=None) -> None:
        self._hands = hands
        self._send_fn = send_fn  # notify user of progress

    async def execute(
        self,
        chain_name: str,
        initial_kwargs: dict | None = None,
        user_id: str = "",
    ) -> ChainResult:
        """Run a named chain."""
        steps = CHAINS.get(chain_name)
        if not steps:
            return ChainResult(
                chain_name=chain_name, status="failed",
                summary=f"Unknown chain: {chain_name}",
            )

        return await self.execute_steps(chain_name, steps, initial_kwargs, user_id)

    async def execute_steps(
        self,
        chain_name: str,
        steps: list[ChainStep],
        initial_kwargs: dict | None = None,
        user_id: str = "",
    ) -> ChainResult:
        """Run a list of chain steps sequentially."""
        result = ChainResult(
            chain_name=chain_name,
            status="running",
            steps_total=len(steps),
        )
        prev_result = None
        current_kwargs = initial_kwargs or {}

        for i, step in enumerate(steps):
            hand = self._hands.get(step.hand_name)
            if not hand:
                log.warning("[Chain] Hand '%s' not found — skipping", step.hand_name)
                continue

            # Notify user of progress
            if self._send_fn and user_id:
                try:
                    await self._send_fn(
                        user_id,
                        f"🔗 Chain `{chain_name}` step {i + 1}/{len(steps)}: "
                        f"{step.description or step.hand_name}",
                    )
                except Exception:
                    pass

            # Transform previous result into kwargs for this step
            if prev_result and step.input_transform:
                try:
                    current_kwargs = step.input_transform(prev_result)
                except Exception as e:
                    log.error("[Chain] Transform error at step %d: %s", i, e)
                    current_kwargs = {}

            # Execute the hand
            log.info("[Chain] %s step %d/%d: %s", chain_name, i + 1, len(steps), step.hand_name)
            try:
                prev_result = await hand.execute(**current_kwargs)
                result.step_results.append(prev_result)
                result.steps_completed += 1

                # Check for abort
                status = getattr(prev_result, "status", "")
                if status == "failed":
                    log.warning("[Chain] Step %d failed — aborting chain", i + 1)
                    break

            except Exception as e:
                log.error("[Chain] Step %d error: %s", i + 1, e)
                result.step_results.append({"error": str(e)})
                break

            # Clear kwargs for next step (will be set by transform)
            current_kwargs = {}

        result.status = "success" if result.steps_completed == len(steps) else "partial"
        result.summary = (
            f"Chain '{chain_name}': {result.steps_completed}/{len(steps)} steps completed"
        )

        # Notify completion
        if self._send_fn and user_id:
            try:
                icon = "✅" if result.status == "success" else "⚠️"
                await self._send_fn(user_id, f"{icon} {result.summary}")
            except Exception:
                pass

        log.info("[Chain] %s", result.summary)
        return result

    @property
    def available_chains(self) -> list[str]:
        """List all available chain names."""
        return list(CHAINS.keys())
