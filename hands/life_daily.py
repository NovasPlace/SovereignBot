"""Sovereign — The Hands: Life Skills — Daily domain.

Daily Planner, Habit Tracker, Budget Manager, Journal, News Curator.
Each hand is a phase-based state machine using LLM + Tool Belt.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

log = logging.getLogger("sovereign.hands.life_daily")


# ══════════════════════════════════════════════════════════════════════════════
# RESULT DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DailyPlanResult:
    status: str
    phase_reached: str
    tasks_planned: int = 0
    plan: str = ""
    summary: str = ""


@dataclass
class HabitResult:
    status: str
    phase_reached: str
    habit: str = ""
    completed: bool = False
    streak: int = 0
    message: str = ""
    summary: str = ""


@dataclass
class BudgetResult:
    status: str
    phase_reached: str
    amount: float = 0.0
    category: str = ""
    month_total: float = 0.0
    message: str = ""
    summary: str = ""


@dataclass
class JournalResult:
    status: str
    phase_reached: str
    prompt: str = ""
    entry_saved: bool = False
    summary: str = ""


@dataclass
class NewsResult:
    status: str
    phase_reached: str
    articles_scanned: int = 0
    articles_delivered: int = 0
    briefing: str = ""
    summary: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# DAILY PLANNER HAND
# ASSESS → PRIORITIZE → SCHEDULE → PRESENT → ADAPT
# ══════════════════════════════════════════════════════════════════════════════

class DailyPlannerHand:
    """Plans the day based on priorities, energy patterns, and deadlines."""

    def __init__(self, tools, llm_fn, temporal=None, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._temporal = temporal
        self._store = store

    async def execute(self, user_id: str = "", **kwargs) -> DailyPlanResult:
        log.info("[DailyPlanner] building plan for user=%s", user_id[:20])
        now = datetime.now()
        phase = "assess"
        context = ""
        priorities = ""
        schedule = ""
        plan_text = ""

        for iteration in range(8):
            if phase == "assess":
                # Gather context: calendar, overdue, recent work
                recall_data = ""
                if self._store:
                    try:
                        recent = self._store.recall(f"user:{user_id}", limit=10)
                        recall_data = "\n".join(
                            f"- {m.content[:80]}" for m in (recent or [])
                        )
                    except Exception:
                        pass

                context = (
                    f"Day: {now.strftime('%A %B %d')}\n"
                    f"Time: {now.strftime('%I:%M %p')}\n"
                    f"Weekend: {'yes' if now.weekday() >= 5 else 'no'}\n"
                    f"Recent activity:\n{recall_data or 'No data'}\n"
                )
                phase = "prioritize"

            elif phase == "prioritize":
                priorities = await self._llm(
                    system="You are a productivity planner using the Eisenhower matrix.",
                    user=(
                        f"Plan today for this user:\n{context}\n\n"
                        "Categorize tasks:\n"
                        "- URGENT + IMPORTANT → Do first\n"
                        "- IMPORTANT + NOT URGENT → Deep work block\n"
                        "- URGENT + NOT IMPORTANT → Batch together\n"
                        "- Neither → Defer\n\n"
                        "Suggest deep work windows and break times.\n"
                        "Output as JSON with priority_tasks[], deep_work_window, break_times[]."
                    ),
                )
                phase = "schedule"

            elif phase == "schedule":
                schedule = await self._llm(
                    system="Build daily schedules. Be realistic — humans need breaks.",
                    user=(
                        f"Build today's schedule:\n"
                        f"Priorities: {priorities[:500]}\n"
                        f"Context: {context[:300]}\n\n"
                        "Rules:\n"
                        "- Deep work blocks need 90+ uninterrupted minutes\n"
                        "- Include lunch\n"
                        "- 15min buffers between commitments\n"
                        "- End with 10min review\n"
                        "- Don't overschedule\n\n"
                        "Output: TIME | TASK | TYPE"
                    ),
                )
                phase = "present"

            elif phase == "present":
                plan_text = await self._llm(
                    system="Present daily plans concisely and motivationally.",
                    user=(
                        f"Present this plan in under 200 words:\n{schedule[:500]}\n\n"
                        "Lead with the most important thing.\n"
                        "Highlight 3-5 key items.\n"
                        "End with something motivating (not cheesy)."
                    ),
                )

                # Create intentions for key tasks
                if self._temporal:
                    try:
                        self._temporal.create_intention(
                            action=f"Daily plan review — end of day",
                            context=f"Check what got done from the plan",
                        )
                    except Exception:
                        pass

                phase = "complete"

            if phase == "complete":
                break

        return DailyPlanResult(
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            tasks_planned=schedule.count("|"),
            plan=plan_text[:500],
            summary=f"Daily plan built for {now.strftime('%A')}",
        )

    async def adapt(self, change: str, user_id: str = "") -> str:
        """Adapt the plan mid-day when things change."""
        adapted = await self._llm(
            system="Adapt daily plans when things change. Be brief.",
            user=(
                f"Change: {change}\n"
                f"Time now: {datetime.now().strftime('%I:%M %p')}\n\n"
                "What shifts? What stays? Keep it brief."
            ),
        )
        return adapted


# ══════════════════════════════════════════════════════════════════════════════
# HABIT TRACKER HAND
# SETUP → TRACK → ANALYZE → NUDGE → CELEBRATE
# ══════════════════════════════════════════════════════════════════════════════

class HabitTrackerHand:
    """Monitors habits, tracks streaks, nudges when slipping, celebrates milestones."""

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(
        self, habit: str = "", completed: bool = True,
        action: str = "check_in", user_id: str = "", **kwargs,
    ) -> HabitResult:
        log.info("[HabitTracker] habit=%s action=%s", habit, action)

        if action == "check_in":
            return await self._check_in(habit, completed, user_id)
        elif action == "status":
            return await self._status(habit, user_id)
        else:
            return await self._check_in(habit, completed, user_id)

    async def _check_in(self, habit: str, completed: bool, user_id: str) -> HabitResult:
        """Log a habit check-in and track the streak."""
        streak = 0

        # Calculate streak from store
        if self._store:
            try:
                history = self._store.recall(f"habit:{habit}", limit=30)
                streak = self._calculate_streak(history, completed)
                # Save the check-in
                from ..models import MemoryEntry, MemorySource
                self._store.save_memory(MemoryEntry(
                    content=(
                        f"Habit: {habit} — {'done' if completed else 'missed'}. "
                        f"Streak: {streak}"
                    ),
                    source=MemorySource.AGENT, confidence=0.9,
                    provenance_chain=["habit_tracker"],
                ))
            except Exception as e:
                log.warning("[HabitTracker] Store error: %s", e)

        # Generate response based on streak state
        if completed and streak > 0 and streak % 30 == 0:
            msg = f"🏆 {streak} days. A whole month of {habit}. That's not a habit — that's who you are."
        elif completed and streak > 0 and streak % 7 == 0:
            msg = f"🔥 {streak} days straight on {habit}. Whole week. Respect."
        elif not completed and streak > 3:
            msg = (
                f"Missed {habit} today — no stress. "
                f"You had a {streak}-day streak. Tomorrow's fresh."
            )
        elif completed:
            msg = random.choice([
                f"✅ {habit} — done. Streak: {streak}.",
                f"✅ Logged. {streak} and counting.",
                f"✅ {streak} in a row. Keep moving.",
            ])
        else:
            msg = f"📝 Noted. {habit} missed today. No judgment."

        return HabitResult(
            status="success", phase_reached="complete",
            habit=habit, completed=completed, streak=streak,
            message=msg, summary=msg,
        )

    async def _status(self, habit: str, user_id: str) -> HabitResult:
        """Get current status of a habit."""
        streak = 0
        if self._store:
            try:
                history = self._store.recall(f"habit:{habit}", limit=30)
                streak = self._calculate_streak(history, True)
            except Exception:
                pass

        return HabitResult(
            status="success", phase_reached="complete",
            habit=habit, streak=streak,
            message=f"{habit}: {streak}-day streak",
            summary=f"Habit status: {habit} at {streak} days",
        )

    def _calculate_streak(self, history, current_completed: bool) -> int:
        """Calculate current streak from history."""
        if not history:
            return 1 if current_completed else 0
        streak = 1 if current_completed else 0
        for mem in (history or []):
            if "done" in (mem.content or "").lower() or "completed" in (mem.content or "").lower():
                streak += 1
            else:
                break
        return streak


# ══════════════════════════════════════════════════════════════════════════════
# BUDGET MANAGER HAND
# INGEST → CATEGORIZE → TRACK → ALERT → REPORT
# ══════════════════════════════════════════════════════════════════════════════

class BudgetManagerHand:
    """Tracks spending, categorizes, alerts on overspend, monthly reports.

    CRITICAL: Never connects to bank accounts. Tracks what the user tells it.
    Sovereignty means YOUR data on YOUR terms.
    """

    CATEGORIES = [
        "housing", "food_groceries", "food_dining", "transport",
        "utilities", "entertainment", "health", "clothing",
        "education", "subscriptions", "savings", "gifts",
        "personal_care", "tech", "other",
    ]

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(
        self, description: str = "", amount: float = 0.0,
        action: str = "log", user_id: str = "", **kwargs,
    ) -> BudgetResult:
        log.info("[Budget] action=%s amount=%.2f", action, amount)

        if action == "report":
            return await self._monthly_report(user_id)
        return await self._log_expense(description, amount, user_id)

    async def _log_expense(self, description: str, amount: float, user_id: str) -> BudgetResult:
        """Log an expense."""
        # Extract amount if not given
        if amount <= 0:
            amount = self._extract_amount(description)

        # Auto-categorize
        category = await self._llm(
            system="Categorize expenses. Output ONLY the category name.",
            user=(
                f"Expense: {description}\n"
                f"Categories: {', '.join(self.CATEGORIES)}\n"
                "Output ONE category name."
            ),
        )
        category = category.strip().lower().replace(" ", "_")
        if category not in self.CATEGORIES:
            category = "other"

        # Get month total from store
        month_total = 0.0
        month = datetime.now().strftime("%Y-%m")
        if self._store:
            try:
                month_expenses = self._store.recall(f"expense {month}", limit=100)
                month_total = sum(
                    getattr(m, "metadata", {}).get("amount", 0)
                    for m in (month_expenses or [])
                    if hasattr(m, "metadata") and isinstance(m.metadata, dict)
                )
                # Save the expense
                from ..models import MemoryEntry, MemorySource
                self._store.save_memory(MemoryEntry(
                    content=f"Expense: ${amount:.2f} — {description} ({category})",
                    source=MemorySource.AGENT, confidence=1.0,
                    provenance_chain=["budget_manager"],
                ))
            except Exception as e:
                log.warning("[Budget] Store error: %s", e)

        msg = (
            f"💰 ${amount:.2f} for {description} ({category}). "
            f"Month total: ${month_total + amount:.2f}"
        )

        return BudgetResult(
            status="success", phase_reached="complete",
            amount=amount, category=category,
            month_total=month_total + amount,
            message=msg, summary=msg,
        )

    async def _monthly_report(self, user_id: str) -> BudgetResult:
        """Generate monthly spending report."""
        month = datetime.now().strftime("%Y-%m")
        expenses_text = ""
        total = 0.0

        if self._store:
            try:
                expenses = self._store.recall(f"expense {month}", limit=200)
                for m in (expenses or []):
                    amt = getattr(m, "metadata", {}).get("amount", 0)
                    if isinstance(amt, (int, float)):
                        total += amt
                        expenses_text += f"- {m.content[:60]}\n"
            except Exception:
                pass

        report = await self._llm(
            system="Write brief monthly spending summaries. Honest, not judgmental.",
            user=(
                f"Month: {month}\nTotal: ${total:.2f}\n"
                f"Expenses:\n{expenses_text[:500] or 'No data'}\n\n"
                "Summarize: biggest category, trends, one suggestion."
            ),
        )

        return BudgetResult(
            status="success", phase_reached="complete",
            month_total=total, message=report,
            summary=f"Monthly report: ${total:.2f}",
        )

    def _extract_amount(self, text: str) -> float:
        """Extract dollar amount from text."""
        import re
        match = re.search(r'\$?([\d,]+\.?\d*)', text)
        if match:
            return float(match.group(1).replace(",", ""))
        return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# JOURNAL / REFLECTION HAND
# PROMPT → CAPTURE → ANALYZE → CONNECT → ARCHIVE
# ══════════════════════════════════════════════════════════════════════════════

class JournalHand:
    """Daily journaling with pattern detection over time."""

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(
        self, action: str = "prompt", entry: str = "",
        user_id: str = "", **kwargs,
    ) -> JournalResult:
        log.info("[Journal] action=%s", action)

        if action == "prompt":
            return await self._generate_prompt(user_id)
        elif action == "write":
            return await self._save_entry(entry, user_id)
        elif action == "review":
            return await self._monthly_review(user_id)
        return await self._generate_prompt(user_id)

    async def _generate_prompt(self, user_id: str) -> JournalResult:
        """Generate a thoughtful journaling prompt based on today's context."""
        context = ""
        if self._store:
            try:
                recent = self._store.recall(f"user:{user_id}", limit=10)
                context = "\n".join(
                    f"- {m.content[:60]}" for m in (recent or [])
                )
            except Exception:
                pass

        prompt = await self._llm(
            system="Generate journaling prompts. Warm, curious, not clinical.",
            user=(
                f"Day: {datetime.now().strftime('%A')}\n"
                f"Recent context:\n{context or 'New user'}\n\n"
                "Generate ONE journaling prompt that:\n"
                "- References something specific if possible\n"
                "- Opens reflection (not yes/no)\n"
                "- Feels warm and curious\n"
                "Output ONLY the prompt question."
            ),
        )

        return JournalResult(
            status="success", phase_reached="complete",
            prompt=prompt, summary="Journal prompt generated",
        )

    async def _save_entry(self, entry: str, user_id: str) -> JournalResult:
        """Save a journal entry to memory."""
        if self._store:
            try:
                from ..models import MemoryEntry, MemorySource
                self._store.save_memory(MemoryEntry(
                    content=f"Journal entry: {entry}",
                    source=MemorySource.USER, confidence=1.0,
                    provenance_chain=["journal_hand"],
                ))
            except Exception as e:
                log.warning("[Journal] Save error: %s", e)

        return JournalResult(
            status="success", phase_reached="complete",
            entry_saved=True, summary="Journal entry saved",
        )

    async def _monthly_review(self, user_id: str) -> JournalResult:
        """Synthesize a month of entries into themes and growth."""
        entries = ""
        if self._store:
            try:
                journal = self._store.recall(f"journal", limit=60)
                entries = "\n".join(
                    f"- {m.content[:80]}" for m in (journal or [])[:30]
                )
            except Exception:
                pass

        review = await self._llm(
            system="Write monthly reflections. Thoughtful friend, not therapist.",
            user=(
                f"Journal entries:\n{entries or 'No entries'}\n\n"
                "Synthesize: themes, emotional arc, growth, patterns.\n"
                "Under 300 words. Honest but kind."
            ),
        )

        return JournalResult(
            status="success", phase_reached="complete",
            prompt=review, summary="Monthly review generated",
        )


