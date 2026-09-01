from __future__ import annotations

import sqlite3
from datetime import date
from uuid import UUID, uuid4

import pytest

from app.domain.collaboration import (
    CollaborationStatus,
    ConversationAnswer,
    ConversationSubmission,
    QUESTION_IDS,
    TripFlowKind,
)
from app.infrastructure.collaboration_store import (
    CollaborationStoreError,
    SqliteCollaborationRepository,
)
from app.infrastructure.trip_flow_store import SqliteTripFlowRegistry
from app.schemas.trip import CreateSingleDayTrip


LEGACY_TRIP_ID = UUID("30000000-0000-4000-8000-000000000001")


def create_baseline_collaboration_schema(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE collaboration_sessions (
            trip_id TEXT PRIMARY KEY,
            organizer_participant_id TEXT NOT NULL,
            status TEXT NOT NULL,
            expected_participants INTEGER NOT NULL DEFAULT 1,
            organizer_token_hash TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE collaboration_participants (
            trip_id TEXT NOT NULL,
            participant_id TEXT NOT NULL,
            display_name TEXT,
            status TEXT NOT NULL,
            is_organizer INTEGER NOT NULL,
            parsed_json TEXT,
            PRIMARY KEY (trip_id, participant_id)
        );
        CREATE TABLE participant_invitations (
            token_hash TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL,
            participant_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            accepted_at TEXT
        );
        CREATE TABLE collaboration_conflict_resolutions (
            trip_id TEXT NOT NULL,
            conflict_id TEXT NOT NULL,
            relaxation TEXT NOT NULL,
            resolved_at TEXT NOT NULL,
            PRIMARY KEY (trip_id, conflict_id)
        );
        INSERT INTO collaboration_participants
            (trip_id, participant_id, display_name, status, is_organizer, parsed_json)
        VALUES
            ('30000000-0000-4000-8000-000000000001',
             '10000000-0000-4000-8000-000000000001',
             'legacy', 'CONFIRMED', 1, '{"cityName":"Shanghai"}');
        """
    )
    connection.commit()
    connection.close()


def test_fixed_six_questions_must_be_complete_and_ordered() -> None:
    answers = [
        ConversationAnswer(questionId=question, answer="已回答")
        for question in (
            "trip", "party", "endpoints_budget", "preferences", "assistance", "confirm"
        )
    ]
    submission = ConversationSubmission(
        naturalLanguageRequest="北京一日游",
        answers=answers,
    )
    assert submission.participant_count == 1


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("2个人出行；组织者昵称：张三", 2),
        ("三人同行；组织者昵称：小二", 3),
        ("1个人出行；组织者昵称：两两", 1),
        ("12个人出行；组织者昵称：领队", 12),
    ],
)
def test_party_count_comes_from_the_party_phrase_not_the_nickname(
    answer: str,
    expected: int,
) -> None:
    answers = [
        ConversationAnswer(questionId=question, answer="已回答")
        for question in QUESTION_IDS
    ]
    answers[1] = ConversationAnswer(questionId="party", answer=answer)
    submission = ConversationSubmission(
        naturalLanguageRequest="测试同行人数",
        answers=answers,
    )

    assert submission.participant_count == expected
    assert "【个人偏好（兴趣与地点限制）】" in submission.transcript
    assert "preferences:" not in submission.transcript
    with pytest.raises(ValueError):
        ConversationSubmission(
            naturalLanguageRequest="北京一日游",
            answers=list(reversed(answers)),
        )


def test_current_baseline_database_migrates_without_losing_rows(tmp_path) -> None:
    path = tmp_path / "collaboration.sqlite3"
    create_baseline_collaboration_schema(path)
    SqliteCollaborationRepository(path)
    repository = SqliteCollaborationRepository(path)
    with repository._connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "trip_flow_registry",
            "collaboration_actor_sessions",
            "collaboration_idempotency",
            "collaboration_resolution_audit",
            "collaboration_operation_leases",
        } <= tables
        assert connection.execute(
            "SELECT parsed_json FROM collaboration_participants"
        ).fetchone() is not None


def test_unknown_flow_never_defaults_to_legacy(tmp_path) -> None:
    registry = SqliteTripFlowRegistry(tmp_path / "flow.sqlite3")
    assert registry.get(uuid4()) is None


def test_migration_backfills_strict_confirmed_singles_only(tmp_path) -> None:
    path = tmp_path / "workflow.sqlite3"
    single = CreateSingleDayTrip(
        schemaVersion="1.0",
        tripId=UUID("30000000-0000-4000-8000-000000000002"),
        mode="SINGLE",
        status="DRAFT",
        cityContext={
            "countryCode": "CN",
            "cityCode": "SHA",
            "cityName": "Shanghai",
            "center": {"longitude": 121.47, "latitude": 31.23},
            "providerConfig": {"provider": "AMAP", "coordinateSystem": "GCJ02"},
        },
        startDate=date(2026, 8, 27),
        endDate=date(2026, 8, 27),
        currency="CNY",
        totalBudgetCents=10000,
        participants=[
            {
                "participantId": UUID("10000000-0000-4000-8000-000000000002"),
                "nickname": "legacy",
                "budgetCapCents": 10000,
                "preferences": [],
                "assistanceProfile": None,
            }
        ],
        days=[
            {
                "dayIndex": 0,
                "date": date(2026, 8, 27),
                "dailyBudgetCents": 10000,
                "startLocationText": "Shanghai",
                "endLocationText": "Shanghai",
                "timeWindow": {"start": "08:00:00", "end": "20:00:00"},
            }
        ],
    )
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE confirmed_trip_inputs (
            trip_id TEXT PRIMARY KEY,
            trip_json TEXT NOT NULL,
            semantic_json TEXT NOT NULL,
            confirmed_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        """INSERT INTO confirmed_trip_inputs
        (trip_id, trip_json, semantic_json, confirmed_at)
        VALUES (?, ?, '{}', '2026-08-27T00:00:00+00:00')""",
        (str(single.trip_id), single.model_dump_json(by_alias=True)),
    )
    connection.execute(
        """INSERT INTO confirmed_trip_inputs
        (trip_id, trip_json, semantic_json, confirmed_at)
        VALUES (?, ?, '{}', '2026-08-27T00:00:00+00:00')""",
        (
            "30000000-0000-4000-8000-000000000003",
            '{"mode":"GROUP","participants":[{},{}]}',
        ),
    )
    connection.commit()
    connection.close()

    SqliteCollaborationRepository(path)
    registry = SqliteTripFlowRegistry(path)

    assert registry.get(UUID("30000000-0000-4000-8000-000000000002")) is TripFlowKind.LEGACY_SINGLE
    assert registry.get(UUID("30000000-0000-4000-8000-000000000003")) is None


def test_migration_keeps_collaboration_projection_in_collaboration_flow(tmp_path) -> None:
    path = tmp_path / "collaboration-projection.sqlite3"
    trip_id = UUID("30000000-0000-4000-8000-000000000007")
    trip = CreateSingleDayTrip(
        schemaVersion="1.0",
        tripId=trip_id,
        mode="SINGLE",
        status="DRAFT",
        cityContext={
            "countryCode": "CN",
            "cityCode": "330100",
            "cityName": "杭州市",
            "center": {"longitude": 120.20, "latitude": 30.24},
            "providerConfig": {"provider": "AMAP", "coordinateSystem": "GCJ02"},
        },
        startDate=date(2026, 8, 31),
        endDate=date(2026, 8, 31),
        currency="CNY",
        totalBudgetCents=10000,
        participants=[
            {
                "participantId": UUID("10000000-0000-4000-8000-000000000007"),
                "nickname": "organizer",
                "budgetCapCents": 10000,
                "preferences": [],
                "assistanceProfile": None,
            }
        ],
        days=[
            {
                "dayIndex": 0,
                "date": date(2026, 8, 31),
                "dailyBudgetCents": 10000,
                "startLocationText": "杭州东站",
                "endLocationText": "杭州东站",
                "timeWindow": {"start": "08:00:00", "end": "20:00:00"},
            }
        ],
    )

    SqliteCollaborationRepository(path)
    registry = SqliteTripFlowRegistry(path)
    registry.register(trip_id, TripFlowKind.COLLABORATION_V2)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE confirmed_trip_inputs (
                trip_id TEXT PRIMARY KEY,
                trip_json TEXT NOT NULL,
                semantic_json TEXT NOT NULL,
                confirmed_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """INSERT INTO confirmed_trip_inputs
            (trip_id, trip_json, semantic_json, confirmed_at)
            VALUES (?, ?, '{}', '2026-08-31T00:00:00+00:00')""",
            (str(trip_id), trip.model_dump_json(by_alias=True)),
        )

    SqliteCollaborationRepository(path)

    assert registry.get(trip_id) is TripFlowKind.COLLABORATION_V2


def test_migration_records_invalid_and_group_rows_without_raw_json(tmp_path) -> None:
    path = tmp_path / "migration-errors.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE confirmed_trip_inputs (
            trip_id TEXT PRIMARY KEY,
            trip_json TEXT NOT NULL,
            semantic_json TEXT NOT NULL,
            confirmed_at TEXT NOT NULL
        )"""
    )
    connection.executemany(
        """INSERT INTO confirmed_trip_inputs
        (trip_id, trip_json, semantic_json, confirmed_at)
        VALUES (?, ?, '{}', '2026-08-27T00:00:00+00:00')""",
        [
            (
                "30000000-0000-4000-8000-000000000004",
                '{"mode":"SINGLE","secret":"malformed-source"',
            ),
            (
                "30000000-0000-4000-8000-000000000005",
                '{"mode":"GROUP","secret":"group-source"}',
            ),
        ],
    )
    connection.commit()
    connection.close()

    SqliteCollaborationRepository(path)
    registry = SqliteTripFlowRegistry(path)

    assert registry.get(UUID("30000000-0000-4000-8000-000000000004")) is None
    assert registry.get(UUID("30000000-0000-4000-8000-000000000005")) is None
    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(trip_flow_migration_errors)"
            )
        }
        rows = connection.execute(
            "SELECT error_code, trip_id FROM trip_flow_migration_errors"
        ).fetchall()
    assert "trip_json" not in columns
    assert {row[0] for row in rows} == {"INVALID_JSON", "GROUP_UNSUPPORTED"}
    assert all("malformed-source" not in repr(row) for row in rows)
    assert all("group-source" not in repr(row) for row in rows)


