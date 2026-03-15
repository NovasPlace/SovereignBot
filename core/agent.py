"""Sovereign — Core: Main agent loop.

The entry point for all agent work. Receives an IncomingMessage,
runs it through the full pipeline, and returns a response.

Pipeline:
  1. Sanitize incoming message (InputCleanse)
  2. Build session context from memory
  3. Planner → list[Action]
  4. For each action: ApprovalGate → Executor
  5. Synthesize response
  6. Log to TRACE (when integrated)
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Callable, Optional

from ..channels.base import IncomingMessage
from ..memory.session import SessionContext
from ..models import Action, ActionType, MemoryEntry, MemorySource, TrustTier
from ..security.audit import AuditEvent, get_audit
from ..security.dna import get_dna_manager
from ..security.trust import TrustViolation
from ..skills.cleanse import InputCleanse
from ..store import get_store
from ..brain import Brain
from ..skillsets.router import SkillsetRouter
from ..cleanser import ResponseCleanser

from .approver import ApprovalGate, ApprovalTimeout
from .executor import Executor, ExecutionAborted, ExecutionError
from .planner import Planner, PlannerError

log = logging.getLogger("sovereign.core.agent")


class SovereignAgent:
    """The sovereign agent. Receive a message, plan, gate, execute, respond.

    This class is intentionally thin — it orchestrates the components
    but contains zero business logic itself. All logic lives in the
    component it delegates to.

    Usage:
        agent = SovereignAgent(llm_fn=my_chat_fn, send_fn=my_send_fn)
        await agent.handle(incoming_message)
    """

    def __init__(
        self,
        llm_fn: Callable,
        send_fn: Callable,
        skill_registry: Optional[dict] = None,
        session_id: str = "default",
        available_skills: Optional[list] = None,
        intelligence_router=None,   # IntelligenceRouter | None
        onboarding=None,            # OnboardingManager | None
        heartbeat=None,             # Heartbeat | None
        emotion_engine=None,        # EmotionEngine | None
        persona_engine=None,        # PersonaEngine | None
        soul=None,                  # SoulLayer | None
        notifications=None,         # NotificationSystem | None
        dreams=None,                # DreamCycle | None
        delegation=None,            # DelegationRouter | None
        task_queue=None,            # TaskQueue | None
        proprioception=None,        # Proprioception | None
        temporal=None,              # TemporalPerception | None
        vision=None,                # VisionSystem | None
        channels=None,              # OutputChannels | None
        membrane=None,              # Membrane | None
        quarantine=None,            # QuarantineSystem | None
    ) -> None:
        self._llm = llm_fn
        self._router = intelligence_router  # if set, used instead of _llm directly
        self._onboarding = onboarding
        self._heartbeat = heartbeat
        self._emotion = emotion_engine
        self._persona = persona_engine
        self._soul = soul
        self._notifs = notifications
        self._dreams = dreams
        self._delegation = delegation
        self._task_queue = task_queue
        self._proprioception = proprioception
        self._temporal = temporal
        self._vision = vision
        self._channels = channels
        self._membrane = membrane
        self._quarantine = quarantine
        self._send = send_fn
        self._session_id = session_id
        self._current_user_id: str = session_id  # updated per-message in handle()
        self._store = get_store()
        self._audit = get_audit()
        self._dna_mgr = get_dna_manager()

        self._dna_mgr.issue(session_id)
        log.info("Sovereign agent initialized: session=%s skills=%d",
                 session_id, len(available_skills or []))

        # ApprovalGate send_prompt reads self._current_user_id at call-time
        # (not at construction time) — avoids the 'default' closure bug
        self._planner = Planner(
            llm_fn=llm_fn,
            available_skills=available_skills or [],
        )

        self._gate = ApprovalGate(
            send_prompt=lambda text: self._send(self._current_user_id, text),
            session_id=session_id,
        )

        self._executor = Executor(
            dna_manager=self._dna_mgr,
            session_id=session_id,
            skill_registry=skill_registry or {},
        )

        # Rolling conversation history — feeds prior turns to LLM as context
        self._session = SessionContext(max_tokens=2048)

        # Brain — genome-loaded prompt assembly with skillset frameworks
        self._brain = Brain()  # uses default genome; can pass genome_path for custom
        self._skillset_router = SkillsetRouter(store=self._store)
        self._cleanser = ResponseCleanser()

    async def handle(self, msg: IncomingMessage) -> str:
        """Process a user message end-to-end. Returns the response text."""
        # Track the real user ID so ApprovalGate + IntelligenceRouter use correct user
        self._current_user_id = msg.user_id
        uid = str(msg.user_id)

        # First-contact detection — one-time flashbulb memory per new user
        if self._onboarding:
            try:
                from ..onboarding import FirstContactHandler
                if self._onboarding.is_new_user(uid):
                    fch = FirstContactHandler(self._store)
                    fch.handle(uid, msg.text)
                    log.info("First contact recorded for user=%s", uid)
            except Exception as e:
                log.debug("First contact handler error: %s", e)

        self._audit.log(
            event_type=AuditEvent.SESSION_START,
            actor=msg.user_id,
            outcome="message-received",
            session_id=self._session_id,
            payload={"platform": msg.platform, "text_len": len(msg.text)},
        )

        # 1. IMMUNE SCREENING — full membrane pipeline (replaces raw InputCleanse)
        if self._membrane:
            screening = self._membrane.screen(msg.text, source=f"{msg.platform}:{msg.user_id}")
            clean_text = screening.cleaned

            if screening.action == "block":
                log.warning("MEMBRANE BLOCKED input from user=%s flags=%s",
                            msg.user_id, screening.flags)
                if self._quarantine:
                    self._quarantine.quarantine(
                        "input", msg.user_id, msg.text,
                        f"Blocked: {', '.join(screening.flags)}",
                        screening.flags, screening.threat_score,
                    )
                return "🛡️ That message was blocked by my immune system. It matched a known threat pattern."

            if screening.action == "quarantine":
                log.warning("MEMBRANE QUARANTINED input from user=%s flags=%s",
                            msg.user_id, screening.flags)
                if self._quarantine:
                    self._quarantine.quarantine(
                        "input", msg.user_id, msg.text,
                        f"Quarantined: {', '.join(screening.flags)}",
                        screening.flags, screening.threat_score,
                    )
                return "⚠️ That message was flagged and quarantined for analysis. It looked suspicious."

            if screening.action == "warn":
                log.info("Membrane warning for user=%s: %s", msg.user_id, screening.flags)
        else:
            # Fallback to raw InputCleanse if membrane not available
            cleanse = InputCleanse.sanitize(msg.text, source=f"{msg.platform}:{msg.user_id}")
            clean_text = cleanse.text
            if cleanse.injection_detected:
                log.warning("Injection detected from user=%s", msg.user_id)
                return "⚠️ Your message contained content that was flagged and sanitized."

        # 1a. VOICE — if the message has audio bytes, transcribe it first
        ear = getattr(self, "_ear", None)
        if ear and msg.metadata.get("has_audio"):
            audio_bytes = msg.metadata.get("audio_bytes", b"")
            audio_fmt   = msg.metadata.get("audio_format", "ogg")
            if audio_bytes:
                try:
                    perception = await ear.hear(audio_bytes, uid, fmt=audio_fmt)
                    if perception.text:
                        clean_text = perception.text
                        log.info(
                            "Voice transcription: %r (conf=%.2f emotion=%s)",
                            clean_text[:60], perception.confidence, perception.voice_emotion,
                        )
                    else:
                        # Whisper not installed — tell user gracefully
                        return (
                            "I heard your voice message but don't have a "
                            "speech-to-text engine installed yet. "
                            "Install openai-whisper to enable listening:"
                            " `pip install openai-whisper`"
                        )
                except Exception as exc:
                    log.warning("Voice transcription failed: %s", exc)

        # 1b. VISION — if the message has an image, the organism looks at it
        vision_context = ""
        if self._vision and msg.metadata.get("has_image"):
            image_bytes = msg.metadata.get("image_bytes", b"")
            caption = msg.metadata.get("caption", "")
            if image_bytes:
                try:
                    perception = self._vision.perceive(image_bytes, uid, caption)
                    vision_context = perception.to_prompt_context()
                    # Enrich the clean_text with what the organism saw
                    if perception.extracted_text:
                        clean_text = (
                            f"{caption} [I can see: {perception.summary}. "
                            f"Text in image: {perception.extracted_text[:300]}]"
                        )
                    else:
                        clean_text = f"{caption} [I can see: {perception.summary}]"
                    log.info("Vision perception: %s (type=%s)",
                             perception.summary[:80], perception.image_type)
                except Exception as e:
                    log.warning("Vision processing failed: %s", e)
                    clean_text = caption or "[User sent an image I couldn't process]"

        # 1c. ECONOMY COMMANDS — /economy, /jobs, /bid, /status
        economy = getattr(self, "_economy", None)
        if economy:
            try:
                economy_response = await economy.handle_command(uid, clean_text)
                if economy_response is not None:
                    return economy_response
            except Exception as exc:
                log.warning("Economy command handler failed: %s", exc)

        # 1d. REFLEX CHECK — fires BEFORE the brain, instant response
        if self._soul:
            reflex = self._soul.pre_brain_check(clean_text, uid)
            if reflex and reflex.bypass_brain:
                log.info("Reflex bypass: %s", reflex.reflex_name)
                self._session.add_user(clean_text)
                self._session.add_agent(reflex.text)
                return reflex.text

        # 1c. HAND ROUTING — check if message triggers an autonomous work pipeline
        hand_router = getattr(self, "_hand_router", None)
        hands = getattr(self, "_hands", None)
        if hand_router and hands:
            match = hand_router.match(clean_text)
            if match and match.confidence >= 0.6:
                hand = hands.get(match.hand_name)
                if hand:
                    log.info("Hand matched: %s (confidence=%.2f)", match.hand_name, match.confidence)
                    # Send immediate acknowledgment
                    hand_label = match.hand_name.replace("_", " ").title()
                    ack = f"🤜 Starting **{hand_label}** pipeline..."
                    await self._send(uid, ack)
                    try:
                        result = await self._dispatch_hand(
                            hand, match.hand_name, clean_text,
                            match.workdir, uid,
                        )
                        response = self._format_hand_result(
                            result, match.hand_name, hand_label,
                        )
                    except Exception as e:
                        log.error("Hand execution failed: %s", e)
                        response = f"⚠️ The {hand_label} pipeline hit an error: {e}"

                    self._session.add_user(clean_text)
                    self._session.add_agent(response)

                    # Record as a meaningful interaction
                    if self._soul:
                        self._soul.record_meaningful_interaction(uid, "task_completed")

                    return response

        # 1c. DREAM INSIGHTS — share what the organism dreamed about
        if self._dreams and self._dreams.has_insights():
            insights = self._dreams.get_dream_insights()
            if insights:
                dream_text = "💭 While you were away, I had some thoughts:\n" + "\n".join(
                    f"• {i.content}" for i in insights
                )
                # Prepend to response later, don't interrupt flow
                self._session.add_agent(dream_text)
                try:
                    await self._send(uid, dream_text)
                except Exception:
                    pass

        # 2. Retrieve session context from memory
        context = self._get_session_context(clean_text)

        # 3. Plan
        try:
            plan_result = await self._planner.plan(
                user_message=clean_text,
                session_context=context,
            )
        except PlannerError as e:
            log.error("Planner failed: %s", e)
            # Fallback: ask LLM directly for a conversational reply
            return await self._conversational_reply(clean_text)

        # If planner can't match a skill, route to conversational reply.
        # This covers both clarification_needed AND empty plan — the LLM
        # handles conversational messages, greetings, questions naturally.
        if not plan_result or (
            isinstance(plan_result, dict) and plan_result.get("clarification_needed")
        ):
            return await self._conversational_reply(clean_text)

        actions: list[Action] = plan_result
        results: list[dict] = []

        # 4. Gate + execute each action in sequence
        for action in actions:
            try:
                action = await self._gate.check(action)
            except ApprovalTimeout:
                await self._send(self._session_id,
                                 f"Action `{action.action_id}` timed out and was rejected.")
                continue

            if not action.is_approved:
                await self._send(self._session_id,
                                 f"Action `{action.action_id}` was rejected.")
                continue

            try:
                result = await self._executor.execute(action)
                results.append(result)
            except ExecutionAborted as e:
                log.warning("Action aborted: %s", e)
                results.append({"output": f"Aborted: {e}", "success": False})
            except ExecutionError as e:
                log.error("Action failed: %s", e)
                results.append({"output": f"Failed: {e}", "success": False})

        # Emotion detection — feed the organism's mood
        if self._emotion:
            emo, intensity = self._emotion.detector.detect(msg.text)
            self._emotion.process_emotion(emo, intensity)

        # Persona learning — adapt to user's communication style
        if self._persona:
            self._persona.learn(uid, msg.text)

        # 5. Synthesize response
        if not results:
            # All actions aborted/rejected — fall back to conversation
            reply = await self._conversational_reply(clean_text)
        else:
            reply = await self._synthesize_with_llm(actions, results, clean_text)

        # 6. Store in rolling session + long-term memory
        self._session.add_user(clean_text)
        self._session.add_agent(reply)
        self._remember_interaction(clean_text, reply)

        # 6b. Feed the soul — topic + emotion observation
        if self._soul:
            topics = self._brain.extract_topics(clean_text)
            emo = self._brain.detect_emotion(clean_text, reply)
            self._soul.observe(uid, clean_text, topics, emo)

        return reply

    async def _conversational_reply(self, user_text: str) -> str:
        """Direct LLM reply using Brain-assembled prompt with session history."""
        # Detect active skillsets from the message
        active = self._skillset_router.detect(user_text)
        frameworks = self._skillset_router.get_frameworks(active) if active else []

        # Get onboarding context
        phase = "discovery"
        behavior = ""
        if self._onboarding:
            uid = str(self._current_user_id)
            phase = self._onboarding.get_phase(uid)
            behavior = self._onboarding.get_behavior(uid)

        # Get mood state for prompt injection
        mood_str = "neutral"
        if self._emotion:
            mood_str = self._emotion.mood
            system_extras = self._emotion.get_mood_prompt_hint()
        else:
            system_extras = ""

        # Build prompt via Brain
        system = self._brain.build_system_prompt(
            skillset_frameworks=frameworks,
            onboarding_phase=phase,
            onboarding_behavior=behavior,
            mood=mood_str,
        )

        # Append persona adaptation hints
        if self._persona:
            uid = str(self._current_user_id)
            persona = self._persona.get(uid)
            system += "\n\n" + persona.to_prompt_hint()

        # Append mood influence
        if system_extras:
            system += "\n\n" + system_extras

        # Append soul context (relationship, curiosity, conscience)
        if self._soul:
            soul_ctx = self._soul.enrich_prompt(str(self._current_user_id), mood_str)
            if soul_ctx:
                system += "\n\n" + soul_ctx

        # Append body awareness (proprioception)
        if self._proprioception:
            body_hint = self._proprioception.body_state.to_prompt_hint()
            if body_hint:
                system += "\n\n" + body_hint

        # Append temporal awareness
        if self._temporal:
            time_hint = self._temporal.to_prompt_hint()
            if time_hint:
                system += "\n\n" + time_hint

        history = self._session.to_string()
        user_prompt = self._brain.build_user_prompt(
            message=user_text,
            conversation_history=history,
        )

        # ReAct loop: LLM can emit [TOOL:name]args[/TOOL] markers
        # which get executed and fed back until no more tool calls
        self._session.add_user(user_text)
        try:
            reply = await self._react_loop(system, user_prompt)
            self._session.add_agent(reply)
            self._remember_interaction(user_text, reply)
            if active:
                log.debug("Skillsets active: %s", self._skillset_router.get_display_names(active))
            return reply
        except Exception as e:
            log.error("Conversational reply failed: %s", e)
            return "I'm having trouble right now. Please try again."

    _TOOL_PATTERN = re.compile(r"\[TOOL:(\w+)\](.*?)\[/TOOL\]", re.DOTALL)
    _MAX_REACT_ITERATIONS = 5

    async def _react_loop(self, system: str, user_prompt: str) -> str:
        """ReAct loop: detect tool calls in LLM output, execute, feed back."""
        toolbelt = getattr(self, "_toolbelt", None)
        current_prompt = user_prompt

        for iteration in range(self._MAX_REACT_ITERATIONS):
            reply = await self._llm(system=system, user=current_prompt)

            # Check for tool calls
            tool_calls = self._TOOL_PATTERN.findall(reply)
            if not tool_calls or not toolbelt:
                # No tool calls — clean any leftover markers and return
                return self._TOOL_PATTERN.sub("", reply).strip()

            # Execute each tool call
            results: list[str] = []
            for tool_name, tool_args in tool_calls:
                tool_args = tool_args.strip()
                log.info("ReAct tool call: %s(%s)", tool_name, tool_args[:60])
                result = await self._execute_tool(toolbelt, tool_name, tool_args)
                results.append(f"[{tool_name}] {result}")

            # Strip tool markers from the reply to get the reasoning text
            reasoning = self._TOOL_PATTERN.sub("", reply).strip()

            # Build follow-up prompt with tool results
            tool_output = "\n\n".join(results)
            current_prompt = (
                f"{current_prompt}\n\n"
                f"Your previous reasoning: {reasoning}\n\n"
                f"Tool results:\n{tool_output}\n\n"
                "Now synthesize a natural response using the real tool output above. "
                "Do NOT make up data or use placeholder text. Use the actual results. "
                "Do NOT use [TOOL:...] markers again unless you need additional information."
            )

        # Max iterations reached — return last reply cleaned
        return self._TOOL_PATTERN.sub("", reply).strip()

    async def _execute_tool(self, toolbelt, tool_name: str, args: str) -> str:
        """Execute a single tool call and return the result as a string."""
        try:
            if tool_name == "shell":
                result = await toolbelt.shell(args, timeout=30)
                return result.data if result.success else (result.error or "Command failed")

            elif tool_name == "file_read":
                result = await toolbelt.file_read(args.strip())
                if result.success:
                    # Cap output to avoid overwhelming the LLM context
                    return result.data[:3000] if result.data else "(empty file)"
                return result.error or "File not found"

            elif tool_name == "file_write":
                # Format: path\n---\ncontent
                parts = args.split("\n---\n", 1)
                if len(parts) == 2:
                    result = await toolbelt.file_write(parts[0].strip(), parts[1])
                    return "File written successfully" if result.success else (result.error or "Write failed")
                return "Invalid format. Use: path\\n---\\ncontent"

            elif tool_name == "web_search":
                result = await toolbelt.web_search(args)
                return result.data[:2000] if result.success else (result.error or "Search failed")

            elif tool_name == "fetch_url":
                result = await toolbelt.fetch_url(args.strip())
                return result.data[:3000] if result.success else (result.error or "Fetch failed")

            elif tool_name == "memory_recall":
                result = await toolbelt.memory_recall(args)
                return result.data[:2000] if result.success else "No memories found"

            else:
                return f"Unknown tool: {tool_name}"

        except Exception as e:
            log.error("Tool execution failed: %s(%s) → %s", tool_name, args[:40], e)
            return f"Error: {e}"

    def _get_session_context(self, query: str) -> str:
        """Retrieve relevant memories to provide context to the planner.

        Excludes raw agent interaction logs to prevent the bot from
        parroting its own previous responses (feedback loop).
        """
        try:
            memories = self._store.search_memories(query, limit=8)
            if not memories:
                return ""
            # Filter out agent Q&A logs — only keep bootstrap, distill, user sources
            useful = [
                m for m in memories
                if m.get("source") != "agent"
            ]
            if not useful:
                return ""
            return "\n".join(
                f"- [{m['source']}] {m['content'][:200]}"
                for m in useful[:5]
            )
        except Exception:
            return ""

    async def _synthesize_with_llm(
        self,
        actions: list[Action],
        results: list[dict],
        user_message: str,
    ) -> str:
        """Ask the LLM to turn raw skill output into a conversational reply."""
        # Build a context block from all skill results
        skill_outputs = []
        for action, result in zip(actions, results):
            output = result.get("output", "")
            success = result.get("success", True)
            if success and output:
                skill_outputs.append(f"[{action.skill_id}]:\n{output}")
            elif not success:
                skill_outputs.append(f"[{action.skill_id} FAILED]: {output}")

        if not skill_outputs:
            return await self._conversational_reply(user_message)

        # Include recent conversation history
        history = self._session.to_string()
        context_block = "\n\n".join(skill_outputs)

        system = self._brain.build_system_prompt(
            skillset_frameworks=self._skillset_router.get_frameworks(
                self._skillset_router.detect(user_message)
            ),
        )
        user_prompt = ""
        if history:
            user_prompt += f"{history}\n\n"
        user_prompt += f"Skill results:\n{context_block}\n\nUser asked: {user_message}\nSovereign:"

        try:
            return await self._llm(system=system, user=user_prompt)
        except Exception as e:
            log.error("Synthesis LLM call failed: %s", e)
            # Fall back to raw output
            return "\n\n".join(skill_outputs)

    def _synthesize(
        self,
        actions: list[Action],
        results: list[dict],
        user_message: str,
    ) -> str:
        """Raw synthesize fallback (used only when LLM synthesis unavailable)."""
        parts = []
        for action, result in zip(actions, results):
            output = result.get("output", "")
            success = result.get("success", True)
            if not success:
                parts.append(f"\u274c {action.skill_id}: {output}")
            elif output:
                parts.append(output)
            else:
                parts.append(f"\u2705 {action.description}")
        return "\n\n".join(parts) if parts else "Done."

    def _remember_interaction(self, user_text: str, response: str) -> None:
        """Store a topic summary of this interaction in memory.

        Saves distilled topics, NOT raw Q&A pairs, to avoid
        polluting memory context with parroted responses.
        """
        from ..models import MemoryEntry, MemorySource
        # Only save substantive exchanges (skip greetings and short responses)
        if len(user_text.split()) < 5 and len(response.split()) < 20:
            return
        topics = self._brain.extract_topics(user_text)
        topic_str = ", ".join(topics)
        summary = f"Discussed {topic_str}: {user_text[:80]}"
        entry = MemoryEntry(
            content=summary,
            source=MemorySource.AGENT,
            provenance_chain=[f"session:{self._session_id}"],
        )
        try:
            self._store.save_memory(entry)
        except Exception as e:
            log.warning("Failed to store interaction memory: %s", e)

    async def _dispatch_hand(
        self, hand, hand_name: str, message: str, workdir: str, user_id: str,
    ) -> Any:
        """Generic hand dispatch — introspects execute() to map standard args."""
        import inspect
        sig = inspect.signature(hand.execute)
        params = list(sig.parameters.keys())

        kwargs: dict[str, Any] = {}

        # Map the user message to the first positional text arg
        text_params = {
            "description", "query", "problem", "bug_report", "topic",
            "question", "target", "habit", "action", "target_url",
        }
        for pname in params:
            if pname == "self":
                continue
            if pname in text_params:
                kwargs[pname] = message
                break
        else:
            # No recognized text param — try first non-self param
            for pname in params:
                if pname != "self":
                    p = sig.parameters[pname]
                    if p.annotation in (str, inspect.Parameter.empty):
                        kwargs[pname] = message
                        break

        # Map standard kwargs if the hand accepts them
        if "workdir" in params and workdir:
            kwargs["workdir"] = workdir
        if "user_id" in params:
            kwargs["user_id"] = user_id

        # Special case: code_engineer needs a CodeRequest
        if hand_name == "code_engineer":
            try:
                from ..hands.code_engineer import CodeRequest
                return await hand.execute(CodeRequest(
                    description=message,
                    workdir=workdir or ".",
                    user_id=user_id,
                ))
            except Exception:
                pass

        return await hand.execute(**kwargs)

    @staticmethod
    def _format_hand_result(result: Any, hand_name: str, hand_label: str) -> str:
        """Extract a user-friendly response from a hand result object."""
        status = getattr(result, "status", "unknown")
        summary = getattr(result, "summary", "")
        phase = getattr(result, "phase_reached", "")

        # Result-type-specific formatting
        content = getattr(result, "content", "")
        answer = getattr(result, "answer", "")
        plan = getattr(result, "plan", "")

        if status == "success":
            emoji = "✅"
        elif status == "partial":
            emoji = "⚡"
        else:
            emoji = "⚠️"

        parts = [f"{emoji} **{hand_label}** — {summary}" if summary else f"{emoji} **{hand_label}** complete"]

        # Append any rich content
        if content:
            parts.append(str(content)[:2000])
        elif answer:
            parts.append(str(answer)[:2000])
        elif plan:
            parts.append(str(plan)[:2000])

        # Show phase info on non-success
        if status != "success" and phase:
            parts.append(f"_Stopped at phase: {phase}_")

        # Show extra fields if present
        for field in ("files_created", "files_modified", "debug_cycles",
                      "hardening", "test_output", "root_cause"):
            val = getattr(result, field, None)
            if val:
                if isinstance(val, list) and val:
                    parts.append(f"**{field.replace('_', ' ').title()}:** {', '.join(str(v) for v in val)}")
                elif isinstance(val, (int, float)) and val > 0:
                    parts.append(f"**{field.replace('_', ' ').title()}:** {val}")
                elif isinstance(val, str) and val.strip():
                    parts.append(f"**{field.replace('_', ' ').title()}:** {val[:300]}")

        return "\n\n".join(parts)

    def resolve_approval(self, action_id: str, user_response: str) -> None:
        """Call this when the user responds to an approval prompt."""
        self._gate.resolve(action_id, user_response)

