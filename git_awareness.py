"""Sovereign — Git Awareness: the organism watches code evolve.

When a commit lands, the organism sees what changed, understands why
from the message and diff, connects it to memory, and flags security-
relevant changes for proactive alerting.

Not a webhook — a sense. The organism scans repos on heartbeat pulses.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field

log = logging.getLogger("sovereign.git_awareness")

_SECURITY_PATTERNS = frozenset({
    "auth", "login", "password", "token", "secret", "key",
    "encrypt", "decrypt", "permission", "cors", "csrf",
    "sanitize", "inject", ".env", "credential", "session",
})


@dataclass
class GitCommit:
    hash: str
    author: str
    message: str
    date: str


@dataclass
class DiffSummary:
    files_changed: list[str] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0
    areas: list[str] = field(default_factory=list)
    security_relevant: bool = False
    is_large: bool = False


@dataclass
class GitPerception:
    """A commit the organism perceived."""
    commit: GitCommit
    diff: DiffSummary
    repo: str
    alert: str = ""


class GitAwareness:
    """Watches local git repositories for changes."""

    SCAN_INTERVAL = 300  # 5 minutes between scans

    def __init__(self, store, notification_system=None) -> None:
        self._store = store
        self._notifs = notification_system
        self._watched_repos: list[str] = []
        self._last_commits: dict[str, str] = {}  # repo → last seen hash
        self._last_scan: float = 0.0
        self._first_scan: bool = True  # don't alert on existing commits at boot
        self._detect_repos()
        log.info("GitAwareness initialized (watching %d repos)", len(self._watched_repos))

    async def on_pulse(self, pulse_count: int, state: str) -> None:
        """Heartbeat phase — scan repos for new commits."""
        now = time.time()
        if now - self._last_scan < self.SCAN_INTERVAL:
            return
        self._last_scan = now

        for repo in self._watched_repos:
            try:
                perceptions = self._scan_repo(repo)
                for p in perceptions:
                    self._remember_commit(p)
                    if p.alert and not self._first_scan:
                        log.info("Git security alert: %s", p.alert)
                        if self._notifs:
                            # Queue as a thought, not an alert to "system"
                            self._notifs.queue_thought(
                                p.commit.author, p.alert
                            )
            except Exception as e:
                log.debug("Git scan error for %s: %s", repo, e)

        self._first_scan = False

    def _detect_repos(self) -> None:
        """Auto-detect git repos under the Agent_System directory."""
        base = os.path.expanduser("~/Desktop/Agent_System")
        if not os.path.isdir(base):
            return
        for entry in os.listdir(base):
            path = os.path.join(base, entry)
            if os.path.isdir(os.path.join(path, ".git")):
                self._watched_repos.append(path)

    def _scan_repo(self, repo: str) -> list[GitPerception]:
        """Check a repo for new commits since last scan."""
        last = self._last_commits.get(repo, "")

        if last:
            cmd = ["git", "-C", repo, "log", f"{last}..HEAD",
                   "--format=%H|%an|%s|%ci", "--no-merges", "-10"]
        else:
            cmd = ["git", "-C", repo, "log", "-3",
                   "--format=%H|%an|%s|%ci", "--no-merges"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return []

        perceptions = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 3)
            if len(parts) < 4:
                continue

            commit = GitCommit(hash=parts[0], author=parts[1],
                               message=parts[2], date=parts[3])
            diff = self._analyze_commit(repo, commit.hash)

            alert = ""
            if diff.security_relevant:
                alert = (
                    f"🔒 Security-relevant commit in {os.path.basename(repo)}: "
                    f"'{commit.message}' ({len(diff.files_changed)} files, "
                    f"+{diff.lines_added}/-{diff.lines_removed})"
                )

            perceptions.append(GitPerception(
                commit=commit, diff=diff,
                repo=os.path.basename(repo), alert=alert,
            ))

        # Update last seen
        if perceptions:
            self._last_commits[repo] = perceptions[0].commit.hash

        return perceptions

    def _analyze_commit(self, repo: str, commit_hash: str) -> DiffSummary:
        """Analyze a commit diff for significance."""
        result = subprocess.run(
            ["git", "-C", repo, "diff", "--stat", f"{commit_hash}~1..{commit_hash}"],
            capture_output=True, text=True, timeout=10,
        )
        ds = DiffSummary()

        for line in result.stdout.strip().split("\n"):
            if "|" in line:
                fname = line.split("|")[0].strip()
                ds.files_changed.append(fname)
                parts = line.split("|")[1].strip().split()
                if len(parts) >= 1:
                    try:
                        changes = int(parts[0])
                        ds.lines_added += changes // 2
                        ds.lines_removed += changes // 2
                    except ValueError:
                        pass

        # Areas affected
        ds.areas = list({f.split("/")[0] for f in ds.files_changed if "/" in f})

        # Security check
        all_text = " ".join(ds.files_changed).lower()
        ds.security_relevant = any(p in all_text for p in _SECURITY_PATTERNS)

        # Large change
        ds.is_large = (ds.lines_added + ds.lines_removed) > 200

        return ds

    def _remember_commit(self, p: GitPerception) -> None:
        """Store the perceived commit in memory."""
        from .models import MemoryEntry, MemorySource
        entry = MemoryEntry(
            content=(
                f"Git commit in {p.repo}: '{p.commit.message}' by {p.commit.author}. "
                f"Changed {len(p.diff.files_changed)} files "
                f"(+{p.diff.lines_added}/-{p.diff.lines_removed}). "
                f"Areas: {', '.join(p.diff.areas)}"
            ),
            source=MemorySource.AGENT,
            provenance_chain=[f"git:{p.repo}"],
        )
        try:
            self._store.save_memory(entry)
        except Exception as e:
            log.debug("Failed to save git memory: %s", e)
