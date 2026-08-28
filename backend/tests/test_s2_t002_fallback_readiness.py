from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.application.collaboration_ports import PlanningAccess, PlanningOperation
from app.application.collaboration_service import CollaborationService
from app.application.trip_draft_revision_service import TripDraftRevisionService
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.collaboration import (
    ConversationSubmission,
    OrganizerConversationRequest,
    QUESTION_IDS,
)
from app.domain.collaboration_digest import member_digest, shared_digest
from app.domain.hard_conflicts import DeterministicHardConflictEvaluator
from app.domain.trip_draft import (
    CareDraft,
    CareWalkLimits,
    FieldEvidence,
    TripUnderstandingGatewayResult,
    TripUnderstandingProposal,
)
from app.infrastructure.collaboration_store import SqliteCollaborationRepository
from app.infrastructure.trip_draft_revision_store import (
    AnswerCommand,
    SqliteTripDraftRevisionRepository,
)
from app.main import create_app


FIXTURE = Path(__file__).parent / "fixtures" / "trip_understanding" / "two_participants.json"


def _ready_proposal() -> TripUnderstandingProposal:
    proposal = TripUnderstandingProposal.model_validate_json(
        FIXTURE.read_text(encoding="utf-8"),
        strict=True,
    )
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
        participant.model_copy(update={"care_draft": ordinary})
        for participant in proposal.participants
    ]
    evidence = [*proposal.field_evidence]
    for index, participant in enumerate(participants):
        evidence.extend(
            [
                FieldEvidence(
                    fieldPath=f"participants[{index}].careDraft.assistanceTypeHint",
                    memberKey=participant.member_key,
                    sourceType="USER_TEXT",
                    sourceText="ordinary assistance",
                ),
                FieldEvidence(
                    fieldPath=f"participants[{index}].careDraft.avoidStairs",
                    memberKey=participant.member_key,
                    sourceType="USER_TEXT",
                    sourceText="no stair restriction",
                ),
            ]
        )
    return proposal.model_copy(
        update={
            "trip": proposal.trip.model_copy(update={"budget_cents": 30_000}),
            "participants": participants,
            "field_evidence": evidence,
            "missing_fields": [],
            "confirmation_questions": [],
        }
    )


def _request(*extra: str) -> OrganizerConversationRequest:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    evidence = " ".join(item["sourceText"] for item in fixture["fieldEvidence"])
    natural_language_request = " ".join(
        (evidence, "ordinary assistance no stair restriction", *extra)
    )
    return OrganizerConversationRequest(
        schemaVersion="1.0",
        referenceDate="2026-08-27",
        naturalLanguageRequest=natural_language_request,
        answers=[
            {"questionId": question_id, "answer": natural_language_request}
            for question_id in QUESTION_IDS
        ],
    )


def _participant_payload(
    request: OrganizerConversationRequest,
    *,
    base_revision: int,
    expected_version: int,
) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "baseRevision": base_revision,
        "expectedVersion": expected_version,
        "naturalLanguageRequest": request.natural_language_request,
        "answers": request.model_dump(mode="json", by_alias=True)["answers"],
    }


class SequenceGateway:
    def __init__(self, *results: TripUnderstandingGatewayResult) -> None:
        self.results = list(results)
        self.calls = 0

    async def understand(self, request: Any) -> TripUnderstandingGatewayResult:
        del request
        result = self.results[self.calls]
        self.calls += 1
        return result


def _model_result(
    proposal: TripUnderstandingProposal,
) -> TripUnderstandingGatewayResult:
    return TripUnderstandingGatewayResult(
        decision="MODEL_PROPOSAL",
        proposal=proposal,
        failureCode=None,
        callCount=1,
        model="test-model",
    )


def _fallback_result() -> TripUnderstandingGatewayResult:
    return TripUnderstandingGatewayResult(
        decision="FIXED_QUESTIONS",
        proposal=None,
        failureCode="LLM_TIMEOUT",
        callCount=2,
        model="test-model",
    )


def _app(tmp_path: Path, gateway: SequenceGateway):
    return create_app(
        settings=Settings(
            _env_file=None,
            plan_version_db_path=tmp_path / "planning.sqlite3",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
        ),
        service=object(),  # type: ignore[arg-type]
        trip_understanding_gateway=gateway,
    )


