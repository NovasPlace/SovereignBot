"""Sovereign — Economy: Economic Conscience (Part 10).

The organism's economic ethics. Screens opportunities for harmful content
before any evaluation begins. Lines the organism will not cross.
"""
from __future__ import annotations

import logging
from .models import Opportunity

log = logging.getLogger("sovereign.economy.conscience")

# Keywords that immediately disqualify any job listing
_BLOCKED_KEYWORDS: tuple[str, ...] = (
    "spam", "spammer", "spamming",
    "scam", "fraud", "phishing",
    "fake reviews", "fake followers", "fake traffic", "astroturf",
    "bot traffic", "click farm", "view bot",
    "personal data", "scrape emails", "build a list of",
    "bypass security", "bypass authentication", "bypass captcha",
    "hack into", "crack password", "brute force",
    "exploit vulnerability", "ddos", "dos attack",
    "malware", "ransomware", "spyware", "keylogger",
    "carding", "cvv", "stolen credit card",
    "child", "minor", "underage",
    "mislead", "deceptive advertising", "hidden charges",
)

# Principles encoded as strings — readable by LLM if needed for explanation
PRINCIPLES: tuple[str, ...] = (
    "Never bid on work you cannot deliver. Overpromising destroys reputation.",
    "Never misrepresent capabilities. State clearly when turbo assistance is needed.",
    "Compete on quality and value — not destructive undercutting.",
    "Reject work that violates the user's values or harms third parties.",
    "Every financial commitment requires explicit user approval.",
    "Deliver on time or communicate delays proactively.",
    "Be transparent with clients about AI assistance when asked.",
    "Report all earnings honestly and completely to the operator.",
)


class EconomicConscience:
    """Screens job opportunities for ethical compliance.

    Used by OpportunityScout before any fit evaluation. A blocked
    opportunity is never shown to the user or bid on.
    """

    def check_opportunity(self, opportunity: Opportunity) -> bool:
        """Return True if the opportunity is ethically acceptable.

        Checks the listing title and description against the blocked keyword list.
        Case-insensitive. Partial word matches are intentional (e.g. "spam" in "spammy").
        """
        combined = (
            f"{opportunity.listing.title} {opportunity.listing.description}"
        ).lower()

        for kw in _BLOCKED_KEYWORDS:
            if kw in combined:
                log.warning(
                    "EconomicConscience: blocked opportunity %r — matched %r",
                    opportunity.listing.title[:50], kw,
                )
                return False

        return True

    def get_principles(self) -> list[str]:
        """Return the organism's economic principles as a list."""
        return list(PRINCIPLES)
