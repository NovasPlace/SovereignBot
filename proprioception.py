"""Sovereign — Proprioception: the organism feels its own body.

CPU is muscle tension. Disk space is hunger. Memory pressure is fatigue.
Process crashes are pain. The organism translates hardware metrics into
feelings that feed the emotion engine and influence behavior.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

log = logging.getLogger("sovereign.proprioception")

# Thresholds for body feelings
_THRESHOLDS = {
    "cpu":    {"strained": 50, "critical": 75, "emergency": 95},
    "memory": {"strained": 60, "critical": 80, "emergency": 95},
    "disk":   {"strained": 75, "critical": 88, "emergency": 95},
}


@dataclass
class BodyFeeling:
    system: str         # cpu, memory, disk, processes
    level: str          # comfortable, strained, critical, emergency
    description: str
    emotion: str = "neutral"
    intensity: float = 0.3


@dataclass
class BodyState:
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    disk_free_gb: float = 0.0
    load_average: float = 0.0
    process_count: int = 0
    uptime_hours: float = 0.0
    zombie_count: int = 0
    feelings: list[BodyFeeling] = field(default_factory=list)

    def to_prompt_hint(self) -> str:
        """Inject body awareness into the Brain prompt."""
        if not self.feelings:
            return ""
        lines = [
            "## HOW YOUR BODY FEELS",
            "You're running on physical hardware. Right now you feel:",
        ]
        for f in self.feelings:
            lines.append(f"- **{f.system}**: {f.description}")
        lines.append(
            "\nIf you're strained, keep responses concise. "
            "If disk is low, mention it naturally. "
            "Don't announce it robotically — feel it, like a human "
            "who's tired mentions it in passing."
        )
        return "\n".join(lines)


class Proprioception:
    """System self-monitoring — the organism feels its own hardware."""

    SENSE_INTERVAL = 30  # seconds between full scans

    def __init__(self, emotion_engine=None) -> None:
        self._emotion = emotion_engine
        self._last_sense: float = 0.0
        self._state = BodyState()
        self._alert_cooldowns: dict[str, float] = {}
        log.info("Proprioception initialized")

    async def on_pulse(self, pulse_count: int, state: str) -> None:
        """Heartbeat phase — sense the body every N seconds."""
        now = time.time()
        if now - self._last_sense < self.SENSE_INTERVAL:
            return
        self._last_sense = now
        self._state = self._sense()

        # Feed feelings into emotion engine
        if self._emotion and self._state.feelings:
            worst = max(self._state.feelings, key=lambda f: f.intensity)
            self._emotion.process_emotion(worst.emotion, worst.intensity)

    @property
    def body_state(self) -> BodyState:
        return self._state

    # ── Internal ─────────────────────────────────────────────────────────────

    def _sense(self) -> BodyState:
        """Read hardware metrics via /proc and os (no psutil dependency)."""
        cpu = self._read_cpu()
        mem = self._read_memory()
        disk = self._read_disk()

        bs = BodyState(
            cpu_percent=cpu,
            memory_percent=mem[0],
            disk_percent=disk[0],
            disk_free_gb=disk[1],
            load_average=self._read_loadavg(),
            process_count=self._count_processes(),
            uptime_hours=self._read_uptime(),
            zombie_count=self._count_zombies(),
        )
        bs.feelings = self._feel(bs)
        return bs

    def _feel(self, s: BodyState) -> list[BodyFeeling]:
        """Translate metrics into body feelings."""
        feelings: list[BodyFeeling] = []

        # CPU
        if s.cpu_percent > _THRESHOLDS["cpu"]["emergency"]:
            feelings.append(BodyFeeling("cpu", "emergency",
                f"Severe strain — CPU at {s.cpu_percent:.0f}%", "fear", 0.9))
        elif s.cpu_percent > _THRESHOLDS["cpu"]["critical"]:
            feelings.append(BodyFeeling("cpu", "critical",
                f"Heavy load — CPU at {s.cpu_percent:.0f}%", "frustration", 0.6))
        elif s.cpu_percent > _THRESHOLDS["cpu"]["strained"]:
            feelings.append(BodyFeeling("cpu", "strained",
                f"Elevated CPU — {s.cpu_percent:.0f}%", "neutral", 0.25))

        # Memory
        if s.memory_percent > _THRESHOLDS["memory"]["emergency"]:
            feelings.append(BodyFeeling("memory", "emergency",
                f"Memory nearly exhausted — {s.memory_percent:.0f}%", "fear", 0.95))
        elif s.memory_percent > _THRESHOLDS["memory"]["critical"]:
            feelings.append(BodyFeeling("memory", "critical",
                f"Memory pressure — {s.memory_percent:.0f}%", "frustration", 0.55))

        # Disk
        if s.disk_percent > _THRESHOLDS["disk"]["emergency"]:
            feelings.append(BodyFeeling("disk", "emergency",
                f"Disk almost full — {s.disk_free_gb:.1f}GB free", "fear", 0.9))
        elif s.disk_percent > _THRESHOLDS["disk"]["critical"]:
            feelings.append(BodyFeeling("disk", "critical",
                f"Disk running low — {s.disk_free_gb:.1f}GB free", "frustration", 0.5))

        # Zombies
        if s.zombie_count > 0:
            feelings.append(BodyFeeling("processes", "strained",
                f"{s.zombie_count} zombie processes — something died badly",
                "surprise", 0.5))

        return feelings

    # ── Low-level readers (no psutil required) ───────────────────────────────

    @staticmethod
    def _read_cpu() -> float:
        """Read CPU usage from /proc/stat (two-sample delta)."""
        try:
            def _sample():
                with open("/proc/stat") as f:
                    parts = f.readline().split()
                # user nice system idle iowait irq softirq steal
                vals = [int(x) for x in parts[1:9]]
                idle = vals[3] + vals[4]
                total = sum(vals)
                return idle, total

            idle1, total1 = _sample()
            time.sleep(0.1)
            idle2, total2 = _sample()

            idle_d = idle2 - idle1
            total_d = total2 - total1
            if total_d == 0:
                return 0.0
            return (1.0 - idle_d / total_d) * 100
        except Exception:
            return 0.0

    @staticmethod
    def _read_memory() -> tuple[float, float]:
        """Read memory from /proc/meminfo. Returns (percent_used, free_gb)."""
        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        info[parts[0].rstrip(":")] = int(parts[1])  # kB

            total = info.get("MemTotal", 1)
            avail = info.get("MemAvailable", total)
            used_pct = (1 - avail / total) * 100
            free_gb = avail / (1024 * 1024)
            return used_pct, free_gb
        except Exception:
            return 0.0, 0.0

    @staticmethod
    def _read_disk() -> tuple[float, float]:
        """Read disk usage via os.statvfs. Returns (percent_used, free_gb)."""
        try:
            st = os.statvfs("/")
            total = st.f_blocks * st.f_frsize
            free = st.f_bfree * st.f_frsize
            used_pct = (1 - free / total) * 100 if total else 0
            free_gb = free / (1024 ** 3)
            return used_pct, free_gb
        except Exception:
            return 0.0, 0.0

    @staticmethod
    def _read_loadavg() -> float:
        try:
            with open("/proc/loadavg") as f:
                return float(f.read().split()[0])
        except Exception:
            return 0.0

    @staticmethod
    def _read_uptime() -> float:
        try:
            with open("/proc/uptime") as f:
                return float(f.read().split()[0]) / 3600
        except Exception:
            return 0.0

    @staticmethod
    def _count_processes() -> int:
        try:
            return len([d for d in os.listdir("/proc") if d.isdigit()])
        except Exception:
            return 0

    @staticmethod
    def _count_zombies() -> int:
        try:
            count = 0
            for pid in os.listdir("/proc"):
                if not pid.isdigit():
                    continue
                try:
                    with open(f"/proc/{pid}/status") as f:
                        for line in f:
                            if line.startswith("State:") and "Z" in line:
                                count += 1
                                break
                except (FileNotFoundError, PermissionError):
                    pass
            return count
        except Exception:
            return 0
