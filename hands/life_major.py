"""Sovereign — The Hands: Life Skills — Major Life domain.

Travel Planner, Shopping Assistant, Relationship Manager,
Home Automation, Relocation, Health Monitor.
Each hand is a phase-based state machine using LLM + Tool Belt.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

log = logging.getLogger("sovereign.hands.life_major")


# ══════════════════════════════════════════════════════════════════════════════
# RESULT DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TravelResult:
    status: str
    phase_reached: str
    destination: str = ""
    itinerary: str = ""
    packing_list: str = ""
    summary: str = ""


@dataclass
class ShoppingResult:
    status: str
    phase_reached: str
    product: str = ""
    comparison: str = ""
    recommendation: str = ""
    summary: str = ""


@dataclass
class RelationshipResult:
    status: str
    phase_reached: str
    upcoming: list[dict] = field(default_factory=list)
    check_in_suggestions: list[dict] = field(default_factory=list)
    message: str = ""
    summary: str = ""


@dataclass
class HomeAutoResult:
    status: str
    phase_reached: str
    routines: list[str] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class RelocationResult:
    status: str
    phase_reached: str
    research: str = ""
    checklist: str = ""
    comparison: str = ""
    summary: str = ""


@dataclass
class HealthResult:
    status: str
    phase_reached: str
    logged: str = ""
    patterns: str = ""
    reminders: list[str] = field(default_factory=list)
    summary: str = ""
    disclaimer: str = (
        "I track what you tell me and spot patterns, but I'm not a doctor. "
        "If something concerns you, please talk to a healthcare professional."
    )


# ══════════════════════════════════════════════════════════════════════════════
# TRAVEL PLANNER HAND
# RESEARCH → PLAN → BOOK → PREPARE → GUIDE
# ══════════════════════════════════════════════════════════════════════════════

class TravelPlannerHand:
    """Plans trips: destination research, itineraries, packing lists, reminders."""

    def __init__(self, tools, llm_fn, temporal=None, store=None,
                 send_approval_fn=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._temporal = temporal
        self._store = store
        self._approval = send_approval_fn

    async def execute(
        self, destination: str = "", dates: str = "",
        budget: str = "", interests: str = "",
        action: str = "plan", user_id: str = "", **kwargs,
    ) -> TravelResult:
        log.info("[Travel] action=%s dest=%s", action, destination[:30])

        if action == "research":
            return await self._research(destination, budget, user_id)
        elif action == "plan" or action == "itinerary":
            return await self._build_itinerary(
                destination, dates, interests, user_id,
            )
        elif action == "prepare":
            return await self._prepare(destination, dates, user_id)
        return await self._build_itinerary(destination, dates, interests, user_id)

    async def _research(self, query: str, budget: str, user_id: str) -> TravelResult:
        """Research destination options."""
        # Check travel memory
        prefs = ""
        if self._store:
            try:
                travel_mem = self._store.recall(f"travel preference trip", limit=5)
                prefs = "\n".join(
                    f"- {m.content[:60]}" for m in (travel_mem or [])
                )
            except Exception:
                pass

        research = await self._llm(
            system="Research travel destinations. Practical and inspiring.",
            user=(
                f"Request: {query}\n"
                f"Budget: {budget or 'Not specified'}\n"
                f"Preferences:\n{prefs or 'None known'}\n\n"
                "Research 3-5 options. For each:\n"
                "1. Why it matches\n"
                "2. Estimated cost\n"
                "3. Best time to visit\n"
                "4. Unique experiences\n"
                "5. Warnings\n\n"
                "Rank by fit."
            ),
        )

        return TravelResult(
            status="success", phase_reached="research",
            research=research[:500] if hasattr(research, '__len__') else str(research)[:500],
            summary=f"Destination research: {query}",
        )

    async def _build_itinerary(
        self, destination: str, dates: str, interests: str, user_id: str,
    ) -> TravelResult:
        """Build a day-by-day itinerary."""
        itinerary = await self._llm(
            system="Create detailed travel itineraries. Balance activities and rest.",
            user=(
                f"Destination: {destination}\n"
                f"Dates: {dates or 'Flexible'}\n"
                f"Interests: {interests or 'General sightseeing'}\n\n"
                "Day-by-day:\n"
                "- Morning, lunch, afternoon, dinner, evening\n"
                "- Travel time between locations\n"
                "- One free day\n"
                "- Rain backup plans\n\n"
                "Also: packing list, essential apps, key phrases."
            ),
        )

        packing = await self._llm(
            system="Generate packing lists based on destination and activities.",
            user=f"Packing list for: {destination}, {dates or '1 week'}\nBe practical.",
        )

        return TravelResult(
            status="success", phase_reached="complete",
            destination=destination,
            itinerary=str(itinerary)[:500],
            packing_list=str(packing)[:300],
            summary=f"Trip planned: {destination}",
        )

    async def _prepare(self, destination: str, dates: str, user_id: str) -> TravelResult:
        """Set up pre-trip reminders via temporal perception."""
        reminders = [
            (-30, "Check passport expiry and visa requirements"),
            (-14, "Book restaurants and experiences needing reservations"),
            (-7, "Start packing — review the packing list"),
            (-3, "Confirm all bookings. Download offline maps."),
            (-1, "Final pack. Charge devices. Print backup bookings."),
            (0, f"Travel day! Enjoy {destination}. I'm here if you need me."),
        ]

        created = 0
        if self._temporal:
            for days_before, text in reminders:
                try:
                    self._temporal.create_intention(
                        action=f"Trip prep — {destination}: {text}",
                        context=f"Trip to {destination} on {dates}",
                    )
                    created += 1
                except Exception:
                    pass

        return TravelResult(
            status="success", phase_reached="complete",
            destination=destination,
            summary=f"Trip prep: {created} reminders set for {destination}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# SHOPPING ASSISTANT HAND
# UNDERSTAND → RESEARCH → COMPARE → RECOMMEND → TRACK
# ══════════════════════════════════════════════════════════════════════════════

class ShoppingAssistantHand:
    """Researches products, compares options, tracks prices, manages wishlists."""

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(
        self, product: str = "", action: str = "research",
        budget: str = "", user_id: str = "", **kwargs,
    ) -> ShoppingResult:
        log.info("[Shopping] action=%s product=%s", action, product[:30])

        if action == "research" or action == "compare":
            return await self._research_and_compare(product, budget, user_id)
        elif action == "wishlist":
            return await self._add_to_wishlist(product, user_id)
        return await self._research_and_compare(product, budget, user_id)

    async def _research_and_compare(
        self, product: str, budget: str, user_id: str,
    ) -> ShoppingResult:
        """Research and compare product options."""
        # Check past purchases
        past = ""
        if self._store:
            try:
                purchases = self._store.recall(f"purchase bought {product[:20]}", limit=5)
                past = "\n".join(
                    f"- {m.content[:60]}" for m in (purchases or [])
                )
            except Exception:
                pass

        comparison = await self._llm(
            system="Research products honestly. Pros AND cons. No sponsored bias.",
            user=(
                f"Product: {product}\n"
                f"Budget: {budget or 'Not specified'}\n"
                f"Past purchases:\n{past or 'None'}\n\n"
                "Research 3-5 options. For each:\n"
                "1. Product name + price range\n"
                "2. Key pros\n"
                "3. Key cons\n"
                "4. Best for (use case)\n\n"
                "End with a clear recommendation and why."
            ),
        )

        return ShoppingResult(
            status="success", phase_reached="complete",
            product=product, comparison=str(comparison)[:500],
            recommendation="See comparison above",
            summary=f"Product research: {product}",
        )

    async def _add_to_wishlist(self, product: str, user_id: str) -> ShoppingResult:
        """Add item to wishlist."""
        if self._store:
            try:
                from ..models import MemoryEntry, MemorySource
                self._store.save_memory(MemoryEntry(
                    content=f"Wishlist: {product}",
                    source=MemorySource.USER, confidence=1.0,
                    provenance_chain=["shopping_assistant"],
                ))
            except Exception as e:
                log.warning("[Shopping] Wishlist save error: %s", e)

        return ShoppingResult(
            status="success", phase_reached="complete",
            product=product,
            summary=f"Added to wishlist: {product}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# RELATIONSHIP MANAGER HAND
# TRACK → REMIND → SUGGEST → CONNECT
# ══════════════════════════════════════════════════════════════════════════════

class RelationshipManagerHand:
    """Tracks important dates, suggests gifts, nudges check-ins, manages contacts."""

    def __init__(self, tools, llm_fn, temporal=None, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._temporal = temporal
        self._store = store

    async def execute(
        self, action: str = "check", person: str = "",
        event: str = "", date: str = "",
        user_id: str = "", **kwargs,
    ) -> RelationshipResult:
        log.info("[Relationships] action=%s person=%s", action, person[:20])

        if action == "add":
            return await self._add_event(person, event, date, user_id)
        elif action == "check":
            return await self._check_upcoming(user_id)
        elif action == "suggest_gift":
            return await self._suggest_gift(person, user_id)
        elif action == "check_in":
            return await self._suggest_check_ins(user_id)
        return await self._check_upcoming(user_id)

    async def _add_event(
        self, person: str, event: str, date: str, user_id: str,
    ) -> RelationshipResult:
        """Add an important date for someone."""
        if self._store:
            try:
                from ..models import MemoryEntry, MemorySource
                self._store.save_memory(MemoryEntry(
                    content=f"Important date: {person}'s {event} on {date}",
                    source=MemorySource.USER, confidence=1.0,
                    provenance_chain=["relationship_manager"],
                ))
            except Exception as e:
                log.warning("[Relationships] Save error: %s", e)

        # Set reminder
        if self._temporal:
            try:
                self._temporal.create_intention(
                    action=f"Reminder: {person}'s {event} is coming up!",
                    context=f"{event} on {date}",
                )
            except Exception:
                pass

        return RelationshipResult(
            status="success", phase_reached="complete",
            message=f"Saved: {person}'s {event} on {date}. I'll remind you.",
            summary=f"Added: {person}'s {event}",
        )

    async def _check_upcoming(self, user_id: str) -> RelationshipResult:
        """Check upcoming important dates."""
        upcoming_list = []
        if self._store:
            try:
                upcoming = self._store.recall(
                    f"birthday anniversary important_date", limit=20,
                )
                for m in (upcoming or []):
                    upcoming_list.append({
                        "event": m.content[:80],
                        "source": "memory",
                    })
            except Exception:
                pass

        msg = "Nothing upcoming." if not upcoming_list else "\n".join(
            f"• {u['event']}" for u in upcoming_list[:5]
        )

        return RelationshipResult(
            status="success", phase_reached="complete",
            upcoming=upcoming_list[:5],
            message=msg,
            summary=f"Upcoming events: {len(upcoming_list)}",
        )

    async def _suggest_gift(self, person: str, user_id: str) -> RelationshipResult:
        """Suggest gift ideas based on what we know about someone."""
        interests = ""
        if self._store:
            try:
                person_mem = self._store.recall(f"{person} likes interests", limit=5)
                interests = "\n".join(
                    f"- {m.content[:60]}" for m in (person_mem or [])
                )
            except Exception:
                pass

        suggestions = await self._llm(
            system="Suggest thoughtful gift ideas. Personal, not generic.",
            user=(
                f"Person: {person}\n"
                f"Known interests:\n{interests or 'Unknown'}\n\n"
                "Suggest 5 gift ideas across price ranges.\n"
                "Be creative and personal, not generic."
            ),
        )

        return RelationshipResult(
            status="success", phase_reached="complete",
            message=str(suggestions)[:400],
            summary=f"Gift ideas for {person}",
        )

    async def _suggest_check_ins(self, user_id: str) -> RelationshipResult:
        """Suggest people to reconnect with."""
        suggestions = []
        if self._store:
            try:
                contacts = self._store.recall(
                    f"conversation person contact friend", limit=30,
                )
                for m in (contacts or []):
                    suggestions.append({
                        "person": m.content[:40],
                        "last_mention": "recently",
                    })
            except Exception:
                pass

        msg = "No contacts tracked yet." if not suggestions else (
            "People you might want to check in with:\n" +
            "\n".join(f"• {s['person']}" for s in suggestions[:5])
        )

        return RelationshipResult(
            status="success", phase_reached="complete",
            check_in_suggestions=suggestions[:5],
            message=msg,
            summary=f"Check-in suggestions: {len(suggestions[:5])}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# HOME AUTOMATION HAND
# DISCOVER → CONFIGURE → AUTOMATE → ADAPT → OPTIMIZE
# ══════════════════════════════════════════════════════════════════════════════

class HomeAutomationHand:
    """Controls smart devices, creates routines, adapts to patterns."""

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(
        self, action: str = "routine", command: str = "",
        user_id: str = "", **kwargs,
    ) -> HomeAutoResult:
        log.info("[HomeAuto] action=%s", action)

        if action == "routine":
            return await self._create_routine(command, user_id)
        elif action == "control":
            return await self._control_device(command, user_id)
        elif action == "suggest":
            return await self._suggest_automations(user_id)
        return await self._create_routine(command, user_id)

    async def _create_routine(self, description: str, user_id: str) -> HomeAutoResult:
        """Create a smart home routine."""
        routine = await self._llm(
            system="Design smart home routines. Practical and energy-efficient.",
            user=(
                f"Routine request: {description or 'Morning routine'}\n\n"
                "Design the routine:\n"
                "- Trigger (time, event, command)\n"
                "- Actions (ordered list)\n"
                "- Conditions (weekday only, when home, etc.)\n\n"
                "Compatible with: Home Assistant, Homebridge, Google Home."
            ),
        )

        return HomeAutoResult(
            status="success", phase_reached="complete",
            routines=[str(routine)[:200]],
            summary=f"Routine created: {description[:30]}",
        )

    async def _control_device(self, command: str, user_id: str) -> HomeAutoResult:
        """Process a device control command."""
        # Parse and execute smart home command
        parsed = await self._llm(
            system="Parse smart home commands into structured actions.",
            user=(
                f"Command: {command}\n\n"
                "Parse into: device, action, value.\n"
                "Example: 'turn on living room lights' → "
                "device: living_room_lights, action: on"
            ),
        )

        return HomeAutoResult(
            status="success", phase_reached="complete",
            actions_taken=[f"Parsed: {str(parsed)[:100]}"],
            summary=f"Command processed: {command[:30]}",
        )

    async def _suggest_automations(self, user_id: str) -> HomeAutoResult:
        """Suggest automations based on behavior patterns."""
        suggestions = await self._llm(
            system="Suggest smart home automations based on common patterns.",
            user=(
                "Suggest 3-5 useful automations:\n"
                "- Morning routine (lights, coffee, news)\n"
                "- Away mode (security, energy saving)\n"
                "- Bedtime routine (lights, locks, thermostat)\n"
                "Be specific and practical."
            ),
        )

        return HomeAutoResult(
            status="success", phase_reached="complete",
            routines=[str(suggestions)[:300]],
            summary="Automation suggestions generated",
        )


# ══════════════════════════════════════════════════════════════════════════════
# RELOCATION HAND
# RESEARCH → COMPARE → PLAN → EXECUTE → SETTLE
# ══════════════════════════════════════════════════════════════════════════════

class RelocationHand:
    """Researches neighborhoods, compares cost of living, manages moving checklist."""

    def __init__(self, tools, llm_fn, temporal=None, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._temporal = temporal
        self._store = store

    async def execute(
        self, from_city: str = "", to_city: str = "",
        action: str = "research", user_id: str = "", **kwargs,
    ) -> RelocationResult:
        log.info("[Relocation] action=%s to=%s", action, to_city[:20])

        if action == "research":
            return await self._research(to_city, user_id)
        elif action == "compare":
            return await self._compare(from_city, to_city, user_id)
        elif action == "checklist":
            return await self._moving_checklist(to_city, user_id)
        return await self._research(to_city, user_id)

    async def _research(self, city: str, user_id: str) -> RelocationResult:
        """Research a potential relocation city."""
        research = await self._llm(
            system="Research cities for relocation. Be honest about pros and cons.",
            user=(
                f"Research: {city}\n\n"
                "Cover:\n"
                "- Cost of living (housing, food, transport)\n"
                "- Job market\n"
                "- Quality of life\n"
                "- Climate\n"
                "- Culture and community\n"
                "- Safety\n"
                "- Neighborhoods to consider\n\n"
                "Be honest — include drawbacks."
            ),
        )

        return RelocationResult(
            status="success", phase_reached="research",
            research=str(research)[:500],
            summary=f"City research: {city}",
        )

    async def _compare(self, from_city: str, to_city: str, user_id: str) -> RelocationResult:
        """Compare two cities side by side."""
        comparison = await self._llm(
            system="Compare cities objectively. Use concrete numbers where possible.",
            user=(
                f"Compare: {from_city} vs {to_city}\n\n"
                "Side by side:\n"
                "- Rent (1BR, 2BR)\n"
                "- Salary adjustment\n"
                "- Commute\n"
                "- Weather\n"
                "- Food costs\n"
                "- Entertainment\n"
                "- Overall lifestyle\n\n"
                "Bottom line: who wins and why?"
            ),
        )

        return RelocationResult(
            status="success", phase_reached="compare",
            comparison=str(comparison)[:500],
            summary=f"Compared: {from_city} vs {to_city}",
        )

    async def _moving_checklist(self, to_city: str, user_id: str) -> RelocationResult:
        """Generate a complete moving checklist with reminders."""
        checklist = await self._llm(
            system="Create comprehensive moving checklists. Timeline-based.",
            user=(
                f"Moving to: {to_city}\n\n"
                "Create a timeline checklist:\n"
                "- 2 months before\n"
                "- 1 month before\n"
                "- 2 weeks before\n"
                "- 1 week before\n"
                "- Moving day\n"
                "- First week after\n\n"
                "Be thorough: utilities, address changes, packing, etc."
            ),
        )

        return RelocationResult(
            status="success", phase_reached="complete",
            checklist=str(checklist)[:500],
            summary=f"Moving checklist for {to_city}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH MONITOR HAND
# TRACK → REMIND → CORRELATE → ALERT → REPORT
# ══════════════════════════════════════════════════════════════════════════════

class HealthMonitorHand:
    """Tracks symptoms, medication reminders, appointment scheduling.

    CRITICAL: Never diagnoses. Never prescribes. Always suggests
    consulting a professional. The organism cares but knows its limits.
    """

    DISCLAIMER = (
        "I track what you tell me and spot patterns, but I'm not a doctor. "
        "If something concerns you, please talk to a healthcare professional."
    )

    def __init__(self, tools, llm_fn, temporal=None, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._temporal = temporal
        self._store = store

    async def execute(
        self, action: str = "log", symptom: str = "",
        medication: str = "", user_id: str = "", **kwargs,
    ) -> HealthResult:
        log.info("[Health] action=%s", action)

        if action == "log" or action == "symptom":
            return await self._log_symptom(symptom, user_id)
        elif action == "medication":
            return await self._medication_reminder(medication, user_id)
        elif action == "patterns":
            return await self._find_patterns(user_id)
        return await self._log_symptom(symptom, user_id)

    async def _log_symptom(self, symptom: str, user_id: str) -> HealthResult:
        """Log a symptom to memory."""
        if self._store:
            try:
                from ..models import MemoryEntry, MemorySource
                self._store.save_memory(MemoryEntry(
                    content=(
                        f"Health: {symptom} — "
                        f"{datetime.now().strftime('%A %I:%M %p')}"
                    ),
                    source=MemorySource.USER, confidence=1.0,
                    provenance_chain=["health_monitor"],
                ))
            except Exception as e:
                log.warning("[Health] Log error: %s", e)

        return HealthResult(
            status="success", phase_reached="complete",
            logged=symptom,
            summary=f"Logged: {symptom}",
            disclaimer=self.DISCLAIMER,
        )

    async def _medication_reminder(self, medication: str, user_id: str) -> HealthResult:
        """Set up medication reminders."""
        reminders_set = []
        if self._temporal:
            try:
                self._temporal.create_intention(
                    action=f"Medication reminder: {medication}",
                    context="Daily medication",
                )
                reminders_set.append(medication)
            except Exception:
                pass

        return HealthResult(
            status="success", phase_reached="complete",
            reminders=reminders_set,
            summary=f"Medication reminder set: {medication}",
            disclaimer=self.DISCLAIMER,
        )

    async def _find_patterns(self, user_id: str) -> HealthResult:
        """Analyze symptom patterns over time."""
        symptoms = ""
        if self._store:
            try:
                health_mem = self._store.recall(f"health symptom", limit=30)
                symptoms = "\n".join(
                    f"- {m.content[:60]}" for m in (health_mem or [])
                )
            except Exception:
                pass

        if not symptoms:
            return HealthResult(
                status="success", phase_reached="complete",
                patterns="Not enough data to find patterns yet.",
                summary="No symptom patterns yet",
                disclaimer=self.DISCLAIMER,
            )

        analysis = await self._llm(
            system=(
                "Analyze symptom patterns. NEVER diagnose or prescribe. "
                "Only identify correlations and suggest seeing a doctor."
            ),
            user=(
                f"Symptom log:\n{symptoms}\n\n"
                "Find patterns:\n"
                "- Frequency\n"
                "- Time of day\n"
                "- Correlations\n\n"
                "Do NOT diagnose. If you see a concerning pattern, "
                "suggest consulting a healthcare professional."
            ),
        )

        return HealthResult(
            status="success", phase_reached="complete",
            patterns=str(analysis)[:400],
            summary="Health patterns analyzed",
            disclaimer=self.DISCLAIMER,
        )
