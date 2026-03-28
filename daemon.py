"""Sovereign — daemon.py

Main entry point. Boots the agent, connects the Telegram channel,
and runs the event loop until interrupted.

Usage:
    SOVEREIGN_BOT_TOKEN=... python3 -m sovereign.daemon

Environment variables:
    SOVEREIGN_BOT_TOKEN     Telegram bot token (required for Telegram mode)
    SOVEREIGN_ALLOWED_USERS Comma-separated Telegram user IDs (optional, restricts access)
    SOVEREIGN_VAULT_PASS    Vault passphrase (leave blank to skip vault unlock)
    SOVEREIGN_OLLAMA_URL    Ollama base URL (default: http://localhost:11434)
    SOVEREIGN_MODEL         Ollama model name (default: llama3)
    SOVEREIGN_SESSION_ID    Session identifier (default: "default")
    SOVEREIGN_LOG_LEVEL     Log level (default: INFO)
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import pathlib
import signal
import sys

# ── Load .env from sovereign/ package directory ────────────────────────────────
# Supports python-dotenv if installed; falls back to a plain key=value reader.

def _load_env() -> None:
    env_path = pathlib.Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
        return
    except ImportError:
        pass
    # stdlib fallback
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = val.strip()

_load_env()

# ── Logging ────────────────────────────────────────────────────────────────────

log_level = os.environ.get("SOVEREIGN_LOG_LEVEL", "INFO").upper()
_log_fmt = logging.Formatter(
    "%(asctime)s  %(name)-35s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)

# Console handler — shows sovereign.* at configured level
_console = logging.StreamHandler()
_console.setLevel(getattr(logging, log_level, logging.INFO))
_console.setFormatter(_log_fmt)

# File handler — rotating, 5 MB × 3 backups, captures everything at DEBUG
from logging.handlers import RotatingFileHandler
_log_path = pathlib.Path(__file__).parent / "daemon.log"
_file_handler = RotatingFileHandler(
    _log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
)
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(_log_fmt)

logging.root.setLevel(logging.DEBUG)
logging.root.addHandler(_console)
logging.root.addHandler(_file_handler)

# Silence noisy third-party loggers that drown out real signals
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)

log = logging.getLogger("sovereign.daemon")

# ── Imports ────────────────────────────────────────────────────────────────────

from .channels.telegram import TelegramAdapter
from .core.agent import SovereignAgent
from .integrations.vault import get_vault
from .skills.registry import SkillRegistry


# ── LLM adapters ──────────────────────────────────────────────────────────────

def _make_ollama_fn(base_url: str, model: str):
    """Ollama local inference — free, private, no key needed.

    Does NOT force JSON format — the planner handles its own JSON extraction
    with a 3-strategy parser. Conversational replies need natural language.
    """
    try:
        import json as _json
        import urllib.request as _req

        async def _call(system: str, user: str) -> str:
            try:
                payload = _json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    "stream": False,
                }).encode()
                request = _req.Request(
                    f"{base_url}/api/chat",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                loop = asyncio.get_event_loop()
                raw = await loop.run_in_executor(
                    None,
                    lambda: _req.urlopen(request, timeout=60).read(),
                )
                return _json.loads(raw)["message"]["content"]
            except (json.JSONDecodeError, Exception) as exc:
                log.warning("_call: parse failed: %s", exc)
                return None

        return _call
    except (json.JSONDecodeError, Exception) as exc:
        log.warning("_make_ollama_fn: parse failed: %s", exc)
        return None


def _make_ollama_structured_fn(base_url: str, model: str):
    """Ollama structured inference — grammar-constrained via JSON Schema.

    Accepts an optional format_schema dict. When provided, Ollama internally
    generates a GBNF grammar from the schema and constrains token generation
    so the output MUST conform to the schema. No invalid JSON possible.

    When format_schema is None, behaves identically to _make_ollama_fn.

    Usage:
        structured_llm = _make_ollama_structured_fn(url, model)
        result = await structured_llm(system, user, format_schema={...})
    """
    try:
        import json as _json
        import urllib.request as _req

        async def _call(system: str, user: str, format_schema: dict | None = None) -> str:
            try:
                body: dict = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    "stream": False,
                }
                if format_schema is not None:
                    body["format"] = format_schema
                    body["temperature"] = 0.3  # lower temp for structured decisions

                payload = _json.dumps(body).encode()
                request = _req.Request(
                    f"{base_url}/api/chat",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                loop = asyncio.get_event_loop()
                raw = await loop.run_in_executor(
                    None,
                    lambda: _req.urlopen(request, timeout=60).read(),
                )
                return _json.loads(raw)["message"]["content"]
            except (json.JSONDecodeError, Exception) as exc:
                log.warning("_call: parse failed: %s", exc)
                return None

        return _call
    except (json.JSONDecodeError, Exception) as exc:
        log.warning("_make_ollama_structured_fn: parse failed: %s", exc)
        return None


def _make_nim_fn(api_keys: list[str], model: str):
    """NVIDIA NIM inference — GPU-accelerated, OpenAI-compatible API.

    Accepts a list of API keys and rotates through them round-robin
    to distribute load across the pool and avoid per-key rate limits.

    Switch to this by setting in sovereign/.env:
        SOVEREIGN_LLM_PROVIDER=nim
        SOVEREIGN_NIM_API_KEYS=nvapi-key1,nvapi-key2,...
        SOVEREIGN_MODEL=meta/llama-3.1-70b-instruct
    """
    try:
        import json as _json
        import urllib.request as _req
        import itertools
        import threading

        NIM_BASE = "https://integrate.api.nvidia.com/v1"
        _key_cycle = itertools.cycle(api_keys)
        _nim_key_lock = threading.Lock()
        def _next_key() -> str:
            with _nim_key_lock:
                return next(_key_cycle)

        async def _call(system: str, user: str) -> str:
            try:
                api_key = _next_key()
                payload = _json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 768,
                }).encode()
                request = _req.Request(
                    f"{NIM_BASE}/chat/completions",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    method="POST",
                )
                loop = asyncio.get_event_loop()
                raw = await loop.run_in_executor(
                    None,
                    lambda: _req.urlopen(request, timeout=60).read(),
                )
                resp = _json.loads(raw)
                return resp["choices"][0]["message"]["content"]
            except (json.JSONDecodeError, Exception) as exc:
                log.warning("NIM _call failed: %s", exc)
                return None

        return _call
    except (json.JSONDecodeError, Exception) as exc:
        log.warning("_make_nim_fn: parse failed: %s", exc)
        return None


def _make_llm_fn(ollama_url: str, model: str):
    """Factory — returns the right LLM fn based on SOVEREIGN_LLM_PROVIDER env var."""
    provider = os.environ.get("SOVEREIGN_LLM_PROVIDER", "ollama").lower()

    if provider == "nim":
        # Support both comma-separated pool and single key
        keys_raw = os.environ.get("SOVEREIGN_NIM_API_KEYS") or os.environ.get("SOVEREIGN_NIM_API_KEY", "")
        keys = [k.strip() for k in keys_raw.split(",") if k.strip()]
        if not keys:
            log.warning("SOVEREIGN_LLM_PROVIDER=nim but no NIM keys found — falling back to Ollama")
        else:
            nim_model = model if "/" in model else f"meta/{model}"
            log.info("LLM: NVIDIA NIM model=%s keys=%d (round-robin)", nim_model, len(keys))
            return _make_nim_fn(keys, nim_model)

    log.info("LLM: Ollama @ %s model=%s", ollama_url, model)
    return _make_ollama_fn(ollama_url, model)



# ── Main ───────────────────────────────────────────────────────────────────────

async def main(stop_event: asyncio.Event | None = None) -> None:
    # ── Vault ──────────────────────────────────────────────────────────────────
    vault = get_vault()
    vault_pass = os.environ.get("SOVEREIGN_VAULT_PASS", "")
    if vault_pass:
        vault.unlock(vault_pass)
        log.info("Vault unlocked")
    else:
        log.warning("SOVEREIGN_VAULT_PASS not set — vault locked")

    # ── Skill registry + builtin installer ────────────────────────────────────
    from .skills.registry import SkillRegistry
    from .skills.installer import install_builtins
    registry = SkillRegistry()
    installed = install_builtins(registry)
    log.info("Skills ready: %s", installed if installed else ["(none)"])

    # ── LLM ────────────────────────────────────────────────────────────────────
    ollama_url = os.environ.get("SOVEREIGN_OLLAMA_URL", "http://localhost:11434")
    model = os.environ.get("SOVEREIGN_MODEL", "llama3.1:8b-instruct-q4_K_M")
    llm_fn = _make_llm_fn(ollama_url, model)

    # ── Session ────────────────────────────────────────────────────────────────
    session_id = os.environ.get("SOVEREIGN_SESSION_ID", "default")

    # ── Organ bridges ──────────────────────────────────────────────────────────
    from .observability.ionichalo import get_halo_bridge
    from .observability.trace import get_trace_bridge
    from .observability.spectra import get_spectra_bridge

    halo   = get_halo_bridge(session_id=session_id)
    trace  = get_trace_bridge()
    spectra = get_spectra_bridge(session_id=session_id)

    halo.start()          # daemon thread — publishes heartbeats every 30s
    halo.increment("skills_installed", len(installed))
    log.info("Organ bridges initialized (IonicHalo / TRACE / Spectra)")

    # Report initial health to Spectra
    spectra.report_health(1.0, signals=["startup", f"skills={len(installed)}"])

    # ── Telegram ───────────────────────────────────────────────────────────────
    bot_token = os.environ.get("SOVEREIGN_BOT_TOKEN", "")
    if not bot_token:
        log.error("SOVEREIGN_BOT_TOKEN not set. Set it in sovereign/.env and restart.")
        sys.exit(1)

    raw_allowed = os.environ.get("SOVEREIGN_ALLOWED_USERS", "")
    allowed_ids: set[int] | None = None
    if raw_allowed:
        try:
            allowed_ids = {int(uid.strip()) for uid in raw_allowed.split(",") if uid.strip()}
            log.info("Restricting access to %d user(s)", len(allowed_ids))
        except ValueError:
            log.warning("SOVEREIGN_ALLOWED_USERS parse failed — allowing all users")

    # ── Build agent ────────────────────────────────────────────────────────────
    from .channels.telegram import TelegramAdapter
    from .core.agent import SovereignAgent
    from .core.planner import Planner

    channel = TelegramAdapter(bot_token=bot_token, allowed_user_ids=allowed_ids)

    async def send_fn(user_id: str, text: str) -> None:
        await channel.send(user_id, text)

    # Pass the populated skill registry to the planner so it knows what's available
    skill_manifests = [m for m, _ in registry.as_skill_registry_dict().values()]

    # ── Intelligence Router ────────────────────────────────────────────────────
    # Local Ollama is always the base brain. NIM turbo fires based on phase.
    # As Cortex fills with distilled knowledge, turbo ratio naturally fades.
    from .onboarding import OnboardingManager, FirstContactHandler, UserLearningEncoder
    from .knowledge_distiller import KnowledgeDistiller
    from .intelligence_router import IntelligenceRouter
    from .store import get_store

    store = get_store()
    onboarding_mgr = OnboardingManager(store)
    distiller = KnowledgeDistiller(store)

    # Self-knowledge bootstrap — seeds Cortex with identity/architecture facts on first boot
    from .bootstrap import bootstrap_self_knowledge
    bootstrap_self_knowledge(store)

    # Create dedicated local-only and NIM-only LLM functions for the router
    # Local model name may differ from NIM model name (e.g. "llama3.1:8b-instruct-q4_K_M" vs "meta/llama-3.1-70b-instruct")
    local_model = os.environ.get("SOVEREIGN_OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")
    local_llm_fn = _make_ollama_fn(ollama_url, local_model)
    structured_llm_fn = _make_ollama_structured_fn(ollama_url, local_model)
    log.info("IntelligenceRouter local brain: Ollama model=%s (structured=yes)", local_model)
    # NIM keys - router always has access to turbo regardless of provider setting
    _nim_keys_raw = os.environ.get("SOVEREIGN_NIM_API_KEYS") or os.environ.get("SOVEREIGN_NIM_API_KEY", "")
    _nim_keys = [k.strip() for k in _nim_keys_raw.split(",") if k.strip()]
    if _nim_keys:
        nim_model = model if "/" in model else f"meta/{model}"
        turbo_llm_fn = _make_nim_fn(_nim_keys, nim_model)
        log.info("IntelligenceRouter: local=Ollama turbo=NIM(%s) keys=%d", nim_model, len(_nim_keys))
    else:
        turbo_llm_fn = local_llm_fn  # both point to local if no NIM keys
        log.warning("IntelligenceRouter: no NIM keys — turbo = local (degraded)")

    router = IntelligenceRouter(
        local_llm_fn=local_llm_fn,
        turbo_llm_fn=turbo_llm_fn,
        onboarding=onboarding_mgr,
        distiller=distiller,
    )

    # Wrap the router as an llm_fn-compatible async callable
    # The agent calls llm_fn(system=..., user=...) — router.route handles the rest
    # Mutable holder so routed_llm_fn always uses the current message's user_id.
    # Updated by handle() each message — avoids closure capturing a static string.
    _uid_holder: list[str] = [list(allowed_ids)[0] if allowed_ids else "default"]

    async def routed_llm_fn(system: str, user: str) -> str:
        result = await router.route(
            user_id=_uid_holder[0],
            system=system,
            user=user,
        )
        return result.text

    # ── Living Systems ─────────────────────────────────────────────────────────
    from .heartbeat import Heartbeat
    from .emotion import EmotionEngine
    from .persona import PersonaEngine
    from .metabolism import MetabolismPhases
    from .soul import SoulLayer
    from .notifications import NotificationSystem
    from .dreams import DreamCycle
    from .meditation import MeditationCycle
    from .delegation import DelegationRouter

    heartbeat = Heartbeat()
    emotion_engine = EmotionEngine()
    persona_engine = PersonaEngine(store=store)
    metabolism = MetabolismPhases(emotion=emotion_engine)
    heartbeat.register_phase(metabolism.on_pulse)

    soul = SoulLayer(store)

    # Proactive notifications — organism reaches out
    notifs = NotificationSystem(send_fn=send_fn)
    heartbeat.register_phase(lambda state, pulse: notifs.dispatch())

    # Dream cycle — memory consolidation during sleep
    dreams = DreamCycle(store, notification_system=notifs)
    heartbeat.register_phase(dreams.on_pulse)

    # Meditation cycle — auto-triggers on sustained stress (agitated/vigilant mood)
    meditation = MeditationCycle(
        emotion_engine=emotion_engine,
        working_memory=None,  # injected after working_memory organ loads
    )
    heartbeat.register_phase(meditation.on_pulse)

    # Multi-agent delegation — route complex tasks to bigger brains
    delegation = DelegationRouter(turbo_fn=turbo_llm_fn if _nim_keys else None)

    # Autonomous task queue — multi-step projects
    from .taskqueue import TaskQueue
    task_queue = TaskQueue(llm_fn=routed_llm_fn, send_fn=send_fn)
    heartbeat.register_phase(lambda state, pulse: task_queue.tick(state))

    # ── Perception Layer ──────────────────────────────────────────────────────
    from .proprioception import Proprioception
    from .temporal import TemporalPerception
    from .git_awareness import GitAwareness
    from .vision import VisionSystem
    from .output_channels import OutputChannels

    proprioception = Proprioception(emotion_engine=emotion_engine)
    heartbeat.register_phase(proprioception.on_pulse)

    temporal = TemporalPerception(notification_system=notifs)
    heartbeat.register_phase(temporal.on_pulse)

    git_eyes = GitAwareness(store, notification_system=notifs)
    heartbeat.register_phase(git_eyes.on_pulse)

    vision = VisionSystem(store)
    channels = OutputChannels(primary_send_fn=send_fn)

    # ── Immune System ─────────────────────────────────────────────────────────
    from .antibodies import AntibodySystem
    from .membrane import Membrane
    from .quarantine import QuarantineSystem

    antibodies = AntibodySystem()
    membrane = Membrane(store, antibodies=antibodies)
    quarantine = QuarantineSystem(store)

    # Antibodies decay over time — check on heartbeat
    async def _antibody_decay(pulse_count: int, state: str) -> None:
        if pulse_count % 360 == 0:  # every ~hour at 10s pulse
            died = antibodies.decay()
            if died:
                log.info("Antibody decay: %d expired", died)
    heartbeat.register_phase(_antibody_decay)

    agent = SovereignAgent(
        llm_fn=routed_llm_fn,
        send_fn=send_fn,
        skill_registry=registry.as_skill_registry_dict(),
        session_id=session_id,
        available_skills=skill_manifests,
        intelligence_router=router,
        onboarding=onboarding_mgr,
        heartbeat=heartbeat,
        emotion_engine=emotion_engine,
        persona_engine=persona_engine,
        soul=soul,
        notifications=notifs,
        dreams=dreams,
        delegation=delegation,
        task_queue=task_queue,
        proprioception=proprioception,
        temporal=temporal,
        vision=vision,
        channels=channels,
        membrane=membrane,
        quarantine=quarantine,
        soma=None,  # injected after SomaDaemon starts (see below)
    )

    # Grammar-constrained LLM for structured tool-call decisions in the ReAct loop
    agent._structured_llm = structured_llm_fn

    # ── The Hands ─────────────────────────────────────────────────────────────
    from .toolbelt import ToolBelt
    from .work_engine import WorkPlanner, WorkExecutor
    from .hands import (
        # Part 8
        CodeEngineerHand, ResearchHand, DeploymentHand,
        WritingHand, SysAdminHand,
        # Part 11 — Engineering
        APIBuilderHand, DebuggerHand, TestEngineerHand,
        CICDEngineerHand, PerformanceProfilerHand,
        # Part 11 — Data
        DataAnalystHand, DatabaseArchitectHand, ScraperHand,
        # Part 11 — Communication
        EmailOperatorHand, SocialMediaHand, MeetingAssistantHand,
        # Part 11 — Business
        InvoiceHand, CompetitiveIntelHand, SEOOptimizerHand, LegalDrafterHand,
        # Part 11 — Product
        DocumentationHand, DesignSystemHand, OnboardingArchitectHand,
        # Part 12 — Life Skills: Daily
        DailyPlannerHand, HabitTrackerHand, BudgetManagerHand,
        JournalHand, NewsCuratorHand,
        # Part 12 — Life Skills: Growth
        FitnessCoachHand, LearningTutorHand, MealPlannerHand,
        ContentConsumptionHand,
        # Part 12 — Life Skills: Major Life
        TravelPlannerHand, ShoppingAssistantHand, RelationshipManagerHand,
        HomeAutomationHand, RelocationHand, HealthMonitorHand,
    )
    from .hand_router import HandRouter

    tool_belt = ToolBelt(store=store, membrane=membrane)
    work_planner = WorkPlanner(llm_fn=routed_llm_fn)
    work_executor = WorkExecutor(tools=tool_belt, llm_fn=routed_llm_fn)

    # Approval function for hands that need user sign-off
    _hand_approve = getattr(channel, "ask_approval", None)

    hands = {
        # Part 8 originals
        "code_engineer": CodeEngineerHand(
            tools=tool_belt, work_planner=work_planner,
            work_executor=work_executor, llm_fn=routed_llm_fn,
        ),
        "research": ResearchHand(tools=tool_belt, llm_fn=routed_llm_fn),
        "deployment": DeploymentHand(tools=tool_belt, llm_fn=routed_llm_fn),
        "writing": WritingHand(tools=tool_belt, llm_fn=routed_llm_fn,
                               persona_engine=persona_engine),
        "sysadmin": SysAdminHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                  store=store),
        # Part 11 — Engineering
        "api_builder": APIBuilderHand(tools=tool_belt, llm_fn=routed_llm_fn),
        "debugger": DebuggerHand(tools=tool_belt, llm_fn=routed_llm_fn, store=store),
        "test_engineer": TestEngineerHand(tools=tool_belt, llm_fn=routed_llm_fn),
        "cicd": CICDEngineerHand(tools=tool_belt, llm_fn=routed_llm_fn),
        "performance": PerformanceProfilerHand(tools=tool_belt, llm_fn=routed_llm_fn),
        # Part 11 — Data
        "data_analyst": DataAnalystHand(tools=tool_belt, llm_fn=routed_llm_fn),
        "database": DatabaseArchitectHand(tools=tool_belt, llm_fn=routed_llm_fn),
        "scraper": ScraperHand(tools=tool_belt, llm_fn=routed_llm_fn),
        # Part 11 — Communication
        "email": EmailOperatorHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                    send_approval_fn=_hand_approve),
        "social_media": SocialMediaHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                         send_approval_fn=_hand_approve),
        "meeting": MeetingAssistantHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                         temporal=temporal),
        # Part 11 — Business
        "invoice": InvoiceHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                temporal=temporal, send_approval_fn=_hand_approve),
        "competitive": CompetitiveIntelHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                             store=store),
        "seo": SEOOptimizerHand(tools=tool_belt, llm_fn=routed_llm_fn),
        "legal": LegalDrafterHand(tools=tool_belt, llm_fn=routed_llm_fn),
        # Part 11 — Product
        "documentation": DocumentationHand(tools=tool_belt, llm_fn=routed_llm_fn),
        "design_system": DesignSystemHand(tools=tool_belt, llm_fn=routed_llm_fn),
        "onboarding": OnboardingArchitectHand(tools=tool_belt, llm_fn=routed_llm_fn),
        # Part 12 — Life Skills: Daily
        "daily_planner": DailyPlannerHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                           temporal=temporal, store=store),
        "habit_tracker": HabitTrackerHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                          store=store),
        "budget": BudgetManagerHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                     store=store),
        "journal": JournalHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                store=store),
        "news_curator": NewsCuratorHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                         store=store),
        # Part 12 — Life Skills: Growth
        "fitness": FitnessCoachHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                     store=store),
        "learning": LearningTutorHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                       store=store),
        "meal_planner": MealPlannerHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                         store=store),
        "content": ContentConsumptionHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                           store=store),
        # Part 12 — Life Skills: Major Life
        "travel": TravelPlannerHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                     temporal=temporal, store=store,
                                     send_approval_fn=_hand_approve),
        "shopping": ShoppingAssistantHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                           store=store),
        "relationships": RelationshipManagerHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                                  temporal=temporal, store=store),
        "home_auto": HomeAutomationHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                         store=store),
        "relocation": RelocationHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                      temporal=temporal, store=store),
        "health": HealthMonitorHand(tools=tool_belt, llm_fn=routed_llm_fn,
                                     temporal=temporal, store=store),
    }

    hand_router = HandRouter(workdir=os.path.expanduser("~/Desktop/Agent_System"))

    # Pass hands and router into the agent
    agent._hands = hands
    agent._hand_router = hand_router
    agent._toolbelt = tool_belt
    agent._executor._toolbelt = tool_belt  # bypass sandbox for file/shell/web

    # ── Container Code Engineer — Docker-isolated coding agent ────────────────
    # Wraps CodeEngineerHand. Complex tasks (multi-file, "build from scratch", etc.)
    # spin up an ephemeral Docker container running Claude Opus 4.6 with GENOME.md.
    # Simple/medium tasks still run inline via Ollama/NIM. Non-fatal if Docker absent.
    try:
        from .container_agent.orchestrator import ContainerOrchestrator
        from .container_agent.hand_integration import ContainerCodeEngineer
        from pathlib import Path

        _genome_md = Path(__file__).resolve().parent.parent / "GEMINI.md"
        _container_orch = ContainerOrchestrator(
            genome_path=_genome_md if _genome_md.exists() else Path(__file__).resolve().parent / "GENOME.md",
        )
        # Wrap the existing code_engineer hand
        hands["code_engineer"] = ContainerCodeEngineer(
            orchestrator=_container_orch,
            existing_hand=hands["code_engineer"],
            brain=agent._brain,
            telegram_send=send_fn,
        )
        log.info("Container Code Engineer ready — Opus 4.6 on demand (Docker required)")
    except Exception as _ce:
        log.warning("Container Code Engineer skipped (Docker not ready): %s", _ce)

    # ── Connector Ecosystem — external service integrations ───────────────────
    # Loads connectors (GitHub, Discord, Notion, Upwork, Stripe, Linear)
    # Each authenticates via vault credentials. Missing creds = connector skipped.
    try:
        from .connectors.wire import wire_connectors
        from .security.dna import get_dna_manager

        dna = get_dna_manager()
        connector_registry = await wire_connectors(
            toolbelt=tool_belt,
            store=store,
            membrane=membrane,
            trace=trace,
            dna=dna,
            vault=vault,
        )
        agent._connector_registry = connector_registry
        total_actions = sum(len(c.actions) for c in connector_registry.connectors.values())
        log.info(
            "Connector registry ready: %d connectors, %d actions",
            len(connector_registry.connectors), total_actions,
        )
    except Exception as e:
        log.warning("Connector ecosystem skipped: %s", e)
        agent._connector_registry = None

    # ── Organism Embed — fuse Agent_System in-process ──────────────────────────
    # Imports and boots in-process organs (Cortex, IonicHalo, Spectra, Oracle, etc.)
    # and launches managed fleet daemons as supervised subprocesses.
    # Non-fatal: if any organ import fails it logs a warning and skips it.
    from .organism_embed import EmbeddedOrganism
    organism = EmbeddedOrganism()
    embed_ok = await organism.boot()
    if embed_ok:
        agent._organism = organism
        
        # Wire OrgTols to expose organism organs to LLM ToolBelt
        try:
            from .orgtols import register_orgtols
            register_orgtols(tool_belt, organism)
        except Exception as oe:
            log.warning("OrgTol registration failed: %s", oe)
            
        asyncio.create_task(organism.supervise(), name="organism_supervisor")

        # Wire CortexDB binding into toolbelt — with retry since CortexDB
        # may not be ready immediately after the daemon subprocess starts.
        async def _wire_cortexdb_when_ready() -> None:
            from .bindings import CortexDB
            import os
            cortexdb_url = os.environ.get("CORTEXDB_URL", "http://localhost:3456")
            cx = CortexDB(cortexdb_url)
            for attempt in range(12):  # up to 60s of retries
                await asyncio.sleep(5)
                if await cx.ping():
                    if hasattr(agent, "_toolbelt"):
                        agent._toolbelt._cortexdb = cx
                    if hasattr(organism, "__dict__"):
                        organism.cortexdb_api = cx
                    agent._organism = organism
                    log.info("CortexDB wired into memory_recall tool (attempt %d)", attempt + 1)
                    return
            log.warning("CortexDB wiring failed after 12 attempts — memory recall limited to PostgreSQL")

        asyncio.create_task(_wire_cortexdb_when_ready(), name="cortexdb_wire")
        log.info(
            "Organism embedded — %d organs direct in-process access",
            organism.organ_count,
        )
    else:
        log.warning("Organism embed failed — running without in-process organs")
        agent._organism = None

    channel._resolve_fn = agent.resolve_approval
    agent._send_approval = channel.send_approval_prompt  # for web_browse inline buttons
    # Wire organism introspection for /commands
    channel._heartbeat = heartbeat
    channel._meditation = meditation
    channel._hands_dict = hands
    channel._store = store
    channel._proprioception = proprioception
    channel._persona_engine = persona_engine  # for _on_location geolocation storage
    channel._skill_registry = registry         # for /clawhub command
    channel._agent = agent                     # for /fleet organism access

    # ── Evolution System (self-improvement loop) ──────────────────────────────
    try:
        from .container_agent.orchestrator import ContainerOrchestrator
        from .evolution.orchestrator import EvolutionOrchestrator
        from .evolution.patcher import EvolutionPatcher
        from .evolution.failure_collector import FailureCollector

        container_orch = ContainerOrchestrator()
        evo_patcher = EvolutionPatcher()
        failure_collector = FailureCollector()

        evo_orchestrator = EvolutionOrchestrator(
            container_orchestrator=container_orch,
            send_fn=send_fn,
            operator_id=str(_uid_holder[0]),
            patcher=evo_patcher,
            failure_collector=failure_collector,
        )
        channel._evolution_orchestrator = evo_orchestrator

        # Wire heartbeat tick — fires autonomous evolution during idle
        heartbeat.register_phase(evo_orchestrator.heartbeat_tick)

        # Expose failure_collector for error-path hooks anywhere in the daemon
        channel._failure_collector = failure_collector

        log.info(
            "Evolution system wired — /evolve command active | "
            "auto-evolve after %d idle pulses (~%d min)",
            180, 30,
        )
    except Exception as e:
        log.warning("Evolution system unavailable: %s", e)
        channel._evolution_orchestrator = None
        channel._failure_collector = None

    # ── Sovereign Substrate ────────────────────────────────────────────────────
    # Connect to the shared substrate so Sovereign's events appear in the
    # ledger, shared state goes on the blackboard, and the agent shows up
    # in the registry for any other connected agents to see.
    _sub = None
    try:
        import sys as _sys
        _agent_root = pathlib.Path(__file__).resolve().parent.parent
        if str(_agent_root) not in _sys.path:
            _sys.path.insert(0, str(_agent_root))
        from substrate import connect as _substrate_connect
        _sub = _substrate_connect(
            agent_id="sovereign",
            model=os.environ.get("SOVEREIGN_LLM_PROVIDER", "ollama"),
            ide="sovereign",
            axiom_file="sovereign-v1",
            capabilities=["telegram", "browser", "code", "planning"],
        )
        _sub.set_task("Listening on Telegram")
        log.info("Substrate connection established — sovereign is on the grid")
    except Exception as _se:
        log.info("Substrate not available (will run standalone): %s", _se)
        _sub = None
    channel._substrate = _sub

    # ── Soma Daemon (computational proprioception) ─────────────────────────────
    try:
        from .soma_daemon import SomaDaemon
        soma = SomaDaemon(emotion_engine=emotion_engine, store=store)
        soma.start()
        channel._soma = soma
        agent._soma = soma   # inject into agent for prompt context
        log.info("SomaDaemon online — 12-dim somatic state vector active")
    except Exception as e:
        log.warning("SomaDaemon unavailable: %s", e)
        channel._soma = None

    # ── Drift Daemon (configuration integrity) ─────────────────────────────────
    try:
        from .drift_daemon import DriftDaemon
        base_path = pathlib.Path(__file__).parent
        drift = DriftDaemon(base_path=base_path, quarantine_sys=quarantine)
        _ = drift.start()
        log.info("DriftDaemon online — watching critical configuration files for drift")
    except Exception as e:
        log.warning("DriftDaemon unavailable: %s", e)

    # ── Circadian Daemon (metabolic sleep cycles) ──────────────────────────────
    try:
        from .circadian_daemon import CircadianDaemon
        circadian = CircadianDaemon(heartbeat=heartbeat, sleep_start_hour=1, sleep_end_hour=8)
        _ = circadian.start()
        log.info("CircadianDaemon online — biological clock actively throttling metabolism")
    except Exception as e:
        log.warning("CircadianDaemon unavailable: %s", e)

    # ── Organ Bridges (manifest-driven) ─────────────────────────────────────────
    from .organ_manifest import DAEMON_BRIDGES, load_bridge
    _bridges_loaded = 0
    for _bridge_spec in DAEMON_BRIDGES:
        if load_bridge(_bridge_spec, agent, heartbeat, session_id=session_id):
            _bridges_loaded += 1
    log.info("Organ bridges loaded: %d/%d", _bridges_loaded, len(DAEMON_BRIDGES))

    # ── Part 9: Voice Layer ────────────────────────────────────────────────────


    from .voice import EarSystem, VoiceSystem

    ear = EarSystem(store=store, emotion_engine=emotion_engine)
    voice = VoiceSystem(
        emotion_engine=emotion_engine,
        persona_engine=persona_engine,
        tts_backend=os.environ.get("SOVEREIGN_TTS_BACKEND", "edge"),
    )
    agent._ear = ear
    agent._voice = voice
    log.info("Voice layer ready (EarSystem + VoiceSystem)")

    # ── Part 10: Economy Engine ────────────────────────────────────────────────
    from .economy import EconomyEngine

    # Wire approval fns through the Telegram channel
    async def _send_approval_fn(user_id: str, text: str, action_id: str) -> None:
        await channel.send_approval_prompt(user_id, text, action_id)

    async def _wait_approval_fn(action_id: str) -> bool:
        return await agent.wait_for_approval(action_id)

    # Build browser orchestrator for actual Freelancer bid submission
    _browser_orch = None
    try:
        from .browser_agent.orchestrator import BrowserOrchestrator as _BO
        from pathlib import Path as _Path
        _browser_orch = _BO(vault=vault)
        log.info("Browser Agent ready — Playwright+Chromium on demand (Docker required)")
    except Exception as _be:
        log.warning("Browser Agent skipped (Docker not ready): %s", _be)

    economy = EconomyEngine(
        store=store,
        llm_fn=routed_llm_fn,
        membrane=membrane,
        temporal=temporal,
        send_fn=send_fn,
        send_approval_fn=_send_approval_fn,
        wait_approval_fn=_wait_approval_fn,
        hands=hands,
        operator_id=_uid_holder[0],
        vault=vault,
        browser_orchestrator=_browser_orch,
        config={
                "enabled_platforms": [
                    "freelancer",   # active — SOVEREIGN_FREELANCER_KEY set
                    # "upwork",     # pending Upwork key review — uncomment when approved
                    # "github_bounties",
                ],
            },
    )
    agent._economy = economy

    async def _economy_pulse(pulse_count: int, state) -> None:
        await economy.on_pulse(pulse_count, str(state))

    heartbeat.register_phase(_economy_pulse)
    log.info("Economy engine ready (Scout/Bid/Execute/Deliver)")

    # ── Status Dashboard ───────────────────────────────────────────────────────
    from . import dashboard as dash_mod
    dash_mod.wire(
        heartbeat=heartbeat,
        proprioception=proprioception,
        hands=hands,
        store=store,
    )
    asyncio.ensure_future(dash_mod.start_dashboard(port=8800))
    log.info("Status dashboard ready (http://localhost:8800)")

    # ── Webhook System ─────────────────────────────────────────────────────────
    try:
        from . import webhooks as wh_mod
        wh_mod.wire(
            operator_id=int(os.environ.get("SOVEREIGN_ALLOWED_USERS", "0").split(",")[0].strip()),
            agent_inbox=send_fn,
            store=store,
        )
        log.info("Webhook system ready — POST http://localhost:8800/webhook/{slug}")
    except Exception as e:
        log.warning("Webhook system failed to wire: %s", e)

    # ── Cross-Hand Chaining ───────────────────────────────────────────────────
    from .hand_chain import HandChainExecutor
    chain_executor = HandChainExecutor(hands=hands, send_fn=send_fn)
    agent._chain_executor = chain_executor
    log.info("Hand chain executor ready (%d chains)", len(chain_executor.available_chains))

    # ── Proactive Loop — the organism reaches out on its own ──────────────
    from .proactive import ProactiveLoop

    operator_id = str(list(allowed_ids)[0]) if allowed_ids else "0"
    proactive = ProactiveLoop(
        telegram=channel,
        temporal=temporal,
        proprioception=proprioception,
        dreams=dreams,
        emotion=emotion_engine,
        narrative=soul.narrative,
        curiosity=soul.curiosity,
        relationship=soul.relationship,
        store=store,
        llm_fn=routed_llm_fn,
        operator_id=operator_id,
    )
    heartbeat.register_phase(proactive.on_pulse)
    log.info("Proactive loop registered — organism will now initiate contact")

    # ── Autonomous Executor — "go do this" upgrade ─────────────────────────────
    # Wires all 5 autonomy upgrades: persistent task queue, tool verification,
    # action-approval gate, task scratchpad, and hierarchical goal decomposer.
    try:
        from .upgrades.sovereign_adapter import build_executor
        autonomous_executor = build_executor(
            agent=agent,
            send_fn=send_fn,
            operator_id=operator_id,
        )
        agent._autonomous_executor = autonomous_executor

        # Register heartbeat maintenance (expire stale approvals/tasks)
        async def _autonomous_maintenance(pulse_count: int, state) -> None:
            await autonomous_executor.on_heartbeat(pulse_count, str(state))
        heartbeat.register_phase(_autonomous_maintenance)

        # Wire approval gate response handler into the Telegram channel
        # The gate's handle_response is called when an operator replies YES/NO
        _orig_handle = getattr(channel, "_handle_approval_text", None)
        async def _gate_response_interceptor(text: str, user_id: int) -> str | None:
            result = await autonomous_executor.gate.handle_response(text, user_id)
            if result:
                return result
            if _orig_handle:
                return await _orig_handle(text, user_id)
            return None
        channel._gate_response_fn = _gate_response_interceptor

        # Resume any tasks that were mid-execution when the bot last restarted
        async def _resume_interrupted() -> None:
            resumed = await autonomous_executor.resume_on_boot()
            if resumed:
                log.info("Autonomous executor resumed %d interrupted tasks", len(resumed))
        asyncio.create_task(_resume_interrupted(), name="autonomous_resume")

        log.info("Autonomous executor ready (persistent queue, verification, approval gate, scratchpad, decomposer)")
    except Exception as _ae:
        log.warning("Autonomous executor skipped: %s", _ae)
        agent._autonomous_executor = None

    # ── ALEPH Topology Beacon ──────────────────────────────────────────────────
    async def _beacon_heartbeat_loop() -> None:
        import httpx, datetime
        from .aleph.models import BeaconPayload
        from .aleph.routes import NODE_ID, OPERATOR, NODE_URL, CAPABILITIES
        
        sequence_num = 0
        cache = {"corpus_size": 0}
        boot_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        is_local = "localhost" in NODE_URL or "127.0.0.1" in NODE_URL
        if is_local:
            log.info("ALEPH Beacon: Localhost mode (%s) - skipping federated broadcast", NODE_URL)
        else:
            log.info("ALEPH Beacon: Federated mode (%s) - mesh broadcasting active", NODE_URL)
        
        while not stop_event.is_set():
            try:
                sequence_num += 1
                
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        r = await client.post(f"http://localhost:8800/aleph/v1/query", json={"query": "module", "limit": 1})
                        if r.status_code == 200:
                            cache["corpus_size"] = r.json().get("total", 0)
                except Exception:
                    pass
                
                payload = BeaconPayload(
                    node_id=NODE_ID,
                    operator=OPERATOR,
                    endpoint=NODE_URL,
                    capabilities=CAPABILITIES,
                    standing=42, # Fixed rank for bootstrap v0.1
                    corpus_size=cache["corpus_size"],
                    online_since=boot_time,
                    ttl=300,
                    beacon_seq=sequence_num,
                    signature="ed25519:stub"
                )
                
                async with httpx.AsyncClient(timeout=10.0) as client:
                    try:
                        # 1. Update our own local topology (always happens)
                        await client.post(
                            f"http://localhost:8800/aleph/v1/beacon", 
                            json=payload.model_dump()
                        )
                    except Exception as pe:
                        log.debug(f"Beacon local heartbeat failed: %s", pe)
                        
                    # 2. If configured with a public URL, broadcast to the federated mesh
                    if not is_local:
                        try:
                            topo_r = await client.get("http://localhost:8800/aleph/v1/topology")
                            if topo_r.status_code == 200:
                                peers = topo_r.json().get("nodes", [])
                                for peer in peers:
                                    peer_url = peer.get("endpoint")
                                    # Don't beacon to ourselves over the network loop
                                    if peer_url and peer_url != NODE_URL:
                                        try:
                                            await client.post(
                                                f"{peer_url.rstrip('/')}/aleph/v1/beacon", 
                                                json=payload.model_dump()
                                            )
                                            log.debug(f"ALEPH: Announced to peer {peer_url}")
                                        except Exception as fwe:
                                            log.debug(f"ALEPH: Broadcast failed for {peer_url} - {fwe}")
                        except Exception as te:
                            log.debug(f"ALEPH: Topology fetch failed during broadcast - {te}")
                        
            except Exception as e:
                log.error("Beacon heartbeat loop error: %s", e)
                
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=150.0)
            except asyncio.TimeoutError:
                pass

    _beacon_task = asyncio.create_task(_beacon_heartbeat_loop(), name="aleph_beacon")

    # ── Connect and run ────────────────────────────────────────────────────────
    await channel.connect()
    heartbeat.start()  # the organism is now alive
    log.info(
        "Sovereign online — session=%s skills=%d "
        "organs=[IonicHalo,TRACE,Spectra,Heartbeat,Soul,Dreams,TaskQueue,"
        "Senses,Immune,Voice,Economy,Dashboard,Chains,Proactive]",
        session_id, len(installed),
    )

    halo.increment("messages_handled", 0)  # register counter

    async def _receive_loop() -> None:
        async for msg in channel.receive():
            heartbeat.on_user_activity()  # wake the organism
            try:
                _uid_holder[0] = str(msg.user_id)  # update routing context per-message
                response = await agent.handle(msg)
                await channel.send(msg.user_id, response)
            except Exception as exc:
                log.error(
                    "Message handler crashed (user=%s): %s",
                    msg.user_id, exc, exc_info=True,
                )
                try:
                    await channel.send(
                        msg.user_id,
                        "⚠️ Something went wrong processing that message. "
                        "The error has been logged.",
                    )
                except Exception:
                    pass  # don't crash the loop trying to report the crash
            halo.increment("messages_handled")
            spectra.report_health(1.0)  # still healthy after handling a message

    # Race the receive loop against the stop event (SIGINT/SIGTERM)
    _recv_task = asyncio.ensure_future(_receive_loop())
    _stop_task = asyncio.ensure_future(
        (stop_event.wait() if stop_event else asyncio.sleep(1e9))
    )

    try:
        done, pending = await asyncio.wait(
            [_recv_task, _stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Propagate any unexpected exception from receive loop
        for task in done:
            if task is _recv_task and not task.cancelled():
                exc = task.exception()
                if exc:
                    log.error("Receive loop exited with error: %s", exc)
    except asyncio.CancelledError:
        pass
    finally:
        _recv_task.cancel()
        _stop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.gather(_recv_task, _stop_task, return_exceptions=True)
        heartbeat.stop()
        halo.stop()
        await channel.disconnect()
        # Gracefully stop organism — flushes Cortex, stops daemons
        if agent._organism:
            await agent._organism.shutdown()
        log.info("Sovereign shut down cleanly")


def run() -> None:
    """Boot the event loop with a graceful-shutdown signal handler.

    Uses asyncio.Event instead of loop.stop() so signals never yank the
    rug out from under a running coroutine (avoids RuntimeError: Event loop
    stopped before Future completed).
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Catch unhandled exceptions in fire-and-forget coroutines
    # (heartbeat phases, organ bridges, background tasks)
    def _loop_exception_handler(loop, context):
        exc = context.get("exception")
        msg = context.get("message", "Unhandled async exception")
        if exc:
            log.error("Asyncio exception: %s — %s", msg, exc, exc_info=exc)
        else:
            log.error("Asyncio exception: %s", msg)

    loop.set_exception_handler(_loop_exception_handler)

    _stop_event = asyncio.Event()

    def _request_shutdown() -> None:
        log.info("Shutdown signal received — stopping gracefully")
        loop.call_soon_threadsafe(_stop_event.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _request_shutdown)

    try:
        loop.run_until_complete(main(_stop_event))
    except KeyboardInterrupt:
        pass
    finally:
        # Cancel any lingering tasks before closing
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


if __name__ == "__main__":
    run()
