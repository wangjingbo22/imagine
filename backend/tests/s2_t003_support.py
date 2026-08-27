from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from app.application.collaboration_ports import CanonicalRevisionPatch
from app.domain.collaboration import ConversationSubmission
from app.domain.trip_draft import TripUnderstandingProposal


@dataclass(frozen=True, slots=True)
class FakeRevision:
    draft_id: UUID
    revision: int
    trip_id: UUID
    understanding: TripUnderstandingProposal
    member_bindings: Mapping[str, UUID]
    source_digest: str


class FakeTripDraftRevisionPort:
    def __init__(self, revision: FakeRevision) -> None:
        self.current = revision
        self.submit_calls = 0
        self.relaxation_calls = 0

    def get_current(self, trip_id: UUID) -> FakeRevision:
        assert trip_id == self.current.trip_id
        return self.current

    async def submit_participant_conversation(
        self,
        *,
        trip_id: UUID,
        participant_id: UUID,
        base_revision: int,
        submission: ConversationSubmission,
        idempotency_key: str,
    ) -> FakeRevision:
        self.submit_calls += 1
        return self.current

    def apply_relaxation(
        self,
        *,
        trip_id: UUID,
        base_revision: int,
        patch: CanonicalRevisionPatch,
        idempotency_key: str,
    ) -> FakeRevision:
        self.relaxation_calls += 1
        return self.current
