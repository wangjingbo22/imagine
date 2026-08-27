from __future__ import annotations

import sqlite3
from uuid import UUID, uuid4

import pytest

from app.domain.collaboration import (
    CollaborationStatus,
    ConversationAnswer,
    ConversationSubmission,
)
from app.infrastructure.collaboration_store import SqliteCollaborationRepository
from app.infrastructure.trip_flow_store import SqliteTripFlowRegistry


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
