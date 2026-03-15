"""Sovereign — Voice Layer (Part 9).

Gives the organism ears (speech-to-text) and a voice (text-to-speech).
The voice reflects the organism's internal mood — subtle prosody shifts that
the listener feels without consciously noticing.
"""
from .ear import EarSystem, HearingPerception, WhisperLocal, VoiceEmotionDetector
from .voice import VoiceSystem
from .tts import TTSEngine

__all__ = [
    "EarSystem",
    "HearingPerception",
    "WhisperLocal",
    "VoiceEmotionDetector",
    "VoiceSystem",
    "TTSEngine",
]