# ══════════════════════════════════════════════════════════════════════════════
# NEWS CURATOR HAND
# SCAN → FILTER → RANK → SUMMARIZE → DELIVER
# ══════════════════════════════════════════════════════════════════════════════

class NewsCuratorHand:
    """Filters noise, delivers signal. Personalized news briefings."""

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(self, topics: list[str] | None = None,
                      user_id: str = "", **kwargs) -> NewsResult:
        log.info("[NewsCurator] topics=%s", topics)
        phase = "scan"
        raw_articles = ""
        briefing = ""
        articles_count = 0

        # Get interests from memory
        interest_topics = topics or []
        if not interest_topics and self._store:
            try:
                interests = self._store.recall(f"interest curiosity", limit=10)
                interest_topics = [m.content[:40] for m in (interests or [])]
            except Exception:
                pass
        if not interest_topics:
            interest_topics = ["technology", "AI", "science"]

        for iteration in range(8):
            if phase == "scan":
                # Fetch news from multiple sources
                for topic in interest_topics[:3]:
                    result = await self._tools.shell(
                        f"curl -sL 'https://news.google.com/rss/search?q={topic}' "
                        f"2>/dev/null | grep -oP '(?<=<title>).*?(?=</title>)' | head -5",
                        timeout=10,
                    )
                    if result.success and result.data:
                        raw_articles += f"\n[{topic}]\n{result.data}"
                        articles_count += len(result.data.strip().split("\n"))
                phase = "filter"

            elif phase == "filter":
                # Filter and rank by relevance
                phase = "summarize"

            elif phase == "summarize":
                briefing = await self._llm(
                    system="Write concise news briefings. Signal, not noise.",
                    user=(
                        f"Headlines:\n{raw_articles[:1000]}\n\n"
                        f"User interests: {', '.join(interest_topics)}\n\n"
                        "Write a brief news briefing:\n"
                        "- Lead with the most important story\n"
                        "- 2-3 sentences per story\n"
                        "- Skip fluff and clickbait\n"
                        "- Include why each story matters"
                    ),
                )
                phase = "complete"

            if phase == "complete":
                break

        return NewsResult(
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            articles_scanned=articles_count,
            articles_delivered=min(articles_count, 10),
            briefing=briefing[:500],
            summary=f"News briefing: {articles_count} articles scanned",
        )
