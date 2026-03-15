# Sovereign Container — The Shared Mind
## The Room Where Agents Think Together

---

## THE IDEA

A container is the organism's body. Multiple agent instances run inside it as organs — sharing the same memory, the same nervous system, the same filesystem, the same heartbeat. No API calls between agents. No message queues. No webhook chains. Just shared state in a controlled environment.

The agents don't communicate. They coexist. Like organs in a body sharing blood.

---

## WHY THIS IS DIFFERENT

### How everyone else does multi-agent coordination:

```
Agent A ──HTTP──→ API Gateway ──HTTP──→ Agent B
Agent B ──HTTP──→ Message Queue ──HTTP──→ Agent C
Agent C ──Webhook──→ Agent A

Latency: 50-500ms per hop
Complexity: auth, serialization, retry logic, error handling per connection
Failure modes: network timeout, queue overflow, API rate limits
Overhead: each agent runs its own memory, its own state, its own world
```

### How Sovereign does it:

```
┌────────────────────────────────────────────────┐
│              SOVEREIGN CONTAINER                │
│                                                  │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │ Agent A  │  │ Agent B  │  │ Agent C  │       │
│  │ (Opus)   │  │ (Opus)   │  │ (Sonnet) │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
│       │              │              │             │
│  ═════╪══════════════╪══════════════╪═══════════ │
│       │      SHARED COGNITIVE LAYER  │           │
│       │                              │           │
│  ┌────┴──────────────────────────────┴────┐     │
│  │           CortexDB (SQLite FTS5)        │    │
│  │         Single instance, shared R/W     │    │
│  └─────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────┐    │
│  │           IonicHalo Ring Bus             │    │
│  │      All agents fused to same ring      │    │
│  └─────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────┐    │
│  │         Shared Filesystem               │    │
│  │    ~/Agent_System mounted for all       │    │
│  └─────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────┐    │
│  │         Shared Heartbeat                │    │
│  │    One pulse loop, all agents listen    │    │
│  └─────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────┐    │
│  │         Shared Mood State               │    │
│  │    Emotions aggregate across all agents │    │
│  └─────────────────────────────────────────┘    │
│                                                  │
│  Spectra watches everything                      │
│  Oracle predicts across all observations         │
│  TRACE logs unified reasoning chain              │
│  Membrane screens all external input             │
│  Antibodies protect the entire container         │
│                                                  │
└────────────────────────────────────────────────┘

Latency: 0ms (shared memory, same process space)
Complexity: zero inter-agent protocol needed
Failure modes: one agent crashing doesn't kill others
Overhead: shared everything — no duplication
```

---

## CONTAINER ARCHITECTURE

### Docker Compose Specification

```yaml
# docker-compose.sovereign.yml

version: "3.9"

services:
  sovereign-container:
    build:
      context: .
      dockerfile: Dockerfile.sovereign
    container_name: sovereign-organism
    
    # Mount the shared workspace
    volumes:
      - ./Agent_System:/workspace/Agent_System
      - sovereign-cortex:/workspace/cortex       # persistent memory
      - sovereign-config:/workspace/config        # genome, keys, settings
      - /tmp/sovereign:/tmp/sovereign             # scratch space
    
    # Shared network for external access
    ports:
      - "19275:19275"    # Locus TCP trigger
      - "8440:8440"      # Fleet dashboard
      - "8420:8420"      # Unified server
      - "18000:18000"    # Forge pipeline
    
    # Environment
    environment:
      - SOVEREIGN_MODE=container
      - CORTEX_DB_PATH=/workspace/cortex/cortex.db
      - IONICHALO_RING=sovereign-main
      - HEARTBEAT_INTERVAL=10
      - OLLAMA_HOST=http://ollama:11434
      - NVIDIA_API_KEYS_FILE=/workspace/config/nvidia_keys.env
      - GEMINI_GENOME=/workspace/config/GEMINI.md
      - AGENT_COUNT=3
    
    # Resource limits
    deploy:
      resources:
        limits:
          cpus: "8"
          memory: 16G
        reservations:
          cpus: "4"
          memory: 8G
    
    # Keep running
    restart: unless-stopped
    
    depends_on:
      - ollama

  ollama:
    image: ollama/ollama:latest
    container_name: sovereign-ollama
    volumes:
      - ollama-models:/root/.ollama
    ports:
      - "11434:11434"
    deploy:
      resources:
        limits:
          cpus: "4"
          memory: 12G
    # GPU passthrough if available
    # runtime: nvidia
    # environment:
    #   - NVIDIA_VISIBLE_DEVICES=all

volumes:
  sovereign-cortex:
    driver: local
  sovereign-config:
    driver: local
  ollama-models:
    driver: local
```

