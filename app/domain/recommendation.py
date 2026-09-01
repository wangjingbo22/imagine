"""S2 recommendation contracts: facts in, bounded place ids out.

The contracts intentionally have no price, route, PASS or PlanVersion fields so
an LLM can never authorise planning facts or workflow state.
"""
from __future__ import annotations

from datetime import datetime
from unicodedata import normalize

from pydantic import Field, field_validator

from app.domain.collaboration import CollaborationModel
from app.domain.models import Place, SourceStatus
from app.domain.parent_trip import (
    MAX_PARENT_TRIP_PLACE_MEMORY,
    ParentTripPlaceMemoryItem,
)


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

    @field_validator("reason")
    @classmethod
    def reject_model_claims_outside_ranking_boundary(cls, value: str) -> str:
        """Keep the legacy JSON ranking path inside the same T031 boundary.

        The model may choose an already-issued place ID and give a short,
        non-authoritative reason.  Facts, validation results and workflow state
        are owned by deterministic server code and must never be smuggled back
        through a natural-language reason.
        """
        normalized = normalize("NFKC", value).casefold()
        forbidden_terms = (
            "price", "cost", "amount", "route", "score", "satisfaction",
            "pass", "planversion", "plan version", "planid", "plan state",
            "status", "current", "价格", "费用", "预算", "路线", "评分",
            "分数", "满意度", "通过", "合格", "计划状态", "状态", "当前版本",
            "计划版本",
        )
        if any(term in normalized for term in forbidden_terms):
            raise ValueError(
                "model reason cannot assert price, route, satisfaction, PASS or plan state"
            )
        return value


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

    tasks: list[CandidatePlace] = Field(min_length=1, max_length=5)
    member_scores: list[MemberScore] = Field(min_length=1, max_length=20)
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
    parent_place_memory: list[ParentTripPlaceMemoryItem] = Field(
        default_factory=list,
        max_length=MAX_PARENT_TRIP_PLACE_MEMORY,
    )


__all__ = [
    "CandidateFactProvenance", "CandidatePlace", "CandidateRecommendation",
    "FactRef", "LlmRanking", "MemberScore", "RecommendationBundle", "TrustedPlan",
]
