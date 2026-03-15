"""Sovereign — Response Cleanser.

Strips tracking characters, watermarks, hidden payloads, and prompt
injection attempts from both incoming user text and outgoing cloud
LLM responses. Trust nothing that comes from outside.
"""
from __future__ import annotations

import re
import logging

log = logging.getLogger("sovereign.cleanser")

# Zero-width and invisible Unicode characters to strip
_INVISIBLE_CHARS = frozenset([
    '\u200b',  # zero-width space
    '\u200c',  # zero-width non-joiner
    '\u200d',  # zero-width joiner
    '\u200e',  # left-to-right mark
    '\u200f',  # right-to-left mark
    '\u2060',  # word joiner
    '\u2061',  # function application
    '\u2062',  # invisible times
    '\u2063',  # invisible separator
    '\u2064',  # invisible plus
    '\ufeff',  # byte order mark
    '\u00ad',  # soft hyphen
    '\u034f',  # combining grapheme joiner
    '\u061c',  # arabic letter mark
    '\u180e',  # mongolian vowel separator
])

_INVISIBLE_RE = re.compile('[' + ''.join(_INVISIBLE_CHARS) + ']')

# Exotic whitespace to normalize
_EXOTIC_SPACES = [
    '\u00a0', '\u2000', '\u2001', '\u2002', '\u2003',
    '\u2004', '\u2005', '\u2006', '\u2007', '\u2008',
    '\u2009', '\u200a', '\u202f', '\u205f', '\u3000',
]

# Prompt injection patterns (case-insensitive)
_INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"ignore all prior",
    r"disregard.*system prompt",
    r"you are now",
    r"new instructions:",
    r"SYSTEM:",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[INST\]",
    r"\[\/INST\]",
]
_INJECTION_RE = re.compile(
    '|'.join(_INJECTION_PATTERNS),
    re.IGNORECASE,
)


class ResponseCleanser:
    """Full sanitization pipeline for text entering or leaving the organism."""

    def __init__(self) -> None:
        self._injection_count = 0

    def full_cleanse(self, text: str) -> str:
        """Complete cleanse pipeline for cloud LLM responses."""
        text = self.strip_invisible(text)
        text = self.strip_embedded_instructions(text)
        text = self.normalize_whitespace(text)
        return text.strip()

    def sanitize_input(self, text: str) -> str:
        """Cleanse user input — strip invisible chars, detect injection."""
        cleaned = self.strip_invisible(text)
        if _INJECTION_RE.search(cleaned):
            self._injection_count += 1
            log.warning(
                "Prompt injection attempt #%d detected in input",
                self._injection_count,
            )
            cleaned = _INJECTION_RE.sub("[BLOCKED]", cleaned)
        return cleaned.strip()

    def sanitize_skill_output(self, result: dict) -> dict:
        """Cleanse skill execution output before it enters the organism."""
        if isinstance(result.get("text"), str):
            result["text"] = self.full_cleanse(result["text"])
        if isinstance(result.get("output"), str):
            result["output"] = self.full_cleanse(result["output"])
        return result

    @staticmethod
    def strip_invisible(text: str) -> str:
        """Remove zero-width and invisible Unicode characters."""
        return _INVISIBLE_RE.sub('', text)

    @staticmethod
    def strip_embedded_instructions(text: str) -> str:
        """Remove hidden instructions that might be embedded in responses."""
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        text = re.sub(r'\[//\]:\s*#.*$', '', text, flags=re.MULTILINE)
        return text

    @staticmethod
    def normalize_whitespace(text: str) -> str:
        """Replace exotic whitespace with standard spaces."""
        for sp in _EXOTIC_SPACES:
            text = text.replace(sp, ' ')
        return text

    @property
    def injection_count(self) -> int:
        return self._injection_count