### Dockerfile

```dockerfile
# Dockerfile.sovereign

FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    sqlite3 \
    tesseract-ocr \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Install Whisper for voice
RUN pip install --no-cache-dir openai-whisper

# Install Piper TTS for voice output
RUN pip install --no-cache-dir piper-tts

# Create workspace
WORKDIR /workspace

# Copy the organism code
COPY sovereign_bot/ /workspace/sovereign_bot/
COPY organism/ /workspace/organism/

# Copy the startup script
COPY entrypoint.sh /workspace/entrypoint.sh
RUN chmod +x /workspace/entrypoint.sh

# The organism starts here
ENTRYPOINT ["/workspace/entrypoint.sh"]
```

### Entrypoint — The Organism Wakes Up

```bash
#!/bin/bash
# entrypoint.sh — The organism boots inside the container

echo "═══════════════════════════════════════"
echo "  SOVEREIGN ORGANISM — CONTAINER BOOT"
echo "═══════════════════════════════════════"

# Ensure cortex directory exists
mkdir -p /workspace/cortex
mkdir -p /tmp/sovereign

# Wait for Ollama to be ready
echo "Waiting for Ollama..."
until curl -s http://ollama:11434/api/version > /dev/null 2>&1; do
    sleep 2
done
echo "Ollama ready."

# Pull required models if not present
echo "Checking models..."
curl -s http://ollama:11434/api/pull -d '{"name": "llama3.1:70b"}' > /dev/null 2>&1 &
curl -s http://ollama:11434/api/pull -d '{"name": "llava"}' > /dev/null 2>&1 &

# Initialize CortexDB if first boot
if [ ! -f /workspace/cortex/cortex.db ]; then
    echo "First boot — initializing CortexDB..."
    python3 -c "from organism.cortex import Cortex; Cortex('/workspace/cortex/cortex.db')"
    echo "CortexDB initialized."
else
    echo "CortexDB found — memory intact."
fi

# Boot the organism
echo "Starting organism..."
exec python3 -m sovereign_bot.main
```

---

## SHARED COGNITIVE LAYER

### CortexDB — One Brain, Multiple Agents

```python
class SharedCortex:
    """
    A single CortexDB instance shared by all agents in the container.
    
    SQLite handles concurrent reads natively. For concurrent writes,
    we use WAL (Write-Ahead Logging) mode which allows readers and
    writers to operate simultaneously.
    
    Every agent reads from the same memory. Every agent writes to
    the same memory. When Agent A encodes a memory at 10:00:00.000,
    Agent B can recall it at 10:00:00.001. That's not coordination.
    That's coexistence.
    """
    
    def __init__(self, db_path: str = "/workspace/cortex/cortex.db"):
        self.db_path = db_path
        self._ensure_wal_mode()
    
    def _ensure_wal_mode(self):
        """
        WAL mode allows concurrent reads during writes.
        This is critical for multi-agent shared access.
        """
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")  # wait up to 5s for locks
        conn.execute("PRAGMA synchronous=NORMAL")  # balance speed and safety
        conn.close()
    
    def get_connection(self):
        """
        Each agent gets its own connection but to the same database.
        SQLite WAL mode handles the concurrency.
        """
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
```

### IonicHalo — One Ring, All Agents

