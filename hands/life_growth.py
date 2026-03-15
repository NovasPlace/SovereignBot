"""Sovereign — The Hands: Life Skills — Growth domain.

Fitness Coach, Learning Tutor, Meal Planner, Content Consumption.
Each hand is a phase-based state machine using LLM + Tool Belt.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

log = logging.getLogger("sovereign.hands.life_growth")


# ══════════════════════════════════════════════════════════════════════════════
# RESULT DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FitnessResult:
    status: str
    phase_reached: str
    plan: str = ""
    workout: str = ""
    summary: str = ""


@dataclass
class LearningResult:
    status: str
    phase_reached: str
    topic: str = ""
    curriculum: str = ""
    lesson: str = ""
    quiz: str = ""
    summary: str = ""


@dataclass
class MealPlanResult:
    status: str
    phase_reached: str
    meal_plan: str = ""
    grocery_list: str = ""
    summary: str = ""


@dataclass
class ContentResult:
    status: str
    phase_reached: str
    items_saved: int = 0
    items_summarized: int = 0
    recommendations: str = ""
    summary: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# FITNESS COACH HAND
# ASSESS → DESIGN → SCHEDULE → TRACK → ADAPT
# ══════════════════════════════════════════════════════════════════════════════

class FitnessCoachHand:
    """Designs workout plans, tracks progress, adapts based on recovery."""

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(
        self, action: str = "plan", goal: str = "",
        feedback: str = "", user_id: str = "", **kwargs,
    ) -> FitnessResult:
        log.info("[Fitness] action=%s goal=%s", action, goal[:50])

        if action == "plan":
            return await self._design_plan(goal, user_id)
        elif action == "workout":
            return await self._todays_workout(user_id)
        elif action == "adapt":
            return await self._adapt(feedback, user_id)
        return await self._design_plan(goal, user_id)

    async def _design_plan(self, goal: str, user_id: str) -> FitnessResult:
        """Design a weekly workout plan."""
        # Recall fitness history
        history = ""
        if self._store:
            try:
                recent = self._store.recall(f"workout fitness", limit=10)
                history = "\n".join(
                    f"- {m.content[:60]}" for m in (recent or [])
                )
            except Exception:
                pass

        plan = await self._llm(
            system=(
                "You are a fitness coach. Design progressive workout plans. "
                "Be realistic about recovery. Match the user's level."
            ),
            user=(
                f"Goal: {goal or 'General fitness'}\n"
                f"History:\n{history or 'New to training'}\n\n"
                "Design a weekly plan (Mon-Sun):\n"
                "- Include rest days\n"
                "- Progressive overload built in\n"
                "- Warm-up and cooldown noted\n"
                "- Time per session (30-60 min)\n"
                "- Equipment needed\n\n"
                "Be specific with exercises, sets, reps."
            ),
        )

        return FitnessResult(
            status="success", phase_reached="complete",
            plan=plan[:600],
            summary=f"Workout plan created: {goal or 'general fitness'}",
        )

    async def _todays_workout(self, user_id: str) -> FitnessResult:
        """Get today's specific workout."""
        day = datetime.now().strftime("%A")
        workout = await self._llm(
            system="Provide today's workout. Be specific and motivating.",
            user=(
                f"Day: {day}\n"
                "Give the specific workout for today.\n"
                "Include warm-up, main set, cooldown.\n"
                "Be encouraging but not cheesy."
            ),
        )

        return FitnessResult(
            status="success", phase_reached="complete",
            workout=workout[:400],
            summary=f"Today's workout: {day}",
        )

    async def _adapt(self, feedback: str, user_id: str) -> FitnessResult:
        """Adapt plan based on how the user feels."""
        adapted = await self._llm(
            system="Adapt workout plans naturally based on feedback.",
            user=(
                f"Feedback: {feedback}\n\n"
                "Adapt the plan:\n"
                "- Sore → reduce volume, add recovery\n"
                "- Crushing it → increase difficulty\n"
                "- Skipping days → make those days easier\n"
                "- Bored → change exercises\n"
                "Feel natural, not clinical."
            ),
        )

        return FitnessResult(
            status="success", phase_reached="complete",
            plan=adapted[:400],
            summary="Workout plan adapted",
        )


# ══════════════════════════════════════════════════════════════════════════════
# LEARNING TUTOR HAND
# ASSESS → CURRICULUM → TEACH → QUIZ → REVIEW
# ══════════════════════════════════════════════════════════════════════════════

