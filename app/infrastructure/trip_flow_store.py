from __future__ import annotations

import hashlib
import sqlite3
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.domain.collaboration import TripFlowKind
from app.schemas.trip import CreateSingleDayTrip


class TripFlowStoreError(RuntimeError):
    pass


def ensure_trip_flow_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS trip_flow_registry (
        trip_id TEXT PRIMARY KEY,
        flow_kind TEXT NOT NULL CHECK(flow_kind IN ('LEGACY_SINGLE','COLLABORATION_V2')),
        created_at TEXT NOT NULL
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS trip_flow_migration_errors (
        error_id TEXT PRIMARY KEY,
        source_table TEXT NOT NULL,
        trip_id TEXT,
        source_row_hash TEXT NOT NULL UNIQUE,
        error_code TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")


def record_migration_error(
    connection: sqlite3.Connection,
    *,
    source_table: str,
    source_trip_id: object,
    error_code: str,
) -> None:
    source_row_id = "" if source_trip_id is None else str(source_trip_id)
    try:
        trip_id = str(UUID(source_row_id))
    except (ValueError, TypeError, AttributeError):
        trip_id = None
    source_row_hash = hashlib.sha256(
        f"{source_table}\x00{source_row_id}\x00{error_code}".encode("utf-8")
    ).hexdigest()
    connection.execute(
        """INSERT OR IGNORE INTO trip_flow_migration_errors
        (error_id, source_table, trip_id, source_row_hash, error_code, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (
            source_row_hash,
            source_table,
            trip_id,
            source_row_hash,
            error_code,
            datetime.now(UTC).isoformat(),
        ),
    )


def register_trip_flow(
    connection: sqlite3.Connection,
    trip_id: UUID,
    kind: TripFlowKind,
) -> None:
    existing = connection.execute(
        "SELECT flow_kind FROM trip_flow_registry WHERE trip_id = ?",
        (str(trip_id),),
    ).fetchone()
    if existing is not None and existing[0] != kind.value:
        raise TripFlowStoreError("TRIP_FLOW_KIND_CONFLICT")
    connection.execute(
        "INSERT OR IGNORE INTO trip_flow_registry VALUES (?, ?, ?)",
        (str(trip_id), kind.value, datetime.now(UTC).isoformat()),
    )


def backfill_confirmed_single_flows(connection: sqlite3.Connection) -> None:
    """Register only strict legacy single-trip confirmations.

    The old confirmed-input table is an input to migration, never a source
    for a collaboration revision. Invalid, group, and otherwise ambiguous
    rows remain unregistered so the readiness guard fails closed.
    """

    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='confirmed_trip_inputs'"
    ).fetchone()
    if table is None:
        return
    rows = connection.execute(
        "SELECT trip_id, trip_json FROM confirmed_trip_inputs"
    ).fetchall()
    for row in rows:
        source_trip_id = row[0]
        try:
            payload = json.loads(row[1])
        except (TypeError, ValueError, json.JSONDecodeError):
            record_migration_error(
                connection,
                source_table="confirmed_trip_inputs",
                source_trip_id=source_trip_id,
                error_code="INVALID_JSON",
            )
            continue
        if not isinstance(payload, dict):
            record_migration_error(
                connection,
                source_table="confirmed_trip_inputs",
                source_trip_id=source_trip_id,
                error_code="INVALID_PAYLOAD",
            )
            continue
        if payload.get("mode") == "GROUP":
            record_migration_error(
                connection,
                source_table="confirmed_trip_inputs",
                source_trip_id=source_trip_id,
                error_code="GROUP_UNSUPPORTED",
            )
            continue
        try:
            trip = CreateSingleDayTrip.model_validate_json(row[1], strict=True)
        except (TypeError, ValueError, json.JSONDecodeError):
            record_migration_error(
                connection,
                source_table="confirmed_trip_inputs",
                source_trip_id=source_trip_id,
                error_code="LEGACY_SINGLE_INVALID",
            )
            continue
        if trip.mode != "SINGLE" or len(trip.participants) != 1:
            record_migration_error(
                connection,
                source_table="confirmed_trip_inputs",
                source_trip_id=source_trip_id,
                error_code="LEGACY_FLOW_UNSUPPORTED",
            )
            continue
        try:
            source_uuid = UUID(str(source_trip_id))
        except (ValueError, TypeError, AttributeError):
            record_migration_error(
                connection,
                source_table="confirmed_trip_inputs",
                source_trip_id=source_trip_id,
                error_code="TRIP_ID_INVALID",
            )
            continue
        if trip.trip_id != source_uuid:
            record_migration_error(
                connection,
                source_table="confirmed_trip_inputs",
                source_trip_id=source_trip_id,
                error_code="TRIP_ID_MISMATCH",
            )
            continue
        register_trip_flow(connection, source_uuid, TripFlowKind.LEGACY_SINGLE)


def mark_legacy_collaboration_rows(connection: sqlite3.Connection) -> None:
    """Prevent baseline collaboration rows from masquerading as revisions."""

    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(collaboration_sessions)")
    }
    if "draft_id" not in columns:
        return
    connection.execute(
        "UPDATE collaboration_sessions SET status='MIGRATION_REQUIRED' "
        "WHERE draft_id IS NULL AND status <> 'MIGRATION_REQUIRED'"
    )
    connection.execute(
        "UPDATE collaboration_participants SET status='MIGRATION_REQUIRED' "
        "WHERE NOT EXISTS ("
        "SELECT 1 FROM collaboration_sessions s WHERE s.trip_id=collaboration_participants.trip_id"
        ") OR trip_id IN ("
        "SELECT trip_id FROM collaboration_sessions WHERE draft_id IS NULL"
        ")"
    )


class SqliteTripFlowRegistry:
    def __init__(self, database_path: Path) -> None:
        self._path = database_path
        self._confirmed_single_ids: set[UUID] = set()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            ensure_trip_flow_schema(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, isolation_level=None, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def get(self, trip_id: UUID) -> TripFlowKind | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT flow_kind FROM trip_flow_registry WHERE trip_id = ?",
                (str(trip_id),),
            ).fetchone()
        return TripFlowKind(row["flow_kind"]) if row is not None else None

    def register(self, trip_id: UUID, kind: TripFlowKind) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                register_trip_flow(connection, trip_id, kind)
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def register_confirmed_single(self, trip: object) -> None:
        trip_id = trip.trip_id
        self.register(trip_id, TripFlowKind.LEGACY_SINGLE)
        self._confirmed_single_ids.add(trip_id)

    def force_registry_only(self, trip_id: UUID, kind: TripFlowKind) -> None:
        self.register(trip_id, kind)

    def is_strict_confirmed_single(self, trip_id: UUID) -> bool:
        if self.get(trip_id) is not TripFlowKind.LEGACY_SINGLE:
            return False
        if trip_id in self._confirmed_single_ids:
            return True
        with self._connect() as connection:
            try:
                row = connection.execute(
                    "SELECT trip_json FROM confirmed_trip_inputs WHERE trip_id=?",
                    (str(trip_id),),
                ).fetchone()
            except sqlite3.OperationalError:
                return False
        if row is None:
            return False
        try:
            import json

            payload = json.loads(row["trip_json"])
            return payload.get("mode") == "SINGLE" and len(payload.get("participants", [])) == 1
        except (TypeError, ValueError, KeyError):
            return False


__all__ = [
    "SqliteTripFlowRegistry",
    "TripFlowStoreError",
    "backfill_confirmed_single_flows",
    "ensure_trip_flow_schema",
    "mark_legacy_collaboration_rows",
    "record_migration_error",
    "register_trip_flow",
]