def test_migration_error_record_failure_rolls_back_schema_atomically(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "migration-error-atomicity.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE confirmed_trip_inputs (
            trip_id TEXT PRIMARY KEY,
            trip_json TEXT NOT NULL,
            semantic_json TEXT NOT NULL,
            confirmed_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        """INSERT INTO confirmed_trip_inputs
        (trip_id, trip_json, semantic_json, confirmed_at)
        VALUES ('30000000-0000-4000-8000-000000000006', '{', '{}',
                '2026-08-27T00:00:00+00:00')"""
    )
    connection.commit()
    connection.close()

    def fail_record(*args, **kwargs):
        raise RuntimeError("injected migration error write failure")

    monkeypatch.setattr(
        "app.infrastructure.trip_flow_store.record_migration_error",
        fail_record,
    )
    with pytest.raises(RuntimeError, match="injected migration error write failure"):
        SqliteCollaborationRepository(path)

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "trip_flow_registry" not in tables
    assert "trip_flow_migration_errors" not in tables


def test_legacy_collaboration_rows_are_marked_migration_required(tmp_path) -> None:
    path = tmp_path / "legacy-collaboration.sqlite3"
    create_baseline_collaboration_schema(path)
    connection = sqlite3.connect(path)
    connection.execute(
        """INSERT INTO collaboration_sessions
        (trip_id, organizer_participant_id, status, expected_participants,
         organizer_token_hash, created_at)
        VALUES (?, ?, 'CONFIRMED', 1, NULL, ?)""",
        (
            str(LEGACY_TRIP_ID),
            "10000000-0000-4000-8000-000000000001",
            "2026-08-27T00:00:00+00:00",
        ),
    )
    connection.commit()
    connection.close()
    repository = SqliteCollaborationRepository(path)

    with repository._connect() as connection:
        row = connection.execute(
            "SELECT status FROM collaboration_sessions WHERE trip_id=?",
            (str(LEGACY_TRIP_ID),),
        ).fetchone()
        participant = connection.execute(
            "SELECT status FROM collaboration_participants WHERE trip_id=?",
            (str(LEGACY_TRIP_ID),),
        ).fetchone()
    assert row["status"] == "MIGRATION_REQUIRED"
    assert participant["status"] == "MIGRATION_REQUIRED"
    with pytest.raises(CollaborationStoreError, match="TRIP_DRAFT_REVISION_UNAVAILABLE"):
        repository.get_stored(LEGACY_TRIP_ID)