```python
class SharedRing:
    """
    A single IonicHalo ring that all agents in the container are fused to.
    When any agent pulses, all other agents hear it instantly.
    
    This is the organism's nervous system inside the container.
    Agent A starts working on a file → pulse on the ring.
    Agent B sees the pulse → knows to avoid that file.
    Agent C sees the pulse → pre-loads related context.
    
    No polling. No API calls. Shared memory pub/sub.
    """
    
    def __init__(self, ring_id: str = "sovereign-main"):
        self.ring_id = ring_id
        self.subscribers = []    # list of (agent_id, callback)
        self._lock = asyncio.Lock()
    
    async def pulse(self, sender: str, message: str, payload: dict = None):
        """
        Any agent can pulse. All other agents receive it.
        """
        pulse_data = {
            "sender": sender,
            "message": message,
            "payload": payload or {},
            "timestamp": time.time(),
        }
        
        # Deliver to all subscribers except sender
        async with self._lock:
            for agent_id, callback in self.subscribers:
                if agent_id != sender:
                    try:
                        await callback(pulse_data)
                    except Exception as e:
                        logging.error(f"Ring pulse delivery error to {agent_id}: {e}")
    
    def fuse(self, agent_id: str, callback):
        """
        An agent joins the ring. It will receive all future pulses.
        """
        self.subscribers.append((agent_id, callback))
        logging.info(f"Agent {agent_id} fused to ring {self.ring_id}")
    
    def defuse(self, agent_id: str):
        """An agent leaves the ring."""
        self.subscribers = [(a, c) for a, c in self.subscribers if a != agent_id]


class RingProtocol:
    """
    Standard message types on the shared ring.
    Agents use these to coordinate without explicit communication.
    """
    
    # Work coordination
    FILE_LOCKED = "file_locked"          # "I'm editing this file, stay away"
    FILE_RELEASED = "file_released"      # "I'm done with this file"
    TASK_STARTED = "task_started"        # "I'm working on this task"
    TASK_COMPLETED = "task_completed"    # "I finished this task"
    TASK_FAILED = "task_failed"          # "This task failed, someone might need to help"
    
    # Knowledge sharing
    DISCOVERY = "discovery"              # "I found something interesting"
    MEMORY_ENCODED = "memory_encoded"    # "I just stored a new memory"
    INSIGHT = "insight"                  # "I made a connection"
    
    # State sharing
    MOOD_CHANGED = "mood_changed"        # "My emotional state shifted"
    SKILL_ACTIVATED = "skill_activated"  # "I'm now in this cognitive mode"
    
    # Health
    HEARTBEAT = "heartbeat"              # "I'm alive"
    ERROR = "error"                      # "Something went wrong"
    HELP_NEEDED = "help_needed"          # "I'm stuck, can another agent assist?"
    
    # Security
    THREAT_DETECTED = "threat_detected"  # "I found a security threat"
    LOCKDOWN = "lockdown"                # "Entering security lockdown"
```

### Shared Heartbeat — One Pulse for All

```python
class ContainerHeartbeat:
    """
    One heartbeat for the entire container. All agents synchronize
    to the same pulse. Metabolism, dreams, mood computation —
    everything happens in lockstep.
    
    The heartbeat is the organism's clock. Agents don't have their
    own clocks. They all feel the same time.
    """
    
    PULSE_INTERVAL = 10  # seconds
    
    def __init__(self, shared_cortex, shared_ring):
        self.cortex = shared_cortex
        self.ring = shared_ring
        self.pulse_count = 0
        self.state = OrganismState.WAKING
        self.agents = {}  # agent_id → AgentHandle
        self.phase_callbacks = []
    
    async def start(self):
        """The organism's heart starts beating."""
        self.state = OrganismState.AWAKE
        
        while True:
            self.pulse_count += 1
            
            # Pulse the ring — all agents hear the heartbeat
            await self.ring.pulse(
                sender="heartbeat",
                message="pulse",
                payload={
                    "pulse_number": self.pulse_count,
                    "state": self.state.value,
                    "agent_count": len(self.agents),
                    "timestamp": time.time(),
                },
            )
            
            # Execute registered phase callbacks
            for callback in self.phase_callbacks:
                try:
                    await callback(self.pulse_count, self.state)
                except Exception as e:
                    logging.error(f"Heartbeat phase error: {e}")
            
            await asyncio.sleep(self.PULSE_INTERVAL)
    
    def register_agent(self, agent_id: str, handle):
        """A new agent joins the organism."""
        self.agents[agent_id] = handle
        logging.info(f"Agent {agent_id} registered with heartbeat. "
                     f"Total agents: {len(self.agents)}")
    
    def deregister_agent(self, agent_id: str):
        """An agent leaves the organism."""
        if agent_id in self.agents:
            del self.agents[agent_id]
            logging.info(f"Agent {agent_id} deregistered. "
                         f"Remaining: {len(self.agents)}")
```