async def _prepare_ready_trip(
    client: httpx.AsyncClient,
    request: OrganizerConversationRequest,
) -> tuple[dict[str, Any], str]:
    created = await client.post(
        "/api/v2/trips/conversations",
        headers={"Idempotency-Key": "p0-ready-create-0001"},
        json=request.model_dump(mode="json", by_alias=True),
    )
    assert created.status_code == 200
    data = created.json()["data"]
    trip_id = data["revision"]["tripId"]
    organizer_token = data["organizerAccess"]["organizerToken"]
    bindings = data["revision"]["memberBindings"]

    first_confirmation = await client.post(
        f"/api/v2/trips/{trip_id}/participants/{bindings['member-1']}/confirm",
        headers={
            "X-Organizer-Token": organizer_token,
            "Idempotency-Key": "p0-ready-confirm-0001",
        },
        json={"schemaVersion": "1.0", "baseRevision": 1, "expectedVersion": 1},
    )
    assert first_confirmation.status_code == 200

    invitation = await client.post(
        f"/api/v2/trips/{trip_id}/participants/{bindings['member-2']}/invitations",
        headers={
            "X-Organizer-Token": organizer_token,
            "Idempotency-Key": "p0-ready-invite-0001",
        },
        json={"schemaVersion": "1.0", "expectedVersion": 2},
    )
    assert invitation.status_code == 200
    token = invitation.json()["data"]["invitationUrl"].split("=", 1)[1]
    redeemed = await client.post(
        "/api/v2/participant-invitations/redeem",
        headers={"Idempotency-Key": "p0-ready-redeem-0001"},
        json={"schemaVersion": "1.0", "token": token},
    )
    assert redeemed.status_code == 200
    member_token = redeemed.json()["data"]["participantSessionToken"]

    second_confirmation = await client.post(
        "/api/v2/member-session/confirm",
        headers={
            "X-Participant-Session": member_token,
            "Idempotency-Key": "p0-ready-confirm-0002",
        },
        json={"schemaVersion": "1.0", "baseRevision": 1, "expectedVersion": 3},
    )
    assert second_confirmation.status_code == 200

    state = await client.get(
        f"/api/v2/trips/{trip_id}/collaboration",
        headers={"X-Organizer-Token": organizer_token},
    )
    assert state.status_code == 200
    assert state.json()["data"]["canPlan"] is True
    return data, member_token


