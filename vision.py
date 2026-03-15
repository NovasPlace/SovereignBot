"""Sovereign — Vision System: the organism sees images.

When a user sends a screenshot, photo, or diagram, the organism
processes it through OCR and classification. Vision perceptions become
memories that trigger emotions and activate skillsets.

Uses Tesseract OCR locally when available, falls back to text-only
descriptions.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("sovereign.vision")

_ERROR_PATTERNS = re.compile(
    r"(error|exception|traceback|failed|permission denied|"
    r"not found|timeout|killed|segfault|panic|fatal|crash)",
    re.IGNORECASE,
)


@dataclass
class VisionPerception:
    """What the organism saw."""
    image_type: str = "unknown"
    summary: str = ""
    extracted_text: str = ""
    emotion: str = "neutral"
    importance: float = 0.3
    suggested_skillset: str | None = None

    def to_prompt_context(self) -> str:
        """Inject what the organism saw into the Brain prompt."""
        parts = [
            "## WHAT YOU SEE",
            f"The user sent an image ({self.image_type}).",
            f"Summary: {self.summary}",
        ]
        if self.extracted_text:
            parts.append(f"Extracted text:\n```\n{self.extracted_text[:600]}\n```")
        parts.append(
            "Respond to what you SEE, not just what they said. "
            "If you see an error, diagnose it. If you see code, review it."
        )
        return "\n".join(parts)


class VisionSystem:
    """Processes images from any input channel into cognitive perceptions."""

    def __init__(self, store) -> None:
        self._store = store
        self._ocr_available = self._check_ocr()
        log.info("VisionSystem initialized (OCR=%s)", "yes" if self._ocr_available else "no")

    def perceive(self, image_bytes: bytes, user_id: str, caption: str = "") -> VisionPerception:
        """The organism looks at an image and forms a perception."""
        p = VisionPerception()

        # Step 1: OCR — extract any readable text
        text = self._ocr(image_bytes) if self._ocr_available else ""
        p.extracted_text = text

        # Step 2: Classify based on content
        if text:
            p.image_type = self._classify_from_text(text)
        else:
            p.image_type = "photo"

        # Step 3: Analyze based on type
        if p.image_type == "terminal_error":
            errors = _ERROR_PATTERNS.findall(text)
            p.summary = f"Terminal output with errors: {', '.join(set(e.lower() for e in errors[:5]))}"
            p.importance = 0.85
            p.emotion = "frustration"
            p.suggested_skillset = "devops_sre"
        elif p.image_type == "code":
            lines = len(text.strip().splitlines())
            p.summary = f"Code screenshot ({lines} lines)"
            p.importance = 0.5
            p.emotion = "curiosity"
            p.suggested_skillset = "threat_analyst"
        elif p.image_type == "terminal":
            p.summary = f"Terminal output ({len(text)} chars)"
            p.importance = 0.4
            p.emotion = "neutral"
        elif p.image_type == "document":
            p.summary = f"Document with text ({len(text.split())} words)"
            p.importance = 0.5
            p.emotion = "neutral"
        else:
            p.summary = caption or "Photo received"
            p.importance = 0.3
            p.emotion = "curiosity"

        # Step 4: Store as memory
        self._remember_perception(p, user_id)

        return p

    def _classify_from_text(self, text: str) -> str:
        """Classify image type from OCR text content."""
        lower = text.lower()

        # Terminal with errors?
        if _ERROR_PATTERNS.search(text):
            if any(ind in lower for ind in ["$", ">>>", "root@", "~#", "bash"]):
                return "terminal_error"
            return "terminal_error"

        # Terminal output?
        terminal_indicators = ["$", ">>>", "root@", "~#", "user@", "bash", "pip install"]
        if any(ind in lower for ind in terminal_indicators):
            return "terminal"

        # Code?
        code_indicators = ["def ", "class ", "import ", "function ", "const ", "var ",
                           "return ", "if (", "for (", "while "]
        if sum(1 for ind in code_indicators if ind in text) >= 2:
            return "code"

        # Document with substantial text
        if len(text.split()) > 30:
            return "document"

        return "general"

    def _ocr(self, image_bytes: bytes) -> str:
        """Extract text from image using Tesseract."""
        try:
            from PIL import Image
            import pytesseract
            import io

            img = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(img)
            return text.strip()
        except Exception as e:
            log.debug("OCR failed: %s", e)
            return ""

    def _remember_perception(self, p: VisionPerception, user_id: str) -> None:
        """Store what the organism saw as a memory."""
        from .models import MemoryEntry, MemorySource
        entry = MemoryEntry(
            content=f"Saw image ({p.image_type}): {p.summary}",
            source=MemorySource.AGENT,
            provenance_chain=[f"vision:{user_id}"],
        )
        try:
            self._store.save_memory(entry)
        except Exception as e:
            log.debug("Failed to save vision memory: %s", e)

    @staticmethod
    def _check_ocr() -> bool:
        """Check if Tesseract OCR is available."""
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False
