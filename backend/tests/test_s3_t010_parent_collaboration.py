import sqlite3
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app
from app.infrastructure.parent_trip_store import SqliteParentTripRepository


PASSWORD = "correct-horse-battery-staple"


def settings(database_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        plan_version_db_path=database_path,
        amap_cache_db_path=database_path.with_name("amap.sqlite3"),
        account_session_db_path=database_path.with_name("accounts.sqlite3"),
    )


async def register_account(
    client: httpx.AsyncClient,
    *,
    email: str,
    display_name: str,
    interests: list[str],
) -> dict[str, object]:
    registered = await client.post(
        "/api/v1/account/register",
        json={
            "email": email,
            "password": PASSWORD,
            "displayName": display_name,
        },
    )
    assert registered.status_code == 200, registered.text
    updated = await client.put(
        "/api/v1/account/me/profile",
        json={
            "displayName": display_name,
            "homeCity": "杭州",
            "interests": interests,
        },
    )
    assert updated.status_code == 200, updated.text
    return updated.json()["data"]


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
            "startDate": (date.today() + timedelta(days=11)).isoformat(),
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
        "/api/v1/account/parent-trip-invitations/redeem",
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
        unauthenticated = await client.post(
            "/api/v1/account/parent-trip-invitations/redeem",
            headers={"Idempotency-Key": "redeem-member-no-account"},
            json={"schemaVersion": "1.0", "token": first_token},
        )
        assert unauthenticated.status_code == 401
        assert unauthenticated.json()["code"] == "ACCOUNT_SESSION_REQUIRED"
        legacy_redeem = await client.post(
            "/api/v3/parent-trip-invitations/redeem",
            headers={"Idempotency-Key": "redeem-member-legacy-path"},
            json={"schemaVersion": "1.0", "token": first_token},
        )
        assert legacy_redeem.status_code == 404

        first_account = await register_account(
            client,
            email="xiaolin@example.com",
            display_name="小林账号",
            interests=["园林", "摄影"],
        )
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
        first_initial = await client.get(
            f"/api/v3/parent-trips/{parent_id}/sync",
            headers={
                "X-Parent-Member-Session": str(first_member["memberSessionToken"])
            },
        )
        assert first_initial.status_code == 200, first_initial.text
        assert first_initial.json()["data"]["visibleProfiles"][0]["nickname"] == "小林账号"
        assert first_initial.json()["data"]["visibleProfiles"][0]["interests"] == [
            "园林",
            "摄影",
        ]
        duplicate_account = await client.post(
            "/api/v1/account/parent-trip-invitations/redeem",
            headers={"Idempotency-Key": "redeem-member-two-duplicate"},
            json={"schemaVersion": "1.0", "token": second_token},
        )
        assert duplicate_account.status_code == 409
        assert duplicate_account.json()["code"] == "PARENT_ACCOUNT_ALREADY_MEMBER"
        consumed = await client.post(
            "/api/v1/account/parent-trip-invitations/redeem",
            headers={"Idempotency-Key": "redeem-member-one-other"},
            json={"schemaVersion": "1.0", "token": first_token},
        )
        assert consumed.status_code == 409
        assert consumed.json()["code"] == "PARENT_INVITATION_ALREADY_REDEEMED"

        logged_out = await client.post("/api/v1/account/logout")
        assert logged_out.status_code == 200
        second_account = await register_account(
            client,
            email="alan@example.com",
            display_name="阿岚账号",
            interests=["美食"],
        )
        mismatched_replay = await client.post(
            "/api/v1/account/parent-trip-invitations/redeem",
            headers={"Idempotency-Key": "redeem-member-one-0001"},
            json={"schemaVersion": "1.0", "token": first_token},
        )
        assert mismatched_replay.status_code == 403
        assert mismatched_replay.json()["code"] == "PARENT_INVITATION_ACCOUNT_MISMATCH"
        second_member = await redeem(
            client,
            second_token,
            "redeem-member-two-0002",
        )
        assert first_member["participantId"] != second_member["participantId"]
        assert first_account["userId"] != second_account["userId"]

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
        with sqlite3.connect(database_path) as connection:
            account_bindings = connection.execute(
                """SELECT account_user_id FROM parent_trip_members
                WHERE parent_trip_id=? AND role='MEMBER'
                ORDER BY participant_id""",
                (parent_id,),
            ).fetchall()
        assert {row[0] for row in account_bindings} == {
            first_account["userId"],
            second_account["userId"],
        }

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


def test_existing_parent_collaboration_database_migrates_account_binding(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-parent.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("""CREATE TABLE parent_trip_members (
            parent_trip_id TEXT NOT NULL,
            participant_id TEXT NOT NULL,
            role TEXT NOT NULL,
            access_status TEXT NOT NULL,
            nickname TEXT NOT NULL,
            interests_json TEXT NOT NULL,
            budget_cap_cents INTEGER,
            profile_version INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(parent_trip_id, participant_id)
        )""")

    SqliteParentTripRepository(database_path)

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(parent_trip_members)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(parent_trip_members)")
        }
    assert "account_user_id" in columns
    assert "ux_parent_trip_members_parent_account" in indexes
