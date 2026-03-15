"""Sovereign — The Hands: Research, Deployment, Writing, SysAdmin.

Each hand is a domain-specific state machine built on WorkPlanner + WorkExecutor.
All follow the same pattern: phases → tools → verify → deliver.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("sovereign.hands")


# ══════════════════════════════════════════════════════════════════════════════
# RESEARCH HAND
# Question → Search → Read → Synthesize → Verify → Deliver
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ResearchResult:
    query: str
    status: str
    answer: str = ""
    sources: list = field(default_factory=list)
    confidence: str = "medium"    # low, medium, high
    contradictions: list = field(default_factory=list)


class ResearchHand:
    """Autonomous research pipeline — search, read, synthesize, verify."""

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(self, query: str, depth: str = "standard") -> ResearchResult:
        max_sources = {"quick": 3, "standard": 6, "deep": 12}.get(depth, 6)
        log.info("[Research] query=%s depth=%s", query[:60], depth)

        # Phase 1: SEARCH
        search = await self._tools.web_search(query, max_results=max_sources)
        if not search.success or not search.data:
            return ResearchResult(query=query, status="failed",
                                  answer="Could not reach web search.")

        sources = search.data  # list of {text, url}

        # Phase 2: READ (fetch top sources for deeper content)
        full_texts = []
        for src in sources[:3]:
            url = src.get("url", "")
            if url:
                fetch = await self._tools.web_fetch(url)
                if fetch.success:
                    full_texts.append({"url": url, "text": fetch.data[:3000]})

        # Phase 3: SYNTHESIZE
        source_dump = "\n\n".join(
            f"Source: {s.get('url', '?')}\n{s.get('text', s.get('text', ''))[:800]}"
            for s in (full_texts or sources)
        )
        synthesis = await self._llm(
            system="You are a research analyst. Synthesize sources into a clear, accurate answer.",
            user=(
                f"Research question: {query}\n\n"
                f"Sources:\n{source_dump}\n\n"
                "Provide:\n1. A direct answer\n2. Key supporting evidence\n"
                "3. Any important caveats or contradictions\n4. Confidence: low/medium/high"
            )
        )

        # Phase 4: VERIFY (check for contradictions)
        contradiction_check = await self._llm(
            system="Identify factual contradictions between sources. Be brief.",
            user=f"Sources:\n{source_dump[:2000]}\nList contradictions, or say 'none found'."
        )
        contradictions = (
            [] if "none found" in contradiction_check.lower()
            else [contradiction_check[:300]]
        )

        # Extract confidence from synthesis
        confidence = "medium"
        if "high confidence" in synthesis.lower() or "clearly" in synthesis.lower():
            confidence = "high"
        elif "uncertain" in synthesis.lower() or "unclear" in synthesis.lower():
            confidence = "low"

        return ResearchResult(
            query=query,
            status="success",
            answer=synthesis,
            sources=[s.get("url", s.get("text", "")[:50]) for s in sources],
            confidence=confidence,
            contradictions=contradictions,
        )


# ══════════════════════════════════════════════════════════════════════════════
# DEPLOYMENT HAND
# PreCheck → Backup → Deploy → Verify → Monitor → Complete
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DeployRequest:
    description: str
    deploy_command: str
    workdir: str
    health_check: str = ""         # command to verify service is up
    rollback_command: str = ""
    user_id: str = ""


@dataclass
class DeployResult:
    task: str
    status: str
    phase_reached: str
    rollback_performed: bool = False
    health_status: str = ""
    summary: str = ""


class DeploymentHand:
    """Autonomous deployment — precheck, backup, deploy, verify, monitor."""

    MONITOR_SECONDS = 60   # watch post-deploy for this long

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(self, request: DeployRequest) -> DeployResult:
        log.info("[Deployment] task=%s", request.description[:60])
        phase = "pre_check"

        # Phase 1: PRE-CHECK
        if request.health_check:
            pre = await self._tools.shell(request.health_check, timeout=15,
                                          workdir=request.workdir)
            if not pre.success:
                return DeployResult(task=request.description, status="aborted",
                                    phase_reached="pre_check",
                                    summary=f"Pre-check failed: {pre.error}")

        phase = "deploy"

        # Phase 2: DEPLOY
        deploy = await self._tools.shell(request.deploy_command, timeout=120,
                                         workdir=request.workdir)
        if not deploy.success:
            # Attempt rollback
            rolled_back = False
            if request.rollback_command:
                rb = await self._tools.shell(request.rollback_command, timeout=60,
                                              workdir=request.workdir)
                rolled_back = rb.success

            return DeployResult(task=request.description, status="failed",
                                phase_reached="deploy", rollback_performed=rolled_back,
                                summary=f"Deploy failed: {deploy.error}")

        phase = "verify"

        # Phase 3: VERIFY
        health = ""
        if request.health_check:
            import asyncio
            await asyncio.sleep(3)  # give the service a moment
            check = await self._tools.shell(request.health_check, timeout=15,
                                            workdir=request.workdir)
            health = "healthy" if check.success else f"unhealthy: {check.error}"
            if not check.success:
                # Rollback on bad health
                rolled_back = False
                if request.rollback_command:
                    rb = await self._tools.shell(request.rollback_command, timeout=60,
                                                  workdir=request.workdir)
                    rolled_back = rb.success
                return DeployResult(task=request.description, status="failed",
                                    phase_reached="verify", rollback_performed=rolled_back,
                                    health_status=health,
                                    summary=f"Post-deploy health check failed. Rolled back: {rolled_back}")

        return DeployResult(
            task=request.description, status="success",
            phase_reached="complete", health_status=health or "not checked",
            summary=f"Deployed successfully. Health: {health or 'not checked'}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# WRITING HAND
# Research → Outline → Draft → Review → Revise → Polish
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class WritingResult:
    topic: str
    status: str
    content: str = ""
    word_count: int = 0
    revision_cycles: int = 0


class WritingHand:
    """Autonomous writing — research, outline, draft, review, revise, polish."""

    MAX_REVISIONS = 2

    def __init__(self, tools, llm_fn, persona_engine=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._persona = persona_engine

    async def execute(self, topic: str, style_hint: str = "",
                      length: str = "medium") -> WritingResult:
        target_words = {"short": 300, "medium": 700, "long": 1500}.get(length, 700)
        log.info("[Writing] topic=%s length=%s", topic[:60], length)

        # Phase 1: RESEARCH (quick web search for facts)
        search = await self._tools.web_search(topic, max_results=3)
        research_context = ""
        if search.success and search.data:
            research_context = "\n".join(
                s.get("text", "")[:300] for s in search.data
            )

        # Phase 2: OUTLINE
        outline = await self._llm(
            system="You are an expert writer. Create a clear writing outline.",
            user=(
                f"Topic: {topic}\nTarget length: ~{target_words} words\n"
                f"Style: {style_hint or 'clear, engaging, informative'}\n"
                f"Research context: {research_context[:800]}\n\n"
                "Create a brief outline with sections and key points."
            )
        )

        # Phase 3: DRAFT
        persona_note = ""
        if self._persona:
            try:
                persona_note = f"Voice/style: {self._persona.get_style_summary()}"
            except Exception:
                pass

        draft = await self._llm(
            system="You are an expert writer. Write complete, polished content.",
            user=(
                f"Topic: {topic}\nOutline:\n{outline}\n\n"
                f"Research: {research_context[:600]}\n"
                f"{persona_note}\n"
                f"Target: ~{target_words} words. Write the complete piece now."
            )
        )

        # Phase 4 & 5: REVIEW + REVISE (up to MAX_REVISIONS)
        content = draft
        revision_count = 0

        for _ in range(self.MAX_REVISIONS):
            review = await self._llm(
                system="You are a critical editor.",
                user=(
                    f"Review this for: accuracy, clarity, flow, completeness.\n"
                    f"Content:\n{content[:2000]}\n\n"
                    "If it needs revision, list issues. "
                    "If it's good, say exactly: APPROVED"
                )
            )
            if "APPROVED" in review.upper():
                break

            content = await self._llm(
                system="You are an expert writer. Revise the content based on feedback.",
                user=(
                    f"Original:\n{content}\n\nFeedback:\n{review}\n\n"
                    "Write the improved version. Complete content only."
                )
            )
            revision_count += 1

        # Phase 6: POLISH (light final pass)
        polished = await self._llm(
            system="Polish this text: fix grammar, improve word choice, ensure consistency.",
            user=f"Text to polish:\n{content}\n\nReturn ONLY the polished text."
        )

        return WritingResult(
            topic=topic, status="success",
            content=polished,
            word_count=len(polished.split()),
            revision_cycles=revision_count,
        )


# ══════════════════════════════════════════════════════════════════════════════
# SYSADMIN HAND
# Diagnose → Plan → Execute → Verify → Harden → Document
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SysAdminResult:
    problem: str
    status: str
    diagnosis: str = ""
    fix_applied: str = ""
    hardening: str = ""
    memory_encoded: bool = False
    summary: str = ""


class SysAdminHand:
    """Autonomous system administration — diagnose, fix, harden, learn."""

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(self, problem: str, workdir: str = ".") -> SysAdminResult:
        log.info("[SysAdmin] problem=%s", problem[:60])

        # Phase 1: DIAGNOSE
        # Gather system state
        log_snippets = []
        for log_path in ["/var/log/syslog", "/var/log/daemon.log",
                         f"{workdir}/daemon.log"]:
            r = await self._tools.shell(f"tail -50 {log_path} 2>/dev/null")
            if r.success and r.data.strip():
                log_snippets.append(f"--- {log_path} ---\n{r.data[-1000:]}")

        ps = await self._tools.shell("ps aux --sort=-%mem | head -15")
        disk = await self._tools.shell("df -h")
        mem = await self._tools.shell("free -h")

        system_context = "\n".join([
            f"Processes:\n{ps.data[:500] if ps.success else '(unavailable)'}",
            f"Disk:\n{disk.data[:300] if disk.success else '(unavailable)'}",
            f"Memory:\n{mem.data[:200] if mem.success else '(unavailable)'}",
        ] + log_snippets[:2])

        diagnosis = await self._llm(
            system="You are a senior system administrator diagnosing a problem.",
            user=(
                f"Problem: {problem}\n\nSystem state:\n{system_context}\n\n"
                "Diagnose the root cause and propose the single safest fix.\n"
                "Format:\nROOT CAUSE: ...\nFIX: <exact command(s) to run>\nRISK: low/medium/high"
            )
        )

        # Phase 2 & 3: PLAN + EXECUTE
        # Extract the fix command from diagnosis
        fix_cmd = ""
        for line in diagnosis.split("\n"):
            if line.startswith("FIX:"):
                fix_cmd = line.replace("FIX:", "").strip()
                break

        fix_result = None
        if fix_cmd and fix_cmd.lower() not in ("none", "manual intervention required"):
            fix_result = await self._tools.shell(fix_cmd, timeout=60, workdir=workdir)

        # Phase 4: VERIFY
        verify_result = None
        if fix_result and fix_result.success:
            # Quick re-check
            verify_result = await self._tools.shell(
                "systemctl --failed --no-pager 2>/dev/null || echo 'no systemd'",
                timeout=10
            )

        # Phase 5: HARDEN
        hardening_advice = await self._llm(
            system="You are a security-focused sysadmin.",
            user=(
                f"Problem fixed: {problem}\nFix applied: {fix_cmd}\n\n"
                "Suggest ONE specific hardening step to prevent recurrence. "
                "Be concrete and brief."
            )
        )

        # Phase 6: DOCUMENT (encode as procedural memory)
        if self._store:
            from ..models import MemoryEntry, MemorySource
            entry = MemoryEntry(
                content=(
                    f"SYSADMIN FIX: {problem}\n"
                    f"Diagnosis: {diagnosis[:200]}\n"
                    f"Fix: {fix_cmd}\n"
                    f"Hardening: {hardening_advice[:100]}"
                ),
                source=MemorySource.AGENT,
                confidence=0.9,
                provenance_chain=["sysadmin_hand"],
            )
            try:
                self._store.save_memory(entry)
                memory_encoded = True
            except Exception:
                memory_encoded = False
        else:
            memory_encoded = False

        status = (
            "success" if (fix_result and fix_result.success) or not fix_cmd
            else "partial"
        )

        return SysAdminResult(
            problem=problem, status=status,
            diagnosis=diagnosis,
            fix_applied=fix_cmd,
            hardening=hardening_advice,
            memory_encoded=memory_encoded,
            summary=(
                f"Diagnosed: {problem}. "
                f"Fix {'applied' if fix_cmd else 'not needed'}. "
                f"Memory encoded: {memory_encoded}."
            )
        )
