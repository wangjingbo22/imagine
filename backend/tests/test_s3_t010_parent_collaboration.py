from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app


def settings(database_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        plan_version_db_path=database_path,
        amap_cache_db_path=database_path.with_name("amap.sqlite3"),
    )


async def create_parent(
    client: httpx.AsyncClient,
    *,
    parent_id: str,
    organizer_token: str,
) -> None:
    response = await client.post(
        "/api/v3/parent-trips",
        headers={"X-Parent-Trip-Token": organizer_token},
        json={
            "schemaVersion": "1.0",
            "parentTripId": parent_id,
            "title": "杭州周末同行",
            "cityName": "杭州",
            "startDate": "2026-09-12",
            "dayBudgetCents": [40_000, 60_000],
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"


async def invite(
    client: httpx.AsyncClient,
    *,
    parent_id: str,
    organizer_token: str,
    expected_version: int,
    idempotency_key: str,
) -> httpx.Response:
    return await client.post(
        f"/api/v3/parent-trips/{parent_id}/invitations",
        headers={
            "X-Parent-Trip-Token": organizer_token,
            "Idempotency-Key": idempotency_key,
        },
        json={
            "schemaVersion": "1.0",
            "expectedSyncVersion": expected_version,
            "expiresInHours": 72,
        },
    )


async def redeem(
    client: httpx.AsyncClient,
    invitation_token: str,
    idempotency_key: str,
) -> dict[str, object]:
    response = await client.post(
        "/api/v3/parent-trip-invitations/redeem",
        headers={"Idempotency-Key": idempotency_key},
        json={"schemaVersion": "1.0", "token": invitation_token},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()["data"]


@pytest.mark.asyncio
async def test_three_people_poll_with_isolated_profiles_and_version_guard(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "parent-collaboration.sqlite3"
    app = create_app(settings=settings(database_path))
    parent_id = str(uuid4())
    organizer_token = "parent-organizer-token-0123456789abcdef"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await create_parent(
            client,
            parent_id=parent_id,
            organizer_token=organizer_token,
        )
        initial = await client.get(
            f"/api/v3/parent-trips/{parent_id}/sync",
            headers={"X-Parent-Trip-Token": organizer_token},
        )
        assert initial.status_code == 200, initial.text
        initial_sync = initial.json()["data"]
        assert initial_sync["syncVersion"] == 1
        assert initial_sync["pollAfterSeconds"] == 5
        assert initial_sync["viewerRole"] == "ORGANIZER"
        assert len(initial_sync["visibleProfiles"]) == 1
        assert initial_sync["parentTrip"]["totalBudgetCents"] == 100_000
        assert [
            day["childStatus"] for day in initial_sync["parentTrip"]["days"]
        ] == ["NOT_CREATED", "NOT_CREATED"]

        first_invite = await invite(
            client,
            parent_id=parent_id,
            organizer_token=organizer_token,
            expected_version=1,
            idempotency_key="invite-member-one-0001",
        )
        assert first_invite.status_code == 200, first_invite.text
        first_data = first_invite.json()["data"]
        first_replay = await invite(
            client,
            parent_id=parent_id,
            organizer_token=organizer_token,
            expected_version=1,
            idempotency_key="invite-member-one-0001",
        )
        assert first_replay.status_code == 200, first_replay.text
        assert first_replay.json()["data"]["invitationUrl"] == first_data[
            "invitationUrl"
        ]

        second_invite = await invite(
            client,
            parent_id=parent_id,
            organizer_token=organizer_token,
            expected_version=2,
            idempotency_key="invite-member-two-0002",
        )
        assert second_invite.status_code == 200, second_invite.text
        second_data = second_invite.json()["data"]
        limit = await invite(
            client,
            parent_id=parent_id,
            organizer_token=organizer_token,
            expected_version=3,
            idempotency_key="invite-member-three-003",
        )
        assert limit.status_code == 409
        assert limit.json()["code"] == "PARENT_TRIP_MEMBER_LIMIT"
        assert limit.headers["cache-control"] == "no-store"

        first_token = str(first_data["invitationUrl"]).rsplit("/", 1)[-1]
        second_token = str(second_data["invitationUrl"]).rsplit("/", 1)[-1]
        first_member = await redeem(
            client,
            first_token,
            "redeem-member-one-0001",
        )
        first_member_replay = await redeem(
            client,
            first_token,
            "redeem-member-one-0001",
        )
        assert first_member_replay["sessionId"] == first_member["sessionId"]
        assert (
            first_member_replay["memberSessionToken"]
            == first_member["memberSessionToken"]
        )
        consumed = await client.post(
            "/api/v3/parent-trip-invitations/redeem",
            headers={"Idempotency-Key": "redeem-member-one-other"},
            json={"schemaVersion": "1.0", "token": first_token},
        )
        assert consumed.status_code == 409
        assert consumed.json()["code"] == "PARENT_INVITATION_ALREADY_REDEEMED"
        second_member = await redeem(
            client,
            second_token,
            "redeem-member-two-0002",
        )
        assert first_member["participantId"] != second_member["participantId"]

        first_session = str(first_member["memberSessionToken"])
        second_session = str(second_member["memberSessionToken"])
        first_updated = await client.put(
            f"/api/v3/parent-trips/{parent_id}/member-profile",
            headers={"X-Parent-Member-Session": first_session},
            json={
                "schemaVersion": "1.0",
                "expectedSyncVersion": 5,
                "nickname": "小林",
                "interests": ["园林", "摄影"],
                "budgetCapCents": 80_000,
            },
        )
        assert first_updated.status_code == 200, first_updated.text
        first_view = first_updated.json()["data"]
        assert first_view["syncVersion"] == 6
        assert len(first_view["visibleProfiles"]) == 1
        assert first_view["visibleProfiles"][0]["nickname"] == "小林"
        assert "待加入成员 2" not in first_updated.text

        second_updated = await client.put(
            f"/api/v3/parent-trips/{parent_id}/member-profile",
            headers={"X-Parent-Member-Session": second_session},
            json={
                "schemaVersion": "1.0",
                "expectedSyncVersion": 6,
                "nickname": "阿岚",
                "interests": ["美食"],
                "budgetCapCents": 60_000,
            },
        )
        assert second_updated.status_code == 200, second_updated.text
        second_view = second_updated.json()["data"]
        assert len(second_view["visibleProfiles"]) == 1
        assert second_view["visibleProfiles"][0]["nickname"] == "阿岚"
        assert "小林" not in second_updated.text

        stale = await client.put(
            f"/api/v3/parent-trips/{parent_id}/member-profile",
            headers={"X-Parent-Member-Session": first_session},
            json={
                "schemaVersion": "1.0",
                "expectedSyncVersion": 6,
                "nickname": "旧版本修改",
                "interests": [],
                "budgetCapCents": None,
            },
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "PARENT_TRIP_VERSION_CONFLICT"

        organizer_view = await client.get(
            f"/api/v3/parent-trips/{parent_id}/sync",
            headers={"X-Parent-Trip-Token": organizer_token},
        )
        assert organizer_view.status_code == 200, organizer_view.text
        organizer_sync = organizer_view.json()["data"]
        assert organizer_sync["syncVersion"] == 7
        assert [
            profile["nickname"] for profile in organizer_sync["visibleProfiles"]
        ] == ["组织者", "小林", "阿岚"]
        assert first_token not in organizer_view.text
        assert first_session not in organizer_view.text
        assert second_session not in organizer_view.text
        stored_database = database_path.read_bytes()
        for secret in (
            organizer_token,
            first_token,
            second_token,
            first_session,
            second_session,
        ):
            assert secret.encode("ascii") not in stored_database

        ambiguous = await client.get(
            f"/api/v3/parent-trips/{parent_id}/sync",
            headers={
                "X-Parent-Trip-Token": organizer_token,
                "X-Parent-Member-Session": first_session,
            },
        )
        assert ambiguous.status_code == 401
        assert ambiguous.json()["code"] == "PARENT_AUTH_CONTEXT_INVALID"

    restarted = create_app(settings=settings(database_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=restarted),
        base_url="http://test",
    ) as client:
        restored = await client.get(
            f"/api/v3/parent-trips/{parent_id}/sync",
            headers={"X-Parent-Member-Session": first_session},
        )
        assert restored.status_code == 200, restored.text
        restored_sync = restored.json()["data"]
        assert restored_sync["syncVersion"] == 7
        assert restored_sync["visibleProfiles"][0]["nickname"] == "小林"
        assert restored_sync["parentTrip"]["days"][0]["budgetCents"] == 40_000
