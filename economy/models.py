"""Sovereign — Economy: Pydantic models (Part 10).

Domain types for the full job pipeline:
  SCOUT → BID → ACCEPT → EXECUTE → DELIVER → COLLECT
"""
from __future__ import annotations

import time
from typing import Optional

from pydantic import BaseModel, Field


class JobListing(BaseModel):
    """Raw job listing scraped from a platform."""
    platform: str = ""
    url: str = ""
    title: str = ""
    description: str = ""
    budget: float = 0.0          # USD
    budget_type: str = "fixed"   # fixed | hourly
    deadline: str = ""
    required_skills: list[str] = Field(default_factory=list)
    client_rating: float = 0.0   # 0-5 platform rating of the client


class FitEvaluation(BaseModel):
    """LLM evaluation of job fit."""
    score: float = 0.0           # 0.0-1.0
    estimated_hours: float = 1.0
    suggested_bid: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class CapabilityProfile(BaseModel):
    """What the organism can do — built from memory."""
    skills: dict[str, int] = Field(default_factory=dict)        # skill → success count
    hand_capabilities: dict[str, list[str]] = Field(default_factory=dict)
    success_rate: float = 1.0
    strongest_areas: list[str] = Field(default_factory=list)


class Opportunity(BaseModel):
    """A job listing with fit evaluation attached."""
    platform: str = ""
    listing: JobListing = Field(default_factory=JobListing)
    fit_score: float = 0.0
    fit_reasons: list[str] = Field(default_factory=list)
    estimated_hours: float = 1.0
    suggested_bid: float = 0.0


class Bid(BaseModel):
    """A proposal for an Opportunity."""
    opportunity: Opportunity = Field(default_factory=Opportunity)
    proposal_text: str = ""
    bid_amount: float = 0.0
    estimated_hours: float = 1.0
    status: str = "draft"        # draft | submitted | won | lost | rejected_by_user
    submitted_at: Optional[float] = None


class ActiveJob(BaseModel):
    """A job in active lifecycle management."""
    job_id: str = ""
    user_id: str = ""
    platform: str = ""
    title: str = ""
    requirements: str = ""
    bid_amount: float = 0.0
    estimated_hours: float = 1.0
    workspace: str = ""           # local working directory
    status: str = "pending"       # pending | in_progress | in_revision | completed | failed | delivered | paid
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    actual_hours: float = 0.0
    revision_count: int = 0
    result: Optional[dict] = None
    error: Optional[str] = None


class EarningsData(BaseModel):
    """Snapshot of the organism's economic activity."""
    total_earned: float = 0.0
    total_pending: float = 0.0
    jobs_completed: int = 0
    jobs_failed: int = 0
    success_rate: float = 1.0
    active_jobs: int = 0
