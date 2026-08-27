from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

from app.application.collaboration_ports import CanonicalRevisionPatch
from app.domain.collaboration import ConversationSubmission
from app.domain.trip_draft import TripUnderstandingProposal


UNDERSTANDING_FIXTURES = Path(__file__).parent / "fixtures" / "trip_understanding"


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


def load_revision(name: str = "two_participants.json") -> FakeRevision:
    proposal = TripUnderstandingProposal.model_validate_json(
        (UNDERSTANDING_FIXTURES / name).read_text(encoding="utf-8"),
        strict=True,
    )
    bindings = {
        participant.member_key: UUID(f"10000000-0000-4000-8000-{index:012d}")
        for index, participant in enumerate(proposal.participants, start=1)
    }
    return FakeRevision(
        draft_id=UUID("20000000-0000-4000-8000-000000000001"),
        revision=1,
        trip_id=UUID("30000000-0000-4000-8000-000000000001"),
        understanding=proposal,
        member_bindings=bindings,
        source_digest="a" * 64,
    )


def revision_with_trip_budget(revision: FakeRevision, cents: int) -> FakeRevision:
    trip = revision.understanding.trip.model_copy(update={"budget_cents": cents})
    proposal = revision.understanding.model_copy(update={"trip": trip})
    return replace(revision, understanding=proposal)


def revision_with_member_budget(
    revision: FakeRevision,
    member_key: str,
    cents: int,
) -> FakeRevision:
    participants = [
        item.model_copy(update={"budget_cap_cents": cents})
        if item.member_key == member_key else item
        for item in revision.understanding.participants
    ]
    proposal = revision.understanding.model_copy(update={"participants": participants})
    return replace(revision, understanding=proposal)


def revision_with_times(
    revision: FakeRevision,
    start: str,
    end: str,
) -> FakeRevision:
    trip = revision.understanding.trip.model_copy(
        update={"start_time": start, "end_time": end}
    )
    return replace(
        revision,
        understanding=revision.understanding.model_copy(update={"trip": trip}),
    )


def revision_with_places(
    revision: FakeRevision,
    *,
    must_visit: list[str],
    avoid_places: list[str],
) -> FakeRevision:
    participants = list(revision.understanding.participants)
    participants[0] = participants[0].model_copy(update={"must_visit": must_visit})
    participants[1] = participants[1].model_copy(update={"avoid_places": avoid_places})
    return replace(
        revision,
        understanding=revision.understanding.model_copy(
            update={"participants": participants}
        ),
    )