@pytest.mark.asyncio
async def test_member_fallback_remains_fail_closed_until_new_revision_is_confirmed(
    tmp_path: Path,
) -> None:
    ready = _ready_proposal()
    changed = ready.model_copy(
        update={
            "participants": [
                ready.participants[0],
                ready.participants[1].model_copy(update={"budget_cap_cents": 41_000}),
            ]
        }
    )
    gateway = SequenceGateway(
        _model_result(ready),
        _fallback_result(),
        _model_result(changed),
    )
    app = _app(tmp_path, gateway)
    request = _request()
    corrected = _request("member-2 correction")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        created, member_token = await _prepare_ready_trip(client, request)
        trip_id = created["revision"]["tripId"]
        organizer_token = created["organizerAccess"]["organizerToken"]
        fallback_payload = _participant_payload(
            corrected,
            base_revision=1,
            expected_version=4,
        )

        fallback = await client.put(
            "/api/v2/member-session/conversation",
            headers={
                "X-Participant-Session": member_token,
                "Idempotency-Key": "p0-member-fallback-0001",
            },
            json=fallback_payload,
        )
        replay = await client.put(
            "/api/v2/member-session/conversation",
            headers={
                "X-Participant-Session": member_token,
                "Idempotency-Key": "p0-member-fallback-0001",
            },
            json=fallback_payload,
        )
        state_after_fallback = await client.get(
            f"/api/v2/trips/{trip_id}/collaboration",
            headers={"X-Organizer-Token": organizer_token},
        )

    assert fallback.status_code == replay.status_code == 200
    assert fallback.headers["Cache-Control"] == replay.headers["Cache-Control"] == "no-store"
    assert replay.json()["data"] == fallback.json()["data"]
    assert fallback.json()["data"]["canPlan"] is False
    assert state_after_fallback.status_code == 200
    state_data = state_after_fallback.json()["data"]
    assert state_data["canPlan"] is False
    assert {
        item["memberKey"]: item["confirmationStatus"]
        for item in state_data["participants"]
    } == {
        "member-1": "CONFIRMED",
        "member-2": "NEEDS_RECONFIRMATION",
    }
    assert gateway.calls == 2

    repository = app.state.trip_draft_revision_creator.repository
    with repository._connect() as connection:
        assert connection.execute(
            "SELECT pending_revision FROM trip_draft_heads WHERE trip_id=?",
            (trip_id,),
        ).fetchone()[0] is None
        assert connection.execute(
            "SELECT COUNT(*) FROM trip_draft_commands WHERE operation='MEMBER_ANSWER'"
        ).fetchone()[0] == 1
    with app.state.collaboration_service.repository._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_idempotency "
            "WHERE operation='ADVANCE_REVISION'"
        ).fetchone()[0] == 0

    guard = app.state.collaboration_readiness_guard
    body_calls = 0
    access = PlanningAccess(
        trip_id=UUID(trip_id),
        organizer_capability=organizer_token,
        operation_id="p0-member-provider-0001",
        operation=PlanningOperation.PROVIDER_FACTS,
    )
    with pytest.raises(AppError) as blocked:
        with guard.operation(access):
            body_calls += 1
    assert blocked.value.code == "COLLABORATION_NOT_READY"
    assert body_calls == 0

    corrected_payload = _participant_payload(
        corrected,
        base_revision=1,
        expected_version=4,
    )
    corrected_response = await _post_member(
        app,
        member_token,
        "p0-member-corrected-0001",
        corrected_payload,
    )
    assert corrected_response.status_code == 200
    assert corrected_response.json()["data"]["currentRevision"] == 2
    assert gateway.calls == 3

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        reconfirmed = await client.post(
            "/api/v2/member-session/confirm",
            headers={
                "X-Participant-Session": member_token,
                "Idempotency-Key": "p0-member-reconfirm-0001",
            },
            json={"schemaVersion": "1.0", "baseRevision": 2, "expectedVersion": 5},
        )
        final_state = await client.get(
            f"/api/v2/trips/{trip_id}/collaboration",
            headers={"X-Organizer-Token": organizer_token},
        )
    assert reconfirmed.status_code == 200
    assert final_state.json()["data"]["canPlan"] is True


