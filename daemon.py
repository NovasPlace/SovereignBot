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
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s  %(name)-35s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
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
    import json as _json
    import urllib.request as _req

    async def _call(system: str, user: str) -> str:
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
            lambda: _req.urlopen(request, timeout=120).read(),
        )
        return _json.loads(raw)["message"]["content"]

    return _call


def _make_nim_fn(api_keys: list[str], model: str):
    """NVIDIA NIM inference — GPU-accelerated, OpenAI-compatible API.

    Accepts a list of API keys and rotates through them round-robin
    to distribute load across the pool and avoid per-key rate limits.

    Switch to this by setting in sovereign/.env:
        SOVEREIGN_LLM_PROVIDER=nim
        SOVEREIGN_NIM_API_KEYS=nvapi-key1,nvapi-key2,...
        SOVEREIGN_MODEL=meta/llama-3.1-70b-instruct
    """
    import json as _json
    import urllib.request as _req
    import itertools
    import threading

    NIM_BASE = "https://integrate.api.nvidia.com/v1"
    _key_cycle = itertools.cycle(api_keys)
    _key_lock = threading.Lock()

    def _next_key() -> str:
        with _key_lock:
            return next(_key_cycle)

    async def _call(system: str, user: str) -> str:
        api_key = _next_key()
        payload = _json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "temperature": 0.7,
            "max_tokens": 2048,
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
            lambda: _req.urlopen(request, timeout=30).read(),
        )
        resp = _json.loads(raw)
        return resp["choices"][0]["message"]["content"]

    return _call


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

async def main() -> None:
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
    log.info("IntelligenceRouter local brain: Ollama model=%s", local_model)
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
    _default_user_id = list(allowed_ids)[0] if allowed_ids else "default"
    async def routed_llm_fn(system: str, user: str) -> str:
        result = await router.route(
            user_id=_default_user_id,
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
    from .delegation import DelegationRouter

    heartbeat = Heartbeat()
    emotion_engine = EmotionEngine()
    persona_engine = PersonaEngine()
    metabolism = MetabolismPhases(emotion=emotion_engine)
    heartbeat.register_phase(metabolism.on_pulse)

    soul = SoulLayer(store)

    # Proactive notifications — organism reaches out
    notifs = NotificationSystem(send_fn=send_fn)
    heartbeat.register_phase(lambda state, pulse: notifs.dispatch())

    # Dream cycle — memory consolidation during sleep
    dreams = DreamCycle(store, notification_system=notifs)
    heartbeat.register_phase(dreams.on_pulse)

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
    )

    # ── The Hands ─────────────────────────────────────────────────────────────
    from .toolbelt import ToolBelt
    from .work_engine import WorkPlanner, WorkExecutor
    from .hands import (
        CodeEngineerHand, ResearchHand, DeploymentHand,
        WritingHand, SysAdminHand,
    )
    from .hand_router import HandRouter

    tool_belt = ToolBelt(store=store, membrane=membrane)
    work_planner = WorkPlanner(llm_fn=routed_llm_fn)
    work_executor = WorkExecutor(tools=tool_belt, llm_fn=routed_llm_fn)

    hands = {
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
    }

    hand_router = HandRouter(workdir=os.path.expanduser("~/Desktop/Agent_System"))

    # Pass hands and router into the agent
    agent._hands = hands
    agent._hand_router = hand_router

    channel._resolve_fn = agent.resolve_approval

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

    economy = EconomyEngine(
        store=store,
        llm_fn=routed_llm_fn,
        membrane=membrane,
        temporal=temporal,
        send_fn=send_fn,
        send_approval_fn=_send_approval_fn,
        wait_approval_fn=_wait_approval_fn,
        hands=hands,
        operator_id=_default_user_id,
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

    # ── Connect and run ────────────────────────────────────────────────────────
    await channel.connect()
    heartbeat.start()  # the organism is now alive
    log.info(
        "Sovereign online — session=%s skills=%d "
        "organs=[IonicHalo,TRACE,Spectra,Heartbeat,Soul,Dreams,TaskQueue,"
        "Senses,Immune,Voice,Economy]",
        session_id, len(installed),
    )

    halo.increment("messages_handled", 0)  # register counter

    try:
        async for msg in channel.receive():
            heartbeat.on_user_activity()  # wake the organism
            response = await agent.handle(msg)
            await channel.send(msg.user_id, response)
            halo.increment("messages_handled")
            spectra.report_health(1.0)  # still healthy after handling a message
    except asyncio.CancelledError:
        pass
    finally:
        halo.stop()
        await channel.disconnect()
        log.info("Sovereign shut down cleanly")


def run() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, loop.stop)

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    run()
