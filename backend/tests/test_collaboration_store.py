from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.collaboration import (
    CollaborationStatus,
    ConversationAnswer,
    ConversationSubmission,
    ParticipantConfirmationStatus,
)
from app.domain.trip_draft import ParsedTripFields
from app.infrastructure.collaboration_store import (
    CollaborationStoreError,
    SqliteCollaborationRepository,
)
from app.application.collaboration_service import CollaborationService
from app.core.errors import AppError
from app.domain.trip_draft import TripDraftParseResult


class StubParser:
    async def parse(self, request):
        return TripDraftParseResult(
            tripId=str(request.trip_id or uuid4()), parsed=_parsed(),
            confirmationItems=[], canPlan=True, trip=None,
        )


def _parsed() -> ParsedTripFields:
    return ParsedTripFields(
        cityName="北京", travelDate="2026-09-01", startTime="09:00",
        endTime="18:00", startLocationText="北京南站", endLocationText="北京南站",
        budgetCents=50_000, interests=["博物馆"], mustVisit=[], avoidPlaces=[],
    )


def test_fixed_six_questions_must_be_complete_and_ordered() -> None:
    answers = [ConversationAnswer(questionId=question, answer="已回答") for question in ("trip", "party", "endpoints_budget", "preferences", "assistance", "confirm")]
    submission = ConversationSubmission(naturalLanguageRequest="北京一日游", answers=answers)
    assert submission.participant_count == 1
    assert "【个人偏好（兴趣与地点限制）】" in submission.transcript
    assert "preferences:" not in submission.transcript
    with pytest.raises(ValueError):
        ConversationSubmission(naturalLanguageRequest="北京一日游", answers=list(reversed(answers)))


def test_invited_members_are_isolated_and_all_confirmed_is_ready(tmp_path) -> None:
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    trip_id, organizer_id = uuid4(), uuid4()
    state, organizer_token = repository.create_session(trip_id, organizer_id, _parsed(), 2)
    assert state.status is CollaborationStatus.INVITING
    assert organizer_token

    invitation = repository.create_invitation(trip_id, organizer_token)
    token = invitation.invitation_url.rsplit("/", 1)[1]
    assert repository.invitation(token).status is ParticipantConfirmationStatus.INVITED
    assert repository.get_state(trip_id).status is CollaborationStatus.COLLECTING_MEMBERS

    repository.submit_invitation(token, _parsed())
    ready = repository.confirm_invitation(token)
    assert ready.status is CollaborationStatus.READY_TO_PLAN
    with pytest.raises(CollaborationStoreError, match="INVITATION_INVALID"):
        repository.invitation(token)


def test_must_visit_and_avoid_conflict_stops_ready_to_plan(tmp_path) -> None:
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    trip_id = uuid4()
    _, organizer_token = repository.create_session(trip_id, uuid4(), _parsed(), 2)
    invitation = repository.create_invitation(trip_id, organizer_token)
    token = invitation.invitation_url.rsplit("/", 1)[1]
    member = _parsed().model_copy(update={"avoid_places": ["故宫"]})
    organizer = _parsed().model_copy(update={"must_visit": ["故宫"]})
    with repository._connect() as connection:
        connection.execute("UPDATE collaboration_participants SET parsed_json = ? WHERE trip_id = ? AND is_organizer = 1", (organizer.model_dump_json(by_alias=True), str(trip_id)))
    repository.submit_invitation(token, member)
    state = repository.confirm_invitation(token)
    assert state.status is CollaborationStatus.CONFLICT_REVIEW
    assert state.conflicts[0].rule_id == "MUST_VISIT_AVOID_PLACE"
    resolved = repository.resolve_conflict(
        trip_id,
        state.conflicts[0].conflict_id,
        "REMOVE_AVOID",
        organizer_token,
    )
    assert resolved.status is CollaborationStatus.READY_TO_PLAN


@pytest.mark.asyncio
async def test_organizer_and_member_conversations_create_a_two_person_session(tmp_path) -> None:
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    service = CollaborationService(repository, StubParser())
    answers = [
        ConversationAnswer(questionId=question, answer=("两个人出行" if question == "party" else "已回答"))
        for question in ("trip", "party", "endpoints_budget", "preferences", "assistance", "confirm")
    ]
    created = await service.create_organizer(ConversationSubmission(naturalLanguageRequest="北京一日游", answers=answers))
    assert created.state is not None
    assert created.state.expected_participants == 2
    assert created.state.status is CollaborationStatus.INVITING
    assert created.organizer_access_token

    invitation = service.invite(created.state.trip_id, created.organizer_access_token)
    token = invitation.invitation_url.rsplit("/", 1)[1]
    await service.submit_member(token, ConversationSubmission(naturalLanguageRequest="我也想去", answers=answers))
    state = service.confirm_member(token)
    assert state.status is CollaborationStatus.READY_TO_PLAN
    service.assert_planning_ready(created.state.trip_id, created.organizer_access_token)
    with pytest.raises(AppError, match="请等待全部成员确认") as error:
        service.assert_planning_ready(created.state.trip_id, "not-the-organizer")
    assert error.value.code == "ORGANIZER_PERMISSION_REQUIRED"


def test_invitation_capacity_is_limited_to_declared_party_size(tmp_path) -> None:
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    trip_id = uuid4()
    _, organizer_token = repository.create_session(trip_id, uuid4(), _parsed(), 2)
    repository.create_invitation(trip_id, organizer_token)
    with pytest.raises(CollaborationStoreError, match="INVITATION_CAPACITY_REACHED"):
        repository.create_invitation(trip_id, organizer_token)


def test_three_person_session_waits_for_every_member_and_keeps_drafts_isolated(tmp_path) -> None:
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    trip_id = uuid4()
    _, organizer_token = repository.create_session(trip_id, uuid4(), _parsed(), 3)
    first = repository.create_invitation(trip_id, organizer_token)
    second = repository.create_invitation(trip_id, organizer_token)
    first_token = first.invitation_url.rsplit("/", 1)[1]
    second_token = second.invitation_url.rsplit("/", 1)[1]

    first_draft = _parsed().model_copy(update={"interests": ["博物馆"]})
    second_draft = _parsed().model_copy(update={"interests": ["美食"]})
    repository.submit_invitation(first_token, first_draft)
    waiting = repository.confirm_invitation(first_token)
    assert waiting.status is CollaborationStatus.COLLECTING_MEMBERS
    assert next(item for item in waiting.participants if item.participant_id == first.participant_id).parsed.interests == ["博物馆"]
    assert next(item for item in waiting.participants if item.participant_id == second.participant_id).parsed is None

    repository.submit_invitation(second_token, second_draft)
    ready = repository.confirm_invitation(second_token)
    assert ready.status is CollaborationStatus.READY_TO_PLAN
    assert next(item for item in ready.participants if item.participant_id == second.participant_id).parsed.interests == ["美食"]