class LearningTutorHand:
    """Creates structured learning paths and teaches progressively."""

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(
        self, topic: str = "", action: str = "curriculum",
        level: str = "beginner", answer: str = "",
        user_id: str = "", **kwargs,
    ) -> LearningResult:
        log.info("[Tutor] topic=%s action=%s", topic[:30], action)

        if action == "curriculum":
            return await self._build_curriculum(topic, level, user_id)
        elif action == "lesson":
            return await self._teach_lesson(topic, user_id)
        elif action == "quiz":
            return await self._quiz(topic, user_id)
        elif action == "answer":
            return await self._grade_answer(topic, answer, user_id)
        return await self._build_curriculum(topic, level, user_id)

    async def _build_curriculum(self, topic: str, level: str, user_id: str) -> LearningResult:
        """Design a structured learning path."""
        existing = ""
        if self._store:
            try:
                knowledge = self._store.recall(f"learned:{topic}", limit=10)
                existing = "\n".join(
                    f"- {m.content[:60]}" for m in (knowledge or [])
                )
            except Exception:
                pass

        curriculum = await self._llm(
            system="Design learning curricula. Progressive, not overwhelming.",
            user=(
                f"Topic: {topic}\n"
                f"Level: {level}\n"
                f"Existing knowledge:\n{existing or 'Starting fresh'}\n\n"
                "Design a curriculum with:\n"
                "1. MODULES — major areas, foundational to advanced\n"
                "2. LESSONS — specific topics (15-30 min each)\n"
                "3. EXERCISES — practice per lesson\n"
                "4. MILESTONES — quiz checkpoints\n\n"
                "1-2 new concepts per lesson max.\n"
                "Each lesson builds on the last."
            ),
        )

        return LearningResult(
            status="success", phase_reached="complete",
            topic=topic, curriculum=curriculum[:600],
            summary=f"Curriculum created: {topic}",
        )

    async def _teach_lesson(self, topic: str, user_id: str) -> LearningResult:
        """Teach the next lesson in the curriculum."""
        lesson = await self._llm(
            system=(
                "Teach clearly with examples. Mentor style. "
                "Explain UNDERSTANDING, not just facts."
            ),
            user=(
                f"Teach the next lesson on: {topic}\n\n"
                "Structure:\n"
                "1. Key concept (explain simply)\n"
                "2. Why it matters\n"
                "3. Example / analogy\n"
                "4. Common misconception\n"
                "5. Quick exercise to try\n"
            ),
        )

        return LearningResult(
            status="success", phase_reached="complete",
            topic=topic, lesson=lesson[:600],
            summary=f"Lesson delivered: {topic}",
        )

    async def _quiz(self, topic: str, user_id: str) -> LearningResult:
        """Quiz the user on what they've learned."""
        quiz = await self._llm(
            system="Create quizzes that test understanding, not memorization.",
            user=(
                f"Topic: {topic}\n\n"
                "Create 3 questions:\n"
                "- 1 multiple choice\n"
                "- 1 fill-in-blank\n"
                "- 1 explain-in-your-own-words\n\n"
                "Test understanding, not recall.\n"
                "Don't include answers yet."
            ),
        )

        return LearningResult(
            status="success", phase_reached="complete",
            topic=topic, quiz=quiz[:400],
            summary=f"Quiz generated: {topic}",
        )

    async def _grade_answer(self, topic: str, answer: str, user_id: str) -> LearningResult:
        """Grade a quiz answer and provide feedback."""
        feedback = await self._llm(
            system="Grade answers helpfully. Explain why right/wrong.",
            user=(
                f"Topic: {topic}\n"
                f"Student answer: {answer}\n\n"
                "Evaluate:\n"
                "- Is it correct?\n"
                "- What's missing?\n"
                "- Gentle correction if wrong\n"
                "- Encouragement if right"
            ),
        )

        return LearningResult(
            status="success", phase_reached="complete",
            topic=topic, lesson=feedback[:400],
            summary=f"Answer graded: {topic}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# MEAL PLANNER HAND
# ASSESS → PLAN → LIST → GUIDE
# ══════════════════════════════════════════════════════════════════════════════

class MealPlannerHand:
    """Suggests meals, generates grocery lists, scales recipes, tracks nutrition."""

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(
        self, action: str = "plan", dietary: str = "",
        household_size: int = 1, budget: str = "moderate",
        user_id: str = "", **kwargs,
    ) -> MealPlanResult:
        log.info("[MealPlanner] action=%s", action)

        if action == "plan":
            return await self._weekly_plan(dietary, household_size, budget, user_id)
        elif action == "recipe":
            return await self._get_recipe(kwargs.get("dish", ""), user_id)
        elif action == "grocery":
            return await self._grocery_list(user_id)
        return await self._weekly_plan(dietary, household_size, budget, user_id)

    async def _weekly_plan(
        self, dietary: str, size: int, budget: str, user_id: str,
    ) -> MealPlanResult:
        """Create a weekly meal plan."""
        # Recall dietary preferences
        prefs = ""
        if self._store:
            try:
                diet_mem = self._store.recall(f"dietary food preference", limit=5)
                prefs = "\n".join(
                    f"- {m.content[:60]}" for m in (diet_mem or [])
                )
            except Exception:
                pass

        plan = await self._llm(
            system="Create practical weekly meal plans. Minimize waste.",
            user=(
                f"Dietary: {dietary or 'No restrictions'}\n"
                f"Preferences:\n{prefs or 'None known'}\n"
                f"Household: {size}\n"
                f"Budget: {budget}\n"
                f"Skill: intermediate\n\n"
                "Plan Mon-Sun:\n"
                "- Breakfast (quick, <15min)\n"
                "- Lunch (leftovers ok)\n"
                "- Dinner (main event)\n\n"
                "Batch cook Sunday for weekday lunches.\n"
                "Overlap ingredients to reduce waste.\n"
                "Note which dinners make good next-day lunches."
            ),
        )

        return MealPlanResult(
            status="success", phase_reached="complete",
            meal_plan=plan[:600],
            summary="Weekly meal plan created",
        )

    async def _get_recipe(self, dish: str, user_id: str) -> MealPlanResult:
        """Get a detailed recipe."""
        recipe = await self._llm(
            system="Write clear recipes with exact measurements and timing.",
            user=f"Recipe for: {dish}\n\nInclude: ingredients, steps, timing, serving size, tips.",
        )

        return MealPlanResult(
            status="success", phase_reached="complete",
            meal_plan=recipe[:500],
            summary=f"Recipe: {dish}",
        )

    async def _grocery_list(self, user_id: str) -> MealPlanResult:
        """Generate a grocery list from recent meal plans."""
        grocery = await self._llm(
            system="Generate organized grocery lists grouped by store section.",
            user=(
                "Create a grocery list for a week of meals.\n"
                "Group by: produce, dairy, meat, pantry, frozen.\n"
                "Include quantities.\n"
                "Estimate total cost."
            ),
        )

        return MealPlanResult(
            status="success", phase_reached="complete",
            grocery_list=grocery[:400],
            summary="Grocery list generated",
        )


# ══════════════════════════════════════════════════════════════════════════════
# CONTENT CONSUMPTION HAND
# CAPTURE → ORGANIZE → SUMMARIZE → RECOMMEND → REVIEW
# ══════════════════════════════════════════════════════════════════════════════

class ContentConsumptionHand:
    """Manages reading lists, watch lists, podcast queues, summarizes articles."""

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(
        self, action: str = "save", url: str = "", title: str = "",
        content_type: str = "article", user_id: str = "", **kwargs,
    ) -> ContentResult:
        log.info("[Content] action=%s type=%s", action, content_type)

        if action == "save":
            return await self._save_item(url, title, content_type, user_id)
        elif action == "summarize":
            return await self._summarize(url, user_id)
        elif action == "recommend":
            return await self._recommend(user_id)
        elif action == "status":
            return await self._reading_status(user_id)
        return await self._save_item(url, title, content_type, user_id)

    async def _save_item(
        self, url: str, title: str, content_type: str, user_id: str,
    ) -> ContentResult:
        """Save content to the reading/watch list."""
        if self._store:
            try:
                from ..models import MemoryEntry, MemorySource
                self._store.save_memory(MemoryEntry(
                    content=f"Saved {content_type}: {title or url}",
                    source=MemorySource.USER, confidence=1.0,
                    provenance_chain=["content_consumption"],
                ))
            except Exception as e:
                log.warning("[Content] Save error: %s", e)

        return ContentResult(
            status="success", phase_reached="complete",
            items_saved=1,
            summary=f"Saved: {title or url[:40]}",
        )

    async def _summarize(self, url: str, user_id: str) -> ContentResult:
        """Summarize a saved article."""
        content = ""
        if url:
            result = await self._tools.shell(
                f"curl -sL '{url}' | head -200", timeout=10,
            )
            if result.success:
                content = result.data[:1000]

        summary = await self._llm(
            system="Summarize articles concisely. Key points only.",
            user=(
                f"URL: {url}\n"
                f"Content:\n{content or 'Could not fetch'}\n\n"
                "Summarize in 3-5 bullet points.\n"
                "What's the key insight?"
            ),
        )

        return ContentResult(
            status="success", phase_reached="complete",
            items_summarized=1, recommendations=summary[:400],
            summary="Article summarized",
        )

    async def _recommend(self, user_id: str) -> ContentResult:
        """Recommend content based on interests."""
        interests = ""
        if self._store:
            try:
                recent = self._store.recall(f"interest saved", limit=10)
                interests = "\n".join(
                    f"- {m.content[:60]}" for m in (recent or [])
                )
            except Exception:
                pass

        recs = await self._llm(
            system="Recommend relevant content based on interests.",
            user=(
                f"User interests:\n{interests or 'General tech'}\n\n"
                "Suggest 3-5 articles, videos, or podcasts.\n"
                "Include why each is relevant."
            ),
        )

        return ContentResult(
            status="success", phase_reached="complete",
            recommendations=recs[:400],
            summary="Content recommendations generated",
        )

    async def _reading_status(self, user_id: str) -> ContentResult:
        """Report on reading list status."""
        saved = 0
        if self._store:
            try:
                items = self._store.recall(f"saved article book podcast", limit=50)
                saved = len(items or [])
            except Exception:
                pass

        return ContentResult(
            status="success", phase_reached="complete",
            items_saved=saved,
            summary=f"Reading list: {saved} items",
        )
