from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from app.schemas.arrival_evidence import (
    ArrivalEvidence,
    CreateArrivalEvidence,
    LocationEvidence,
    LocationEvidenceSource,
)


@dataclass(frozen=True, slots=True)
class ArrivalEvidenceStoreError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


class SqliteArrivalEvidenceRepository:
    """Persists one-shot readings; no session or continuous tracking state exists."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            isolation_level=None,
            timeout=5,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS arrival_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    longitude REAL NOT NULL,
                    latitude REAL NOT NULL,
                    accuracy REAL NOT NULL,
                    captured_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    UNIQUE (trip_id, idempotency_key)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_arrival_evidence_trip_task_time
                ON arrival_evidence (trip_id, task_id, captured_at, evidence_id)
                """
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ArrivalEvidence:
        return ArrivalEvidence(
            evidence_id=UUID(row["evidence_id"]),
            trip_id=UUID(row["trip_id"]),
            task_id=row["task_id"],
            location_evidence=LocationEvidence(
                longitude=row["longitude"],
                latitude=row["latitude"],
                accuracy=row["accuracy"],
                captured_at=datetime.fromisoformat(row["captured_at"]),
                source=LocationEvidenceSource(row["source"]),
            ),
            idempotency_key=row["idempotency_key"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
        )

    @staticmethod
    def _same_request(
        row: sqlite3.Row,
        request: CreateArrivalEvidence,
    ) -> bool:
        location = request.location_evidence
        return (
            row["task_id"] == request.task_id
            and row["longitude"] == location.longitude
            and row["latitude"] == location.latitude
            and row["accuracy"] == location.accuracy
            and row["captured_at"] == location.captured_at.isoformat()
            and row["source"] == location.source.value
        )

    def save(
        self,
        trip_id: UUID,
        request: CreateArrivalEvidence,
    ) -> ArrivalEvidence:
        trip_text = str(trip_id)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    """
                    SELECT * FROM arrival_evidence
                    WHERE trip_id = ? AND idempotency_key = ?
                    """,
                    (trip_text, request.idempotency_key),
                ).fetchone()
                if existing is not None:
                    if not self._same_request(existing, request):
                        raise ArrivalEvidenceStoreError(
                            "ARRIVAL_EVIDENCE_IDEMPOTENCY_CONFLICT",
                            "相同 idempotencyKey 已用于不同的定位证据",
                        )
                    connection.execute("COMMIT")
                    return self._from_row(existing)

                evidence_id = uuid4()
                recorded_at = datetime.now(UTC)
                location = request.location_evidence
                connection.execute(
                    """
                    INSERT INTO arrival_evidence (
                        evidence_id, trip_id, task_id, longitude, latitude,
                        accuracy, captured_at, source, idempotency_key,
                        recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(evidence_id),
                        trip_text,
                        request.task_id,
                        location.longitude,
                        location.latitude,
                        location.accuracy,
                        location.captured_at.isoformat(),
                        location.source.value,
                        request.idempotency_key,
                        recorded_at.isoformat(),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM arrival_evidence WHERE evidence_id = ?",
                    (str(evidence_id),),
                ).fetchone()
                connection.execute("COMMIT")
                assert row is not None
                return self._from_row(row)
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def get(self, trip_id: UUID, evidence_id: UUID) -> ArrivalEvidence:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM arrival_evidence
                WHERE trip_id = ? AND evidence_id = ?
                """,
                (str(trip_id), str(evidence_id)),
            ).fetchone()
        if row is None:
            raise ArrivalEvidenceStoreError(
                "ARRIVAL_EVIDENCE_NOT_FOUND",
                "未找到指定到达定位证据",
            )
        return self._from_row(row)

    def list_for_trip(
        self,
        trip_id: UUID,
        *,
        task_id: str | None = None,
    ) -> list[ArrivalEvidence]:
        sql = "SELECT * FROM arrival_evidence WHERE trip_id = ?"
        parameters: list[str] = [str(trip_id)]
        if task_id is not None:
            sql += " AND task_id = ?"
            parameters.append(task_id)
        sql += " ORDER BY captured_at, evidence_id"
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._from_row(row) for row in rows]


__all__ = ["ArrivalEvidenceStoreError", "SqliteArrivalEvidenceRepository"]
