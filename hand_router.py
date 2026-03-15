"""Sovereign — Hand Router.

Detects when an incoming message triggers a work pipeline (a Hand)
rather than just a conversation. Routes to the appropriate Hand and
manages approval flow.

Pattern matching is intentionally simple — trigger phrases are
short, concrete, and unambiguous to minimize false positives.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

log = logging.getLogger("sovereign.hand_router")

# Trigger phrases for each hand — lower-cased
_TRIGGERS: dict[str, list[str]] = {
    "code_engineer": [
        "write code", "write a function", "write a class", "write a script",
        "write tests", "implement this", "implement a", "build this",
        "create a module", "create a function", "fix this code",
        "refactor", "add a feature", "debug my code", "write me a",
        "code this", "make a plugin", "add to the codebase",
    ],
    "research": [
        "research this", "find out about", "what's the latest on",
        "deep dive", "literature review", "compare options",
        "look into", "investigate", "write a report on",
        "what do you know about", "summarize the state of",
    ],
    "deployment": [
        "deploy this", "ship it", "push to production", "release",
        "update the server", "restart the service", "run the deploy",
        "deploy the app", "put this into production",
    ],
    "writing": [
        "write a post", "write a blog", "draft an article", "write a paper",
        "write documentation", "write a readme", "write an essay",
        "write a summary", "write copy", "write marketing",
        "ghostwrite", "write me an email",
    ],
    "sysadmin": [
        "something's broken", "server is down", "fix the server",
        "diagnose", "why is this failing", "system problem",
        "service is not starting", "out of disk", "memory issue",
        "cpu is spiking", "check the logs", "restart",
    ],
}


@dataclass
class HandMatch:
    hand_name: str
    task: str               # extracted task description
    workdir: str = ""
    confidence: float = 0.8


class HandRouter:
    """Detect and route work pipeline requests."""

    def __init__(self, workdir: str = None) -> None:
        self._default_workdir = workdir or os.path.expanduser("~")

    def match(self, message: str) -> HandMatch | None:
        """Return the best matching hand for this message, or None."""
        lower = message.lower().strip()

        best_hand = None
        best_score = 0

        for hand_name, triggers in _TRIGGERS.items():
            for trigger in triggers:
                if trigger in lower:
                    # Score by trigger specificity (longer = more specific)
                    score = len(trigger)
                    if score > best_score:
                        best_score = score
                        best_hand = hand_name

        if not best_hand:
            return None

        return HandMatch(
            hand_name=best_hand,
            task=message,
            workdir=self._default_workdir,
            confidence=min(1.0, best_score / 20),
        )

    @property
    def all_triggers(self) -> list[str]:
        """All trigger phrases across all hands."""
        return [t for triggers in _TRIGGERS.values() for t in triggers]
