"""Sovereign — Voice: Ear System (Part 9).

The organism's ears. Converts spoken audio into text that enters the
normal message pipeline. Also detects emotional state from the voice itself.

Two components:
  WhisperLocal  — speech-to-text using openai-whisper (optional dep)
  VoiceEmotionDetector — heuristic emotion classification from audio features
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass

log = logging.getLogger("sovereign.voice.ear")


# ── Pydantic models ────────────────────────────────────────────────────────────

class VoiceEmotion(BaseModel):
    emotion: str = "neutral"   # frustration | surprise | curiosity | satisfaction | neutral
    intensity: float = 0.3     # 0.0-1.0


class TranscriptionResult(BaseModel):
    text: str = ""
    confidence: float = 0.8
    language: str = "en"
    segments: list = Field(default_factory=list)


class HearingPerception(BaseModel):
    text: str = ""
    confidence: float = 0.0
    language: str = "en"
    duration: float = 0.0
    voice_emotion: str = "neutral"
    voice_intensity: float = 0.3
    source: str = ""
    is_partial: bool = False


# ── Whisper local STT ─────────────────────────────────────────────────────────

class WhisperLocal:
    """Local Whisper model for sovereign speech-to-text.

    Lazy-loads openai-whisper on first use. Falls back gracefully
    if not installed — callers must handle None return.
    """

    WHISPER_AVAILABLE = None  # None = not checked yet

    def __init__(self, model_size: str = "base") -> None:
        self.model_size = model_size
        self._model = None

    async def _ensure_loaded(self) -> bool:
        """Load Whisper model if available. Returns True if ready."""
        if self._model is not None:
            return True
        if WhisperLocal.WHISPER_AVAILABLE is False:
            return False

        loop = asyncio.get_event_loop()
        try:
            import whisper  # type: ignore
            self._model = await loop.run_in_executor(
                None, lambda: whisper.load_model(self.model_size)
            )
            WhisperLocal.WHISPER_AVAILABLE = True
            log.info("Whisper %s model loaded", self.model_size)
            return True
        except ImportError:
            WhisperLocal.WHISPER_AVAILABLE = False
            log.warning(
                "openai-whisper not installed — local STT disabled. "
                "Install: pip install openai-whisper"
            )
            return False

    async def transcribe(
        self, audio_bytes: bytes, fmt: str = "ogg"
    ) -> TranscriptionResult | None:
        """Transcribe audio bytes. Returns None if Whisper unavailable."""
        if not await self._ensure_loaded():
            return None

        loop = asyncio.get_event_loop()
        with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name

        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._model.transcribe(  # type: ignore[union-attr]
                    temp_path,
                    language=None,  # auto-detect
                    fp16=False,     # CPU safe
                ),
            )
            segments = result.get("segments", [])
            avg_conf = (
                sum(s.get("avg_logprob", -0.5) for s in segments) / len(segments)
                if segments else -0.5
            )
            # avg_logprob is ≤0; map to 0-1 range (−1 → 0.5, 0 → 1.0)
            confidence = max(0.0, min(1.0, 1.0 + avg_conf))

            return TranscriptionResult(
                text=result["text"].strip(),
                confidence=confidence,
                language=result.get("language", "en"),
                segments=segments,
            )
        finally:
            os.unlink(temp_path)


# ── Voice emotion detection ───────────────────────────────────────────────────

class VoiceEmotionDetector:
    """Detect emotional state from voice audio characteristics.

    Analyzes HOW something is said (pitch, energy, rate) rather
    than what is said. Heuristic rule-based — surprisingly effective
    at catching frustration, excitement, and calm.

    Does NOT analyse word content — stays in signal space only.
    """

    async def analyze(self, audio_bytes: bytes) -> VoiceEmotion:
        """Return emotion + intensity from raw audio bytes."""
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._analyze_sync, audio_bytes
            )
        except Exception as exc:
            log.debug("VoiceEmotionDetector: analysis failed (%s) — neutral", exc)
            return VoiceEmotion(emotion="neutral", intensity=0.3)

    def _analyze_sync(self, audio_bytes: bytes) -> VoiceEmotion:
        import numpy as np  # type: ignore

        # Try wav format first; Telegram sends OGG which we may not parse here.
        # If we can't parse, fall through to neutral gracefully.
        try:
            from scipy.io import wavfile  # type: ignore
            sample_rate, data = wavfile.read(io.BytesIO(audio_bytes))
        except Exception:
            # OGG/MP3 etc — try numpy raw float32 fallback
            try:
                import numpy as np
                data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
                sample_rate = 16000
            except Exception:
                return VoiceEmotion(emotion="neutral", intensity=0.3)

        if len(data.shape) > 1:
            data = data.mean(axis=1)
        data = data.astype(np.float32)

        rms = float(np.sqrt(np.mean(data ** 2)))
        if rms < 1e-6:
            return VoiceEmotion(emotion="neutral", intensity=0.2)

        # Normalise
        data_norm = data / (np.max(np.abs(data)) + 1e-8)

        # Crude energy (relative volume)
        energy = min(1.0, rms / 5000.0)

        # Zero-crossing rate as speech-rate proxy
        zcr = float(np.mean(np.abs(np.diff(np.sign(data_norm)))) * 0.5)
        rate = min(1.0, zcr / 0.3)

        # Pitch proxy via spectral centroid of abs values
        abs_data = np.abs(data_norm)
        centroid = float(np.sum(np.arange(len(abs_data)) * abs_data) / (np.sum(abs_data) + 1e-8))
        pitch = min(1.0, centroid / (len(abs_data) * 0.3))

        return self._classify(energy, rate, pitch)

    @staticmethod
    def _classify(energy: float, rate: float, pitch: float) -> VoiceEmotion:
        # High energy + high pitch + fast → frustration or excitement
        if energy > 0.65 and pitch > 0.55 and rate > 0.6:
            emotion = "frustration" if pitch > 0.75 else "surprise"
            return VoiceEmotion(emotion=emotion, intensity=round(min(1.0, energy * 1.1), 2))

        # Low energy + slow → calm / sadness
        if energy < 0.25 and rate < 0.35:
            return VoiceEmotion(emotion="neutral", intensity=0.2)

        # High pitch variance + moderate energy → curiosity
        if 0.3 < energy < 0.65 and pitch > 0.5:
            return VoiceEmotion(emotion="curiosity", intensity=round(energy, 2))

        # High energy + low pitch → satisfied confidence
        if energy > 0.55 and pitch < 0.4:
            return VoiceEmotion(emotion="satisfaction", intensity=round(energy * 0.9, 2))

        return VoiceEmotion(emotion="neutral", intensity=0.3)


# ── Ear System ────────────────────────────────────────────────────────────────

class EarSystem:
    """The organism's ears.

    Converts spoken audio into a HearingPerception that also carries
    the emotional tone detected from the voice itself.
    """

    def __init__(self, store=None, emotion_engine=None) -> None:
        self._store = store
        self._emotion = emotion_engine
        self._whisper = WhisperLocal(model_size="base")
        self._emotion_detector = VoiceEmotionDetector()

    async def hear(
        self,
        audio_bytes: bytes,
        user_id: str,
        fmt: str = "ogg",
    ) -> HearingPerception:
        """Hear spoken audio. Returns HearingPerception with text + voice emotion."""
        perception = HearingPerception()

        # ── TRANSCRIBE ──────────────────────────────────────────────────────
        result = await self._whisper.transcribe(audio_bytes, fmt)
        if result and result.text:
            perception.text = result.text
            perception.confidence = result.confidence
            perception.language = result.language
            perception.source = "whisper_local"
            log.info(
                "EarSystem: transcribed %d bytes → %r (conf=%.2f)",
                len(audio_bytes), perception.text[:60], perception.confidence,
            )
        else:
            # Whisper not available — leave text empty
            # The caller (agent/telegram) can tell the user to install it
            perception.source = "unavailable"
            log.warning("EarSystem: no STT available — returning empty transcription")

        # ── VOICE EMOTION ───────────────────────────────────────────────────
        voice_emotion = await self._emotion_detector.analyze(audio_bytes)
        perception.voice_emotion = voice_emotion.emotion
        perception.voice_intensity = voice_emotion.intensity

        # Feed voice emotion into the emotion engine if available
        if self._emotion is not None:
            try:
                self._emotion.process_emotion(voice_emotion.emotion, voice_emotion.intensity)
            except Exception:
                pass

        # ── MEMORY ─────────────────────────────────────────────────────────
        if self._store is not None and perception.text:
            try:
                from ..memory.cortex import MemoryType
                self._store.remember(
                    content=f"Heard (voice) from {user_id}: {perception.text[:200]}",
                    memory_type=MemoryType.EPISODIC,
                    tags=[f"user:{user_id}", "voice", "heard"],
                    importance=0.5,
                    emotion=voice_emotion.emotion,
                    source="ear_system",
                    metadata={
                        "transcription_confidence": perception.confidence,
                        "voice_emotion": voice_emotion.emotion,
                        "voice_intensity": voice_emotion.intensity,
                        "language": perception.language,
                    },
                )
            except Exception:
                pass

        return perception
