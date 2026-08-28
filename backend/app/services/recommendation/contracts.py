from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from app.domain.models import SourceStatus
from app.schemas.constraint import Constraint
from app.schemas.llm import (
    ProviderCandidateSelectionProposal,
    ProviderCandidateSelectionRequest,
)
from app.schemas.trip import ContractModel, Trip
from app.services.fairness import FairRecommendationDecision
from app.services.planning.models import (
    CandidateEndpointFact,
    CandidatePlanRequest,
)


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
OpaqueId = Annotated[str, Field(min_length=1, max_length=160)]


class ProviderCandidateFactView(ContractModel):
    """Read-only T006 fact projection that may be shown to the model."""

    place_fact_id: OpaqueId
    provider_place_id: OpaqueId
    name: Annotated[str, Field(min_length=1, max_length=120)]
    category: Annotated[str, Field(min_length=1, max_length=80)]
    source_status: SourceStatus
    known_attributes: dict[str, JsonValue] = Field(default_factory=dict)
    # T006 snapshots now carry the payload digest needed to build T008's
    # opaque FactRef identity.  ``None`` preserves compatibility with older
    # in-memory fixtures; the application adapter derives a scoped digest for
    # those fixtures without exposing Provider payloads to the model.
    fact_digest: Digest | None = None


class ProviderFactBundle(ContractModel):
    """Server-restored T006 fact set consumed by T009 without re-registering it."""

    schema_version: Literal["1.0"] = "1.0"
    fact_set_id: OpaqueId
    provider_fact_digest: Digest
    trip: Trip
    start_location: CandidateEndpointFact
    end_location: CandidateEndpointFact
    confirmed_constraints: tuple[Constraint, ...]
    confirmed_trip_summary: dict[str, JsonValue]
    candidate_facts: tuple[ProviderCandidateFactView, ...] = Field(
        min_length=6,
        max_length=8,
    )

    @model_validator(mode="after")
    def validate_allowlist(self) -> "ProviderFactBundle":
        fact_ids = [item.place_fact_id for item in self.candidate_facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("candidateFacts.placeFactId values must be unique")
        provider_ids = [item.provider_place_id for item in self.candidate_facts]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("candidateFacts.providerPlaceId values must be unique")
        trusted_statuses = {
            SourceStatus.ONLINE,
            SourceStatus.VERIFIED_CACHE,
            SourceStatus.USER_CONFIRMED,
        }
        if any(
            item.source_status not in trusted_statuses
            for item in self.candidate_facts
        ):
            raise ValueError(
                "candidateFacts require ONLINE, VERIFIED_CACHE or USER_CONFIRMED facts"
            )
        expected_city = self.trip.city_context.city_code
        if self.start_location.city_code != expected_city:
            raise ValueError("startLocation must belong to the confirmed Trip city")
        if self.end_location.city_code != expected_city:
            raise ValueError("endLocation must belong to the confirmed Trip city")
        return self


class RecommendationOrchestrationRequest(ContractModel):
    """Public request: clients may select a signed set, never facts or scores."""

    schema_version: Literal["1.0"] = "1.0"
    fact_set_id: OpaqueId
    provider_fact_digest: Digest


class BuiltRouteCandidate(ContractModel):
    """Trusted route-backed candidate returned by the T006/Provider seam."""

    request: CandidatePlanRequest
    selected_place_fact_ids: tuple[OpaqueId, ...] = Field(
        min_length=2,
        max_length=3,
    )
    detour_meters: Annotated[int, Field(ge=0)]


FallbackReason = Literal[
    "LLM_NOT_CONFIGURED",
    "LLM_UNAVAILABLE",
    "LLM_TIMEOUT",
    "LLM_AUTH_FAILED",
    "LLM_INVALID_JSON",
    "LLM_SCHEMA_INVALID",
    "LLM_OUT_OF_ALLOWLIST",
    "LLM_FORMAT_INVALID",
    "LLM_DIGEST_MISMATCH",
    "LLM_ALLOWLIST_VIOLATION",
    "LLM_PROPOSAL_UNUSABLE",
]


class RecommendationOrchestrationResult(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    trip_id: UUID
    trace_id: OpaqueId
    provider_fact_digest: Digest
    strategy: Literal["LLM_PROPOSAL", "DETERMINISTIC_FALLBACK"]
    fallback_reason: FallbackReason | None
    selected_place_fact_ids: tuple[OpaqueId, ...] = Field(
        min_length=2,
        max_length=3,
    )
    selection_rationale: Annotated[str, Field(min_length=1, max_length=240)]
    risk_notes: tuple[
        Annotated[str, Field(min_length=1, max_length=240)], ...
    ] = Field(max_length=8)
    decision: FairRecommendationDecision

    @model_validator(mode="after")
    def validate_fallback_shape(self) -> "RecommendationOrchestrationResult":
        if (self.strategy == "DETERMINISTIC_FALLBACK") != (
            self.fallback_reason is not None
        ):
            raise ValueError("fallbackReason must be present exactly for fallback")
        if len(self.decision.selected_plan.tasks) not in {3, 4}:
            raise ValueError("the unique recommendation must contain 3 or 4 tasks")
        return self


__all__ = [
    "BuiltRouteCandidate",
    "Digest",
    "FallbackReason",
    "ProviderCandidateFactView",
    "ProviderCandidateSelectionProposal",
    "ProviderCandidateSelectionRequest",
    "ProviderFactBundle",
    "RecommendationOrchestrationRequest",
    "RecommendationOrchestrationResult",
]
