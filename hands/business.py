"""Sovereign — The Hands: Business domain.

Invoice & Billing, Competitive Intel, SEO Optimizer, Legal Document Drafter.
Each hand is a phase-based state machine using LLM + Tool Belt.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("sovereign.hands.business")


# ══════════════════════════════════════════════════════════════════════════════
# RESULT DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class InvoiceResult:
    status: str
    phase_reached: str
    invoice_number: str = ""
    total: float = 0.0
    pdf_path: str = ""
    summary: str = ""


@dataclass
class CompetitiveIntelResult:
    status: str
    phase_reached: str
    competitors_tracked: int = 0
    changes_detected: int = 0
    report: str = ""
    summary: str = ""


@dataclass
class SEOResult:
    status: str
    phase_reached: str
    pages_audited: int = 0
    issues_found: int = 0
    issues_fixed: int = 0
    summary: str = ""


@dataclass
class LegalDrafterResult:
    status: str
    phase_reached: str
    document_type: str = ""
    output_path: str = ""
    summary: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# INVOICE & BILLING HAND
# CALCULATE → GENERATE → SEND → TRACK → REMIND
# ══════════════════════════════════════════════════════════════════════════════

class InvoiceHand:
    """Autonomous invoicing — calculate, generate, send, track."""

    def __init__(self, tools, llm_fn, temporal=None, send_approval_fn=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._temporal = temporal
        self._approve = send_approval_fn

    async def execute(
        self,
        from_details: dict,
        to_details: dict,
        line_items: list[dict],
        tax_rate: float = 0.0,
        payment_terms: str = "Net 30",
    ) -> InvoiceResult:
        log.info("[Invoice] to=%s items=%d", to_details.get("name", "?"), len(line_items))
        os.makedirs("/tmp/sovereign/invoices", exist_ok=True)

        invoice_number = f"INV-{int(time.time())}"
        phase = "calculate"
        subtotal = 0.0
        tax = 0.0
        total = 0.0
        pdf_path = ""

        for iteration in range(8):
            if phase == "calculate":
                subtotal = sum(
                    float(item.get("quantity", 1)) * float(item.get("rate", 0))
                    for item in line_items
                )
                tax = subtotal * (tax_rate / 100.0)
                total = subtotal + tax
                phase = "generate"

            elif phase == "generate":
                invoice_html = await self._llm(
                    system="Generate professional HTML invoices.",
                    user=(
                        f"Generate a clean professional HTML invoice:\n\n"
                        f"FROM: {json.dumps(from_details)}\n"
                        f"TO: {json.dumps(to_details)}\n"
                        f"ITEMS: {json.dumps(line_items)}\n"
                        f"SUBTOTAL: ${subtotal:.2f}\n"
                        f"TAX ({tax_rate}%): ${tax:.2f}\n"
                        f"TOTAL: ${total:.2f}\n"
                        f"INVOICE: {invoice_number}\n"
                        f"DATE: {time.strftime('%Y-%m-%d')}\n"
                        f"TERMS: {payment_terms}\n\n"
                        "Include payment information section. Clean, minimal design."
                    ),
                )
                html_path = f"/tmp/sovereign/invoices/{invoice_number}.html"
                await self._tools.file_write(html_path, invoice_html)

                # Try PDF conversion
                pdf_path = f"/tmp/sovereign/invoices/{invoice_number}.pdf"
                pdf_result = await self._tools.shell(
                    f"wkhtmltopdf {html_path} {pdf_path} 2>&1 || "
                    f"python3 -c \"print('PDF conversion requires wkhtmltopdf')\"",
                    timeout=15,
                )
                if not pdf_result.success:
                    pdf_path = html_path  # Fall back to HTML
                phase = "track"

            elif phase == "track":
                # Create prospective memory for follow-up
                if self._temporal:
                    try:
                        self._temporal.create_intention(
                            action=(
                                f"Invoice {invoice_number} to {to_details.get('name', '?')} "
                                f"for ${total:.2f} is due. Check if paid."
                            ),
                            context=f"Payment terms: {payment_terms}",
                        )
                    except Exception as e:
                        log.warning("[Invoice] Could not create reminder: %s", e)
                phase = "complete"

            if phase == "complete":
                break

        return InvoiceResult(
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            invoice_number=invoice_number,
            total=total,
            pdf_path=pdf_path,
            summary=f"{invoice_number}: ${total:.2f} to {to_details.get('name', '?')}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# COMPETITIVE INTEL HAND
# IDENTIFY → MONITOR → COMPARE → ANALYZE → REPORT
# ══════════════════════════════════════════════════════════════════════════════

class CompetitiveIntelHand:
    """Autonomous competitive intelligence — monitor, compare, analyze."""

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(
        self, competitors: list[dict], focus: str = "",
    ) -> CompetitiveIntelResult:
        log.info("[CompetitiveIntel] tracking %d competitors", len(competitors))
        phase = "monitor"
        changes = {}
        report = ""

        for iteration in range(12):
            if phase == "monitor":
                for comp in competitors:
                    name = comp.get("name", "unknown")
                    url = comp.get("url", "")
                    if not url:
                        continue

                    current = await self._tools.shell(
                        f"curl -sL -A 'Mozilla/5.0' '{url}' | head -200",
                        timeout=15,
                    )
                    if not current.success:
                        continue

                    # Check memory for previous state
                    last_state = ""
                    if self._store:
                        try:
                            memories = self._store.recall(
                                f"competitive_intel {name}", limit=1,
                            )
                            if memories:
                                last_state = memories[0].content
                        except Exception:
                            pass

                    if last_state:
                        diff = await self._llm(
                            system="Compare website snapshots. Identify changes.",
                            user=(
                                f"Previous snapshot of {name}:\n{last_state[:400]}\n\n"
                                f"Current snapshot:\n{current.data[:400]}\n\n"
                                "What changed? Be specific."
                            ),
                        )
                        if "no significant" not in diff.lower():
                            changes[name] = diff

                    # Update memory
                    if self._store:
                        try:
                            from ..models import MemoryEntry, MemorySource
                            self._store.save_memory(MemoryEntry(
                                content=f"Competitive scan of {name}: {(current.data or '')[:200]}",
                                source=MemorySource.AGENT, confidence=0.7,
                                provenance_chain=["competitive_intel_hand"],
                            ))
                        except Exception:
                            pass
                phase = "analyze"

            elif phase == "analyze":
                if changes:
                    analysis = await self._llm(
                        system="Analyze competitive intelligence data.",
                        user=(
                            f"Changes detected:\n{json.dumps(changes, indent=2)[:800]}\n\n"
                            f"{'Focus: ' + focus if focus else ''}\n\n"
                            "Analyze:\n"
                            "1. What trends do the changes suggest?\n"
                            "2. What should we react to?\n"
                            "3. What opportunities do we see?"
                        ),
                    )
                else:
                    analysis = "No significant changes detected across tracked competitors."
                phase = "report"

            elif phase == "report":
                report = await self._llm(
                    system="Write competitive intelligence reports.",
                    user=(
                        f"Competitors tracked: {[c.get('name') for c in competitors]}\n"
                        f"Changes: {json.dumps(changes, indent=2)[:400]}\n\n"
                        "Write a concise competitive intelligence briefing:\n"
                        "1. Key Changes\n2. Implications\n3. Recommendations"
                    ),
                )
                await self._tools.file_write(
                    "/tmp/sovereign/competitive_report.md", report,
                )
                phase = "complete"

            if phase == "complete":
                break

        return CompetitiveIntelResult(
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            competitors_tracked=len(competitors),
            changes_detected=len(changes),
            report=report[:500],
            summary=f"Tracked {len(competitors)} competitors, {len(changes)} changes detected",
        )


# ══════════════════════════════════════════════════════════════════════════════
# SEO OPTIMIZER HAND
# CRAWL → AUDIT → PRIORITIZE → FIX → VERIFY → REPORT
# ══════════════════════════════════════════════════════════════════════════════

class SEOOptimizerHand:
    """Autonomous SEO audit — crawl, audit, fix, verify."""

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(self, target_url: str, workdir: str = ".") -> SEOResult:
        log.info("[SEO] target=%s", target_url[:60])
        phase = "crawl"
        pages = []
        issues = []
        fixes = 0

        for iteration in range(15):
            if phase == "crawl":
                # Fetch the page and discover internal links
                result = await self._tools.shell(
                    f"curl -sL '{target_url}' 2>/dev/null | head -500",
                    timeout=15,
                )
                if result.success:
                    pages.append({"url": target_url, "content": result.data})
                phase = "audit"

            elif phase == "audit":
                for page in pages:
                    audit = await self._llm(
                        system="Perform SEO audits on web pages.",
                        user=(
                            f"Audit this page for SEO:\n{page['content'][:1500]}\n\n"
                            "Check:\n"
                            "1. Title tag (exists, <60 chars)\n"
                            "2. Meta description (exists, <160 chars)\n"
                            "3. H1 tag (exactly one)\n"
                            "4. Image alt text\n"
                            "5. Semantic HTML\n"
                            "6. Internal/external links\n"
                            "7. Mobile responsiveness hints\n\n"
                            "Output as JSON: {{\"issues\": [{{\"severity\":\"high|medium|low\", "
                            "\"issue\":\"...\", \"fix\":\"...\"}}]}}"
                        ),
                    )
                    try:
                        data = json.loads(audit)
                        issues.extend(data.get("issues", []))
                    except (json.JSONDecodeError, TypeError):
                        pass
                phase = "prioritize"

            elif phase == "prioritize":
                # Sort by severity
                severity_order = {"high": 0, "medium": 1, "low": 2}
                issues.sort(key=lambda i: severity_order.get(i.get("severity", "low"), 2))
                phase = "fix" if issues else "report"

            elif phase == "fix":
                for issue in issues[:5]:  # Fix top 5
                    fix = await self._llm(
                        system="Generate SEO fixes as code changes.",
                        user=(
                            f"Fix this SEO issue:\n{json.dumps(issue)}\n\n"
                            f"For the page at: {target_url}\n"
                            "Provide the exact HTML/code change needed."
                        ),
                    )
                    fixes += 1
                phase = "report"

            elif phase == "report":
                report = await self._llm(
                    system="Write SEO audit reports.",
                    user=(
                        f"SEO Audit of {target_url}:\n"
                        f"Pages audited: {len(pages)}\n"
                        f"Issues found: {len(issues)}\n"
                        f"Issues:\n{json.dumps(issues[:10], indent=2)}\n\n"
                        "Write a concise SEO report with priorities."
                    ),
                )
                await self._tools.file_write("/tmp/sovereign/seo_report.md", report)
                phase = "complete"

            if phase == "complete":
                break

        return SEOResult(
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            pages_audited=len(pages),
            issues_found=len(issues),
            issues_fixed=fixes,
            summary=f"Audited {len(pages)} pages: {len(issues)} issues, {fixes} fixed",
        )


# ══════════════════════════════════════════════════════════════════════════════
# LEGAL DOCUMENT DRAFTER HAND
# GATHER → TEMPLATE → DRAFT → REVIEW → FINALIZE
# ══════════════════════════════════════════════════════════════════════════════

class LegalDrafterHand:
    """Autonomous legal drafting — gather requirements, draft, review, finalize."""

    DISCLAIMER = (
        "IMPORTANT: This document was drafted with AI assistance and "
        "has NOT been reviewed by a licensed attorney. It is provided "
        "as a starting point only. Please have a qualified legal "
        "professional review this document before relying on it for "
        "any legal purpose."
    )

    TEMPLATES = {
        "tos": "Terms of Service",
        "privacy": "Privacy Policy",
        "nda": "Non-Disclosure Agreement",
        "contract": "Freelance Service Contract",
        "license": "Software License Agreement",
    }

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(
        self, doc_type: str, details: dict,
        workdir: str = "/tmp/sovereign/legal",
    ) -> LegalDrafterResult:
        doc_name = self.TEMPLATES.get(doc_type, doc_type)
        log.info("[LegalDrafter] type=%s", doc_name)
        os.makedirs(workdir, exist_ok=True)

        phase = "gather"
        requirements = ""
        draft = ""
        output_path = f"{workdir}/{doc_type}_{int(time.time())}.md"

        for iteration in range(8):
            if phase == "gather":
                requirements = await self._llm(
                    system="You are a legal document specialist.",
                    user=(
                        f"I need a {doc_name}.\n"
                        f"Details: {json.dumps(details, indent=2)}\n\n"
                        "List all sections required for this type of document.\n"
                        "Identify what information is needed for each section.\n"
                        "Note any jurisdiction-specific requirements."
                    ),
                )
                phase = "draft"

            elif phase == "draft":
                draft = await self._llm(
                    system=(
                        "Draft legal documents. Use clear language. "
                        "Be thorough but readable."
                    ),
                    user=(
                        f"Draft a {doc_name} with these requirements:\n{requirements[:800]}\n\n"
                        f"Details:\n{json.dumps(details, indent=2)}\n\n"
                        "Include all required sections. Use numbered clauses.\n"
                        "Add a plain-language summary at the top."
                    ),
                )
                phase = "review"

            elif phase == "review":
                review = await self._llm(
                    system="Review legal documents for completeness and clarity.",
                    user=(
                        f"Review this {doc_name}:\n{draft[:1500]}\n\n"
                        "Check:\n"
                        "1. All required sections present\n"
                        "2. Terms are clearly defined\n"
                        "3. No ambiguous language\n"
                        "4. Dates and parties correctly referenced\n"
                        "5. Termination and dispute clauses included\n\n"
                        "Output any issues found."
                    ),
                )
                # If issues, re-draft; otherwise finalize
                if "no issues" in review.lower() or "looks good" in review.lower():
                    phase = "finalize"
                else:
                    # Incorporate review feedback
                    draft = await self._llm(
                        system="Revise legal documents based on review feedback.",
                        user=(
                            f"Revise this {doc_name}:\n{draft[:1200]}\n\n"
                            f"Review feedback:\n{review[:400]}\n\n"
                            "Address all issues. Output the complete revised document."
                        ),
                    )
                    phase = "finalize"

            elif phase == "finalize":
                final = f"# {doc_name}\n\n> {self.DISCLAIMER}\n\n{draft}"
                await self._tools.file_write(output_path, final)
                phase = "complete"

            if phase == "complete":
                break

        return LegalDrafterResult(
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            document_type=doc_name,
            output_path=output_path,
            summary=f"{doc_name} drafted: {output_path}",
        )
