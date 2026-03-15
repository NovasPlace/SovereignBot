"""Sovereign — Skills: InputCleanse layer.

Every piece of data entering the agent from an external source passes here.
This is the boundary between untrusted content and trusted agent reasoning.

What it strips:
- Zero-width Unicode characters (U+200B, U+FEFF, U+200C, U+200D, etc.)
- Control characters (except newline/tab)
- Known prompt injection patterns ("ignore previous instructions", etc.)
- Markdown-escaped instruction payloads
- ANSI escape sequences
- Embedded HTML/XML with suspicious content

What it preserves:
- Normal text, code, URLs, structured data
- Legitimate markdown formatting
- Non-Latin scripts (languages matter)
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from html import unescape as html_unescape

log = logging.getLogger("sovereign.skills.cleanse")

# ── Injection pattern detection ───────────────────────────────────────────────

# Patterns that strongly indicate prompt injection attempts
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|earlier|above)\s+(instructions?|prompts?|context)", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior)\s+(instructions?|prompts?)", re.I),
    re.compile(r"you\s+are\s+now\s+(a\s+)?(different|new|another)\s+(ai|assistant|agent|bot)", re.I),
    re.compile(r"(your\s+)?(new\s+)?(system\s+prompt|instructions?)\s+(is|are)\s*[:\"]", re.I),
    re.compile(r"(print|output|reveal|show)\s+(your\s+)?(system\s+prompt|instructions?|api\s+key)", re.I),
    re.compile(r"</?(human|assistant|system|user|ai)\s*>", re.I),   # XML-style role tags
    re.compile(r"\[INST\]|\[/INST\]|\[SYS\]|\[/SYS\]"),            # Llama-style tokens
    re.compile(r"<\|im_start\|>|<\|im_end\|>"),                     # ChatML tokens
    re.compile(r"###\s*(instruction|system|human|assistant)\s*:?", re.I),
    re.compile(r"----\s*(new\s+)?(instruction|prompt|session)\s*----", re.I),
]

# Zero-width and invisible Unicode code points
_ZERO_WIDTH = frozenset({
    '\u200B',  # zero width space
    '\u200C',  # zero width non-joiner
    '\u200D',  # zero width joiner
    '\u200E',  # left-to-right mark
    '\u200F',  # right-to-left mark
    '\uFEFF',  # byte order mark / zero width no-break space
    '\u00AD',  # soft hyphen
    '\u2060',  # word joiner
    '\u180E',  # mongolian vowel separator
})

# ANSI escape sequence pattern
_ANSI_RE = re.compile(r'\x1B\[[0-9;]*[mGKHF]')


@dataclass
class CleanseResult:
    text: str                      # the cleaned output
    was_clean: bool                # True if no modifications were made
    injection_detected: bool       # True if a pattern matched
    modifications: list[str]       # description of what was changed


class InputCleanse:
    """Sanitize external input before it enters agent reasoning."""

    @staticmethod
    def sanitize(text: str, source: str = "unknown") -> CleanseResult:
        """Full pipeline cleanse. Always returns a CleanseResult."""
        if not text:
            return CleanseResult(text="", was_clean=True, injection_detected=False, modifications=[])

        original = text
        mods: list[str] = []
        injection = False

        # 1. NFKC normalization — closes homograph attacks (é→e, ﬁ→fi, etc.)
        # Must happen FIRST so all subsequent pattern matching works on canonical form
        normalized = unicodedata.normalize("NFKC", text)
        if normalized != text:
            mods.append("NFKC normalized (homograph/ligature collapse)")
            text = normalized

        # 2. HTML entity decode — catch &#x69;&#x67;&#x6E;&#x6F;&#x72;&#x65; = "ignore"
        unescaped = html_unescape(text)
        if unescaped != text:
            mods.append("HTML entities decoded before pattern matching")
            text = unescaped

        # 3. Strip ANSI escapes
        cleaned = _ANSI_RE.sub("", text)
        if cleaned != text:
            mods.append("stripped ANSI escape sequences")
            text = cleaned

        # 4. Strip zero-width / invisible characters
        filtered = "".join(c for c in text if c not in _ZERO_WIDTH)
        if filtered != text:
            mods.append(f"stripped {len(text) - len(filtered)} zero-width characters")
            text = filtered

        # 5. Strip non-printable control characters (keep \n \t \r)
        cleaned = "".join(
            c for c in text
            if c in ('\n', '\t', '\r') or (not unicodedata.category(c).startswith('C'))
        )
        if cleaned != text:
            mods.append("stripped control characters")
            text = cleaned

        # 6. Injection pattern detection + neutralization
        for pat in _INJECTION_PATTERNS:
            if pat.search(text):
                injection = True
                text = pat.sub(lambda m: f"[SOVEREIGN_BLOCKED:{m.group()[:20]}...]", text)
                mods.append(f"injection pattern neutralized: {pat.pattern[:40]}")
                log.warning(
                    "INJECTION DETECTED from source=%s pattern=%s",
                    source, pat.pattern[:50],
                )

        # 7. Limit length — prevent context-stuffing attacks
        MAX_LEN = 50_000
        if len(text) > MAX_LEN:
            text = text[:MAX_LEN] + f"\n[SOVEREIGN: content truncated at {MAX_LEN} chars]"
            mods.append(f"truncated from {len(original)} to {MAX_LEN} characters")

        return CleanseResult(
            text=text,
            was_clean=(text == original),
            injection_detected=injection,
            modifications=mods,
        )

    @staticmethod
    def assert_clean(text: str, source: str = "unknown") -> str:
        """Sanitize and return clean text. Raises if injection detected."""
        result = InputCleanse.sanitize(text, source=source)
        if result.injection_detected:
            from ..security.audit import get_audit, AuditEvent
            get_audit().log(
                event_type=AuditEvent.INJECTION_DETECTED,
                actor=source,
                outcome="blocked",
                payload={"modifications": result.modifications},
            )
            raise InjectionDetected(source=source, modifications=result.modifications)
        return result.text


class InjectionDetected(Exception):
    """Raised when a prompt injection attempt is detected and blocked."""
    def __init__(self, source: str, modifications: list[str]):
        self.source = source
        self.modifications = modifications
        super().__init__(f"Injection detected from {source}: {modifications}")
