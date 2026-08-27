from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.application.collaboration_ports import CanonicalRevisionPatch
from app.domain.collaboration import CollaborationIssue
from app.domain.collaboration import ConversationSubmission
from app.domain.hard_conflicts import DeterministicHardConflictEvaluator
from app.domain.trip_draft import CareDraft, CareNapWindow, CareWalkLimits
from app.domain.trip_draft import TripUnderstandingProposal


UNDERSTANDING_FIXTURES = Path(__file__).parent / "fixtures" / "trip_understanding"


@dataclass(slots=True)
class FrozenClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


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


def _care_for_case(
    *,
    assistance: str = "ORDINARY",
    continuous: int | None = None,
    transfers: int | None = None,
    rest: int | None = None,
    nap: tuple[str, str] | None = None,
) -> CareDraft:
    return CareDraft(
        assistanceTypeHint=assistance,
        childAge=None,
        walkLimits=CareWalkLimits(
            maxContinuousMeters=continuous,
            maxDailyMeters=None,
        ),
        maxTransfers=transfers,
        restIntervalMinutes=rest,
        napWindow=(CareNapWindow(start=nap[0], end=nap[1]) if nap else None),
        avoidStairs=False,
    )


def _replace_care(
    revision: FakeRevision,
    care_values: tuple[CareDraft, ...],
    *,
    clear_input_issues: bool,
) -> FakeRevision:
    participants = [
        item.model_copy(update={"care_draft": care})
        for item, care in zip(
            revision.understanding.participants,
            care_values,
            strict=True,
        )
    ]
    update: dict[str, object] = {"participants": participants}
    if clear_input_issues:
        update |= {
            "missing_fields": [],
            "ambiguities": [],
            "confirmation_questions": [],
        }
    return replace(
        revision,
        understanding=revision.understanding.model_copy(update=update),
    )


def evaluate_fixture_case(case: dict[str, str]) -> tuple[CollaborationIssue, ...]:
    revision = load_revision(Path(case["baseFixture"]).name)
    mutation = case["mutation"]
    if mutation == "NORMALIZE_READY":
        cap = min(
            item.budget_cap_cents
            for item in revision.understanding.participants
            if item.budget_cap_cents is not None
        )
        revision = revision_with_trip_budget(revision, cap)
        care_values = tuple(
            item.care_draft or _care_for_case()
            for item in revision.understanding.participants
        )
        revision = _replace_care(revision, care_values, clear_input_issues=True)
    elif mutation == "NFKC_MUST_AVOID":
        revision = revision_with_places(
            revision,
            must_visit=[" 锛达綀锝呫€€锛綍锝庯絼 "],
            avoid_places=["the bund"],
        )
    elif mutation == "REVERSE_TIME":
        revision = revision_with_times(revision, "20:00", "08:30")
    elif mutation == "NAP_COVERS_TRIP":
        revision = revision_with_times(revision, "13:00", "14:00")
        care_values = tuple(
            _care_for_case(assistance="LOW_STAMINA", nap=("13:00", "14:00"))
            for _ in revision.understanding.participants
        )
        revision = _replace_care(revision, care_values, clear_input_issues=True)
    elif mutation == "NUMERIC_CARE_LIMITS":
        care_values = (
            _care_for_case(
                assistance="LOW_STAMINA", continuous=500, transfers=0, rest=60
            ),
            _care_for_case(
                assistance="LOW_STAMINA", continuous=1000, transfers=2, rest=90
            ),
        )
        revision = _replace_care(revision, care_values, clear_input_issues=True)
    elif mutation != "NONE":
        raise AssertionError(f"unknown fixture mutation: {mutation}")
    return DeterministicHardConflictEvaluator().evaluate(
        revision,
        organizer_participant_id=revision.member_bindings["member-1"],
    )


def serialize_issues(
    issues: tuple[CollaborationIssue, ...],
) -> list[dict[str, object]]:
    return [
        item.model_dump(mode="json", by_alias=True)
        for item in issues
    ]
