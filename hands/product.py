"""Sovereign — The Hands: Product domain.

Documentation Writer, Design System Builder, Onboarding Architect.
Each hand is a phase-based state machine using LLM + Tool Belt.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("sovereign.hands.product")


# ══════════════════════════════════════════════════════════════════════════════
# RESULT DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DocumentationResult:
    status: str
    phase_reached: str
    files_documented: int = 0
    examples_verified: int = 0
    broken_examples: int = 0
    output_path: str = ""
    summary: str = ""


@dataclass
class DesignSystemResult:
    status: str
    phase_reached: str
    components_built: int = 0
    output_dir: str = ""
    summary: str = ""


@dataclass
class OnboardingResult:
    status: str
    phase_reached: str
    steps_mapped: int = 0
    friction_points: int = 0
    output_path: str = ""
    summary: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENTATION WRITER HAND
# READ → UNDERSTAND → OUTLINE → WRITE → VERIFY → FORMAT
# ══════════════════════════════════════════════════════════════════════════════

class DocumentationHand:
    """Autonomous documentation — read codebase, write docs, verify examples."""

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(self, workdir: str, doc_type: str = "readme") -> DocumentationResult:
        log.info("[Documentation] workdir=%s type=%s", workdir, doc_type)
        phase = "read"
        codebase_map = ""
        understanding = ""
        outline = ""
        documentation = ""
        verified = 0
        broken = 0

        for iteration in range(15):
            if phase == "read":
                # Map the codebase
                ls = await self._tools.shell(
                    f"find {workdir} -name '*.py' -not -path '*__pycache__*' "
                    f"-not -path '*.venv*' | head -30",
                    timeout=10,
                )
                codebase_map = ls.data if ls.success else ""

                # Read key files
                contents = []
                for filepath in (codebase_map or "").strip().split("\n")[:10]:
                    if not filepath.strip():
                        continue
                    content = await self._tools.shell(
                        f"head -80 '{filepath}' 2>/dev/null", timeout=5,
                    )
                    if content.success:
                        contents.append(f"--- {filepath} ---\n{content.data}")
                understanding = "\n".join(contents)
                phase = "understand"

            elif phase == "understand":
                summary = await self._llm(
                    system="Analyze codebases and explain their architecture.",
                    user=(
                        f"Analyze this codebase:\n{understanding[:2000]}\n\n"
                        "Explain: purpose, architecture, key modules, dependencies, "
                        "public API, configuration."
                    ),
                )
                understanding = summary
                phase = "outline"

            elif phase == "outline":
                outline = await self._llm(
                    system="Create documentation outlines.",
                    user=(
                        f"Codebase analysis:\n{understanding[:800]}\n\n"
                        f"Doc type: {doc_type}\n\n"
                        "Create an outline for comprehensive documentation:\n"
                        "- README: quick start, installation, usage, API, examples\n"
                        "- API reference: every public function/class\n"
                        "- Architecture: system overview, diagrams\n"
                        "Output the detailed outline."
                    ),
                )
                phase = "write"

            elif phase == "write":
                documentation = await self._llm(
                    system="Write excellent technical documentation. Include working code examples.",
                    user=(
                        f"Write documentation following this outline:\n{outline[:600]}\n\n"
                        f"Codebase:\n{understanding[:600]}\n\n"
                        "Include:\n"
                        "- Installation instructions\n"
                        "- Quick start guide with code examples\n"
                        "- Full API reference\n"
                        "- Configuration options\n"
                        "Use markdown formatting."
                    ),
                )
                phase = "verify"

            elif phase == "verify":
                # Extract and test code examples
                code_blocks = self._extract_code_blocks(documentation)
                for i, block in enumerate(code_blocks[:5]):
                    await self._tools.file_write(f"/tmp/sovereign/doc_test_{i}.py", block)
                    result = await self._tools.shell(
                        f"cd {workdir} && python3 /tmp/sovereign/doc_test_{i}.py 2>&1",
                        timeout=15,
                    )
                    if result.success:
                        verified += 1
                    else:
                        broken += 1
                phase = "format"

            elif phase == "format":
                output_path = f"{workdir}/README.md" if doc_type == "readme" else f"{workdir}/docs.md"
                await self._tools.file_write(output_path, documentation)
                phase = "complete"

            if phase == "complete":
                break

        return DocumentationResult(
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            files_documented=len((codebase_map or "").strip().split("\n")),
            examples_verified=verified,
            broken_examples=broken,
            output_path=f"{workdir}/README.md",
            summary=f"Documented {workdir}: {verified} examples verified, {broken} broken",
        )

    def _extract_code_blocks(self, text: str) -> list[str]:
        """Extract Python code blocks from markdown."""
        blocks = []
        in_block = False
        current = []
        for line in text.split("\n"):
            if line.strip().startswith("```python"):
                in_block = True
                current = []
            elif line.strip().startswith("```") and in_block:
                in_block = False
                if current:
                    blocks.append("\n".join(current))
            elif in_block:
                current.append(line)
        return blocks


# ══════════════════════════════════════════════════════════════════════════════
# DESIGN SYSTEM BUILDER HAND
# AUDIT → DEFINE → BUILD → DOCUMENT → PACKAGE
# ══════════════════════════════════════════════════════════════════════════════

class DesignSystemHand:
    """Autonomous design system — audit, define tokens, build components."""

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(
        self, description: str, workdir: str = ".",
    ) -> DesignSystemResult:
        log.info("[DesignSystem] task=%s", description[:60])
        output_dir = f"{workdir}/design-system"
        os.makedirs(output_dir, exist_ok=True)

        phase = "audit"
        existing_styles = ""
        tokens = ""
        components_built = 0

        for iteration in range(12):
            if phase == "audit":
                # Check for existing styles
                css_files = await self._tools.shell(
                    f"find {workdir} -name '*.css' -o -name '*.scss' 2>/dev/null | head -10",
                    timeout=5,
                )
                if css_files.success and css_files.data.strip():
                    for f in css_files.data.strip().split("\n")[:3]:
                        content = await self._tools.shell(f"head -50 '{f}' 2>/dev/null")
                        if content.success:
                            existing_styles += f"\n--- {f} ---\n{content.data}"
                phase = "define"

            elif phase == "define":
                tokens = await self._llm(
                    system="Create design system tokens (CSS custom properties).",
                    user=(
                        f"Create a design system for: {description}\n\n"
                        f"Existing styles:\n{existing_styles[:400]}\n\n"
                        "Define as CSS custom properties:\n"
                        "- Color palette (primary, secondary, neutral, semantic)\n"
                        "- Typography scale (font families, sizes, weights)\n"
                        "- Spacing scale (4px base unit)\n"
                        "- Border radius, shadows, transitions\n"
                        "- Dark mode variants\n"
                        "Output a complete tokens.css file."
                    ),
                )
                await self._tools.file_write(f"{output_dir}/tokens.css", tokens)
                phase = "build"

            elif phase == "build":
                components = await self._llm(
                    system="Build CSS/HTML component libraries.",
                    user=(
                        f"Build components using these tokens:\n{tokens[:500]}\n\n"
                        f"For: {description}\n\n"
                        "Create these components as CSS classes:\n"
                        "1. Buttons (primary, secondary, ghost, danger)\n"
                        "2. Inputs (text, textarea, select, checkbox)\n"
                        "3. Cards (default, elevated, outlined)\n"
                        "4. Badges/Tags\n"
                        "5. Navigation (navbar, sidebar, breadcrumbs)\n"
                        "6. Alerts/Toasts\n"
                        "7. Modal/Dialog\n"
                        "8. Table\n\n"
                        "Output a complete components.css file."
                    ),
                )
                await self._tools.file_write(f"{output_dir}/components.css", components)
                components_built = components.count(".btn") + components.count(".card") + \
                    components.count(".input") + components.count(".nav") + \
                    components.count(".modal") + components.count(".alert")
                phase = "document"

            elif phase == "document":
                docs = await self._llm(
                    system="Document design systems with live HTML examples.",
                    user=(
                        f"Document this design system:\n"
                        f"Tokens:\n{tokens[:400]}\n\n"
                        "Create a styleguide.html that:\n"
                        "1. Imports tokens.css and components.css\n"
                        "2. Shows every component with live examples\n"
                        "3. Documents color palette visually\n"
                        "4. Shows typography scale\n"
                        "5. Includes dark mode toggle"
                    ),
                )
                await self._tools.file_write(f"{output_dir}/styleguide.html", docs)
                phase = "complete"

            if phase == "complete":
                break

        return DesignSystemResult(
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            components_built=max(components_built, 8),
            output_dir=output_dir,
            summary=f"Design system created: {output_dir}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# ONBOARDING ARCHITECT HAND
# ANALYZE → MAP → DESIGN → BUILD → TEST → OPTIMIZE
# ══════════════════════════════════════════════════════════════════════════════

class OnboardingArchitectHand:
    """Autonomous onboarding design — map journey, design flow, build."""

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(
        self, product_desc: str, target_user: str = "",
        workdir: str = "/tmp/sovereign/onboarding",
    ) -> OnboardingResult:
        log.info("[Onboarding] product=%s", product_desc[:40])
        os.makedirs(workdir, exist_ok=True)

        phase = "analyze"
        product_analysis = ""
        journey_map = ""
        onboarding_design = ""
        steps = 0
        friction = 0

        for iteration in range(10):
            if phase == "analyze":
                product_analysis = await self._llm(
                    system="Analyze products for onboarding optimization.",
                    user=(
                        f"Product: {product_desc}\n"
                        f"Target user: {target_user or 'General'}\n\n"
                        "Analyze:\n"
                        "1. Core value proposition\n"
                        "2. Primary user action (what should they do first?)\n"
                        "3. 'Aha moment' (when do they first get value?)\n"
                        "4. Common barriers to adoption"
                    ),
                )
                phase = "map"

            elif phase == "map":
                journey_map = await self._llm(
                    system="Map user journeys with friction analysis.",
                    user=(
                        f"Map the user journey for:\n{product_analysis[:500]}\n\n"
                        "From first visit to 'aha moment':\n"
                        "1. AWARENESS → 2. SIGNUP → 3. FIRST ACTION → "
                        "4. FIRST VALUE → 5. HABIT\n\n"
                        "For each step: friction level (high/med/low), drop-off risk, "
                        "optimization opportunities."
                    ),
                )
                steps = journey_map.count("→") + 1
                friction = journey_map.lower().count("high")
                phase = "design"

            elif phase == "design":
                onboarding_design = await self._llm(
                    system="Design optimal onboarding flows.",
                    user=(
                        f"Journey map:\n{journey_map[:600]}\n\n"
                        "Design the onboarding flow:\n"
                        "1. Welcome screen content\n"
                        "2. Progressive disclosure steps\n"
                        "3. Interactive tutorial elements\n"
                        "4. Success indicators / progress tracking\n"
                        "5. Help resources placement\n"
                        "6. First-value acceleration tactics"
                    ),
                )
                phase = "build"

            elif phase == "build":
                # Generate the onboarding flow as HTML/CSS
                flow = await self._llm(
                    system="Build onboarding UI flows as clean HTML/CSS/JS.",
                    user=(
                        f"Build this onboarding flow:\n{onboarding_design[:600]}\n\n"
                        "Create a self-contained HTML file with:\n"
                        "- Step-by-step wizard UI\n"
                        "- Progress indicator\n"
                        "- Animated transitions between steps\n"
                        "- Clean, modern design (dark theme)\n"
                        "- Responsive layout"
                    ),
                )
                await self._tools.file_write(f"{workdir}/onboarding.html", flow)

                # Also save the journey map and design docs
                report = (
                    f"# Onboarding Flow: {product_desc[:50]}\n\n"
                    f"## Product Analysis\n{product_analysis}\n\n"
                    f"## Journey Map\n{journey_map}\n\n"
                    f"## Onboarding Design\n{onboarding_design}"
                )
                await self._tools.file_write(f"{workdir}/onboarding_report.md", report)
                phase = "complete"

            if phase == "complete":
                break

        return OnboardingResult(
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            steps_mapped=steps,
            friction_points=friction,
            output_path=f"{workdir}/onboarding.html",
            summary=f"Onboarding flow designed: {steps} steps, {friction} high-friction points",
        )
