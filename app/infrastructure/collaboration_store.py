from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from app.infrastructure.trip_flow_store import ensure_trip_flow_schema


class CollaborationStoreError(RuntimeError):
    pass


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    name: str,
    declaration: str,
) -> None:
    existing = {
        row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if name not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


class SqliteCollaborationRepository:
    def __init__(
        self,
        database_path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = database_path
        self._clock = clock or (lambda: datetime.now(UTC))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, isolation_level=None, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS collaboration_sessions (
                trip_id TEXT PRIMARY KEY,
                organizer_participant_id TEXT NOT NULL,
                status TEXT NOT NULL,
                expected_participants INTEGER NOT NULL DEFAULT 1,
                organizer_token_hash TEXT,
                created_at TEXT NOT NULL,
                draft_id TEXT,
                current_revision INTEGER NOT NULL DEFAULT 1,
                version INTEGER NOT NULL DEFAULT 1,
                policy_version TEXT NOT NULL DEFAULT 'S2-T003.1',
                readiness_digest TEXT,
                updated_at TEXT
            )""")
            for name, declaration in (
                ("expected_participants", "INTEGER NOT NULL DEFAULT 1"),
                ("organizer_token_hash", "TEXT"),
                ("created_at", "TEXT"),
                ("draft_id", "TEXT"),
                ("current_revision", "INTEGER NOT NULL DEFAULT 1"),
                ("version", "INTEGER NOT NULL DEFAULT 1"),
                ("policy_version", "TEXT NOT NULL DEFAULT 'S2-T003.1'"),
                ("readiness_digest", "TEXT"),
                ("updated_at", "TEXT"),
            ):
                _ensure_column(connection, "collaboration_sessions", name, declaration)

            connection.execute("""CREATE TABLE IF NOT EXISTS collaboration_participants (
                trip_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                display_name TEXT,
                status TEXT NOT NULL,
                is_organizer INTEGER NOT NULL,
                parsed_json TEXT,
                member_key TEXT,
                role TEXT,
                confirmed_revision INTEGER,
                confirmed_shared_digest TEXT,
                confirmed_member_digest TEXT,
                updated_at TEXT,
                PRIMARY KEY (trip_id, participant_id)
            )""")
            for name, declaration in (
                ("display_name", "TEXT"),
                ("is_organizer", "INTEGER NOT NULL DEFAULT 0"),
                ("parsed_json", "TEXT"),
                ("member_key", "TEXT"),
                ("role", "TEXT"),
                ("confirmed_revision", "INTEGER"),
                ("confirmed_shared_digest", "TEXT"),
                ("confirmed_member_digest", "TEXT"),
                ("updated_at", "TEXT"),
            ):
                _ensure_column(connection, "collaboration_participants", name, declaration)

            connection.execute("""CREATE TABLE IF NOT EXISTS participant_invitations (
                token_hash TEXT PRIMARY KEY,
                trip_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                accepted_at TEXT,
                invitation_id TEXT,
                status TEXT,
                created_at TEXT,
                redeemed_at TEXT,
                redeemed_session_id TEXT,
                version INTEGER NOT NULL DEFAULT 1
            )""")
            for name, declaration in (
                ("revoked_at", "TEXT"),
                ("accepted_at", "TEXT"),
                ("invitation_id", "TEXT"),
                ("status", "TEXT"),
                ("created_at", "TEXT"),
                ("redeemed_at", "TEXT"),
                ("redeemed_session_id", "TEXT"),
                ("version", "INTEGER NOT NULL DEFAULT 1"),
            ):
                _ensure_column(connection, "participant_invitations", name, declaration)

            connection.execute("""CREATE TABLE IF NOT EXISTS collaboration_actor_sessions (
              session_id TEXT PRIMARY KEY,
              trip_id TEXT NOT NULL,
              participant_id TEXT NOT NULL,
              role TEXT NOT NULL,
              token_hash TEXT NOT NULL UNIQUE,
              expires_at TEXT NOT NULL,
              revoked_at TEXT,
              created_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS collaboration_idempotency (
              actor_scope TEXT NOT NULL,
              actor_id TEXT NOT NULL,
              operation TEXT NOT NULL,
              idempotency_key TEXT NOT NULL,
              request_digest TEXT NOT NULL,
              resource_id TEXT,
              result_json TEXT,
              completed_at TEXT,
              PRIMARY KEY(actor_scope, actor_id, operation, idempotency_key)
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS collaboration_resolution_audit (
              audit_id TEXT PRIMARY KEY,
              trip_id TEXT NOT NULL,
              item_id TEXT NOT NULL,
              relaxation_id TEXT NOT NULL,
              actor_id TEXT NOT NULL,
              before_revision INTEGER NOT NULL,
              after_revision INTEGER NOT NULL,
              created_at TEXT NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS collaboration_operation_leases (
              operation_id TEXT PRIMARY KEY,
              trip_id TEXT NOT NULL,
              readiness_digest TEXT NOT NULL,
              operation TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              completed_at TEXT
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS collaboration_conflict_resolutions (
                trip_id TEXT NOT NULL,
                conflict_id TEXT NOT NULL,
                relaxation TEXT NOT NULL,
                resolved_at TEXT NOT NULL,
                PRIMARY KEY (trip_id, conflict_id)
            )""")
            ensure_trip_flow_schema(connection)


__all__ = ["CollaborationStoreError", "SqliteCollaborationRepository"]
