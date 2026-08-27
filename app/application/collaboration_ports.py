from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.domain.collaboration import ConversationSubmission, JsonValue, RelaxationAction
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


__all__ = [
    "CanonicalRevisionPatch",
    "TripDraftRevisionPort",
    "TripDraftRevisionUnavailable",
    "TripDraftRevisionView",
    "UnavailableTripDraftRevisionPort",
]
