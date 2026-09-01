from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.domain.parent_trip import ParentTripCreateRequest


class ParentTripStoreError(RuntimeError):
    pass


class SqliteParentTripRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS parent_trips (
                parent_trip_id TEXT PRIMARY KEY, title TEXT NOT NULL, city_name TEXT NOT NULL,
                start_date TEXT NOT NULL, day_count INTEGER NOT NULL CHECK(day_count BETWEEN 2 AND 3),
                organizer_token_hash TEXT NOT NULL, created_at TEXT NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS parent_trip_days (
                parent_trip_id TEXT NOT NULL, day_index INTEGER NOT NULL,
                travel_date TEXT NOT NULL, budget_cents INTEGER NOT NULL,
                child_trip_id TEXT UNIQUE,
                PRIMARY KEY(parent_trip_id, day_index),
                FOREIGN KEY(parent_trip_id) REFERENCES parent_trips(parent_trip_id)
            )""")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, isolation_level=None, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def create(self, request: ParentTripCreateRequest, token: str) -> None:
        parent_id = str(request.parent_trip_id)
        digest = self._hash(token)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM parent_trips WHERE parent_trip_id=?", (parent_id,)
            ).fetchone()
            if existing is not None:
                if not secrets.compare_digest(existing["organizer_token_hash"], digest):
                    connection.execute("ROLLBACK")
                    raise ParentTripStoreError("PARENT_TRIP_PERMISSION_REQUIRED")
                rows = connection.execute(
                    "SELECT * FROM parent_trip_days WHERE parent_trip_id=? ORDER BY day_index",
                    (parent_id,),
                ).fetchall()
                same = (
                    existing["title"] == request.title
                    and existing["city_name"] == request.city_name
                    and existing["start_date"] == request.start_date.isoformat()
                    and [row["budget_cents"] for row in rows] == request.day_budget_cents
                )
                connection.execute("ROLLBACK")
                if same:
                    return
                raise ParentTripStoreError("PARENT_TRIP_IMMUTABLE")
            now = datetime.now(UTC).isoformat()
            connection.execute(
                "INSERT INTO parent_trips VALUES (?, ?, ?, ?, ?, ?, ?)",
                (parent_id, request.title, request.city_name, request.start_date.isoformat(),
                 len(request.day_budget_cents), digest, now),
            )
            for index, budget in enumerate(request.day_budget_cents):
                connection.execute(
                    "INSERT INTO parent_trip_days VALUES (?, ?, ?, ?, NULL)",
                    (parent_id, index, (request.start_date + timedelta(days=index)).isoformat(), budget),
                )
            connection.execute("COMMIT")

    def authorized_rows(self, parent_trip_id: UUID, token: str):
        with closing(self._connect()) as connection:
            parent = connection.execute(
                "SELECT * FROM parent_trips WHERE parent_trip_id=?", (str(parent_trip_id),)
            ).fetchone()
            if parent is None:
                raise ParentTripStoreError("PARENT_TRIP_NOT_FOUND")
            if not secrets.compare_digest(parent["organizer_token_hash"], self._hash(token)):
                raise ParentTripStoreError("PARENT_TRIP_PERMISSION_REQUIRED")
            days = connection.execute(
                "SELECT * FROM parent_trip_days WHERE parent_trip_id=? ORDER BY day_index",
                (str(parent_trip_id),),
            ).fetchall()
            return dict(parent), [dict(row) for row in days]

    def sibling_rows_for_child(self, child_trip_id: UUID) -> list[dict[str, object]]:
        """Return the other days in the same parent trip, if this child is linked.

        This lookup is intentionally internal to server-side planning.  The
        public parent-trip read path still requires the parent organizer token.
        """
        with closing(self._connect()) as connection:
            owner = connection.execute(
                "SELECT parent_trip_id FROM parent_trip_days WHERE child_trip_id=?",
                (str(child_trip_id),),
            ).fetchone()
            if owner is None:
                return []
            rows = connection.execute(
                "SELECT * FROM parent_trip_days WHERE parent_trip_id=? "
                "AND child_trip_id IS NOT NULL AND child_trip_id<>? ORDER BY day_index",
                (owner["parent_trip_id"], str(child_trip_id)),
            ).fetchall()
            return [dict(row) for row in rows]

    def link(self, parent_trip_id: UUID, day_index: int, child_trip_id: UUID, token: str) -> None:
        self.authorized_rows(parent_trip_id, token)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT child_trip_id FROM parent_trip_days WHERE parent_trip_id=? AND day_index=?",
                (str(parent_trip_id), day_index),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise ParentTripStoreError("PARENT_TRIP_DAY_NOT_FOUND")
            if row["child_trip_id"] is not None and row["child_trip_id"] != str(child_trip_id):
                connection.execute("ROLLBACK")
                raise ParentTripStoreError("PARENT_TRIP_DAY_IMMUTABLE")
            try:
                connection.execute(
                    "UPDATE parent_trip_days SET child_trip_id=? WHERE parent_trip_id=? AND day_index=?",
                    (str(child_trip_id), str(parent_trip_id), day_index),
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as error:
                connection.execute("ROLLBACK")
                raise ParentTripStoreError("CHILD_TRIP_ALREADY_LINKED") from error
