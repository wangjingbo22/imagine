from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.domain.collaboration import TripFlowKind


class TripFlowStoreError(RuntimeError):
    pass


def ensure_trip_flow_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS trip_flow_registry (
        trip_id TEXT PRIMARY KEY,
        flow_kind TEXT NOT NULL CHECK(flow_kind IN ('LEGACY_SINGLE','COLLABORATION_V2')),
        created_at TEXT NOT NULL
    )""")


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
    "ensure_trip_flow_schema",
    "register_trip_flow",
]
