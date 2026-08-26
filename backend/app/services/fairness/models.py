from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.trip import ContractModel
from app.services.planning.models import CandidatePlan


class FairRecommendationCandidate(ContractModel):
    """Server-owned candidate facts admitted to deterministic fairness ranking."""

    plan: CandidatePlan
    provider_fact_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    detour_meters: Annotated[int, Field(ge=0)]


class SatisfactionDeduction(ContractModel):
    rule_id: Literal["FAIR.INTEREST.UNMET"]
    points: Annotated[int, Field(ge=1, le=100)]
    preference_value: Annotated[str, Field(min_length=1, max_length=120)]
    reason: Annotated[str, Field(min_length=1, max_length=240)]


class ParticipantSatisfaction(ContractModel):
    participant_id: UUID
    nickname: Annotated[str, Field(min_length=1, max_length=40)]
    score: Annotated[int, Field(ge=0, le=100)]
    deductions: tuple[SatisfactionDeduction, ...]

    @model_validator(mode="after")
    def validate_score_from_deductions(self) -> "ParticipantSatisfaction":
        if self.score != max(0, 100 - sum(item.points for item in self.deductions)):
            raise ValueError("score must equal 100 minus traceable deductions")
        return self


class CandidateFairnessEvaluation(ContractModel):
    candidate_id: str
    participant_scores: tuple[ParticipantSatisfaction, ...]
    minimum_score: Annotated[int, Field(ge=0, le=100)]
    average_score: Annotated[float, Field(ge=0, le=100)]
    total_cost_cents: Annotated[int | None, Field(ge=0)]
    known_total_cost_cents: Annotated[int, Field(ge=0)]
    detour_meters: Annotated[int, Field(ge=0)]
    stable_id: str

    @model_validator(mode="after")
    def validate_derived_scores(self) -> "CandidateFairnessEvaluation":
        scores = [item.score for item in self.participant_scores]
        if not scores:
            raise ValueError("participantScores must not be empty")
        if self.minimum_score != min(scores):
            raise ValueError("minimumScore must be derived from participantScores")
        expected_average = round(sum(scores) / len(scores), 4)
        if self.average_score != expected_average:
            raise ValueError("averageScore must be derived from participantScores")
        return self


class CandidateHardRejection(ContractModel):
    candidate_id: str
    participant_id: UUID | None = None
    rule_id: Literal[
        "FAIR.HARD.CONSTRAINT_NOT_PASS",
        "FAIR.HARD.MUST_VISIT_MISSING",
        "FAIR.HARD.AVOID_PLACE_PRESENT",
        "FAIR.HARD.BUDGET_CAP_EXCEEDED",
    ]
    reason: Annotated[str, Field(min_length=1, max_length=240)]


class FairRecommendationDecision(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    selected_plan: CandidatePlan
    selected_evaluation: CandidateFairnessEvaluation
    evaluated_candidate_ids: tuple[str, ...]
    hard_rejections: tuple[CandidateHardRejection, ...]
    ranking_rule: Literal[
        "MAX_MIN_THEN_AVERAGE_THEN_COST_THEN_DETOUR_THEN_STABLE_ID"
    ] = "MAX_MIN_THEN_AVERAGE_THEN_COST_THEN_DETOUR_THEN_STABLE_ID"

    @model_validator(mode="after")
    def validate_single_selected_plan(self) -> "FairRecommendationDecision":
        if self.selected_plan.candidate_id != self.selected_evaluation.candidate_id:
            raise ValueError("selected plan and evaluation candidateId must match")
        if self.selected_plan.candidate_id not in self.evaluated_candidate_ids:
            raise ValueError("selected plan must belong to evaluated candidates")
        return self


__all__ = [
    "CandidateFairnessEvaluation",
    "CandidateHardRejection",
    "FairRecommendationCandidate",
    "FairRecommendationDecision",
    "ParticipantSatisfaction",
    "SatisfactionDeduction",
]