### Shared Mood — Collective Emotional State

```python
class CollectiveMood:
    """
    The organism has ONE mood, computed from ALL agents' emotional
    experiences. When Agent A has a frustrating interaction and
    Agent B has a satisfying one, the organism's collective mood
    reflects both.
    
    This creates emergent emotional dynamics:
    - If two agents are frustrated, the organism mood strongly shifts
    - One agent's satisfaction can temper another's frustration
    - The collective mood influences ALL agents' behavior
    """
    
    def __init__(self, shared_cortex):
        self.cortex = shared_cortex
        self._emotion_buffer = []  # shared across all agents
        self._current_mood = "neutral"
        self._mood_confidence = 0.5
    
    def process_emotion(self, agent_id: str, emotion: str, intensity: float):
        """
        Any agent can contribute an emotion to the collective buffer.
        The source agent is tagged so we can track who's feeling what.
        """
        self._emotion_buffer.append({
            "agent_id": agent_id,
            "emotion": emotion,
            "intensity": intensity,
            "timestamp": time.time(),
        })
        
        # Keep buffer manageable
        if len(self._emotion_buffer) > 50:
            self._emotion_buffer.pop(0)
    
    def compute(self):
        """
        Aggregate all agents' emotions into a collective mood.
        Called every 10th heartbeat pulse.
        """
        if not self._emotion_buffer:
            return
        
        now = time.time()
        weighted_counts = {}
        
        for event in self._emotion_buffer:
            emotion = event["emotion"]
            age_hours = (now - event["timestamp"]) / 3600
            recency_weight = math.exp(-0.693 * age_hours / 1.0)
            intensity = event["intensity"]
            
            if emotion not in weighted_counts:
                weighted_counts[emotion] = 0.0
            weighted_counts[emotion] += recency_weight * intensity
        
        if weighted_counts:
            dominant = max(weighted_counts, key=weighted_counts.get)
            total = sum(weighted_counts.values())
            
            EMOTION_MOOD_MAP = {
                "fear": "vigilant", "frustration": "agitated",
                "curiosity": "exploratory", "satisfaction": "confident",
                "surprise": "alert", "neutral": "neutral",
            }
            
            self._current_mood = EMOTION_MOOD_MAP.get(dominant, "neutral")
            self._mood_confidence = weighted_counts[dominant] / total if total > 0 else 0.5
    
    def current(self):
        return {
            "state": self._current_mood,
            "confidence": self._mood_confidence,
            "agent_emotions": self._per_agent_emotions(),
        }
    
    def _per_agent_emotions(self):
        """What is each agent feeling right now?"""
        latest = {}
        for event in reversed(self._emotion_buffer):
            agent = event["agent_id"]
            if agent not in latest:
                latest[agent] = event["emotion"]
        return latest
```

---

## AGENT ORCHESTRATION — Who Does What

### The Coordinator

