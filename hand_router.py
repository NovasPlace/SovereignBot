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
    # ── Part 8 originals ──────────────────────────────────────────────
    "code_engineer": [
        "write code", "write a function", "write a class", "write a script",
        "implement this", "implement a", "build this",
        "create a module", "create a function", "fix this code",
        "refactor", "add a feature", "code this",
        "make a plugin", "add to the codebase",
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
        "why is this failing", "system problem",
        "service is not starting", "out of disk", "memory issue",
        "cpu is spiking", "check the logs",
    ],
    # ── Part 11: Engineering ──────────────────────────────────────────
    "api_builder": [
        "build api", "build an api", "rest api", "graphql",
        "design endpoints", "api design", "create an api",
    ],
    "debugger": [
        "debug", "bug report", "not working", "broken behavior",
        "wrong output", "regression", "find the bug",
        "why is this broken", "trace this error",
    ],
    "test_engineer": [
        "write tests", "test suite", "coverage", "unit test",
        "integration test", "generate tests", "test this code",
    ],
    "cicd": [
        "ci/cd", "github actions", "pipeline", "continuous integration",
        "automated deploy", "gitlab ci", "set up ci",
    ],
    "performance": [
        "slow", "performance", "benchmark", "optimize speed",
        "bottleneck", "profile this", "make it faster",
    ],
    # ── Part 11: Data ─────────────────────────────────────────────────
    "data_analyst": [
        "analyze data", "analyze this csv", "spreadsheet",
        "chart", "visualization", "statistics",
        "trend analysis", "data report",
    ],
    "database": [
        "schema", "migration", "database design", "sql",
        "optimize query", "design tables", "database schema",
    ],
    "scraper": [
        "scrape", "crawl", "extract data from",
        "web scraping", "pull data from website",
        "scrape this site",
    ],
    # ── Part 11: Communication ────────────────────────────────────────
    "email": [
        "check email", "draft email", "reply to email",
        "inbox", "email summary", "send email",
    ],
    "social_media": [
        "post on", "tweet", "linkedin post",
        "social media", "schedule post", "check mentions",
        "write a tweet", "facebook post",
    ],
    "meeting": [
        "meeting notes", "summarize meeting", "action items from meeting",
        "transcribe meeting", "follow up from meeting",
        "meeting summary",
    ],
    # ── Part 11: Business ─────────────────────────────────────────────
    "invoice": [
        "invoice", "bill client", "generate invoice",
        "send invoice", "payment tracking",
    ],
    "competitive": [
        "competitor analysis", "competitive analysis",
        "market research", "what are they doing",
        "monitor competitors", "track competitors",
    ],
    "seo": [
        "seo", "search ranking", "meta tags",
        "page speed", "search optimization", "seo audit",
    ],
    "legal": [
        "terms of service", "privacy policy", "contract",
        "nda", "license agreement", "legal document",
        "draft a contract",
    ],
    # ── Part 11: Product ──────────────────────────────────────────────
    "documentation": [
        "write docs", "generate docs", "api reference",
        "document this codebase", "generate readme",
    ],
    "design_system": [
        "design system", "component library", "style guide",
        "design tokens", "ui kit", "build components",
    ],
    "onboarding": [
        "onboarding flow", "user journey", "first-time experience",
        "tutorial", "walkthrough flow", "user onboarding",
    ],
    # ── Part 12: Life Skills — Daily ─────────────────────────────────
    "daily_planner": [
        "plan my day", "what should I do today", "daily plan",
        "what's on my plate", "priorities today", "schedule my day",
        "morning plan", "today's agenda",
    ],
    "habit_tracker": [
        "habit", "streak", "I did my", "I skipped",
        "track my", "did I", "how many days", "habit check",
        "habit status", "log habit",
    ],
    "budget": [
        "spent", "bought", "cost", "budget", "expense",
        "how much did I spend", "monthly spending", "receipt",
        "log expense", "financial report", "money tracker",
    ],
    "journal": [
        "journal", "reflect", "how was my day", "write about",
        "monthly review", "looking back", "journal prompt",
        "daily reflection", "journaling",
    ],
    "news_curator": [
        "news", "what's happening", "headlines", "briefing",
        "catch me up", "what did I miss", "daily news",
        "news digest", "current events",
    ],
    # ── Part 12: Life Skills — Growth ────────────────────────────────
    "fitness": [
        "workout", "exercise", "gym", "run", "lift",
        "fitness", "sore", "rest day", "gains",
        "workout plan", "fitness plan",
    ],
    "learning": [
        "learn", "study", "teach me", "quiz me", "explain",
        "course", "understand", "curriculum",
        "learning path", "tutor",
    ],
    "meal_planner": [
        "meal plan", "dinner", "recipe", "grocery", "what to eat",
        "cook", "ingredients", "hungry", "meal prep",
        "grocery list", "weekly meals",
    ],
    "content": [
        "save this article", "reading list", "watch later",
        "podcast", "book recommendation", "summarize this",
        "watch list", "saved articles",
    ],
    # ── Part 12: Life Skills — Major Life ────────────────────────────
    "travel": [
        "trip", "vacation", "travel", "flight", "hotel",
        "where should I go", "itinerary", "packing list",
        "plan a trip", "travel plan",
    ],
    "shopping": [
        "buy", "purchase", "looking for", "best product",
        "recommend a", "compare products", "review",
        "deal", "price check", "wishlist",
    ],
    "relationships": [
        "birthday", "anniversary", "gift idea", "check in with",
        "haven't talked to", "contact list", "friend",
        "gift suggestion", "important date",
    ],
    "home_auto": [
        "lights", "thermostat", "smart home", "automation",
        "routine", "turn on", "turn off", "lock door",
        "home automation", "smart devices",
    ],
    "relocation": [
        "moving", "relocate", "new city", "apartment",
        "neighborhood", "cost of living", "moving checklist",
        "move to", "compare cities",
    ],
    "health": [
        "symptom", "medication", "doctor", "appointment",
        "headache", "feeling sick", "medicine reminder",
        "health log", "track symptom",
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
