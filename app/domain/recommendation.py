"""S2 recommendation contracts: facts in, bounded place ids out.

The contracts intentionally have no price, route, PASS or PlanVersion fields so
an LLM can never authorise planning facts or workflow state.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.domain.collaboration import CollaborationModel
from app.domain.models import Place, SourceStatus


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


class CandidateFactProvenance(CollaborationModel):
    fact_ref_id: str = Field(min_length=1, max_length=160)
    provider_object_id: str = Field(min_length=1, max_length=160)
    source_status: SourceStatus
    fetched_at: datetime
    is_stale: bool


class LlmRanking(CollaborationModel):
    recommendations: list[CandidateRecommendation] = Field(min_length=1, max_length=8)


class MemberScore(CollaborationModel):
    """A deterministic per-member score for the selected plan, not an LLM fact."""

    participant_id: str
    score: int = Field(ge=0, le=100)
    penalty_rule_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class TrustedPlan(CollaborationModel):
    """The single, explainable winner exposed to the S2 recommendation page."""

    tasks: list[CandidatePlace] = Field(min_length=1, max_length=4)
    member_scores: list[MemberScore] = Field(min_length=1, max_length=3)
    lowest_member_score: int = Field(ge=0, le=100)
    care_points: list[str] = Field(default_factory=list)
    compromises: list[str] = Field(default_factory=list)
    unknown_facts: list[str] = Field(default_factory=list)
    confirmation_message: str


class RecommendationBundle(CollaborationModel):
    candidates: list[CandidatePlace] = Field(min_length=1, max_length=8)
    recommendations: list[CandidateRecommendation] = Field(min_length=1, max_length=8)
    used_deterministic_fallback: bool
    trusted_plan: TrustedPlan | None = None
    fact_set_id: str | None = Field(default=None, min_length=1, max_length=160)
    provider_fact_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    provenance: list[CandidateFactProvenance] = Field(
        default_factory=list,
        max_length=8,
    )


__all__ = [
    "CandidateFactProvenance", "CandidatePlace", "CandidateRecommendation",
    "FactRef", "LlmRanking", "MemberScore", "RecommendationBundle", "TrustedPlan",
]
