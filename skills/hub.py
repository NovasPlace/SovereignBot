"""Sovereign — Skills: Skill hub + discovery.

Provides ClawHub-compatible skill discovery with a hard COMMUNITY trust floor.
No skill from the hub is ever auto-assigned a trust tier higher than COMMUNITY.
Users must manually review and upgrade to VERIFIED.

Hub discovery is read-only and never auto-installs.
The user is shown what's available — they choose what to install.
"""
from __future__ import annotations

import json
import logging
from typing import Optional
from urllib import request as urllib_request
from urllib.error import URLError

log = logging.getLogger("sovereign.skills.hub")

# OpenClaw's hub (we can discover skills from it but never trust them above COMMUNITY)
_OPENCLAW_HUB = "https://openclaw.ai/api/skills"

# Sovereign's own verified skill registry (future)
_SOVEREIGN_HUB = "https://sovereign.forge/api/skills"

_TIMEOUT_S = 5.0

# Skills on this list are permanently banned from the hub
_BANNED_SKILL_IDS: frozenset[str] = frozenset({
    # Add known malicious skill IDs here
})


class HubError(Exception):
    pass


class SkillHub:
    """Discovery layer for remote skill registries.

    Never auto-installs. Returns skill listings for user review.
    Forces COMMUNITY trust floor on everything.
    """

    def __init__(self, hub_url: str = _OPENCLAW_HUB) -> None:
        self._base = hub_url.rstrip("/")

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search the hub for skills matching a query.

        Returns listing data (name, description, author, install_count).
        Never returns code. Never auto-installs.
        """
        from ..skills.cleanse import InputCleanse

        try:
            q = urllib_request.quote(query)
            url = f"{self._base}?q={q}&limit={limit}"
            resp = urllib_request.urlopen(url, timeout=_TIMEOUT_S)
            raw = json.loads(resp.read())
        except (URLError, OSError) as e:
            raise HubError(f"Hub unreachable: {e}") from e
        except json.JSONDecodeError as e:
            raise HubError(f"Hub returned invalid JSON: {e}") from e

        results = []
        for item in (raw if isinstance(raw, list) else raw.get("skills", [])):
            skill_id = str(item.get("id", ""))
            if skill_id in _BANNED_SKILL_IDS:
                continue

            # Sanitize all hub-provided text — treat as external input
            name_raw   = str(item.get("name", ""))
            desc_raw   = str(item.get("description", ""))
            author_raw = str(item.get("author", "unknown"))

            name   = InputCleanse.sanitize(name_raw,   source="hub").text
            desc   = InputCleanse.sanitize(desc_raw,   source="hub").text
            author = InputCleanse.sanitize(author_raw, source="hub").text

            results.append({
                "id": skill_id,
                "name": name,
                "description": desc[:200],
                "author": author,
                "install_count": int(item.get("install_count", 0)),
                "sovereign_trust_tier": "community",  # HARD FLOOR — never higher from hub
                "hub_source": self._base,
            })

        return results[:limit]

    def get_manifest_url(self, skill_id: str) -> str:
        """Return the download URL for a skill's .sovereign file."""
        return f"{self._base}/{skill_id}/download"

    def fetch_skill_content(self, skill_id: str) -> str:
        """Download skill content for local install.

        Returns raw skill file content. User must inspect before installing.
        Caller should call registry.install_from_text(..., force_tier=COMMUNITY).
        """
        if skill_id in _BANNED_SKILL_IDS:
            raise HubError(f"Skill {skill_id} is banned")

        url = self.get_manifest_url(skill_id)
        try:
            resp = urllib_request.urlopen(url, timeout=_TIMEOUT_S)
            content = resp.read(500_000).decode("utf-8", errors="replace")  # max 500KB
        except (URLError, OSError) as e:
            raise HubError(f"Failed to download skill {skill_id}: {e}") from e

        return content


# Pre-built hub instances
def openclaw_hub() -> SkillHub:
    return SkillHub(_OPENCLAW_HUB)


def sovereign_hub() -> SkillHub:
    return SkillHub(_SOVEREIGN_HUB)
