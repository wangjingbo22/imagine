from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ContextManager, Protocol, runtime_checkable
from uuid import UUID

from app.domain.collaboration import (
    ConversationSubmission,
    JsonValue,
    RelaxationAction,
    TripFlowKind,
)
from app.domain.trip_draft import TripUnderstandingProposal


@runtime_checkable
class TripDraftRevisionView(Protocol):
    draft_id: UUID
    revision: int
    trip_id: UUID
    understanding: TripUnderstandingProposal
    member_bindings: Mapping[str, UUID]
    source_digest: str


@dataclass(frozen=True, slots=True)
class CanonicalRevisionPatch:
    action: RelaxationAction
    participant_id: UUID | None
    field_path: str
    value: JsonValue


class TripDraftRevisionUnavailable(RuntimeError):
    pass


class TripDraftRevisionPort(Protocol):
    def get_current(self, trip_id: UUID) -> TripDraftRevisionView: ...

    async def submit_participant_conversation(
        self,
        *,
        trip_id: UUID,
        participant_id: UUID,
        base_revision: int,
        submission: ConversationSubmission,
        idempotency_key: str,
    ) -> TripDraftRevisionView: ...

    def apply_relaxation(
        self,
        *,
        trip_id: UUID,
        base_revision: int,
        patch: CanonicalRevisionPatch,
        idempotency_key: str,
    ) -> TripDraftRevisionView: ...


class UnavailableTripDraftRevisionPort:
    @staticmethod
    def _raise() -> None:
        raise TripDraftRevisionUnavailable("TRIP_DRAFT_REVISION_UNAVAILABLE")

    def get_current(self, trip_id: UUID) -> TripDraftRevisionView:
        self._raise()
        raise AssertionError("unreachable")

    async def submit_participant_conversation(
        self,
        *,
        trip_id: UUID,
        participant_id: UUID,
        base_revision: int,
        submission: ConversationSubmission,
        idempotency_key: str,
    ) -> TripDraftRevisionView:
        self._raise()
        raise AssertionError("unreachable")

    def apply_relaxation(
        self,
        *,
        trip_id: UUID,
        base_revision: int,
        patch: CanonicalRevisionPatch,
        idempotency_key: str,
    ) -> TripDraftRevisionView:
        self._raise()
        raise AssertionError("unreachable")


class PlanningOperation(StrEnum):
    PROVIDER_FACTS = "PROVIDER_FACTS"
    RECOMMENDATION = "RECOMMENDATION"
    GENERATE_V1 = "GENERATE_V1"
    CONFIRM_REVIEW = "CONFIRM_REVIEW"
    GENERATE_V2 = "GENERATE_V2"
    PLAN_DECISION = "PLAN_DECISION"


@dataclass(frozen=True, slots=True)
class PlanningAccess:
    trip_id: UUID
    organizer_capability: str | None
    operation_id: str
    operation: PlanningOperation


@dataclass(frozen=True, slots=True)
class ReadinessPermit:
    trip_id: UUID
    readiness_digest: str
    operation_id: str
    operation: PlanningOperation
    flow_kind: TripFlowKind
    expires_at: datetime


class CollaborationReadinessGuard(Protocol):
    def operation(self, access: PlanningAccess) -> ContextManager[ReadinessPermit]: ...


__all__ = [
    "CanonicalRevisionPatch",
    "CollaborationReadinessGuard",
    "PlanningAccess",
    "PlanningOperation",
    "ReadinessPermit",
    "TripDraftRevisionPort",
    "TripDraftRevisionUnavailable",
    "TripDraftRevisionView",
    "UnavailableTripDraftRevisionPort",
]
