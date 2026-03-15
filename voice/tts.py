"""Sovereign — Voice: TTS Engine (Part 9).

Multi-backend text-to-speech. Uses edge-tts by default (free, async,
no model download required). Falls back gracefully if backend unavailable.

Backends:
  edge  — Microsoft Edge TTS via edge-tts library (default, free)
  piper — Local Piper TTS (requires piper + ONNX model)
"""
from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger("sovereign.voice.tts")

# Default TTS voice — consistent identity across all interactions
EDGE_VOICE_MALE = "en-US-GuyNeural"
EDGE_VOICE_FEMALE = "en-US-JennyNeural"


class TTSEngine:
    """Text-to-speech engine with configurable backend.

    Usage:
        engine = TTSEngine(backend="edge")
        audio_bytes = await engine.synthesize("Hello world", speed=1.0, pitch=0.0)
    """

    def __init__(self, backend: str = "edge", voice: str | None = None) -> None:
        self.backend = backend
        self._voice = voice or os.environ.get("SOVEREIGN_TTS_VOICE", EDGE_VOICE_MALE)
        self._edge_available: bool | None = None

    async def synthesize(
        self,
        text: str,
        speed: float = 1.0,
        pitch: float = 0.0,
        energy: float = 0.5,
        warmth: float = 0.5,
        breathiness: float = 0.1,
    ) -> bytes:
        """Convert text to audio bytes (OGG/MP3).

        Returns empty bytes if synthesis fails — callers must handle this.
        """
        if not text.strip():
            return b""

        try:
            if self.backend == "piper":
                audio = await self._piper_synthesize(text, speed, pitch)
            else:
                audio = await self._edge_synthesize(text, speed, pitch)

            if audio:
                log.debug("TTS: synthesized %d chars → %d bytes", len(text), len(audio))
            return audio

        except Exception as exc:
            log.warning("TTS synthesis failed (%s): %s", self.backend, exc)
            return b""

    async def _edge_synthesize(self, text: str, speed: float, pitch: float) -> bytes:
        """Edge TTS — Microsoft free cloud TTS via edge-tts library."""
        if self._edge_available is False:
            return b""

        try:
            import edge_tts  # type: ignore
        except ImportError:
            if self._edge_available is None:
                log.warning(
                    "edge-tts not installed — TTS disabled. "
                    "Install: pip install edge-tts"
                )
            self._edge_available = False
            return b""

        self._edge_available = True

        # Convert speed (multiplier) → Edge rate string (e.g. "+10%" or "-5%")
        rate_pct = int((speed - 1.0) * 100)
        rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"

        # Convert pitch (semitone delta) → Edge pitch string
        pitch_hz = int(pitch * 20)  # 1.0 → +20Hz
        pitch_str = f"+{pitch_hz}Hz" if pitch_hz >= 0 else f"{pitch_hz}Hz"

        communicate = edge_tts.Communicate(
            text,
            voice=self._voice,
            rate=rate_str,
            pitch=pitch_str,
        )

        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])

        return b"".join(chunks)

    async def _piper_synthesize(self, text: str, speed: float, pitch: float) -> bytes:
        """Piper TTS — local, fast, runs on CPU."""
        piper_model = os.environ.get(
            "SOVEREIGN_PIPER_MODEL", "en_US-lessac-medium.onnx"
        )

        length_scale = round(1.0 / max(speed, 0.1), 3)

        proc = await asyncio.create_subprocess_exec(
            "piper",
            "--model", piper_model,
            "--output-raw",
            "--length-scale", str(length_scale),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        stdout, _ = await proc.communicate(text.encode())
        return stdout if proc.returncode == 0 else b""

    def is_available(self) -> bool:
        """Non-blocking availability check based on cached state."""
        if self.backend == "piper":
            return True  # presence of binary checked at runtime
        return self._edge_available is not False  # assume available until proven otherwise