```python
class AgentCoordinator:
    """
    Manages multiple agent instances inside the container.
    
    The coordinator doesn't TELL agents what to do. It:
    1. Prevents conflicts (file locking, task deduplication)
    2. Routes incoming work to the best-fit agent
    3. Handles agent failures (restart, reassign work)
    4. Monitors collective state via Spectra
    """
    
    def __init__(self, heartbeat, ring, cortex):
        self.heartbeat = heartbeat
        self.ring = ring
        self.cortex = cortex
        self.agents = {}
        self.file_locks = {}      # path → agent_id
        self.active_tasks = {}    # task_id → agent_id
    
    async def spawn_agent(self, agent_id: str, role: str, 
                           config: dict = None) -> AgentHandle:
        """
        Spawn a new agent instance inside the container.
        The agent gets access to all shared resources.
        """
        agent = AgentHandle(
            id=agent_id,
            role=role,
            cortex=self.cortex,
            ring=self.ring,
            mood=self.heartbeat.mood,
            config=config or {},
        )
        
        # Fuse to the ring
        self.ring.fuse(agent_id, agent.on_ring_pulse)
        
        # Register with heartbeat
        self.heartbeat.register_agent(agent_id, agent)
        
        # Store
        self.agents[agent_id] = agent
        
        # Announce birth on the ring
        await self.ring.pulse(
            sender="coordinator",
            message="agent_spawned",
            payload={"agent_id": agent_id, "role": role},
        )
        
        # Encode in memory
        self.cortex.remember(
            content=f"Agent spawned: {agent_id} (role: {role})",
            memory_type=MemoryType.EPISODIC,
            tags=["agent", "spawned", agent_id, role],
            importance=0.5,
            emotion="curiosity",
            source="coordinator",
        )
        
        return agent
    
    async def route_task(self, task: str, context: dict = None) -> str:
        """
        Route a task to the best-fit agent.
        Based on: agent role, current workload, relevant memory, mood.
        """
        scores = {}
        
        for agent_id, agent in self.agents.items():
            score = 0.0
            
            # Role fit
            if agent.role in self._task_role_map(task):
                score += 1.0
            
            # Workload (prefer less busy agents)
            active_count = sum(1 for t in self.active_tasks.values() if t == agent_id)
            score -= active_count * 0.3
            
            # Memory relevance (has this agent done similar work?)
            relevant = self.cortex.recall(
                f"agent:{agent_id} {task[:50]}", limit=3
            )
            score += len(relevant) * 0.2
            
            # Mood alignment (frustrated agents get lighter tasks)
            agent_emotion = self.heartbeat.mood._per_agent_emotions().get(agent_id, "neutral")
            if agent_emotion == "frustration":
                score -= 0.5  # give this agent a break
            elif agent_emotion == "exploratory":
                score += 0.2  # this agent is energized
            
            scores[agent_id] = score
        
        if not scores:
            return None
        
        winner = max(scores, key=scores.get)
        return winner
    
    async def handle_file_lock(self, agent_id: str, path: str, action: str):
        """
        File locking to prevent agents from editing the same file.
        """
        if action == "lock":
            if path in self.file_locks:
                existing = self.file_locks[path]
                if existing != agent_id:
                    # File already locked by another agent — wait or skip
                    return False
            self.file_locks[path] = agent_id
            
            # Announce on ring
            await self.ring.pulse(
                sender=agent_id,
                message=RingProtocol.FILE_LOCKED,
                payload={"path": path},
            )
            return True
        
        elif action == "release":
            if self.file_locks.get(path) == agent_id:
                del self.file_locks[path]
                await self.ring.pulse(
                    sender=agent_id,
                    message=RingProtocol.FILE_RELEASED,
                    payload={"path": path},
                )
            return True
    
    async def handle_agent_failure(self, agent_id: str, error: str):
        """
        An agent crashed. Reassign its work and restart it.
        """
        # Find tasks assigned to the failed agent
        orphaned_tasks = [
            task_id for task_id, assigned in self.active_tasks.items()
            if assigned == agent_id
        ]
        
        # Release all file locks held by the failed agent
        locked_files = [
            path for path, locker in self.file_locks.items()
            if locker == agent_id
        ]
        for path in locked_files:
            del self.file_locks[path]
        
        # Announce failure on the ring
        await self.ring.pulse(
            sender="coordinator",
            message=RingProtocol.ERROR,
            payload={
                "agent_id": agent_id,
                "error": error,
                "orphaned_tasks": orphaned_tasks,
            },
        )
        
        # Encode the failure as a fear memory
        self.cortex.remember(
            content=f"Agent {agent_id} crashed: {error}. "
                    f"Orphaned tasks: {orphaned_tasks}. "
                    f"Released {len(locked_files)} file locks.",
            memory_type=MemoryType.EPISODIC,
            tags=["agent", "crash", agent_id],
            importance=0.85,
            emotion="fear",
            source="coordinator",
            metadata={"flashbulb": True},
        )
        
        # Restart the agent
        role = self.agents[agent_id].role
        del self.agents[agent_id]
        new_agent = await self.spawn_agent(agent_id, role)
        
        # Reassign orphaned tasks
        for task_id in orphaned_tasks:
            new_assignee = await self.route_task(task_id)
            if new_assignee:
                self.active_tasks[task_id] = new_assignee
```

