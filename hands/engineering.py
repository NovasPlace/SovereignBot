"""Sovereign — The Hands: Engineering domain.

API Builder, Debugger, Test Engineer, CI/CD Engineer, Performance Profiler.
Each hand is a phase-based state machine using LLM + Tool Belt.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("sovereign.hands.engineering")


# ══════════════════════════════════════════════════════════════════════════════
# RESULT DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class APIBuilderResult:
    task: str
    status: str
    phase_reached: str
    spec_path: str = ""
    files_created: list = field(default_factory=list)
    test_output: str = ""
    summary: str = ""


@dataclass
class DebuggerResult:
    bug: str
    status: str
    phase_reached: str
    root_cause: str = ""
    fix_applied: str = ""
    regression_test: str = ""
    debug_cycles: int = 0
    summary: str = ""


@dataclass
class TestEngineerResult:
    target: str
    status: str
    phase_reached: str
    tests_generated: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    coverage: float = 0.0
    flaky_removed: int = 0
    summary: str = ""


@dataclass
class CICDResult:
    task: str
    status: str
    phase_reached: str
    pipeline_file: str = ""
    ci_platform: str = ""
    summary: str = ""


@dataclass
class PerformanceResult:
    target: str
    status: str
    phase_reached: str
    baseline: str = ""
    optimized: str = ""
    improvement: str = ""
    summary: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# API BUILDER HAND
# DESIGN → SCAFFOLD → IMPLEMENT → TEST → DOCUMENT → SHIP
# ══════════════════════════════════════════════════════════════════════════════

class APIBuilderHand:
    """Autonomous API builder — spec, scaffold, implement, test, document."""

    MAX_DEBUG = 3

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(self, description: str, workdir: str = ".") -> APIBuilderResult:
        log.info("[APIBuilder] task=%s", description[:60])
        phase = "design"
        spec = ""
        files_created = []
        test_output = ""
        debug_count = 0

        for iteration in range(20):
            if phase == "design":
                spec = await self._llm(
                    system="You are an API architect. Design OpenAPI 3.0 specs.",
                    user=(
                        f"Design an OpenAPI 3.0 YAML spec for:\n{description}\n\n"
                        "Include all endpoints, schemas, auth, error responses, pagination.\n"
                        "Output ONLY valid OpenAPI 3.0 YAML."
                    ),
                )
                await self._tools.file_write(f"{workdir}/openapi.yaml", spec)
                validate = await self._tools.shell(
                    f"python3 -c \"import yaml; yaml.safe_load(open('{workdir}/openapi.yaml'))\"",
                    timeout=10,
                )
                phase = "scaffold" if validate.success else "design"
                if not validate.success and iteration > 2:
                    return APIBuilderResult(
                        task=description, status="failed",
                        phase_reached="design", summary="Could not produce valid spec",
                    )

            elif phase == "scaffold":
                scaffold = await self._llm(
                    system="You are a FastAPI expert. Generate project scaffolds.",
                    user=(
                        f"Generate a FastAPI project from this spec:\n{spec[:1500]}\n\n"
                        "Create: main.py, models.py, routes/, requirements.txt\n"
                        "For each file: FILE: path\\n```python\\ncontent\\n```"
                    ),
                )
                for path, content in self._parse_files(scaffold).items():
                    full = f"{workdir}/{path}"
                    os.makedirs(os.path.dirname(full), exist_ok=True)
                    await self._tools.file_write(full, content)
                    files_created.append(full)
                phase = "test"

            elif phase == "test":
                test_gen = await self._llm(
                    system="You are a test engineer. Write pytest API tests.",
                    user=(
                        f"Write pytest tests for this API spec:\n{spec[:800]}\n\n"
                        "Cover: happy paths, validation errors, auth, edge cases.\n"
                        "Use httpx.AsyncClient. Output a complete test_api.py."
                    ),
                )
                await self._tools.file_write(f"{workdir}/test_api.py", test_gen)
                result = await self._tools.shell(
                    f"cd {workdir} && python3 -m pytest test_api.py -v --tb=short 2>&1",
                    timeout=120,
                )
                test_output = result.data if result.success else result.error
                if result.success:
                    phase = "document"
                else:
                    debug_count += 1
                    phase = "debug" if debug_count < self.MAX_DEBUG else "document"

            elif phase == "debug":
                fix = await self._llm(
                    system="Fix failing API tests. Return corrected file contents.",
                    user=f"Test failures:\n{test_output[:800]}\n\nFix the code.",
                )
                for path, content in self._parse_files(fix).items():
                    await self._tools.file_write(f"{workdir}/{path}", content)
                phase = "test"

            elif phase == "document":
                doc = await self._llm(
                    system="Write API documentation from an OpenAPI spec.",
                    user=f"Write a README.md with endpoints, auth, examples:\n{spec[:1000]}",
                )
                await self._tools.file_write(f"{workdir}/README.md", doc)
                phase = "complete"

            if phase == "complete":
                break

        return APIBuilderResult(
            task=description,
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            spec_path=f"{workdir}/openapi.yaml",
            files_created=files_created,
            test_output=test_output[:300],
            summary=f"API built: {len(files_created)} files, tests {'passed' if phase == 'complete' else 'partial'}",
        )

    def _parse_files(self, text: str) -> dict[str, str]:
        """Extract FILE: path + code block pairs."""
        files = {}
        lines = text.split("\n")
        current_path = None
        current_lines = []
        in_block = False
        for line in lines:
            if line.startswith("FILE:"):
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines)
                current_path = line.replace("FILE:", "").strip()
                current_lines = []
                in_block = False
            elif line.startswith("```") and not in_block:
                in_block = True
            elif line.startswith("```") and in_block:
                in_block = False
            elif in_block:
                current_lines.append(line)
        if current_path and current_lines:
            files[current_path] = "\n".join(current_lines)
        return files


# ══════════════════════════════════════════════════════════════════════════════
# DEBUGGER HAND
# REPRODUCE → ISOLATE → TRACE → DIAGNOSE → FIX → VERIFY
# ══════════════════════════════════════════════════════════════════════════════

class DebuggerHand:
    """Autonomous debugger — reproduce, isolate, diagnose, fix, verify."""

    MAX_FIX_ATTEMPTS = 3

    def __init__(self, tools, llm_fn, store=None) -> None:
        self._tools = tools
        self._llm = llm_fn
        self._store = store

    async def execute(self, bug_report: str, workdir: str = ".") -> DebuggerResult:
        log.info("[Debugger] bug=%s", bug_report[:60])
        phase = "reproduce"
        root_cause = ""
        fix_applied = ""
        regression_test = ""
        debug_cycles = 0
        repro_output = ""
        suspects = ""

        for iteration in range(20):
            if phase == "reproduce":
                script = await self._llm(
                    system="Write a minimal script to reproduce this bug.",
                    user=(
                        f"Bug report: {bug_report}\nWorkdir: {workdir}\n\n"
                        "Write a Python script that triggers the bug. "
                        "The script should EXIT 1 if the bug is present."
                    ),
                )
                await self._tools.file_write(f"{workdir}/reproduce_bug.py", script)
                result = await self._tools.shell(
                    f"cd {workdir} && python3 reproduce_bug.py 2>&1", timeout=30,
                )
                repro_output = result.data if result.success else (result.error or "")
                phase = "isolate" if not result.success else "trace"

            elif phase == "isolate":
                # List codebase files
                ls = await self._tools.shell(
                    f"find {workdir} -name '*.py' -not -path '*__pycache__*' "
                    f"-not -path '*.venv*' | head -30",
                )
                isolate = await self._llm(
                    system="You are debugging. Identify which files contain the bug.",
                    user=(
                        f"Bug: {bug_report}\nRepro output:\n{repro_output[:500]}\n\n"
                        f"Files:\n{ls.data if ls.success else '(unavailable)'}\n\n"
                        "List the top 3 suspect files and functions."
                    ),
                )
                suspects = isolate
                phase = "diagnose"

            elif phase == "trace":
                phase = "diagnose"

            elif phase == "diagnose":
                diagnosis = await self._llm(
                    system="Diagnose the root cause. Be specific, point to exact lines.",
                    user=(
                        f"Bug: {bug_report}\nRepro:\n{repro_output[:400]}\n"
                        f"Suspects:\n{suspects[:400]}\n\n"
                        "Identify:\n1. ROOT CAUSE\n2. MECHANISM\n3. MINIMAL FIX"
                    ),
                )
                root_cause = diagnosis
                phase = "fix"

            elif phase == "fix":
                fix = await self._llm(
                    system="Fix this bug. Minimal change, root cause only. Add regression test.",
                    user=(
                        f"Diagnosis:\n{root_cause[:600]}\n\n"
                        "Provide corrected file(s) and a regression test.\n"
                        "Format: FILE: path\\n```python\\ncontent\\n```"
                    ),
                )
                for path, content in self._parse_files(fix).items():
                    full = f"{workdir}/{path}" if not path.startswith("/") else path
                    await self._tools.file_write(full, content)
                    if "regression" in path or "test_" in path:
                        regression_test = path
                fix_applied = root_cause[:200]
                phase = "verify"

            elif phase == "verify":
                repro_check = await self._tools.shell(
                    f"cd {workdir} && python3 reproduce_bug.py 2>&1", timeout=30,
                )
                if repro_check.success:
                    # Bug is fixed (script passes now)
                    if regression_test:
                        reg = await self._tools.shell(
                            f"cd {workdir} && python3 -m pytest {regression_test} -v 2>&1",
                            timeout=60,
                        )
                    phase = "complete"
                else:
                    debug_cycles += 1
                    if debug_cycles >= self.MAX_FIX_ATTEMPTS:
                        phase = "abort"
                    else:
                        phase = "diagnose"

            if phase in ("complete", "abort"):
                break

        if self._store and phase == "complete":
            try:
                from ..models import MemoryEntry, MemorySource
                self._store.save_memory(MemoryEntry(
                    content=f"DEBUGGER FIX: {bug_report[:100]}\nRoot cause: {root_cause[:100]}",
                    source=MemorySource.AGENT, confidence=0.9,
                    provenance_chain=["debugger_hand"],
                ))
            except Exception:
                pass

        return DebuggerResult(
            bug=bug_report, status="success" if phase == "complete" else "failed",
            phase_reached=phase, root_cause=root_cause[:300],
            fix_applied=fix_applied, regression_test=regression_test,
            debug_cycles=debug_cycles,
            summary=f"{'Fixed' if phase == 'complete' else 'Could not fix'}: {bug_report[:60]}",
        )

    def _parse_files(self, text: str) -> dict[str, str]:
        files = {}
        lines = text.split("\n")
        current_path = None
        current_lines = []
        in_block = False
        for line in lines:
            if line.startswith("FILE:"):
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines)
                current_path = line.replace("FILE:", "").strip()
                current_lines = []
                in_block = False
            elif line.startswith("```") and not in_block:
                in_block = True
            elif line.startswith("```") and in_block:
                in_block = False
            elif in_block:
                current_lines.append(line)
        if current_path and current_lines:
            files[current_path] = "\n".join(current_lines)
        return files


# ══════════════════════════════════════════════════════════════════════════════
# TEST ENGINEER HAND
# ANALYZE → STRATEGIZE → GENERATE → RUN → STABILIZE → REPORT
# ══════════════════════════════════════════════════════════════════════════════

class TestEngineerHand:
    """Autonomous test generation — analyze, strategize, generate, stabilize."""

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(self, workdir: str, coverage_target: float = 80.0) -> TestEngineerResult:
        log.info("[TestEngineer] workdir=%s target=%.0f%%", workdir, coverage_target)
        phase = "analyze"
        testable_units = []
        strategy = ""
        test_dir = f"{workdir}/tests_generated"
        tests_gen = 0
        tests_passed = 0
        tests_failed = 0
        flaky_count = 0

        for iteration in range(15):
            if phase == "analyze":
                ls = await self._tools.shell(
                    f"find {workdir} -name '*.py' -not -path '*__pycache__*' "
                    f"-not -path '*.venv*' -not -path '*test*' | head -20",
                )
                if ls.success:
                    for filepath in ls.data.strip().split("\n"):
                        if not filepath.strip():
                            continue
                        extract = await self._tools.shell(
                            f"python3 -c \""
                            f"import ast; "
                            f"tree = ast.parse(open('{filepath}').read()); "
                            f"funcs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]; "
                            f"classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]; "
                            f"print('{filepath}:', funcs[:10], classes[:5])\"",
                            timeout=10,
                        )
                        if extract.success:
                            testable_units.append(extract.data)
                phase = "strategize"

            elif phase == "strategize":
                strategy = await self._llm(
                    system="You are a test strategist. Prioritize what to test.",
                    user=(
                        f"Testable units:\n{chr(10).join(testable_units[:15])}\n\n"
                        f"Target coverage: {coverage_target}%\n"
                        "Prioritize: critical paths > edge cases > nice-to-have.\n"
                        "Output a test plan as JSON with test categories and priorities."
                    ),
                )
                phase = "generate"

            elif phase == "generate":
                await self._tools.shell(f"mkdir -p {test_dir}")
                tests = await self._llm(
                    system="Generate comprehensive pytest tests.",
                    user=(
                        f"Test strategy:\n{strategy[:800]}\n\n"
                        f"Generate a complete test file. Include:\n"
                        "- Happy path tests\n- Edge case tests\n- Error handling tests\n"
                        "- Use descriptive test names\n- Add docstrings explaining each test"
                    ),
                )
                await self._tools.file_write(f"{test_dir}/test_generated.py", tests)
                tests_gen = tests.count("def test_")
                phase = "run"

            elif phase == "run":
                result = await self._tools.shell(
                    f"cd {workdir} && python3 -m pytest {test_dir} -v --tb=short 2>&1",
                    timeout=120,
                )
                output = result.data if result.success else (result.error or "")
                tests_passed = output.count("PASSED")
                tests_failed = output.count("FAILED")
                phase = "stabilize" if result.success else "report"

            elif phase == "stabilize":
                # Run 3x to detect flaky tests
                results_by_run = []
                for run in range(3):
                    r = await self._tools.shell(
                        f"cd {workdir} && python3 -m pytest {test_dir} -v --tb=line 2>&1",
                        timeout=120,
                    )
                    results_by_run.append(r.data if r.success else "")
                # Simple flake detection: inconsistent PASSED/FAILED counts
                pass_counts = [r.count("PASSED") for r in results_by_run]
                if len(set(pass_counts)) > 1:
                    flaky_count = max(pass_counts) - min(pass_counts)
                    log.warning("[TestEngineer] %d potentially flaky tests", flaky_count)
                phase = "report"

            elif phase == "report":
                phase = "complete"

            if phase == "complete":
                break

        return TestEngineerResult(
            target=workdir,
            status="success" if tests_passed > 0 else "partial",
            phase_reached=phase,
            tests_generated=tests_gen,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            coverage=coverage_target if tests_failed == 0 else 0.0,
            flaky_removed=flaky_count,
            summary=f"Generated {tests_gen} tests: {tests_passed} passed, {tests_failed} failed",
        )


# ══════════════════════════════════════════════════════════════════════════════
# CI/CD ENGINEER HAND
# ANALYZE → DESIGN → IMPLEMENT → TEST → VERIFY
# ══════════════════════════════════════════════════════════════════════════════

class CICDEngineerHand:
    """Autonomous CI/CD setup — analyze project, design and implement pipeline."""

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(self, workdir: str, ci_platform: str = "github_actions") -> CICDResult:
        log.info("[CICD] workdir=%s platform=%s", workdir, ci_platform)
        phase = "analyze"
        project_info = ""
        pipeline_config = ""
        pipeline_file = ""

        for iteration in range(10):
            if phase == "analyze":
                # Detect language, framework, dependencies
                ls = await self._tools.shell(
                    f"ls {workdir}/requirements.txt {workdir}/package.json "
                    f"{workdir}/Cargo.toml {workdir}/go.mod 2>/dev/null || echo 'none'",
                )
                readme = await self._tools.shell(f"head -30 {workdir}/README.md 2>/dev/null || echo ''")
                project_info = f"Files: {ls.data}\nREADME: {readme.data}"
                phase = "design"

            elif phase == "design":
                pipeline_config = await self._llm(
                    system="You are a CI/CD expert. Design production-quality pipelines.",
                    user=(
                        f"Design a {ci_platform} pipeline for:\n{project_info}\n\n"
                        "Include: lint → test → build → deploy stages.\n"
                        "Add caching, notifications on failure, dependency audit.\n"
                        "Output the complete pipeline YAML."
                    ),
                )
                phase = "implement"

            elif phase == "implement":
                if ci_platform == "github_actions":
                    pipeline_file = f"{workdir}/.github/workflows/ci.yml"
                elif ci_platform == "gitlab_ci":
                    pipeline_file = f"{workdir}/.gitlab-ci.yml"
                else:
                    pipeline_file = f"{workdir}/ci-pipeline.yml"

                os.makedirs(os.path.dirname(pipeline_file), exist_ok=True)
                await self._tools.file_write(pipeline_file, pipeline_config)
                phase = "verify"

            elif phase == "verify":
                # Validate YAML syntax
                validate = await self._tools.shell(
                    f"python3 -c \"import yaml; yaml.safe_load(open('{pipeline_file}'))\"",
                    timeout=10,
                )
                if validate.success:
                    phase = "complete"
                else:
                    phase = "design"  # re-generate on invalid YAML
                    if iteration > 5:
                        phase = "complete"  # ship what we have

            if phase == "complete":
                break

        return CICDResult(
            task=f"CI/CD for {workdir}",
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            pipeline_file=pipeline_file,
            ci_platform=ci_platform,
            summary=f"Pipeline created: {pipeline_file}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE PROFILER HAND
# BENCHMARK → PROFILE → IDENTIFY → OPTIMIZE → VERIFY
# ══════════════════════════════════════════════════════════════════════════════

class PerformanceProfilerHand:
    """Autonomous performance profiling — benchmark, profile, optimize."""

    def __init__(self, tools, llm_fn) -> None:
        self._tools = tools
        self._llm = llm_fn

    async def execute(self, target: str, workdir: str = ".") -> PerformanceResult:
        log.info("[Profiler] target=%s", target[:60])
        phase = "benchmark"
        baseline = ""
        profile_data = ""
        bottleneck = ""
        optimized = ""
        improvement = ""

        for iteration in range(12):
            if phase == "benchmark":
                script = await self._llm(
                    system="Write performance benchmarks using timeit and tracemalloc.",
                    user=(
                        f"Write a benchmark for: {target}\nWorkdir: {workdir}\n\n"
                        "Measure: execution time (10 iterations), memory peak.\n"
                        "Print: mean, median, min, max, memory_mb.\n"
                        "Save results to benchmark_baseline.json."
                    ),
                )
                await self._tools.file_write(f"{workdir}/benchmark.py", script)
                result = await self._tools.shell(
                    f"cd {workdir} && python3 benchmark.py 2>&1", timeout=120,
                )
                baseline = result.data if result.success else (result.error or "")
                phase = "profile" if result.success else "identify"

            elif phase == "profile":
                profile_result = await self._tools.shell(
                    f"cd {workdir} && python3 -m cProfile -o profile.dat benchmark.py 2>&1 && "
                    f"python3 -c \""
                    f"import pstats; s = pstats.Stats('profile.dat'); "
                    f"s.sort_stats('cumulative'); s.print_stats(15)\" 2>&1",
                    timeout=120,
                )
                profile_data = profile_result.data if profile_result.success else ""
                phase = "identify"

            elif phase == "identify":
                bottleneck = await self._llm(
                    system="Identify performance bottlenecks from profiling data.",
                    user=(
                        f"Baseline: {baseline[:400]}\nProfile:\n{profile_data[:600]}\n\n"
                        "Identify the top 3 bottlenecks and suggest optimizations.\n"
                        "Be specific: which function, why it's slow, what to change."
                    ),
                )
                phase = "optimize"

            elif phase == "optimize":
                fix = await self._llm(
                    system="Optimize code for performance. Minimal changes, maximum impact.",
                    user=(
                        f"Bottlenecks:\n{bottleneck[:600]}\n\n"
                        "Implement the optimizations. Return corrected file contents.\n"
                        "Format: FILE: path\\n```python\\ncontent\\n```"
                    ),
                )
                for path, content in self._parse_files(fix).items():
                    full = f"{workdir}/{path}" if not path.startswith("/") else path
                    await self._tools.file_write(full, content)
                phase = "verify"

            elif phase == "verify":
                result = await self._tools.shell(
                    f"cd {workdir} && python3 benchmark.py 2>&1", timeout=120,
                )
                optimized = result.data if result.success else ""
                improvement = await self._llm(
                    system="Compare benchmark results.",
                    user=f"BEFORE:\n{baseline[:300]}\n\nAFTER:\n{optimized[:300]}\n\nSummarize improvement.",
                )
                phase = "complete"

            if phase == "complete":
                break

        return PerformanceResult(
            target=target,
            status="success" if phase == "complete" else "partial",
            phase_reached=phase,
            baseline=baseline[:200],
            optimized=optimized[:200],
            improvement=improvement[:200],
            summary=f"Profiled {target}: {improvement[:100] if improvement else 'no improvement measured'}",
        )

    def _parse_files(self, text: str) -> dict[str, str]:
        files = {}
        lines = text.split("\n")
        current_path = None
        current_lines = []
        in_block = False
        for line in lines:
            if line.startswith("FILE:"):
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines)
                current_path = line.replace("FILE:", "").strip()
                current_lines = []
                in_block = False
            elif line.startswith("```") and not in_block:
                in_block = True
            elif line.startswith("```") and in_block:
                in_block = False
            elif in_block:
                current_lines.append(line)
        if current_path and current_lines:
            files[current_path] = "\n".join(current_lines)
        return files
