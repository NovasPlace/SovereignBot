"""Sovereign — The Hands: Data domain.

Data Analyst, Database Architect, Scraper.
Each hand is a phase-based state machine using LLM + Tool Belt.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("sovereign.hands.data")


# ══════════════════════════════════════════════════════════════════════════════
# RESULT DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DataAnalystResult:
    question: str
    status: str
    phase_reached: str
    report: str = ""
    charts: list = field(default_factory=list)
    summary: str = ""


@dataclass
class DatabaseArchitectResult:
    task: str
    status: str
    phase_reached: str
    schema_file: str = ""
    migrations: list = field(default_factory=list)
    summary: str = ""


@dataclass
class ScraperResult:
    target: str
    status: str
    phase_reached: str
    records_scraped: int = 0
    output_file: str = ""
    summary: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# DATA ANALYST HAND
# INGEST → CLEAN → EXPLORE → ANALYZE → VISUALIZE → REPORT
# ══════════════════════════════════════════════════════════════════════════════

class DataAnalystHand:
    """Autonomous data analysis — ingest, clean, analyze, visualize, report."""

    WORK_DIR = "/tmp/sovereign/data_analysis"

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(self, question: str, data_source: str) -> DataAnalystResult:
        log.info("[DataAnalyst] question=%s source=%s", question[:40], data_source[:40])
        os.makedirs(self.WORK_DIR, exist_ok=True)
        os.makedirs(f"{self.WORK_DIR}/charts", exist_ok=True)

        phase = "ingest"
        data_summary = ""
        clean_summary = ""
        explore_summary = ""
        analysis = ""
        charts = []
        report = ""

        for iteration in range(18):
            if phase == "ingest":
                # Try file read first, then URL
                result = await self._tools.shell(
                    f"head -100 '{data_source}' 2>/dev/null || "
                    f"curl -sL '{data_source}' | head -100",
                    timeout=30,
                )
                if not result.success:
                    return DataAnalystResult(
                        question=question, status="failed", phase_reached="ingest",
                        summary=f"Could not load data source: {data_source}",
                    )

                parse_script = await self._llm(
                    system="Write a Python data parsing script using pandas.",
                    user=(
                        f"Parse this data:\n{result.data[:500]}\n\n"
                        "1. Detect format (CSV, JSON, Excel)\n"
                        "2. Load into pandas DataFrame\n"
                        "3. Print df.shape, df.dtypes, df.head()\n"
                        "4. Save to /tmp/sovereign/data_analysis/data.pkl\n"
                        "Output ONLY Python code."
                    ),
                )
                await self._tools.file_write(f"{self.WORK_DIR}/parse.py", parse_script)
                parse_r = await self._tools.shell(
                    f"cd {self.WORK_DIR} && python3 parse.py 2>&1", timeout=30,
                )
                data_summary = parse_r.data if parse_r.success else ""
                phase = "clean" if parse_r.success else "abort"

            elif phase == "clean":
                script = await self._llm(
                    system="Write a data cleaning script.",
                    user=(
                        f"Clean the data at {self.WORK_DIR}/data.pkl:\n"
                        f"Summary: {data_summary[:400]}\n\n"
                        "Handle: missing values, duplicates, type conversions.\n"
                        "Save to data_clean.pkl. Print cleaning summary."
                    ),
                )
                await self._tools.file_write(f"{self.WORK_DIR}/clean.py", script)
                r = await self._tools.shell(
                    f"cd {self.WORK_DIR} && python3 clean.py 2>&1", timeout=30,
                )
                clean_summary = r.data if r.success else data_summary
                phase = "explore"

            elif phase == "explore":
                script = await self._llm(
                    system="Write an exploratory data analysis script.",
                    user=(
                        f"Explore {self.WORK_DIR}/data_clean.pkl:\n"
                        f"Data: {clean_summary[:300]}\n"
                        f"Question: {question}\n\n"
                        "Compute: describe(), correlations, value_counts.\n"
                        "Identify top 5 patterns relevant to the question.\n"
                        "Print structured summary."
                    ),
                )
                await self._tools.file_write(f"{self.WORK_DIR}/explore.py", script)
                r = await self._tools.shell(
                    f"cd {self.WORK_DIR} && python3 explore.py 2>&1", timeout=30,
                )
                explore_summary = r.data if r.success else ""
                phase = "analyze"

            elif phase == "analyze":
                script = await self._llm(
                    system="Write a statistical analysis script.",
                    user=(
                        f"Analyze to answer: {question}\n\n"
                        f"Exploration findings: {explore_summary[:400]}\n\n"
                        "Use appropriate methods (t-test, regression, correlation, etc).\n"
                        "Print clear findings with numbers and significance levels.\n"
                        "Save results to analysis_results.txt."
                    ),
                )
                await self._tools.file_write(f"{self.WORK_DIR}/analyze.py", script)
                r = await self._tools.shell(
                    f"cd {self.WORK_DIR} && python3 analyze.py 2>&1", timeout=60,
                )
                analysis = r.data if r.success else explore_summary
                phase = "visualize"

            elif phase == "visualize":
                script = await self._llm(
                    system="Write a matplotlib visualization script.",
                    user=(
                        f"Create 2-4 charts for: {question}\n"
                        f"Analysis: {analysis[:400]}\n\n"
                        "Use seaborn whitegrid style. Clear titles and labels.\n"
                        f"Save PNGs to {self.WORK_DIR}/charts/"
                    ),
                )
                await self._tools.file_write(f"{self.WORK_DIR}/visualize.py", script)
                await self._tools.shell(
                    f"cd {self.WORK_DIR} && python3 visualize.py 2>&1", timeout=30,
                )
                chart_ls = await self._tools.shell(
                    f"ls {self.WORK_DIR}/charts/*.png 2>/dev/null",
                )
                charts = (chart_ls.data or "").strip().split("\n") if chart_ls.success else []
                phase = "report"

            elif phase == "report":
                report = await self._llm(
                    system="Write a concise data analysis report.",
                    user=(
                        f"Question: {question}\n\n"
                        f"Data: {clean_summary[:200]}\n"
                        f"Analysis: {analysis[:400]}\n"
                        f"Charts: {charts}\n\n"
                        "Structure: Executive Summary, Key Findings, Methodology, Recommendations.\n"
                        "Every claim must reference specific numbers from the analysis."
                    ),
                )
                await self._tools.file_write(f"{self.WORK_DIR}/report.md", report)
                phase = "complete"

            if phase in ("complete", "abort"):
                break

        return DataAnalystResult(
            question=question,
            status="success" if phase == "complete" else "failed",
            phase_reached=phase,
            report=report[:500],
            charts=charts,
            summary=f"Analysis of '{question[:40]}': {'complete' if report else 'failed'}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE ARCHITECT HAND
# ANALYZE → DESIGN → MIGRATE → SEED → OPTIMIZE → VERIFY
# ══════════════════════════════════════════════════════════════════════════════

class DatabaseArchitectHand:
    """Autonomous DB design — schema, migrations, optimization."""

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(self, description: str, workdir: str = ".") -> DatabaseArchitectResult:
        log.info("[DatabaseArchitect] task=%s", description[:60])
        phase = "analyze"
        requirements = ""
        schema = ""
        migrations = []

        for iteration in range(12):
            if phase == "analyze":
                # Check existing database state
                existing = await self._tools.shell(
                    f"find {workdir} -name '*.sql' -o -name 'models.py' -o -name 'schema.*' 2>/dev/null | head -10",
                )
                requirements = await self._llm(
                    system="You are a database architect.",
                    user=(
                        f"Requirements: {description}\n"
                        f"Existing files: {existing.data if existing.success else 'none'}\n\n"
                        "Analyze data relationships, access patterns, and constraints.\n"
                        "Output the analysis as structured notes."
                    ),
                )
                phase = "design"

            elif phase == "design":
                schema = await self._llm(
                    system="Design database schemas. Use PostgreSQL SQL.",
                    user=(
                        f"Analysis:\n{requirements[:600]}\n\n"
                        "Design a schema with:\n"
                        "- Tables with appropriate types and constraints\n"
                        "- Foreign keys and indexes\n"
                        "- NOT NULL where appropriate\n"
                        "- CHECK constraints for validation\n"
                        "Output complete CREATE TABLE statements."
                    ),
                )
                await self._tools.file_write(f"{workdir}/schema.sql", schema)
                phase = "migrate"

            elif phase == "migrate":
                migration = await self._llm(
                    system="Write reversible database migrations.",
                    user=(
                        f"Schema:\n{schema[:800]}\n\n"
                        "Generate:\n"
                        "1. Up migration (CREATE tables)\n"
                        "2. Down migration (DROP tables, in reverse order)\n"
                        "Output as two separate SQL files."
                    ),
                )
                ts = str(int(__import__("time").time()))
                up_path = f"{workdir}/migrations/{ts}_up.sql"
                down_path = f"{workdir}/migrations/{ts}_down.sql"
                os.makedirs(f"{workdir}/migrations", exist_ok=True)
                # Split migration into up/down
                parts = migration.split("-- DOWN")
                await self._tools.file_write(up_path, parts[0])
                if len(parts) > 1:
                    await self._tools.file_write(down_path, parts[1])
                migrations = [up_path, down_path]
                phase = "optimize"

            elif phase == "optimize":
                optimizations = await self._llm(
                    system="Optimize database schema and queries.",
                    user=(
                        f"Schema:\n{schema[:600]}\n\n"
                        "Suggest:\n"
                        "1. Additional indexes for common query patterns\n"
                        "2. Partition strategy for large tables\n"
                        "3. Query optimization hints\n"
                        "Output as SQL statements."
                    ),
                )
                await self._tools.file_write(f"{workdir}/optimize.sql", optimizations)
                phase = "verify"

            elif phase == "verify":
                # Validate SQL syntax
                validate = await self._tools.shell(
                    f"python3 -c \"open('{workdir}/schema.sql').read()\" 2>&1",
                    timeout=5,
                )
                phase = "complete"

            if phase == "complete":
                break

        return DatabaseArchitectResult(
            task=description,
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            schema_file=f"{workdir}/schema.sql",
            migrations=migrations,
            summary=f"Schema designed: {workdir}/schema.sql",
        )


# ══════════════════════════════════════════════════════════════════════════════
# SCRAPER HAND
# TARGET → ANALYZE → BUILD → TEST → HARDEN → DELIVER
# ══════════════════════════════════════════════════════════════════════════════

class ScraperHand:
    """Autonomous web scraper — analyze target, build, harden, deliver."""

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(
        self, target_url: str, data_desc: str, output_format: str = "json",
        workdir: str = "/tmp/sovereign/scraper",
    ) -> ScraperResult:
        log.info("[Scraper] url=%s", target_url[:60])
        os.makedirs(workdir, exist_ok=True)

        phase = "analyze"
        page_content = ""
        page_analysis = ""
        scraper_code = ""
        records = 0

        for iteration in range(15):
            if phase == "analyze":
                fetch = await self._tools.shell(
                    f"curl -sL -A 'Mozilla/5.0' '{target_url}' | head -200",
                    timeout=15,
                )
                if not fetch.success:
                    return ScraperResult(
                        target=target_url, status="failed", phase_reached="analyze",
                        summary="Could not fetch target URL",
                    )
                page_content = fetch.data or ""
                page_analysis = await self._llm(
                    system="Analyze web pages for scraping.",
                    user=(
                        f"URL: {target_url}\nContent:\n{page_content[:1500]}\n\n"
                        f"Target data: {data_desc}\n\n"
                        "Identify: CSS selectors, pagination type, auth needed, "
                        "anti-bot measures, data structure."
                    ),
                )
                phase = "build"

            elif phase == "build":
                scraper_code = await self._llm(
                    system="Build web scrapers with requests/BeautifulSoup or playwright.",
                    user=(
                        f"Build a scraper for: {target_url}\n"
                        f"Target data: {data_desc}\n"
                        f"Analysis:\n{page_analysis[:600]}\n\n"
                        "Use requests + BeautifulSoup (fall back to playwright if JS needed).\n"
                        "Handle pagination. Save results as {output_format}.\n"
                        f"Output to {workdir}/results.{output_format}\n"
                        "Include error handling and logging."
                    ),
                )
                await self._tools.file_write(f"{workdir}/scraper.py", scraper_code)
                phase = "test"

            elif phase == "test":
                result = await self._tools.shell(
                    f"cd {workdir} && python3 scraper.py 2>&1", timeout=60,
                )
                if result.success:
                    # Count records
                    count = await self._tools.shell(
                        f"python3 -c \"import json; "
                        f"d=json.load(open('{workdir}/results.json')); "
                        f"print(len(d) if isinstance(d, list) else 1)\" 2>/dev/null || echo 0",
                    )
                    records = int((count.data or "0").strip()) if count.success else 0
                    phase = "harden"
                else:
                    phase = "build"
                    if iteration > 5:
                        phase = "harden"

            elif phase == "harden":
                hardened = await self._llm(
                    system="Harden scrapers against real-world issues.",
                    user=(
                        f"Harden this scraper:\n{scraper_code[:600]}\n\n"
                        "Add:\n"
                        "1. Retry with exponential backoff (3 retries)\n"
                        "2. Random delays (1-3s between requests)\n"
                        "3. Rotating User-Agent headers\n"
                        "4. Graceful handling of missing elements\n"
                        "5. Duplicate detection\n"
                        "6. Rate limit detection (429 → pause)\n"
                        "Output the complete hardened scraper."
                    ),
                )
                await self._tools.file_write(f"{workdir}/scraper.py", hardened)
                phase = "deliver"

            elif phase == "deliver":
                # Final run with hardened scraper
                result = await self._tools.shell(
                    f"cd {workdir} && python3 scraper.py 2>&1", timeout=120,
                )
                if result.success:
                    count = await self._tools.shell(
                        f"python3 -c \"import json; "
                        f"d=json.load(open('{workdir}/results.json')); "
                        f"print(len(d) if isinstance(d, list) else 1)\" 2>/dev/null || echo 0",
                    )
                    records = int((count.data or "0").strip()) if count.success else records
                phase = "complete"

            if phase in ("complete", "abort"):
                break

        return ScraperResult(
            target=target_url,
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            records_scraped=records,
            output_file=f"{workdir}/results.{output_format}",
            summary=f"Scraped {records} records from {target_url[:40]}",
        )
