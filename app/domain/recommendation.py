"""S2 recommendation contracts: facts in, bounded place ids out.

The contracts intentionally have no price, route, PASS or PlanVersion fields so
an LLM can never authorise planning facts or workflow state.
"""
from __future__ import annotations

from pydantic import Field

from app.domain.collaboration import CollaborationModel
from app.domain.models import Place


class FactRef(CollaborationModel):
    fact_ref_id: str = Field(min_length=1, max_length=120)
    place: Place


class CandidatePlace(CollaborationModel):
    fact_ref_id: str
    place_id: str
    name: str
    category: str | None = None


class CandidateRecommendation(CollaborationModel):
    place_id: str
    reason: str = Field(min_length=1, max_length=80)


class LlmRanking(CollaborationModel):
    recommendations: list[CandidateRecommendation] = Field(min_length=1, max_length=8)


class RecommendationBundle(CollaborationModel):
    candidates: list[CandidatePlace] = Field(min_length=1, max_length=8)
    recommendations: list[CandidateRecommendation] = Field(min_length=1, max_length=8)
    used_deterministic_fallback: bool


__all__ = [
    "CandidatePlace", "CandidateRecommendation", "FactRef", "LlmRanking",
    "RecommendationBundle",
]
