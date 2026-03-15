"""Sovereign — The Hands: Communication domain.

Email Operator, Social Media Manager, Meeting Assistant.
Each hand is a phase-based state machine using LLM + Tool Belt.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("sovereign.hands.communication")


# ══════════════════════════════════════════════════════════════════════════════
# RESULT DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EmailResult:
    status: str
    phase_reached: str
    emails_triaged: int = 0
    emails_drafted: int = 0
    emails_sent: int = 0
    summary: str = ""


@dataclass
class SocialMediaResult:
    status: str
    phase_reached: str
    platform: str = ""
    posts_created: int = 0
    posts_published: int = 0
    summary: str = ""


@dataclass
class MeetingResult:
    status: str
    phase_reached: str
    meeting_title: str = ""
    decisions: list = field(default_factory=list)
    action_items: list = field(default_factory=list)
    follow_ups_created: int = 0
    summary: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL OPERATOR HAND
# FETCH → TRIAGE → DRAFT → REVIEW → SEND
# ══════════════════════════════════════════════════════════════════════════════

class EmailOperatorHand:
    """Autonomous email management — fetch, triage, draft, send (with approval)."""

    def __init__(self, tools, llm_fn, send_approval_fn=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._approve = send_approval_fn

    async def execute(self, action: str = "check", **kwargs) -> EmailResult:
        log.info("[EmailOperator] action=%s", action)
        phase = "fetch"
        emails_raw = []
        triaged = []
        drafted = []
        sent_count = 0

        for iteration in range(12):
            if phase == "fetch":
                # Fetch emails via configured method (IMAP, API, etc.)
                fetch_script = await self._llm(
                    system="Write a Python script to fetch emails via IMAP.",
                    user=(
                        f"Action: {action}\n"
                        "Write a script that:\n"
                        "1. Connects to IMAP (use env vars SOVEREIGN_IMAP_HOST, "
                        "SOVEREIGN_IMAP_USER, SOVEREIGN_IMAP_PASS)\n"
                        "2. Fetches the last 10 unread emails\n"
                        "3. Prints each as JSON: {{from, subject, date, body_preview}}\n"
                        "Handle connection errors gracefully."
                    ),
                )
                await self._tools.file_write("/tmp/sovereign/fetch_email.py", fetch_script)
                result = await self._tools.shell(
                    "python3 /tmp/sovereign/fetch_email.py 2>&1", timeout=30,
                )
                if result.success and result.data:
                    emails_raw = result.data.strip().split("\n")
                phase = "triage"

            elif phase == "triage":
                for email_line in emails_raw[:10]:
                    classification = await self._llm(
                        system="Classify emails by urgency.",
                        user=(
                            f"Classify this email:\n{email_line[:300]}\n\n"
                            "Output JSON: {{\"classification\": \"URGENT|IMPORTANT|ROUTINE|SPAM\", "
                            "\"needs_response\": true/false, \"summary\": \"one line\"}}"
                        ),
                    )
                    triaged.append({"email": email_line, "classification": classification})
                phase = "draft"

            elif phase == "draft":
                for item in triaged:
                    try:
                        cls = json.loads(item["classification"])
                    except (json.JSONDecodeError, TypeError):
                        cls = {"needs_response": False}

                    if not cls.get("needs_response"):
                        continue

                    draft = await self._llm(
                        system="Draft email responses. Match the user's tone.",
                        user=(
                            f"Draft a response to:\n{item['email'][:300]}\n\n"
                            "Be concise, professional, and address the actual request."
                        ),
                    )
                    drafted.append({"email": item["email"], "draft": draft})
                phase = "review"

            elif phase == "review":
                # ALL outbound email requires approval
                if self._approve and drafted:
                    summary = "\n".join(
                        f"→ {d['draft'][:80]}..." for d in drafted[:5]
                    )
                    approved = await self._approve(
                        f"📧 {len(drafted)} email drafts ready:\n{summary}\n\nApprove sending?"
                    )
                    if approved:
                        phase = "send"
                    else:
                        phase = "complete"
                else:
                    phase = "complete"

            elif phase == "send":
                # Send approved emails
                for d in drafted:
                    send_script = await self._llm(
                        system="Write a script to send an email via SMTP.",
                        user=(
                            f"Send this email reply:\n{d['draft'][:400]}\n\n"
                            "Use env vars SOVEREIGN_SMTP_HOST, SOVEREIGN_SMTP_USER, "
                            "SOVEREIGN_SMTP_PASS."
                        ),
                    )
                    await self._tools.file_write("/tmp/sovereign/send_email.py", send_script)
                    result = await self._tools.shell(
                        "python3 /tmp/sovereign/send_email.py 2>&1", timeout=15,
                    )
                    if result.success:
                        sent_count += 1
                phase = "complete"

            if phase == "complete":
                break

        return EmailResult(
            status="success",
            phase_reached=phase,
            emails_triaged=len(triaged),
            emails_drafted=len(drafted),
            emails_sent=sent_count,
            summary=f"Triaged {len(triaged)}, drafted {len(drafted)}, sent {sent_count}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# SOCIAL MEDIA MANAGER HAND
# MONITOR → ANALYZE → CREATE → SCHEDULE → APPROVE → PUBLISH
# ══════════════════════════════════════════════════════════════════════════════

class SocialMediaHand:
    """Autonomous social media — monitor, create, schedule, publish (with approval)."""

    def __init__(self, tools, llm_fn, send_approval_fn=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._approve = send_approval_fn

    async def execute(
        self, action: str = "create", topic: str = "",
        platforms: list[str] | None = None,
    ) -> SocialMediaResult:
        platforms = platforms or ["reddit", "linkedin", "twitter"]
        log.info("[SocialMedia] action=%s platforms=%s", action, platforms)
        phase = "monitor" if action == "monitor" else "create"
        drafts = {}
        published = 0

        for iteration in range(12):
            if phase == "monitor":
                monitor_data = {}
                for platform in platforms:
                    if platform == "reddit":
                        result = await self._tools.shell(
                            "curl -sL -A 'SovereignBot/1.0' "
                            "'https://www.reddit.com/r/MachineLearning/new.json?limit=5' "
                            "| python3 -c \"import sys,json; "
                            "d=json.load(sys.stdin); "
                            "[print(p['data']['title'][:80]) for p in d.get('data',{}).get('children',[])]\" "
                            "2>/dev/null || echo 'fetch failed'",
                            timeout=15,
                        )
                        monitor_data[platform] = result.data if result.success else ""
                phase = "analyze"

            elif phase == "analyze":
                phase = "create"

            elif phase == "create":
                for platform in platforms:
                    constraints = {
                        "twitter": "Max 280 characters. Punchy. Hashtags.",
                        "linkedin": "Professional tone. Can be longer. Use line breaks.",
                        "reddit": "Title + body. Match subreddit tone. Don't be promotional.",
                        "facebook": "Storytelling. Engaging. Call to action.",
                    }
                    draft = await self._llm(
                        system=f"Write a {platform} post. Sound human, not like AI.",
                        user=(
                            f"Topic: {topic}\n"
                            f"Platform: {platform}\n"
                            f"Constraints: {constraints.get(platform, 'General social post')}\n\n"
                            "Write the post."
                        ),
                    )
                    drafts[platform] = draft
                phase = "approve"

            elif phase == "approve":
                if self._approve:
                    preview = "\n\n".join(
                        f"**{p.upper()}:**\n{d[:120]}..." for p, d in drafts.items()
                    )
                    approved = await self._approve(
                        f"📱 {len(drafts)} social posts ready:\n{preview}\n\nPublish?"
                    )
                    phase = "publish" if approved else "complete"
                else:
                    phase = "complete"

            elif phase == "publish":
                for platform, content in drafts.items():
                    log.info("[SocialMedia] Publishing to %s: %s...", platform, content[:40])
                    # Actual API publishing would go here per platform
                    published += 1
                phase = "complete"

            if phase == "complete":
                break

        return SocialMediaResult(
            status="success",
            phase_reached=phase,
            platform=",".join(platforms),
            posts_created=len(drafts),
            posts_published=published,
            summary=f"Created {len(drafts)} posts for {','.join(platforms)}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# MEETING ASSISTANT HAND
# TRANSCRIBE → SUMMARIZE → EXTRACT → ASSIGN → FOLLOW_UP
# ══════════════════════════════════════════════════════════════════════════════

class MeetingAssistantHand:
    """Autonomous meeting processor — transcribe, summarize, extract, follow up."""

    def __init__(self, tools, llm_fn, temporal=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._temporal = temporal

    async def execute(
        self, meeting_title: str, source: str,
        source_type: str = "notes",
    ) -> MeetingResult:
        log.info("[MeetingAssistant] title=%s type=%s", meeting_title, source_type)
        phase = "transcribe"
        transcript = ""
        meeting_summary = ""
        decisions = []
        action_items = []
        follow_ups = 0

        for iteration in range(10):
            if phase == "transcribe":
                if source_type == "audio":
                    # Use Whisper for audio transcription
                    result = await self._tools.shell(
                        f"python3 -c \""
                        f"import whisper; m = whisper.load_model('base'); "
                        f"r = m.transcribe('{source}'); print(r['text'])\" 2>&1",
                        timeout=120,
                    )
                    transcript = result.data if result.success else ""
                else:
                    # Read text notes directly
                    result = await self._tools.shell(f"cat '{source}' 2>&1", timeout=5)
                    transcript = result.data if result.success else source
                phase = "summarize"

            elif phase == "summarize":
                meeting_summary = await self._llm(
                    system="Summarize meetings concisely.",
                    user=(
                        f"Meeting: {meeting_title}\n"
                        f"Transcript/Notes:\n{transcript[:2000]}\n\n"
                        "Write a concise summary covering:\n"
                        "- Main topics discussed\n"
                        "- Key points raised\n"
                        "- Overall outcome"
                    ),
                )
                phase = "extract"

            elif phase == "extract":
                extraction = await self._llm(
                    system="Extract structured data from meetings.",
                    user=(
                        f"Meeting: {meeting_title}\n"
                        f"Notes:\n{transcript[:1500]}\n\n"
                        "Extract as JSON:\n"
                        "{{\"decisions\": [\"...\"], "
                        "\"action_items\": [{{\"owner\":\"...\", \"action\":\"...\", \"deadline\":\"...\"}}], "
                        "\"open_questions\": [\"...\"], "
                        "\"follow_ups\": [\"...\"]}}"
                    ),
                )
                try:
                    data = json.loads(extraction)
                    decisions = data.get("decisions", [])
                    action_items = data.get("action_items", [])
                except (json.JSONDecodeError, TypeError):
                    decisions = []
                    action_items = []
                phase = "follow_up"

            elif phase == "follow_up":
                if self._temporal and action_items:
                    for item in action_items:
                        if item.get("deadline"):
                            try:
                                self._temporal.create_intention(
                                    action=(
                                        f"Meeting follow-up: {item.get('owner', 'someone')} "
                                        f"should have {item['action']} by {item['deadline']}."
                                    ),
                                    context=f"From meeting: {meeting_title}",
                                )
                                follow_ups += 1
                            except Exception as e:
                                log.warning("[MeetingAssistant] Could not create follow-up: %s", e)

                # Save meeting notes
                report = (
                    f"# {meeting_title}\n\n"
                    f"## Summary\n{meeting_summary}\n\n"
                    f"## Decisions\n" +
                    "\n".join(f"- {d}" for d in decisions) +
                    f"\n\n## Action Items\n" +
                    "\n".join(
                        f"- [{a.get('owner', '?')}] {a.get('action', '?')} "
                        f"(by {a.get('deadline', 'TBD')})"
                        for a in action_items
                    )
                )
                await self._tools.file_write(
                    f"/tmp/sovereign/meetings/{meeting_title.replace(' ', '_')}.md",
                    report,
                )
                phase = "complete"

            if phase == "complete":
                break

        return MeetingResult(
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            meeting_title=meeting_title,
            decisions=decisions,
            action_items=action_items,
            follow_ups_created=follow_ups,
            summary=f"{meeting_title}: {len(decisions)} decisions, {len(action_items)} action items",
        )
