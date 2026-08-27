from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from app.application.collaboration_ports import UnavailableTripDraftRevisionPort
from app.application.collaboration_service import CollaborationService
from app.core.errors import AppError
from app.domain.collaboration import ParticipantConfirmationStatus, ParticipantConversationRequest
from app.domain.collaboration_digest import member_digest, shared_digest
from app.domain.hard_conflicts import DeterministicHardConflictEvaluator
from app.domain.trip_draft import CareDraft, CareWalkLimits
from app.infrastructure.collaboration_store import SqliteCollaborationRepository
from backend.tests.s2_t003_support import (
    FakeRevision,
    FakeTripDraftRevisionPort,
    load_revision,
    revision_with_member_budget,
    revision_with_trip_budget,
)


@dataclass(slots=True)
class ReadyHarness:
    service: CollaborationService
    revisions: FakeTripDraftRevisionPort
    repository: SqliteCollaborationRepository
    revision: FakeRevision
    organizer_token: str


def _ready_harness(tmp_path) -> ReadyHarness:
    revision = load_revision()
    ordinary = CareDraft(
        assistanceTypeHint="ORDINARY",
        childAge=None,
        walkLimits=CareWalkLimits(
            maxContinuousMeters=None,
            maxDailyMeters=None,
        ),
        maxTransfers=None,
        restIntervalMinutes=None,
        napWindow=None,
        avoidStairs=False,
    )
    participants = [
        item.model_copy(update={"care_draft": ordinary})
        for item in revision.understanding.participants
    ]
    trip = revision.understanding.trip.model_copy(update={"budget_cents": 30_000})
    proposal = revision.understanding.model_copy(update={
        "trip": trip,
        "participants": participants,
        "missing_fields": [],
        "ambiguities": [],
        "confirmation_questions": [],
    })
    revision = replace(revision, understanding=proposal)
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    bootstrap = repository.bootstrap_collaboration(revision, "0123456789abcdef")
    assert bootstrap.organizer_token is not None
    version = 1
    for index, member_key in enumerate(sorted(revision.member_bindings), start=1):
        repository.record_confirmation(
            trip_id=revision.trip_id,
            participant_id=revision.member_bindings[member_key],
            revision=revision.revision,
            source_digest=revision.source_digest,
            shared_digest=shared_digest(revision),
            member_digest=member_digest(revision, member_key),
            expected_version=version,
            idempotency_key=f"confirm-{index:08d}",
        )
        version += 1
    revisions = FakeTripDraftRevisionPort(revision)
    service = CollaborationService(
        repository=repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    return ReadyHarness(service, revisions, repository, revision, bootstrap.organizer_token)


def _member_request(version: int) -> ParticipantConversationRequest:
    question_ids = (
        "trip", "party", "endpoints_budget", "preferences", "assistance", "confirm"
    )
    return ParticipantConversationRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=version,
        naturalLanguageRequest="我想把个人预算改为三百元",
        answers=[{"questionId": key, "answer": "已回答"} for key in question_ids],
    )


def _dump(repository: SqliteCollaborationRepository) -> tuple[tuple[object, ...], ...]:
    with repository._connect() as connection:
        return tuple(
            tuple(row)
            for table in (
                "collaboration_sessions",
                "collaboration_participants",
                "participant_invitations",
                "collaboration_actor_sessions",
                "collaboration_idempotency",
            )
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")
        )


@pytest.mark.asyncio
async def test_unavailable_t002_changes_no_rows_or_downstream_calls(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    invitation = harness.repository.create_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        organizer_token=harness.organizer_token,
        expected_version=3,
        idempotency_key="invite-000000001",
        expires_in_hours=72,
    )
    assert invitation.invitation_url is not None
    session = harness.repository.redeem_invitation(
        invitation.invitation_url.split("=", 1)[1],
        "redeem-000000001",
    )
    assert session.participant_session_token is not None
    service = CollaborationService(
        repository=harness.repository,
        revisions=UnavailableTripDraftRevisionPort(),
        evaluator=DeterministicHardConflictEvaluator(),
    )
    before = _dump(harness.repository)
    with pytest.raises(AppError) as captured:
        await service.submit_member(
            session_token=session.participant_session_token,
            request=_member_request(version=4),
            idempotency_key="7777777777777777",
        )
    assert captured.value.code == "TRIP_DRAFT_REVISION_UNAVAILABLE"
    assert captured.value.http_status == 503
    assert _dump(harness.repository) == before


def test_member_only_change_invalidates_only_that_confirmation(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    changed = revision_with_member_budget(harness.revision, "member-2", 31_000)
    harness.revisions.current = changed
    state = harness.service.organizer_state(
        harness.revision.trip_id,
        harness.organizer_token,
    )
    statuses = {item.member_key: item.confirmation_status for item in state.participants}
    assert statuses == {
        "member-1": ParticipantConfirmationStatus.CONFIRMED,
        "member-2": ParticipantConfirmationStatus.NEEDS_RECONFIRMATION,
    }


def test_shared_change_invalidates_every_confirmation(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    harness.revisions.current = revision_with_trip_budget(harness.revision, 29_000)
    state = harness.service.organizer_state(
        harness.revision.trip_id,
        harness.organizer_token,
    )
    assert {item.confirmation_status for item in state.participants} == {
        ParticipantConfirmationStatus.NEEDS_RECONFIRMATION
    }