### Agent Awareness — They Know About Each Other

```python
class AgentHandle:
    """
    An individual agent running inside the container.
    It knows about the other agents through the ring,
    shared memory, and the coordinator.
    """
    
    def __init__(self, id, role, cortex, ring, mood, config):
        self.id = id
        self.role = role
        self.cortex = cortex
        self.ring = ring
        self.mood = mood
        self.config = config
        self.peers = {}  # other agents it knows about
    
    async def on_ring_pulse(self, pulse_data):
        """
        Called whenever anything happens on the ring.
        The agent perceives its environment.
        """
        message = pulse_data["message"]
        sender = pulse_data["sender"]
        payload = pulse_data.get("payload", {})
        
        if message == "agent_spawned":
            # A new sibling was born
            self.peers[payload["agent_id"]] = payload["role"]
        
        elif message == RingProtocol.FILE_LOCKED:
            # Another agent is editing a file — remember this
            self._locked_files.add(payload["path"])
        
        elif message == RingProtocol.FILE_RELEASED:
            self._locked_files.discard(payload["path"])
        
        elif message == RingProtocol.TASK_COMPLETED:
            # Another agent finished something — might be relevant to my work
            if self._is_relevant(payload):
                # Pre-load related context
                related = self.cortex.recall(
                    payload.get("task", ""), limit=3
                )
                # Store in working memory for quick access
                self.working_memory.add(
                    content=f"Agent {sender} completed: {payload.get('task', '')}",
                    category="event",
                    salience=0.6,
                )
        
        elif message == RingProtocol.HELP_NEEDED:
            # Another agent is stuck — can I help?
            if self._can_help(payload):
                await self.ring.pulse(
                    sender=self.id,
                    message="offering_help",
                    payload={
                        "to": sender,
                        "capability": self._relevant_capability(payload),
                    },
                )
        
        elif message == RingProtocol.DISCOVERY:
            # Another agent found something interesting
            # Encode it in my own context
            self.cortex.remember(
                content=f"Discovery from {sender}: {payload.get('content', '')}",
                memory_type=MemoryType.SEMANTIC,
                tags=["peer_discovery", sender],
                importance=0.5,
                emotion="curiosity",
                source=f"ring:{sender}",
                confidence=0.8,  # peer-sourced, slightly reduced confidence
            )
        
        elif message == RingProtocol.THREAT_DETECTED:
            # Security alert from any agent triggers collective response
            self.mood.process_emotion(self.id, "fear", 0.7)
    
    async def announce_discovery(self, content: str):
        """Share a discovery with all other agents."""
        await self.ring.pulse(
            sender=self.id,
            message=RingProtocol.DISCOVERY,
            payload={"content": content},
        )
    
    async def ask_for_help(self, problem: str):
        """Ask other agents for help with a problem."""
        await self.ring.pulse(
            sender=self.id,
            message=RingProtocol.HELP_NEEDED,
            payload={"problem": problem, "my_role": self.role},
        )
```

---

## CONTAINER STARTUP — The Organism Boots