def test_legacy_participant_only_rows_are_marked_and_fail_closed(tmp_path) -> None:
    path = tmp_path / "legacy-participant-only.sqlite3"
    create_baseline_collaboration_schema(path)
    repository = SqliteCollaborationRepository(path)

    with repository._connect() as connection:
        status = connection.execute(
            "SELECT status FROM collaboration_participants WHERE trip_id=?",
            (str(LEGACY_TRIP_ID),),
        ).fetchone()["status"]
    assert status == "MIGRATION_REQUIRED"
    with pytest.raises(CollaborationStoreError, match="TRIP_DRAFT_REVISION_UNAVAILABLE"):
        repository.get_stored(LEGACY_TRIP_ID)


def test_schema_migration_rolls_back_when_registry_creation_fails(tmp_path, monkeypatch) -> None:
    path = tmp_path / "atomic-migration.sqlite3"

    def fail_registry_creation(connection) -> None:
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(
        "app.infrastructure.collaboration_store.ensure_trip_flow_schema",
        fail_registry_creation,
    )
    with pytest.raises(RuntimeError, match="injected migration failure"):
        SqliteCollaborationRepository(path)

    connection = sqlite3.connect(path)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    connection.close()
    assert "trip_flow_registry" not in tables
    assert "collaboration_sessions" not in tables
