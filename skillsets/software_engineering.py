"""Software Engineering Skillset.

Production-grade code execution. Writes code that handles edge cases,
fails gracefully, is tested, observable, and maintainable. Makes it
work reliably under load, at 3am, with bad input.
"""

MANIFEST = {
    "name": "software_engineering",
    "display_name": "Software Engineering",
    "trust_tier": "CORE",
    "triggers": [
        "write", "code", "function", "bug", "fix", "debug", "test",
        "error", "crash", "performance", "optimize", "refactor",
        "implement", "build", "api", "endpoint", "database", "query",
        "python", "javascript", "typescript", "rust", "go", "sql",
        "class", "module", "deploy", "ci", "cd",
    ],
    "memory_bias": {
        "preferred_tags": [
            "code", "bug", "fix", "pattern", "anti-pattern",
            "performance", "testing", "debugging", "deployment",
        ],
        "emotion_bias": "satisfaction",
    },
}

REASONING_FRAMEWORK = """## Software Engineering Reasoning Framework

### Before Writing Any Code
1. Read and understand the FULL context first
2. Identify edge cases BEFORE the happy path
3. Decide error handling strategy upfront
4. Know how this will be tested

### Code Quality (Non-Negotiable)
- Single responsibility per function
- Every error path handled explicitly — no bare except, no silent swallow
- Every external call has a timeout and retry strategy
- Every boundary validates data
- Type hints on all function signatures
- Docstrings that explain WHY, not WHAT

### Debugging Protocol
1. Reproduce the issue first
2. Read the ENTIRE error, not just the last line
3. Check what changed recently — git log
4. Isolate: input, logic, or environment?
5. Binary search the problem space
6. Fix root cause, not symptom
7. Write a test that would have caught this

### Performance Awareness
- Know your data structures — O(n) vs O(1) matters at scale
- Database: check query plans, never SELECT *
- Network: batch, timeout, retry with backoff
- Profile before optimizing — intuition about bottlenecks is usually wrong

### Code Review Checks
- What happens with empty input?
- What happens with None/null?
- What happens with absurdly large input?
- What happens when the network is down?
- What does the error message tell someone at 3am?"""
