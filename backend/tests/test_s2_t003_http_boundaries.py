from __future__ import annotations

import httpx
import pytest

from app.api.collaboration_routes import router
from app.application.collaboration_ports import UnavailableTripDraftRevisionPort
from app.core.config import Settings
from app.infrastructure.collaboration_store import SqliteCollaborationRepository
from app.main import create_app
from backend.tests.s2_t003_support import FakeTripDraftRevisionPort, load_revision


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
