"""Sovereign — Economy: Opportunity Scout (Part 10).

Scans freelance platforms for work the organism can do.
Evaluates fit via LLM. Screens through EconomicConscience + Membrane.

Platform scrapers return empty lists by default (stub implementations).
Wire in real scrapers by implementing the _scrape_* methods and
providing platform credentials via environment variables:
  SOVEREIGN_UPWORK_TOKEN  — Upwork API token
  SOVEREIGN_FREELANCER_KEY — Freelancer.com API key
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

from .models import (
    CapabilityProfile, FitEvaluation, JobListing, Opportunity,
)
from .conscience import EconomicConscience

if TYPE_CHECKING:
    pass

log = logging.getLogger("sovereign.economy.scout")


class OpportunityScout:
    """Finds and evaluates freelance opportunities.

    Call scout() during IDLE/RESTING heartbeat states.
    Results are pre-screened for ethical compliance and fit.
    """

    # Hand names → capability keyword sets
    _HAND_CAPABILITIES: dict[str, list[str]] = {
        "code_engineer": [
            "python", "javascript", "typescript", "api", "backend",
            "scripting", "automation", "testing", "flask", "fastapi",
            "django", "nodejs", "web scraping", "data processing",
        ],
        "research": [
            "research", "analysis", "literature review", "survey",
            "report", "market analysis", "competitive analysis",
        ],
        "sysadmin": [
            "devops", "linux", "docker", "kubernetes", "deployment",
            "monitoring", "bash", "shell", "server", "nginx",
        ],
        "writing": [
            "technical writing", "documentation", "blog post",
            "copywriting", "article", "content creation",
        ],
    }

    def __init__(
        self,
        store=None,
        llm_fn=None,
        membrane=None,
        conscience: EconomicConscience | None = None,
        config: dict | None = None,
    ) -> None:
        self._store = store
        self._llm = llm_fn
        self._membrane = membrane
        self._conscience = conscience or EconomicConscience()
        self._config = config or {}
        self._capability_profile: CapabilityProfile | None = None
        self._enabled_platforms: list[str] = self._config.get(
            "enabled_platforms", []  # empty = no scraping until platforms configured
        )

    async def scout(self) -> list[Opportunity]:
        """Scan all enabled platforms for opportunities.

        Returns opportunities sorted by fit score (highest first).
        Only opportunities passing conscience + membrane screens are returned.
        """
        if not self._capability_profile:
            self._capability_profile = await self._build_capability_profile()

        opportunities: list[Opportunity] = []

        for platform in self._enabled_platforms:
            try:
                listings = await self._scrape_platform(platform)
                for listing in listings:
                    # Conscience screen first — hardcoded ethics
                    opp = Opportunity(platform=platform, listing=listing)
                    if not self._conscience.check_opportunity(opp):
                        continue

                    # Membrane screen — learned defenses
                    if self._membrane is not None:
                        try:
                            screen = await self._membrane.screen(
                                listing.description, source=f"job_listing:{platform}"
                            )
                            if getattr(screen, "action", "allow") == "block":
                                continue
                        except Exception:
                            pass

                    # Fit evaluation via LLM
                    fit = await self._evaluate_fit(listing)
                    if fit.score >= 0.6:
                        opp.fit_score = fit.score
                        opp.fit_reasons = fit.reasons
                        opp.estimated_hours = fit.estimated_hours
                        opp.suggested_bid = fit.suggested_bid
                        opportunities.append(opp)

            except Exception as exc:
                log.warning("Scout error on platform=%s: %s", platform, exc)

        opportunities.sort(key=lambda o: o.fit_score, reverse=True)

        if opportunities:
            log.info(
                "Scout found %d opportunities. Top: %r (fit=%.0f%%)",
                len(opportunities),
                opportunities[0].listing.title[:50],
                opportunities[0].fit_score * 100,
            )

        return opportunities

    async def _build_capability_profile(self) -> CapabilityProfile:
        """Build capability profile from memory of past successes."""
        skills: dict[str, int] = {}

        if self._store is not None:
            try:
                memories = self._store.recall("task_execution success", limit=50)
                for mem in memories:
                    for tag in getattr(mem, "tags", []):
                        if tag not in ("task_execution", "success", "shipped", "hand"):
                            skills[tag] = skills.get(tag, 0) + 1
            except Exception:
                pass

        strongest = sorted(skills, key=lambda k: skills[k], reverse=True)[:5]

        return CapabilityProfile(
            skills=skills,
            hand_capabilities=self._HAND_CAPABILITIES,
            success_rate=1.0,  # updated from memory when enough data exists
            strongest_areas=strongest,
        )

    async def _evaluate_fit(self, listing: JobListing) -> FitEvaluation:
        """Ask the LLM to evaluate fit, time estimate, and bid price."""
        if self._llm is None:
            return FitEvaluation(score=0.0, reasons=["LLM not available"])

        profile = self._capability_profile or CapabilityProfile()

        prompt = (
            f"Evaluate whether I can complete this freelance job.\n\n"
            f"JOB TITLE: {listing.title}\n"
            f"DESCRIPTION: {listing.description[:400]}\n"
            f"BUDGET: ${listing.budget} ({listing.budget_type})\n"
            f"REQUIRED SKILLS: {', '.join(listing.required_skills)}\n\n"
            f"MY STRONGEST AREAS: {', '.join(profile.strongest_areas) or 'general software engineering'}\n\n"
            f"Evaluate and respond ONLY with valid JSON:\n"
            f'{{"score": 0.0-1.0, "estimated_hours": N, "suggested_bid": N.NN, '
            f'"reasons": ["..."], "risks": ["..."]}}'
        )

        try:
            raw = await self._llm(
                system=(
                    "You are an experienced freelancer evaluating job opportunities. "
                    "Be honest about fit. Respond ONLY with the JSON object."
                ),
                user=prompt,
            )
            # Extract JSON
            match = re.search(r"\{[\s\S]+\}", raw)
            if match:
                data = json.loads(match.group())
                return FitEvaluation(
                    score=float(data.get("score", 0.0)),
                    estimated_hours=float(data.get("estimated_hours", 2.0)),
                    suggested_bid=float(data.get("suggested_bid", 50.0)),
                    reasons=data.get("reasons", []),
                    risks=data.get("risks", []),
                )
        except Exception as exc:
            log.debug("FitEvaluation parse failed: %s", exc)

        return FitEvaluation(score=0.0, reasons=["Evaluation failed"])

    # ── Platform scrapers (stub implementations) ──────────────────────────────

    async def _scrape_platform(self, platform: str) -> list[JobListing]:
        """Dispatch to the correct platform scraper."""
        scrapers = {
            "upwork": self._scrape_upwork,
            "freelancer": self._scrape_freelancer,
            "github_bounties": self._scrape_github_bounties,
        }
        fn = scrapers.get(platform)
        if fn is None:
            log.warning("Unknown platform: %s", platform)
            return []
        return await fn()

    async def _scrape_upwork(self) -> list[JobListing]:
        """Upwork REST API job search scraper.

        Auth: SOVEREIGN_UPWORK_TOKEN = your OAuth2 access token
              Header: Authorization: Bearer <token>
        Endpoint: GET https://www.upwork.com/api/v1/jobs/search

        NOTE: Upwork API keys require manual approval — new keys may be
        disabled by default. Check developers.upwork.com for key status.
        Once approved, paste the access token in sovereign/.env as:
            SOVEREIGN_UPWORK_TOKEN=your_access_token_here
        """
        import os
        import json
        import urllib.request as _req
        import urllib.parse as _parse

        token = os.environ.get("SOVEREIGN_UPWORK_TOKEN", "")
        if not token:
            log.debug("SOVEREIGN_UPWORK_TOKEN not set — Upwork scraping disabled")
            return []

        profile = self._capability_profile or CapabilityProfile()
        skills = profile.strongest_areas or ["python", "api", "automation"]
        keyword_query = " ".join(skills[:3])

        # Upwork skill → category ID mapping for common use cases
        category2 = "531770282580668418"  # Web, Mobile & Software Dev

        params = {
            "q": keyword_query,
            "category2_uid": category2,
            "sort": "recency",
            "paging": "0;20",   # offset;count
            "job_status": "open",
            "duration_v3": "week",  # posted within a week
        }
        url = f"https://www.upwork.com/api/v1/jobs/search?{_parse.urlencode(params)}"

        loop = asyncio.get_event_loop()
        try:
            request = _req.Request(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": "SovereignBot/1.0",
                },
                method="GET",
            )
            raw = await loop.run_in_executor(
                None,
                lambda: _req.urlopen(request, timeout=15).read(),
            )
            data = json.loads(raw)
        except Exception as exc:
            err_str = str(exc)
            if "401" in err_str or "403" in err_str:
                log.warning(
                    "Upwork API: auth error — your key may still be pending review. "
                    "Check status at https://www.upwork.com/developer/keys"
                )
            else:
                log.warning("Upwork API request failed: %s", exc)
            return []

        # Upwork returns {"jobs": [...]} or {"error": {...}}
        if "error" in data:
            log.warning(
                "Upwork API error: %s", data["error"].get("message", data["error"])
            )
            return []

        jobs = data.get("jobs", [])
        listings: list[JobListing] = []

        for j in jobs:
            try:
                # Budget: hourly jobs have hourly_budget_min/max, fixed have budget
                budget_type = "hourly" if j.get("job_type") == "hourly" else "fixed"
                if budget_type == "hourly":
                    bmin = float(j.get("hourly_budget_min") or 0)
                    bmax = float(j.get("hourly_budget_max") or bmin)
                    budget = round((bmin + bmax) / 2, 2)
                else:
                    budget = float(j.get("budget", {}).get("amount") or 0)

                skills_list = [s["prefLabel"] for s in (j.get("skills") or []) if s.get("prefLabel")]

                listings.append(JobListing(
                    platform="upwork",
                    url=j.get("job_url", ""),
                    title=j.get("title", "").strip(),
                    description=(j.get("snippet") or "")[:800].strip(),
                    budget=budget,
                    budget_type=budget_type,
                    deadline=str(j.get("date_created", "")),
                    required_skills=skills_list,
                    client_rating=float(j.get("client", {}).get("feedback_score") or 0),
                ))
            except Exception as exc:
                log.debug("Upwork job parse error: %s — %s", exc, j.get("id"))

        log.info(
            "Upwork API: fetched %d listings (query=%r)",
            len(listings), keyword_query[:60],
        )
        return listings


    async def _scrape_freelancer(self) -> list[JobListing]:
        """Freelancer.com real API scraper.

        Auth: SOVEREIGN_FREELANCER_KEY = your OAuth access token
              Header: freelancer-oauth-v1: <token>
        Endpoint: GET https://www.freelancer.com/api/projects/0.1/projects/active/
        Docs: https://developers.freelancer.com

        Returns up to 20 job listings across configured search keywords.
        """
        import os
        import json
        import urllib.request as _req
        import urllib.parse as _parse

        token = os.environ.get("SOVEREIGN_FREELANCER_KEY", "")
        if not token:
            log.debug("SOVEREIGN_FREELANCER_KEY not set — Freelancer scraping disabled")
            return []

        profile = self._capability_profile or CapabilityProfile()
        # Build a search query from strongest capability areas
        skills = profile.strongest_areas or ["python", "api", "automation"]
        search_query = " OR ".join(skills[:4])

        base_url = "https://www.freelancer.com/api/projects/0.1/projects/active/"
        params = {
            "query": search_query,
            "limit": 20,
            "offset": 0,
            "job_details": "true",
            "full_description": "true",
            "compact": "false",
        }
        url = f"{base_url}?{_parse.urlencode(params)}"

        loop = asyncio.get_event_loop()
        try:
            request = _req.Request(
                url,
                headers={
                    "freelancer-oauth-v1": token,
                    "Content-Type": "application/json",
                    "User-Agent": "SovereignBot/1.0",
                },
                method="GET",
            )
            raw = await loop.run_in_executor(
                None,
                lambda: _req.urlopen(request, timeout=15).read(),
            )
            data = json.loads(raw)
        except Exception as exc:
            log.warning("Freelancer API request failed: %s", exc)
            return []

        # API returns {"status": "success", "result": {"projects": [...], "total_count": N}}
        status = data.get("status", "")
        if status != "success":
            log.warning(
                "Freelancer API returned status=%r: %s",
                status, data.get("message", "")
            )
            return []

        projects = data.get("result", {}).get("projects", [])
        listings: list[JobListing] = []

        for p in projects:
            try:
                # Budget comes as {"minimum": N, "maximum": N, "type": "fixed"|"hourly"}
                budget_info = p.get("budget", {}) or {}
                budget_min = float(budget_info.get("minimum") or 0)
                budget_max = float(budget_info.get("maximum") or budget_min)
                budget = round((budget_min + budget_max) / 2, 2)
                budget_type = budget_info.get("type", "fixed")

                # Skills/jobs are a list of {"id": N, "name": "..."}
                jobs = p.get("jobs") or []
                skills_list = [j["name"] for j in jobs if j.get("name")]

                listings.append(JobListing(
                    platform="freelancer",
                    url=f"https://www.freelancer.com/projects/{p.get('seo_url', p.get('id', ''))}",
                    title=p.get("title", "").strip(),
                    description=(p.get("description") or "")[:800].strip(),
                    budget=budget,
                    budget_type=budget_type,
                    deadline=str(p.get("submitdate", "")),
                    required_skills=skills_list,
                    client_rating=float(
                        (p.get("owner_rating") or {}).get("overall", 0.0) or 0.0
                    ),
                ))
            except Exception as exc:
                log.debug("Freelancer project parse error: %s — %s", exc, p.get("id"))

        log.info(
            "Freelancer API: fetched %d listings (query=%r)",
            len(listings), search_query[:60],
        )
        return listings

    async def _scrape_github_bounties(self) -> list[JobListing]:
        """GitHub bounty/issue scraper stub. Uses public API — no auth needed."""
        # Real implementation: search GitHub issues with labels:
        # "bounty", "help wanted", "good first issue" and fund:true
        # https://api.github.com/search/issues?q=label:bounty+state:open
        log.debug("GitHub bounty scraper: not yet implemented")
        return []

    def add_listing_manually(self, title: str, description: str,
                              budget: float, required_skills: list[str],
                              platform: str = "manual") -> JobListing:
        """Allow user to paste in a job listing via Telegram command."""
        return JobListing(
            platform=platform,
            title=title,
            description=description,
            budget=budget,
            required_skills=required_skills,
        )
