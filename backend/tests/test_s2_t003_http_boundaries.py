from __future__ import annotations

import httpx
import pytest

from app.api.collaboration_routes import router
from app.application.collaboration_ports import UnavailableTripDraftRevisionPort
from app.domain.collaboration import IssueCode, QUESTION_IDS, ResolveConfirmationItemRequest
from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.collaboration_store import SqliteCollaborationRepository
from app.main import create_app
from backend.tests.s2_t003_support import (
    FakeTripDraftRevisionPort,
    load_revision,
    revision_with_trip_budget,
)
from backend.tests.test_s2_t003_collaboration_service import (
    _AdvancingRevisionPort,
    _ready_harness,
)


def test_collaboration_route_table_contains_only_scoped_frozen_paths() -> None:
    paths = {(route.path, method) for route in router.routes for method in route.methods}
    expected = {
        ("/api/v2/trips/conversations", "POST"),
        ("/api/v2/trips/{trip_id}/participants/{participant_id}/invitations", "POST"),
        ("/api/v2/participant-invitations/redeem", "POST"),
        ("/api/v2/member-session", "GET"),
        ("/api/v2/member-session/conversation", "PUT"),
        ("/api/v2/member-session/confirm", "POST"),
        ("/api/v2/member-session/confirmation-items/{item_id}/resolve", "POST"),
        ("/api/v2/trips/{trip_id}/participants/{participant_id}/confirm", "POST"),
        ("/api/v2/trips/{trip_id}/collaboration", "GET"),
        ("/api/v2/trips/{trip_id}/confirmation-items/{item_id}/resolve", "POST"),
        ("/api/v2/trips/{trip_id}/participants/{participant_id}/invitations/{invitation_id}", "DELETE"),
    }
    assert expected <= paths
    assert not any("{token}" in path for path, _ in paths)
    assert not any("/conflicts/" in path for path, _ in paths)


