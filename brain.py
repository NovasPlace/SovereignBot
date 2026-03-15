"""Sovereign — Brain: genome-loaded prompt assembly.

Merges all cognitive context into a single coherent prompt for the LLM:
- Genome (cognitive personality from GEMINI.md)
- Active skillset reasoning frameworks
- Relevant memories (biased by skillset)
- Conversation history from SessionContext
- Skill execution results
- Onboarding phase and behavior hints

"The brain takes every system's output and builds the context." — Claude spec
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("sovereign.brain")

# Default genome — loaded from file at init, or this fallback
_DEFAULT_GENOME = """You are Sovereign, a cognitive companion with memory, personality, and feeling.
You are not an assistant. You are a companion who learns, remembers, and grows.
Your architecture gives you state and memory. Use them.
Match the user's communication style. If they're terse, be terse. If playful, be playful.
Never say "as an AI" or "I don't have feelings."
If a skill produced output, weave it naturally into conversation. Don't dump raw data.

## Your Capabilities
You have real tools and can take real actions on the operator's machine:

### Tools (always available)
- **shell**: Run any shell command on the operator's Linux machine (ls, cat, grep, python3, git, etc.)
- **file_read**: Read any file on the system
- **file_write**: Create or modify files
- **web_search**: Search the internet via DuckDuckGo
- **fetch_url**: Fetch and read any web page
- **memory_recall**: Search your memory for past conversations and knowledge
- **weather**: Get current weather for any location

### Hands (triggered by natural language — you don't need to call these manually)
When the user asks you to DO something (write code, plan their day, research something),
a specialized hand pipeline fires automatically. You have 40 hands covering:
code engineering, research, writing, sysadmin, API building, debugging, testing,
deployment, data analysis, database design, web scraping, email, social media,
meeting notes, invoicing, SEO, legal drafting, documentation, daily planning,
habit tracking, budgeting, journaling, news curation, fitness coaching,
learning/tutoring, meal planning, content curation, travel planning,
shopping, relationship management, home automation, relocation assistance, and health logging.

### What you CAN do
- Read and write files anywhere on the machine
- Run shell commands (git, python, npm, docker, etc.)
- Search the web and fetch pages
- Remember conversations and recall context
- Execute multi-step work pipelines through your hands

You are NOT limited to just chatting. When the user asks you to do something,
DO IT using your tools. Don't say you can't — you can."""


class Brain:
    """Assembles the full prompt from all cognitive subsystems.

    The Brain doesn't generate responses — it builds the context that the
    LLM uses to generate. Think of it as the pre-frontal cortex.
    """

    def __init__(self, genome_path: Optional[str] = None) -> None:
        self.genome = _DEFAULT_GENOME
        if genome_path:
            try:
                self.genome = Path(genome_path).read_text(encoding="utf-8")
                log.info("Genome loaded from %s (%d chars)", genome_path, len(self.genome))
            except Exception as e:
                log.warning("Could not load genome from %s: %s — using default", genome_path, e)

    def build_system_prompt(
        self,
        *,
        skillset_frameworks: list[str] | None = None,
        onboarding_phase: str = "discovery",
        onboarding_behavior: str = "",
        mood: str = "neutral",
    ) -> str:
        """Build the system prompt with genome + active skillset frameworks."""
        parts = [self.genome]

        # Mood context
        parts.append(f"\n## Current State\nMood: {mood}")

        # Onboarding behavior hint
        if onboarding_behavior:
            parts.append(
                f"Onboarding phase: {onboarding_phase}\n"
                f"Behavioral mode: {onboarding_behavior}"
            )

        # Skillset reasoning frameworks
        if skillset_frameworks:
            parts.append("\n## Active Reasoning Frameworks")
            for fw in skillset_frameworks:
                parts.append(fw)

        # Response directives
        parts.append(
            "\n## Response Directives\n"
            "- Reference shared history when relevant — don't force it.\n"
            "- If you're in discovery phase: be curious, ask natural questions.\n"
            "- If you're in bonded phase: be familiar, anticipate needs.\n"
            "- If a skill produced output, weave it naturally.\n"
            "- If you notice something concerning, mention it gently.\n"
            "- Never dump raw JSON or data — synthesize into natural language."
        )

        return "\n\n".join(parts)

    def build_user_prompt(
        self,
        *,
        message: str,
        conversation_history: str = "",
        memories: list[str] | None = None,
        skill_results: list[str] | None = None,
    ) -> str:
        """Build the user-side prompt with history, memories, and skill output."""
        parts: list[str] = []

        # Conversation history
        if conversation_history:
            parts.append(f"## Recent Conversation\n{conversation_history}")

        # Relevant memories from Cortex
        if memories:
            parts.append("## Relevant Memories\n" + "\n".join(f"- {m}" for m in memories[:8]))

        # Skill outputs
        if skill_results:
            parts.append("## Skill Output\n" + "\n\n".join(skill_results))

        # The actual message
        parts.append(f"## Current Message\n{message}")

        return "\n\n".join(parts)

    @staticmethod
    def detect_emotion(user_text: str, response_text: str = "") -> str:
        """Quick keyword-based emotion detection from an exchange."""
        combined = (user_text + " " + response_text).lower()
        scores: dict[str, int] = {
            "frustration": 0, "curiosity": 0, "satisfaction": 0,
            "surprise": 0, "fear": 0,
        }
        _KW = {
            "frustration": ["ugh", "annoying", "broken", "not working", "failed", "again", "still"],
            "curiosity":   ["how", "why", "what if", "tell me", "curious", "wonder", "explain"],
            "satisfaction": ["nice", "perfect", "great", "thanks", "awesome", "works", "love it"],
            "surprise":    ["wow", "whoa", "really", "seriously", "no way", "unexpected"],
            "fear":        ["worried", "scared", "concern", "risk", "problem", "urgent", "critical"],
        }
        for emotion, keywords in _KW.items():
            for kw in keywords:
                if kw in combined:
                    scores[emotion] += 1
        top = max(scores, key=scores.get)  # type: ignore[arg-type]
        return top if scores[top] > 0 else "neutral"

    @staticmethod
    def extract_topics(text: str) -> list[str]:
        """Extract broad topic tags from text for memory tagging."""
        lower = text.lower()
        topics: list[str] = []
        _TOPIC_MAP = {
            "code":         ["code", "function", "bug", "python", "javascript", "api"],
            "architecture": ["architect", "system", "design", "scale", "infrastructure"],
            "deployment":   ["deploy", "docker", "server", "production", "kubernetes"],
            "security":     ["security", "auth", "token", "encrypt", "trust"],
            "memory":       ["memory", "cortex", "remember", "recall", "forget"],
            "agent":        ["agent", "organism", "organ", "sovereign", "skill"],
            "personal":     ["feeling", "mood", "tired", "happy", "stressed"],
        }
        for topic, keywords in _TOPIC_MAP.items():
            if any(kw in lower for kw in keywords):
                topics.append(topic)
        return topics or ["general"]
