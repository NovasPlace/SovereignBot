"""Sovereign — Skillset Router.

Detects which engineering skillsets are relevant for an incoming message,
loads their reasoning frameworks, and biases memory recall toward
relevant knowledge. This changes HOW the bot thinks.
"""
from __future__ import annotations

import logging
from typing import Any

from . import (
    staff_engineering,
    software_engineering,
    architectural_engineering,
    threat_analyst,
    devops_sre,
    research_scientist,
    mentor_teacher,
    project_manager,
    data_engineer,
    negotiator,
    inventor,
    financial_advisor,
    systems_architect,
    web_designer,
    app_developer,
    creative_writer,
    automation_engineer,
    game_developer,
    graphics_3d,
    networking,
    hardware_engineer,
    music_audio,
)

log = logging.getLogger("sovereign.skillsets.router")

# Registry — add new skillsets here
_SKILLSETS: dict[str, dict[str, Any]] = {
    "staff_engineering": {
        "manifest": staff_engineering.MANIFEST,
        "framework": staff_engineering.REASONING_FRAMEWORK,
    },
    "software_engineering": {
        "manifest": software_engineering.MANIFEST,
        "framework": software_engineering.REASONING_FRAMEWORK,
    },
    "architectural_engineering": {
        "manifest": architectural_engineering.MANIFEST,
        "framework": architectural_engineering.REASONING_FRAMEWORK,
    },
    "threat_analyst": {
        "manifest": threat_analyst.MANIFEST,
        "framework": threat_analyst.REASONING_FRAMEWORK,
    },
    "devops_sre": {
        "manifest": devops_sre.MANIFEST,
        "framework": devops_sre.REASONING_FRAMEWORK,
    },
    "research_scientist": {
        "manifest": research_scientist.MANIFEST,
        "framework": research_scientist.REASONING_FRAMEWORK,
    },
    "mentor_teacher": {
        "manifest": mentor_teacher.MANIFEST,
        "framework": mentor_teacher.REASONING_FRAMEWORK,
    },
    "project_manager": {
        "manifest": project_manager.MANIFEST,
        "framework": project_manager.REASONING_FRAMEWORK,
    },
    "data_engineer": {
        "manifest": data_engineer.MANIFEST,
        "framework": data_engineer.REASONING_FRAMEWORK,
    },
    "negotiator": {
        "manifest": negotiator.MANIFEST,
        "framework": negotiator.REASONING_FRAMEWORK,
    },
    "inventor": {
        "manifest": inventor.MANIFEST,
        "framework": inventor.REASONING_FRAMEWORK,
    },
    "financial_advisor": {
        "manifest": financial_advisor.MANIFEST,
        "framework": financial_advisor.REASONING_FRAMEWORK,
    },
    "systems_architect": {
        "manifest": systems_architect.MANIFEST,
        "framework": systems_architect.REASONING_FRAMEWORK,
    },
    "web_designer": {
        "manifest": web_designer.MANIFEST,
        "framework": web_designer.REASONING_FRAMEWORK,
    },
    "app_developer": {
        "manifest": app_developer.MANIFEST,
        "framework": app_developer.REASONING_FRAMEWORK,
    },
    "creative_writer": {
        "manifest": creative_writer.MANIFEST,
        "framework": creative_writer.REASONING_FRAMEWORK,
    },
    "automation_engineer": {
        "manifest": automation_engineer.MANIFEST,
        "framework": automation_engineer.REASONING_FRAMEWORK,
    },
    "game_developer": {
        "manifest": game_developer.MANIFEST,
        "framework": game_developer.REASONING_FRAMEWORK,
    },
    "graphics_3d": {
        "manifest": graphics_3d.MANIFEST,
        "framework": graphics_3d.REASONING_FRAMEWORK,
    },
    "networking": {
        "manifest": networking.MANIFEST,
        "framework": networking.REASONING_FRAMEWORK,
    },
    "hardware_engineer": {
        "manifest": hardware_engineer.MANIFEST,
        "framework": hardware_engineer.REASONING_FRAMEWORK,
    },
    "music_audio": {
        "manifest": music_audio.MANIFEST,
        "framework": music_audio.REASONING_FRAMEWORK,
    },
}


class SkillsetRouter:
    """Detects active skillsets and assembles cognitive context for the Brain."""

    def __init__(self, store=None) -> None:
        self._store = store
        self._skillsets = _SKILLSETS
        log.info("SkillsetRouter loaded: %d skillsets", len(self._skillsets))

    def detect(self, message: str) -> list[str]:
        """Return names of skillsets whose triggers match the message.

        Returns at most 3 active skillsets (highest trigger-match count first).
        """
        lower = message.lower()
        scores: dict[str, int] = {}

        for name, entry in self._skillsets.items():
            triggers = entry["manifest"]["triggers"]
            hit_count = sum(1 for t in triggers if t in lower)
            if hit_count > 0:
                scores[name] = hit_count

        # Sort by match count descending, cap at 3
        ranked = sorted(scores, key=scores.get, reverse=True)[:3]
        return ranked

    def get_frameworks(self, active: list[str]) -> list[str]:
        """Return reasoning framework strings for the active skillsets."""
        return [
            self._skillsets[name]["framework"]
            for name in active
            if name in self._skillsets
        ]

    def get_memory_tags(self, active: list[str]) -> list[str]:
        """Return preferred memory search tags from active skillsets."""
        tags: list[str] = []
        for name in active:
            if name in self._skillsets:
                bias = self._skillsets[name]["manifest"].get("memory_bias", {})
                tags.extend(bias.get("preferred_tags", []))
        return tags

    def get_display_names(self, active: list[str]) -> list[str]:
        return [
            self._skillsets[name]["manifest"]["display_name"]
            for name in active
            if name in self._skillsets
        ]