@pytest.mark.asyncio
async def test_organizer_confirm_success_and_replay_responses_are_no_store(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    app = create_app(
        settings=Settings(
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=tmp_path / "plan.sqlite3",
        ),
        collaboration_repository=harness.repository,
        trip_draft_revision_port=harness.revisions,
    )
    participant_id = harness.revision.member_bindings["member-1"]
    path = (
        f"/api/v2/trips/{harness.revision.trip_id}/participants/"
        f"{participant_id}/confirm"
    )
    payload = {
        "schemaVersion": "1.0",
        "baseRevision": 1,
        "expectedVersion": 3,
    }
    headers = {
        "X-Organizer-Token": harness.organizer_token,
        "Idempotency-Key": "d020-organizer-confirm",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        first = await client.post(path, headers=headers, json=payload)
        replay = await client.post(path, headers=headers, json=payload)

    assert first.status_code == replay.status_code == 200
    assert first.headers["Cache-Control"] == "no-store"
    assert replay.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "target", "method", "payload", "headers"),
    [
        (
            "/api/v2/trips/conversations",
            "trip_draft_revision_creator",
            "create_initial",
            {
                "schemaVersion": "1.0",
                "referenceDate": "2026-08-27",
                "naturalLanguageRequest": "busy",
                "answers": [
                    {"questionId": question_id, "answer": "busy"}
                    for question_id in QUESTION_IDS
                ],
            },
            {"Idempotency-Key": "d020-organizer-conversation"},
        ),
        (
            "/api/v2/member-session/conversation",
            "collaboration_service",
            "submit_member",
            {
                "schemaVersion": "1.0",
                "baseRevision": 1,
                "expectedVersion": 1,
                "naturalLanguageRequest": "busy",
                "answers": [
                    {"questionId": question_id, "answer": "busy"}
                    for question_id in QUESTION_IDS
                ],
            },
            {
                "X-Participant-Session": "session-for-test",
                "Idempotency-Key": "d020-member-conversation",
            },
        ),
        (
            "/api/v2/trips/30000000-0000-4000-8000-000000000001/participants/"
            "10000000-0000-4000-8000-000000000001/confirm",
            "collaboration_service",
            "confirm_organizer",
            {"schemaVersion": "1.0", "baseRevision": 1, "expectedVersion": 1},
            {
                "X-Organizer-Token": "organizer-for-test",
                "Idempotency-Key": "d020-organizer-confirm-error",
            },
        ),
    ],
)
async def test_conversation_and_confirm_in_progress_errors_are_no_store(
    tmp_path,
    monkeypatch,
    path,
    target,
    method,
    payload,
    headers,
) -> None:
    app = create_app(
        settings=Settings(
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=tmp_path / "plan.sqlite3",
        ),
        trip_draft_revision_port=UnavailableTripDraftRevisionPort(),
    )

    def fail_in_progress(*args, **kwargs):
        raise AppError(
            "COLLABORATION_OPERATION_IN_PROGRESS",
            "operation is already in progress",
            409,
            True,
        )

    monkeypatch.setattr(getattr(app.state, target), method, fail_in_progress)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.request("POST" if method != "submit_member" else "PUT", path, headers=headers, json=payload)

    assert response.status_code == 409
    assert response.json()["code"] == "COLLABORATION_OPERATION_IN_PROGRESS"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_revoke_http_converges_when_t002_is_unavailable(tmp_path) -> None:
    revision = load_revision()
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    bootstrap = repository.bootstrap_collaboration(revision, "bootstrap-revoke-0001")
    assert bootstrap.organizer_token is not None
    invitation = repository.create_invitation(
        trip_id=revision.trip_id,
        participant_id=revision.member_bindings["member-2"],
        organizer_token=bootstrap.organizer_token,
        expected_version=1,
        idempotency_key="invite-revoke-0001",
    )
    app = create_app(
        settings=Settings(
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=tmp_path / "plan.sqlite3",
        ),
        collaboration_repository=repository,
        trip_draft_revision_port=UnavailableTripDraftRevisionPort(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.delete(
            f"/api/v2/trips/{revision.trip_id}/participants/"
            f"{revision.member_bindings['member-2']}/invitations/{invitation.invitation_id}",
            params={"expectedVersion": 2},
            headers={
                "X-Organizer-Token": bootstrap.organizer_token,
                "Idempotency-Key": "revoke-http-0001",
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["accessStatus"] == "REVOKED"


@pytest.mark.asyncio
async def test_redeem_retry_returns_metadata_without_replaying_session_secret(tmp_path) -> None:
    revision = load_revision()
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    bootstrap = repository.bootstrap_collaboration(revision, "bootstrap-redeem-0001")
    assert bootstrap.organizer_token is not None
    invitation = repository.create_invitation(
        trip_id=revision.trip_id,
        participant_id=revision.member_bindings["member-2"],
        organizer_token=bootstrap.organizer_token,
        expected_version=1,
        idempotency_key="invite-redeem-0001",
    )
    assert invitation.invitation_url is not None
    app = create_app(
        settings=Settings(
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=tmp_path / "plan.sqlite3",
        ),
        collaboration_repository=repository,
        trip_draft_revision_port=FakeTripDraftRevisionPort(revision),
    )
    payload = {
        "schemaVersion": "1.0",
        "token": invitation.invitation_url.split("=", 1)[1],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        first = await client.post(
            "/api/v2/participant-invitations/redeem",
            headers={"Idempotency-Key": "redeem-http-0001"},
            json=payload,
        )
        replay = await client.post(
            "/api/v2/participant-invitations/redeem",
            headers={"Idempotency-Key": "redeem-http-0001"},
            json=payload,
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    first_data = first.json()["data"]
    replay_data = replay.json()["data"]
    assert first_data["participantSessionToken"]
    assert replay_data["participantSessionToken"] is None
    assert replay_data["sessionTokenAvailable"] is False
    assert replay_data["sessionId"] == first_data["sessionId"]


@pytest.mark.asyncio
async def test_resolve_authentication_failures_are_json_contract_errors(tmp_path) -> None:
    revision = load_revision()
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    app = create_app(
        settings=Settings(
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=tmp_path / "plan.sqlite3",
        ),
        collaboration_repository=repository,
        trip_draft_revision_port=FakeTripDraftRevisionPort(revision),
    )
    payload = {
        "schemaVersion": "1.0",
        "baseRevision": 1,
        "expectedVersion": 1,
        "relaxationId": "rx_0000000000000000",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        member_response = await client.post(
            f"/api/v2/member-session/confirmation-items/ci_0000000000000000/resolve",
            headers={
                "X-Participant-Session": "forged-member-session",
                "Idempotency-Key": "resolve-auth-member-01",
            },
            json=payload,
        )
        organizer_response = await client.post(
            f"/api/v2/trips/{revision.trip_id}/confirmation-items/"
            "ci_0000000000000000/resolve",
            headers={
                "X-Organizer-Token": "forged-organizer-token",
                "Idempotency-Key": "resolve-auth-organizer-01",
            },
            json=payload,
        )

    assert member_response.status_code == 401
    assert member_response.headers["content-type"].startswith("application/json")
    assert member_response.json()["code"] == "PARTICIPANT_SESSION_REQUIRED"
    assert organizer_response.status_code == 403
    assert organizer_response.headers["content-type"].startswith("application/json")
    assert organizer_response.json()["code"] == "ORGANIZER_PERMISSION_REQUIRED"


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ("organizer", "member"))
async def test_resolve_success_and_replay_responses_are_no_store(tmp_path, scope) -> None:
    case_root = tmp_path / scope
    case_root.mkdir()
    harness = _ready_harness(case_root)
    conflict = revision_with_trip_budget(harness.revision, 45_000)
    revisions = _AdvancingRevisionPort(conflict)
    app = create_app(
        settings=Settings(
            amap_web_service_key="test-amap",
            amap_cache_db_path=case_root / "amap.sqlite3",
            plan_version_db_path=case_root / "plan.sqlite3",
        ),
        collaboration_repository=harness.repository,
        trip_draft_revision_port=revisions,
    )
    state = app.state.collaboration_service.organizer_state(
        harness.revision.trip_id,
        harness.organizer_token,
    )
    issue = next(item for item in state.confirmation_items if item.code is IssueCode.CONFLICT)
    if scope == "organizer":
        option = next(item for item in issue.relaxations if item.actor_scope.value == "ORGANIZER")
        path = (
            f"/api/v2/trips/{harness.revision.trip_id}/confirmation-items/"
            f"{issue.item_id}/resolve"
        )
        headers = {
            "X-Organizer-Token": harness.organizer_token,
            "Idempotency-Key": "d018-organizer-resolve-1",
        }
        expected_version = 3
    else:
        option = next(
            item
            for item in issue.relaxations
            if item.actor_scope.value == "PARTICIPANT"
            and item.participant_id == harness.revision.member_bindings["member-2"]
        )
        invitation = harness.repository.create_invitation(
            trip_id=harness.revision.trip_id,
            participant_id=harness.revision.member_bindings["member-2"],
            organizer_token=harness.organizer_token,
            expected_version=3,
            idempotency_key="d018-member-invite-1",
        )
        redeemed = harness.repository.redeem_invitation(
            invitation.invitation_url.split("=", 1)[1],
            "d018-member-redeem-1",
        )
        assert redeemed.participant_session_token is not None
        path = f"/api/v2/member-session/confirmation-items/{issue.item_id}/resolve"
        headers = {
            "X-Participant-Session": redeemed.participant_session_token,
            "Idempotency-Key": "d018-member-resolve-1",
        }
        expected_version = 4
    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=expected_version,
        relaxationId=option.relaxation_id,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        first = await client.post(
            path,
            headers=headers,
            json=request.model_dump(mode="json", by_alias=True),
        )
        replay = await client.post(
            path,
            headers=headers,
            json=request.model_dump(mode="json", by_alias=True),
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.headers["Cache-Control"] == "no-store"
    assert replay.headers["Cache-Control"] == "no-store"
    assert first.json()["data"] == replay.json()["data"]
