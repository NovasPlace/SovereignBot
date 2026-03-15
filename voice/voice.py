"""Sovereign — Voice: VoiceSystem (Part 9).

The organism's voice. Converts text responses into spoken audio that
reflects the organism's current emotional state via subtle prosody shifts.

The voice IS the mood made audible — not theatrical, just perceptible.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .tts import TTSEngine

if TYPE_CHECKING:
    pass

log = logging.getLogger("sovereign.voice.voice")

# ── Mood → prosody parameter tables ──────────────────────────────────────────
# speed: speech rate multiplier (1.0 = normal)
# pitch: semitone shift from neutral (0.0 = no shift)
# energy: amplitude modifier
# warmth: low-frequency boost (simulated)
# breathiness: breath noise blend

_MOOD_PARAMS: dict[str, dict[str, float]] = {
    "neutral": {
        "speed": 1.0, "pitch": 0.0, "energy": 0.5,
        "warmth": 0.6, "breathiness": 0.1,
    },
    "vigilant": {
        "speed": 0.92, "pitch": -0.15, "energy": 0.42,
        "warmth": 0.38, "breathiness": 0.05,
    },
    "agitated": {
        "speed": 1.14, "pitch": 0.08, "energy": 0.72,
        "warmth": 0.28, "breathiness": 0.0,
    },
    "exploratory": {
        "speed": 1.06, "pitch": 0.12, "energy": 0.65,
        "warmth": 0.72, "breathiness": 0.18,
    },
    "confident": {
        "speed": 1.0, "pitch": -0.06, "energy": 0.62,
        "warmth": 0.52, "breathiness": 0.0,
    },
    "alert": {
        "speed": 1.1, "pitch": 0.06, "energy": 0.7,
        "warmth": 0.42, "breathiness": 0.05,
    },
    # Mapped from voice emotion → organism state modulations
    "frustration": {
        "speed": 0.96, "pitch": -0.1, "energy": 0.45,
        "warmth": 0.52, "breathiness": 0.0,
    },
    "curiosity": {
        "speed": 1.04, "pitch": 0.1, "energy": 0.58,
        "warmth": 0.68, "breathiness": 0.12,
    },
    "satisfaction": {
        "speed": 0.98, "pitch": 0.0, "energy": 0.52,
        "warmth": 0.72, "breathiness": 0.08,
    },
}
_NEUTRAL = _MOOD_PARAMS["neutral"]


def _blend_params(target: dict, confidence: float) -> dict:
    """Blend target params toward neutral based on confidence.

    Low-confidence moods produce subtle shifts; strong moods are more pronounced.
    confidence=1.0 → full target, confidence=0.0 → neutral.
    """
    return {
        k: _NEUTRAL[k] + (target[k] - _NEUTRAL[k]) * confidence
        for k in target
    }


class VoiceSystem:
    """The organism's voice — Text → spoken audio with mood prosody.

    Usage:
        voice = VoiceSystem(emotion_engine, persona_engine)
        audio_bytes = await voice.speak("Hello!", user_id="123")
    """

    def __init__(
        self,
        emotion_engine=None,
        persona_engine=None,
        tts_backend: str = "edge",
    ) -> None:
        self._emotion = emotion_engine
        self._persona = persona_engine
        self._tts = TTSEngine(backend=tts_backend)

    async def speak(self, text: str, user_id: str = "default") -> bytes:
        """Convert text to spoken audio with mood-appropriate prosody.

        Returns raw audio bytes (MP3/OGG from Edge TTS, or raw PCM from Piper).
        Returns empty bytes b"" if TTS unavailable.
        """
        params = self._compute_params(user_id)
        audio = await self._tts.synthesize(text, **params)
        if audio:
            log.debug(
                "VoiceSystem: spoke %d chars → %d bytes (mood=%s)",
                len(text), len(audio), params.get("_mood_label", "?"),
            )
        params.pop("_mood_label", None)
        return audio

    def _compute_params(self, user_id: str) -> dict:
        """Map current mood + user persona to TTS synthesis parameters."""
        mood_state = "neutral"
        confidence = 0.5

        if self._emotion is not None:
            try:
                mood = self._emotion.current()
                mood_state = getattr(mood, "state", "neutral")
                confidence = getattr(mood, "confidence", 0.5)
            except Exception:
                pass

        # Speed base adjusted by persona verbosity
        speed_base = 1.0
        if self._persona is not None:
            try:
                persona = self._persona.get_persona(user_id)
                verbosity = getattr(persona, "verbosity", 0.5)
                if verbosity < 0.3:
                    speed_base = 1.08   # terse users → slightly faster
                elif verbosity > 0.7:
                    speed_base = 0.94   # verbose users → slightly slower
            except Exception:
                pass

        target = _MOOD_PARAMS.get(mood_state, _NEUTRAL)
        blended = _blend_params(target, confidence)

        # Apply persona speed offset
        blended["speed"] = blended["speed"] * (speed_base / 1.0)

        # Tag for debugging only
        blended["_mood_label"] = mood_state

        return blended
