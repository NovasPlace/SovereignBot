"""Sovereign — Core: Task planner.

Converts natural language user intent into a structured plan:
a list of Actions with explicit type, skill, and payload.

The planner talks to the configured LLM provider and returns
structured JSON that gets validated against our Action schema.
Every planning decision is emitted to TRACE (when integrated).

Design principle: the planner PROPOSES — it never executes.
The executor handles execution after the approval gate.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from ..models import Action, ActionType, SkillManifest, TrustTier

log = logging.getLogger("sovereign.core.planner")

# System prompt — ruthlessly simple so llama3.1:8b stays on task
_PLANNER_SYSTEM = """You are a task router. Decide if the user's message needs a skill, or is just conversation.

AVAILABLE SKILLS: {skills}

RULES:
- If the user is asking for something a skill can do (weather, web search, file read, shell command, etc.) → use FORMAT A.
- If the user is chatting, asking a question you can answer from knowledge, greeting, or just talking → use FORMAT B.
- Only use skills from the list above. Never invent skill names.

FORMAT A — needs a skill:
{{"plan":[{{"skill":"<skill_name_exactly>","description":"<what it does>","payload":{{<params>}}}}],"reasoning":"<why>"}}

FORMAT B — conversational (chat, greetings, questions, anything that doesn't need a skill):
{{"clarification_needed":true,"question":"conversational"}}

Output ONLY JSON. No markdown. No prose."""


class PlannerError(Exception):
    pass


class Planner:
    """LLM-powered task planner.

    Converts user messages into validated Action lists.
    Supports any provider that has a chat-completion interface.
    """

    def __init__(
        self,
        llm_fn,  # async fn(system: str, user: str) -> str
        available_skills: Optional[list[SkillManifest]] = None,
        default_trust_tier: TrustTier = TrustTier.UNTRUSTED,
    ) -> None:
        self._llm = llm_fn
        self._skills = available_skills or []
        self._default_tier = default_trust_tier

    async def plan(
        self,
        user_message: str,
        session_context: str = "",
    ) -> list[Action] | dict:
        """Plan a list of actions from a user message.

        Returns:
            list[Action] — if a plan was successfully generated
            [] — if no skills are loaded (agent falls back to direct LLM reply)
            {"clarification_needed": True, "question": str} — if LLM needs more info
        """
        # Short-circuit: no skills loaded — skip JSON planning entirely.
        # The agent's conversational fallback handles the response; no need to
        # ask the LLM to produce JSON it will hallucinate skills into.
        if not self._skills:
            log.debug("No skills loaded — skipping planner, using conversational fallback")
            return []

        skills_desc = self._describe_skills()
        system = _PLANNER_SYSTEM.format(skills=skills_desc)
        user_prompt = f"{user_message}"
        if session_context:
            user_prompt = f"CONTEXT:\n{session_context}\n\nREQUEST:\n{user_message}"

        t0 = time.monotonic()
        raw = await self._llm(system=system, user=user_prompt)
        elapsed = time.monotonic() - t0
        log.debug("Planner LLM responded in %.2fs", elapsed)

        parsed = self._parse_plan(raw)

        if parsed.get("clarification_needed"):
            return parsed

        actions = []
        for item in parsed.get("plan", []):
            action = self._build_action(item)
            if action:
                actions.append(action)

        if not actions:
            raise PlannerError("LLM returned a plan with no valid actions")

        log.info("Plan: %d actions | reasoning: %s", len(actions),
                 parsed.get("reasoning", "")[:80])
        return actions

    def _build_action(self, item: dict) -> Optional[Action]:
        """Build an Action from a simplified plan item {skill, description, payload}."""
        skill_id = item.get("skill") or item.get("skill_id") or item.get("type", "")
        if not skill_id or skill_id in ("clarification_needed", "unknown"):
            return None

        manifest = self._find_skill(skill_id)
        if not manifest:
            log.warning("Planner referenced unknown skill: %s", skill_id)
            return None

        trust_tier = manifest.trust_tier if manifest else self._default_tier

        try:
            return Action(
                type=ActionType.CUSTOM,  # all skill calls are CUSTOM type
                description=item.get("description", f"Run {skill_id}"),
                skill_id=skill_id,
                trust_tier=trust_tier,
                payload=item.get("payload", {}),
            )
        except Exception as e:
            log.warning("Failed to build action: %s", e)
            return None

    def _find_skill(self, skill_id: str) -> Optional[SkillManifest]:
        for s in self._skills:
            if s.name == skill_id:
                return s
        return None

    def _describe_skills(self) -> str:
        if not self._skills:
            return "none loaded"
        return ", ".join(
            f"{s.name} ({s.trust_tier.value})" for s in self._skills
        )

    def _parse_plan(self, raw: str) -> dict:
        """Extract JSON from LLM response with multiple fallback strategies."""
        import re
        text = raw.strip()

        # Strategy 1: raw text is already valid JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strategy 2: strip markdown code fences
        fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Strategy 3: find first {...} block in the response
        brace_match = re.search(r"(\{[\s\S]+\})", text)
        if brace_match:
            try:
                return json.loads(brace_match.group(1))
            except json.JSONDecodeError:
                pass

        # All strategies failed — fall through to conversational reply
        raise PlannerError(
            f"LLM returned non-JSON response: {raw[:200]}... | error: could not extract JSON"
        )