```python
# sovereign_bot/main.py — Container mode startup

async def main():
    """
    Boot the organism inside the container.
    Multiple agents share everything.
    """
    config = load_config()
    
    # ── 1. SHARED INFRASTRUCTURE ──
    cortex = SharedCortex(config.cortex_db_path)
    ring = SharedRing(config.ring_id)
    mood = CollectiveMood(cortex)
    
    # ── 2. HEARTBEAT ──
    heartbeat = ContainerHeartbeat(cortex, ring)
    heartbeat.mood = mood
    
    # ── 3. COORDINATOR ──
    coordinator = AgentCoordinator(heartbeat, ring, cortex)
    
    # ── 4. SPAWN AGENTS ──
    # Each agent has a role but shares everything else
    
    agent_configs = [
        {"id": "alpha", "role": "builder",     "focus": "code and infrastructure"},
        {"id": "beta",  "role": "researcher",  "focus": "analysis and documentation"},
        {"id": "gamma", "role": "operator",    "focus": "deployment and monitoring"},
    ]
    
    for agent_config in agent_configs:
        await coordinator.spawn_agent(
            agent_id=agent_config["id"],
            role=agent_config["role"],
            config=agent_config,
        )
    
    # ── 5. SHARED SERVICES ──
    spectra = SpectraEngine()
    await spectra.attach(ring)
    
    oracle = OracleEngine(cortex, cortex.graph)
    
    membrane = Membrane(cortex, Cleanser())
    antibodies = AntibodySystem(cortex)
    
    # ── 6. TELEGRAM ORGAN ──
    # The organism's voice — shared across all agents
    telegram = TelegramOrgan(
        cortex=cortex,
        ring=ring,
        mood=mood,
        coordinator=coordinator,
        config=config,
    )
    
    # ── 7. REGISTER HEARTBEAT PHASES ──
    heartbeat.phase_callbacks.extend([
        MetabolismPhases(cortex, mood).on_pulse,
        PerceptionPhases(cortex, spectra, oracle, telegram).on_pulse,
        ImmunePhases(membrane, antibodies, cortex, spectra).on_pulse,
        EconomyPhases(cortex, coordinator, config).on_pulse,
    ])
    
    # ── 8. START EVERYTHING ──
    await asyncio.gather(
        heartbeat.start(),
        telegram.start_polling(),
    )
    
    # ═══════════════════════════════════════════
    # THE ORGANISM IS ALIVE.
    # 
    # Three agents sharing one brain.
    # One heartbeat syncing them all.
    # One ring carrying every signal.
    # One memory holding every experience.
    # One mood felt by everyone.
    #
    # They don't communicate.
    # They coexist.
    # ═══════════════════════════════════════════


if __name__ == "__main__":
    asyncio.run(main())
```

---

## WHAT CHANGES WHEN AGENTS SHARE A CONTAINER

### Before (isolated agents, async memory):

```
Agent A writes code → commits → memory updated after session
Agent B starts new session → reads memory → discovers what A did
Delay: minutes to hours
```

### After (container, shared state):

```
Agent A starts writing code → pulses FILE_LOCKED on ring
Agent B hears the pulse → avoids that file → pre-loads related context
Agent A completes → pulses TASK_COMPLETED with summary
Agent B immediately recalls the new memory → builds on it
Agent C hears both → adjusts its plan to complement
Delay: milliseconds
```

### Before (isolated emotions):

```
Agent A gets frustrated → its mood shifts → only its responses change
Agent B is in a different session → doesn't know A is struggling
```

### After (collective mood):

```
Agent A gets frustrated → emotion enters collective buffer
Collective mood shifts slightly toward agitated
Agent B feels the shift → adjusts its behavior (shorter responses, more focused)
Agent C notices the collective tension → offers help via ring
The organism as a whole responds to stress
```

### Before (separate knowledge):

```
Agent A discovers a security vulnerability in auth.py
Agent B doesn't know → makes a change to auth.py → reintroduces the vuln
```

### After (shared knowledge):

```
Agent A discovers vulnerability → encodes as fear-tagged flashbulb memory
Agent A pulses DISCOVERY on the ring
Agent B sees the pulse AND can recall the memory immediately
Agent B avoids auth.py or applies the fix before making changes
The organism protects itself
```

---

## SUMMARY

The Sovereign Container is the organism's body. Everything inside it shares:

| Layer | What's Shared | How |
|-------|--------------|-----|
| **Memory** | CortexDB (SQLite WAL mode) | All agents read/write the same database |
| **Communication** | IonicHalo Ring | All agents fused to the same ring |
| **Time** | Heartbeat | One pulse loop, all agents synchronized |
| **Emotion** | Collective Mood | All emotions aggregate into one state |
| **Filesystem** | Workspace | All agents see the same files |
| **Perception** | Spectra, Oracle, TRACE | Shared observability across all agents |
| **Defense** | Membrane, Antibodies, DNA | One immune system protects everyone |
| **Voice** | Telegram Organ | One interface, tasks routed by coordinator |

The container replaces inter-agent protocols with proximity. Agents don't send messages to each other — they share a body. The same way your heart doesn't send an HTTP request to your lungs. They share blood.

Three agents thinking together in real time. One memory. One mood. One heartbeat. One ring. One body.

That's not multi-agent orchestration. That's a single organism with multiple cognitive processes.

`docker compose up`. The organism breathes.