async def _post_member(
    app,
    token: str,
    key: str,
    payload: dict[str, object],
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.put(
            "/api/v2/member-session/conversation",
            headers={
                "X-Participant-Session": token,
                "Idempotency-Key": key,
            },
            json=payload,
        )


def _direct_ready_trip(tmp_path: Path):
    proposal = _ready_proposal()
    revision_repository = SqliteTripDraftRevisionRepository(
        tmp_path / "planning.sqlite3"
    )
    gateway = SequenceGateway(_model_result(proposal))
    revisions = TripDraftRevisionService(
        repository=revision_repository,
        gateway=gateway,
    )
    revision = asyncio.run(
        revisions.create_initial(_request(), idempotency_key="p0-direct-create-0001")
    )
    collaboration_repository = SqliteCollaborationRepository(
        tmp_path / "planning.sqlite3"
    )
    bootstrap = collaboration_repository.bootstrap_collaboration(
        revision,
        "p0-direct-bootstrap-0001",
    )
    version = 1
    for member_key in sorted(revision.member_bindings):
        collaboration_repository.record_confirmation(
            trip_id=revision.trip_id,
            participant_id=revision.member_bindings[member_key],
            revision=revision.revision,
            source_digest=revision.source_digest,
            shared_digest=shared_digest(revision),
            member_digest=member_digest(revision, member_key),
            expected_version=version,
            idempotency_key=f"p0-direct-confirm-{version:04d}",
        )
        version += 1
    service = CollaborationService(
        repository=collaboration_repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    assert service.organizer_state(
        revision.trip_id,
        bootstrap.organizer_token,
    ).can_plan is True
    return (
        revision_repository,
        gateway,
        revisions,
        collaboration_repository,
        service,
        revision,
        bootstrap.organizer_token,
    )


def _submission(label: str) -> ConversationSubmission:
    request = _request(label)
    return ConversationSubmission(
        naturalLanguageRequest=request.natural_language_request,
        answers=request.answers,
    )


def _changed_member(
    proposal: TripUnderstandingProposal,
    member_key: str,
    budget_cap_cents: int,
) -> TripUnderstandingProposal:
    return proposal.model_copy(
        update={
            "participants": [
                participant.model_copy(
                    update={"budget_cap_cents": budget_cap_cents}
                )
                if participant.member_key == member_key
                else participant
                for participant in proposal.participants
            ]
        }
    )


def _advance_direct(
    collaboration_repository: SqliteCollaborationRepository,
    revision,
    revised,
    participant_id: UUID,
    key: str,
) -> None:
    stored = collaboration_repository.get_stored(revision.trip_id)
    collaboration_repository.advance_revision(
        trip_id=revision.trip_id,
        before_revision=revision.revision,
        after_revision=revised.revision,
        expected_version=stored.version,
        actor_scope="PARTICIPANT",
        actor_id=str(participant_id),
        idempotency_key=key,
    )


def _reconfirm_direct(
    collaboration_repository: SqliteCollaborationRepository,
    revised,
    member_key: str,
    key: str,
) -> None:
    stored = collaboration_repository.get_stored(revised.trip_id)
    collaboration_repository.record_confirmation(
        trip_id=revised.trip_id,
        participant_id=revised.member_bindings[member_key],
        revision=revised.revision,
        source_digest=revised.source_digest,
        shared_digest=shared_digest(revised),
        member_digest=member_digest(revised, member_key),
        expected_version=stored.version,
        idempotency_key=key,
    )


@pytest.mark.parametrize(
    ("failed_scope", "success_member", "expected_statuses"),
    [
        (
            "member",
            "member-1",
            {"member-1": "CONFIRMED", "member-2": "NEEDS_RECONFIRMATION"},
        ),
        (
            "shared",
            "member-1",
            {"member-1": "NEEDS_RECONFIRMATION", "member-2": "NEEDS_RECONFIRMATION"},
        ),
    ],
)
def test_unrelated_same_target_revision_does_not_clear_failed_answer_attempt(
    tmp_path: Path,
    failed_scope: str,
    success_member: str,
    expected_statuses: dict[str, str],
) -> None:
    (
        revision_repository,
        gateway,
        revisions,
        collaboration_repository,
        service,
        revision,
        organizer_token,
    ) = _direct_ready_trip(tmp_path)
    member_1 = revision.member_bindings["member-1"]
    member_2 = revision.member_bindings["member-2"]

    if failed_scope == "member":
        gateway.results.append(_fallback_result())
        failed = asyncio.run(
            revisions.submit_participant_conversation(
                trip_id=revision.trip_id,
                participant_id=member_2,
                base_revision=1,
                submission=_submission("member-2 failed correction"),
                idempotency_key="p0-unrelated-member-fail-0001",
            )
        )
        assert getattr(failed, "answer_revision") == 2
    else:
        claim = revision_repository.claim_next(
            AnswerCommand(
                actor_scope="SYSTEM",
                actor_id="ORGANIZER",
                operation="ORGANIZER_ANSWER",
                idempotency_key="p0-unrelated-shared-fail-0001",
                request_digest="e" * 64,
            ),
            draft_id=revision.draft_id,
            trip_id=revision.trip_id,
            base_revision=revision.revision,
        )
        revision_repository.fail(claim, code="LLM_TIMEOUT")

    gateway.results.append(
        _model_result(
            _changed_member(
                revision.understanding,
                success_member,
                51_000 if success_member == "member-1" else 41_000,
            )
        )
    )
    succeeded = asyncio.run(
        revisions.submit_participant_conversation(
            trip_id=revision.trip_id,
            participant_id=member_1,
            base_revision=1,
            submission=_submission("member-1 unrelated success"),
            idempotency_key="p0-unrelated-success-0001",
        )
    )
    _advance_direct(
        collaboration_repository,
        revision,
        succeeded,
        member_1,
        "p0-unrelated-advance-0001",
    )
    _reconfirm_direct(
        collaboration_repository,
        succeeded,
        "member-1",
        "p0-unrelated-reconfirm-0001",
    )

    state = service.organizer_state(revision.trip_id, organizer_token)
    assert state.can_plan is False
    assert {
        item.member_key: item.confirmation_status.value
        for item in state.participants
    } == expected_statuses
    assert gateway.calls == (3 if failed_scope == "member" else 2)


def test_same_actor_success_clears_only_that_actor_failed_answer_attempt(
    tmp_path: Path,
) -> None:
    (
        _revision_repository,
        gateway,
        revisions,
        collaboration_repository,
        service,
        revision,
        organizer_token,
    ) = _direct_ready_trip(tmp_path)
    member_2 = revision.member_bindings["member-2"]
    gateway.results.append(_fallback_result())
    asyncio.run(
        revisions.submit_participant_conversation(
            trip_id=revision.trip_id,
            participant_id=member_2,
            base_revision=1,
            submission=_submission("member-2 failed correction"),
            idempotency_key="p0-same-actor-fail-0001",
        )
    )
    gateway.results.append(
        _model_result(_changed_member(revision.understanding, "member-2", 41_000))
    )
    succeeded = asyncio.run(
        revisions.submit_participant_conversation(
            trip_id=revision.trip_id,
            participant_id=member_2,
            base_revision=1,
            submission=_submission("member-2 retry correction"),
            idempotency_key="p0-same-actor-success-0001",
        )
    )
    _advance_direct(
        collaboration_repository,
        revision,
        succeeded,
        member_2,
        "p0-same-actor-advance-0001",
    )
    _reconfirm_direct(
        collaboration_repository,
        succeeded,
        "member-2",
        "p0-same-actor-reconfirm-0001",
    )

    state = service.organizer_state(revision.trip_id, organizer_token)
    assert state.can_plan is True
    assert gateway.calls == 3


def test_unresolved_system_answer_failure_blocks_all_ready_participants(
    tmp_path: Path,
) -> None:
    proposal = _ready_proposal()
    request = _request()

    revision_repository = SqliteTripDraftRevisionRepository(
        tmp_path / "planning.sqlite3"
    )
    gateway = SequenceGateway(_model_result(proposal))
    revisions = TripDraftRevisionService(
        repository=revision_repository,
        gateway=gateway,
    )
    revision = asyncio.run(
        revisions.create_initial(request, idempotency_key="p0-system-create-0001")
    )
    collaboration_repository = SqliteCollaborationRepository(
        tmp_path / "planning.sqlite3"
    )
    bootstrap = collaboration_repository.bootstrap_collaboration(
        revision,
        "p0-system-bootstrap-01",
    )
    version = 1
    for member_key in sorted(revision.member_bindings):
        collaboration_repository.record_confirmation(
            trip_id=revision.trip_id,
            participant_id=revision.member_bindings[member_key],
            revision=revision.revision,
            source_digest=revision.source_digest,
            shared_digest=shared_digest(revision),
            member_digest=member_digest(revision, member_key),
            expected_version=version,
            idempotency_key=f"p0-system-confirm-{version:04d}",
        )
        version += 1
    service = CollaborationService(
        repository=collaboration_repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    assert service.organizer_state(
        revision.trip_id,
        bootstrap.organizer_token,
    ).can_plan is True

    claim = revision_repository.claim_next(
        AnswerCommand(
            actor_scope="SYSTEM",
            actor_id="ORGANIZER",
            operation="ORGANIZER_ANSWER",
            idempotency_key="p0-system-fallback-0001",
            request_digest="f" * 64,
        ),
        draft_id=revision.draft_id,
        trip_id=revision.trip_id,
        base_revision=revision.revision,
    )
    revision_repository.fail(claim, code="LLM_TIMEOUT")

    state = service.organizer_state(revision.trip_id, bootstrap.organizer_token)
    assert state.can_plan is False
    assert {
        item.confirmation_status.value for item in state.participants
    } == {"NEEDS_RECONFIRMATION"}
