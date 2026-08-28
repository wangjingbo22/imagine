from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from uuid import UUID

from app.application.collaboration_ports import UnresolvedAnswerAttempt
from app.domain.trip_draft import TripDraftRevision, TripUnderstandingExtraction


@dataclass(frozen=True, slots=True)
class AnswerCommand:
    actor_scope: str
    actor_id: str
    operation: str
    idempotency_key: str
    request_digest: str

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (
            self.actor_scope,
            self.actor_id,
            self.operation,
            self.idempotency_key,
        )


@dataclass(frozen=True, slots=True)
class ClaimedCommand:
    command: AnswerCommand
    draft_id: UUID
    trip_id: UUID
    target_revision: int


@dataclass(frozen=True, slots=True)
class CompletedCommand:
    revision: TripDraftRevision


@dataclass(frozen=True, slots=True)
class CommandInProgress:
    target_revision: int


@dataclass(frozen=True, slots=True)
class FailedCommand:
    code: str
    outcome_json: str | None = None


CommandClaim = ClaimedCommand | CompletedCommand | CommandInProgress | FailedCommand


class TripDraftRevisionStoreError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class SqliteTripDraftRevisionRepository:
    def __init__(
        self,
        database_path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = Path(database_path)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, isolation_level=None, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _immediate_transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._immediate_transaction() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS trip_draft_heads (
                    draft_id TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL UNIQUE,
                    current_revision INTEGER NOT NULL,
                    pending_revision INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS trip_draft_revisions (
                    draft_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    trip_id TEXT NOT NULL,
                    understanding_json TEXT NOT NULL,
                    member_bindings_json TEXT NOT NULL,
                    source_request_digest TEXT NOT NULL,
                    source_digest TEXT NOT NULL,
                    recognition_source TEXT NOT NULL,
                    recognition_model TEXT,
                    degraded_reason TEXT,
                    llm_call_count INTEGER NOT NULL CHECK (llm_call_count IN (0, 1, 2)),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (draft_id, revision),
                    UNIQUE (trip_id, revision)
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS trip_draft_commands (
                    actor_scope TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    base_revision INTEGER NOT NULL,
                    target_revision INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('CLAIMED', 'COMPLETED', 'FAILED')),
                    failure_code TEXT,
                    outcome_json TEXT,
                    claimed_at TEXT NOT NULL,
                    completed_at TEXT,
                    PRIMARY KEY (actor_scope, actor_id, operation, idempotency_key)
                )"""
            )
            command_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(trip_draft_commands)"
                ).fetchall()
            }
            if "outcome_json" not in command_columns:
                connection.execute(
                    "ALTER TABLE trip_draft_commands ADD COLUMN outcome_json TEXT"
                )

    @staticmethod
    def _find_command(
        connection: sqlite3.Connection,
        command: AnswerCommand,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """SELECT * FROM trip_draft_commands
               WHERE actor_scope=? AND actor_id=? AND operation=? AND idempotency_key=?""",
            command.identity,
        ).fetchone()

    def _replay_or_conflict(
        self,
        connection: sqlite3.Connection,
        prior: sqlite3.Row,
        command: AnswerCommand,
    ) -> CommandClaim:
        if prior["request_digest"] != command.request_digest:
            raise TripDraftRevisionStoreError("IDEMPOTENCY_KEY_REUSED")
        status = prior["status"]
        if status == "CLAIMED":
            return CommandInProgress(target_revision=prior["target_revision"])
        if status == "FAILED":
            return FailedCommand(
                code=prior["failure_code"] or "TRIP_DRAFT_REVISION_UNAVAILABLE",
                outcome_json=prior["outcome_json"],
            )
        if status == "COMPLETED":
            revision = self._load_revision(
                connection,
                draft_id=UUID(prior["draft_id"]),
                revision=prior["target_revision"],
            )
            return CompletedCommand(revision=revision)
        raise TripDraftRevisionStoreError("TRIP_DRAFT_REVISION_UNAVAILABLE")

    def _assert_no_active_planning_lease(
        self,
        connection: sqlite3.Connection,
        trip_id: UUID,
    ) -> None:
        try:
            row = connection.execute(
                """SELECT 1 FROM collaboration_operation_leases
                   WHERE trip_id=? AND completed_at IS NULL AND expires_at>?""",
                (str(trip_id), self._clock().isoformat()),
            ).fetchone()
        except sqlite3.OperationalError as error:
            if "no such table" in str(error).lower():
                return
            raise
        if row is not None:
            raise TripDraftRevisionStoreError("COLLABORATION_OPERATION_IN_PROGRESS")

    @staticmethod
    def _load_head(
        connection: sqlite3.Connection,
        draft_id: UUID,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM trip_draft_heads WHERE draft_id=?",
            (str(draft_id),),
        ).fetchone()

    def _require_current_and_idle(
        self,
        head: sqlite3.Row | None,
        *,
        draft_id: UUID,
        trip_id: UUID,
        base_revision: int,
    ) -> sqlite3.Row:
        if head is None or head["trip_id"] != str(trip_id):
            raise TripDraftRevisionStoreError("TRIP_DRAFT_REVISION_UNAVAILABLE")
        if head["pending_revision"] is not None:
            raise TripDraftRevisionStoreError("TRIP_DRAFT_REVISION_UNAVAILABLE")
        if head["current_revision"] != base_revision:
            raise TripDraftRevisionStoreError("DRAFT_REVISION_STALE")
        return head

    @staticmethod
    def _insert_claim(
        connection: sqlite3.Connection,
        command: AnswerCommand,
        *,
        draft_id: UUID,
        base_revision: int,
        target_revision: int,
        claimed_at: str,
    ) -> None:
        connection.execute(
            """INSERT INTO trip_draft_commands
               (actor_scope, actor_id, operation, idempotency_key, request_digest,
                draft_id, base_revision, target_revision, status, failure_code,
                claimed_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'CLAIMED', NULL, ?, NULL)""",
            (
                command.actor_scope,
                command.actor_id,
                command.operation,
                command.idempotency_key,
                command.request_digest,
                str(draft_id),
                base_revision,
                target_revision,
                claimed_at,
            ),
        )

    def claim_initial(
        self,
        command: AnswerCommand,
        *,
        draft_id: UUID,
        trip_id: UUID,
    ) -> CommandClaim:
        with self._immediate_transaction() as connection:
            prior = self._find_command(connection, command)
            if prior is not None:
                return self._replay_or_conflict(connection, prior, command)
            self._assert_no_active_planning_lease(connection, trip_id)
            head = self._load_head(connection, draft_id)
            if head is not None:
                self._require_current_and_idle(
                    head,
                    draft_id=draft_id,
                    trip_id=trip_id,
                    base_revision=0,
                )
            now = self._clock().isoformat()
            if head is None:
                connection.execute(
                    """INSERT INTO trip_draft_heads
                       (draft_id, trip_id, current_revision, pending_revision, created_at, updated_at)
                       VALUES (?, ?, 0, 1, ?, ?)""",
                    (str(draft_id), str(trip_id), now, now),
                )
            else:
                updated = connection.execute(
                    """UPDATE trip_draft_heads SET pending_revision=1, updated_at=?
                       WHERE draft_id=? AND trip_id=? AND current_revision=0
                         AND pending_revision IS NULL""",
                    (now, str(draft_id), str(trip_id)),
                ).rowcount
                if updated != 1:
                    raise TripDraftRevisionStoreError("DRAFT_REVISION_STALE")
            self._insert_claim(
                connection,
                command,
                draft_id=draft_id,
                base_revision=0,
                target_revision=1,
                claimed_at=now,
            )
            return ClaimedCommand(command, draft_id, trip_id, 1)

    def claim_next(
        self,
        command: AnswerCommand,
        *,
        draft_id: UUID,
        trip_id: UUID,
        base_revision: int,
    ) -> CommandClaim:
        with self._immediate_transaction() as connection:
            prior = self._find_command(connection, command)
            if prior is not None:
                return self._replay_or_conflict(connection, prior, command)
            self._assert_no_active_planning_lease(connection, trip_id)
            head = self._require_current_and_idle(
                self._load_head(connection, draft_id),
                draft_id=draft_id,
                trip_id=trip_id,
                base_revision=base_revision,
            )
            target_revision = base_revision + 1
            now = self._clock().isoformat()
            self._insert_claim(
                connection,
                command,
                draft_id=draft_id,
                base_revision=base_revision,
                target_revision=target_revision,
                claimed_at=now,
            )
            updated = connection.execute(
                """UPDATE trip_draft_heads SET pending_revision=?, updated_at=?
                   WHERE draft_id=? AND trip_id=? AND current_revision=?
                     AND pending_revision IS NULL""",
                (
                    target_revision,
                    now,
                    str(draft_id),
                    str(trip_id),
                    head["current_revision"],
                ),
            ).rowcount
            if updated != 1:
                raise TripDraftRevisionStoreError("DRAFT_REVISION_STALE")
            return ClaimedCommand(command, draft_id, trip_id, target_revision)

    def _load_revision(
        self,
        connection: sqlite3.Connection,
        *,
        draft_id: UUID,
        revision: int,
    ) -> TripDraftRevision:
        row = connection.execute(
            """SELECT * FROM trip_draft_revisions
               WHERE draft_id=? AND revision=?""",
            (str(draft_id), revision),
        ).fetchone()
        if row is None:
            raise TripDraftRevisionStoreError("TRIP_DRAFT_REVISION_UNAVAILABLE")
        try:
            payload = {
                "schemaVersion": "1.0",
                "draftId": row["draft_id"],
                "revision": row["revision"],
                "tripId": row["trip_id"],
                "understanding": json.loads(row["understanding_json"]),
                "memberBindings": json.loads(row["member_bindings_json"]),
                "sourceDigest": row["source_digest"],
                "createdAt": row["created_at"],
            }
            return TripDraftRevision.model_validate_json(
                _canonical_json(payload),
                strict=True,
            )
        except Exception as error:
            raise TripDraftRevisionStoreError("TRIP_DRAFT_REVISION_UNAVAILABLE") from error

    def complete(
        self,
        claim: ClaimedCommand,
        revision: TripDraftRevision,
        extraction: object,
    ) -> None:
        if revision.revision != claim.target_revision:
            raise TripDraftRevisionStoreError("DRAFT_REVISION_STALE")
        if revision.draft_id != claim.draft_id or revision.trip_id != claim.trip_id:
            raise TripDraftRevisionStoreError("DRAFT_REVISION_STALE")
        if getattr(extraction, "proposal", None) != revision.understanding:
            raise TripDraftRevisionStoreError("TRIP_UNDERSTANDING_INVALID")
        call_count = getattr(extraction, "call_count", None)
        if call_count is None:
            call_count = getattr(extraction, "llm_call_count", None)
        if call_count not in {0, 1, 2}:
            raise TripDraftRevisionStoreError("TRIP_UNDERSTANDING_INVALID")
        recognition_source = getattr(extraction, "recognition_source", None)
        if recognition_source is None:
            recognition_source = "MODEL_PROPOSAL"
        recognition_model = getattr(extraction, "model", None)
        if recognition_model is None:
            recognition_model = getattr(extraction, "recognition_model", None)
        degraded_reason = getattr(extraction, "failure_code", None)
        if degraded_reason is None:
            degraded_reason = getattr(extraction, "degraded_reason", None)
        with self._immediate_transaction() as connection:
            prior = self._find_command(connection, claim.command)
            if prior is None or prior["request_digest"] != claim.command.request_digest:
                raise TripDraftRevisionStoreError("TRIP_DRAFT_REVISION_UNAVAILABLE")
            if prior["status"] == "COMPLETED":
                raise TripDraftRevisionStoreError("DRAFT_REVISION_IMMUTABLE")
            if prior["status"] != "CLAIMED":
                raise TripDraftRevisionStoreError("TRIP_DRAFT_REVISION_UNAVAILABLE")
            head = self._load_head(connection, claim.draft_id)
            if (
                head is None
                or head["trip_id"] != str(claim.trip_id)
                or head["current_revision"] != prior["base_revision"]
                or head["pending_revision"] != claim.target_revision
            ):
                raise TripDraftRevisionStoreError("DRAFT_REVISION_STALE")
            try:
                connection.execute(
                    """INSERT INTO trip_draft_revisions
                       (draft_id, revision, trip_id, understanding_json, member_bindings_json,
                        source_request_digest, source_digest, recognition_source, recognition_model,
                        degraded_reason, llm_call_count, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(revision.draft_id),
                        revision.revision,
                        str(revision.trip_id),
                        _canonical_json(
                            revision.understanding.model_dump(mode="json", by_alias=True)
                        ),
                        _canonical_json(
                            {key: str(value) for key, value in revision.member_bindings.items()}
                        ),
                        claim.command.request_digest,
                        revision.source_digest,
                        recognition_source,
                        recognition_model,
                        degraded_reason,
                        call_count,
                        revision.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise TripDraftRevisionStoreError("DRAFT_REVISION_IMMUTABLE") from error
            now = self._clock().isoformat()
            updated = connection.execute(
                """UPDATE trip_draft_heads
                   SET current_revision=?, pending_revision=NULL, updated_at=?
                   WHERE draft_id=? AND trip_id=? AND current_revision=?
                     AND pending_revision=?""",
                (
                    claim.target_revision,
                    now,
                    str(claim.draft_id),
                    str(claim.trip_id),
                    prior["base_revision"],
                    claim.target_revision,
                ),
            ).rowcount
            if updated != 1:
                raise TripDraftRevisionStoreError("DRAFT_REVISION_STALE")
            updated = connection.execute(
                """UPDATE trip_draft_commands
                   SET status='COMPLETED', completed_at=?
                   WHERE actor_scope=? AND actor_id=? AND operation=?
                     AND idempotency_key=? AND status='CLAIMED'""",
                (
                    now,
                    *claim.command.identity,
                ),
            ).rowcount
            if updated != 1:
                raise TripDraftRevisionStoreError("TRIP_DRAFT_REVISION_UNAVAILABLE")

    def fail(
        self,
        claim: ClaimedCommand,
        *,
        code: str,
        outcome_json: str | None = None,
    ) -> None:
        with self._immediate_transaction() as connection:
            prior = self._find_command(connection, claim.command)
            if prior is None or prior["request_digest"] != claim.command.request_digest:
                raise TripDraftRevisionStoreError("TRIP_DRAFT_REVISION_UNAVAILABLE")
            if prior["status"] == "FAILED":
                return
            if prior["status"] != "CLAIMED":
                raise TripDraftRevisionStoreError("DRAFT_REVISION_IMMUTABLE")
            head = self._load_head(connection, claim.draft_id)
            if (
                head is None
                or head["trip_id"] != str(claim.trip_id)
                or head["current_revision"] != prior["base_revision"]
                or head["pending_revision"] != claim.target_revision
            ):
                raise TripDraftRevisionStoreError("DRAFT_REVISION_STALE")
            now = self._clock().isoformat()
            released = connection.execute(
                """UPDATE trip_draft_heads
                   SET pending_revision=NULL, updated_at=?
                   WHERE draft_id=? AND trip_id=? AND current_revision=?
                     AND pending_revision=?""",
                (
                    now,
                    str(claim.draft_id),
                    str(claim.trip_id),
                    prior["base_revision"],
                    claim.target_revision,
                ),
            ).rowcount
            if released != 1:
                raise TripDraftRevisionStoreError("DRAFT_REVISION_STALE")
            updated = connection.execute(
                """UPDATE trip_draft_commands
                   SET status='FAILED', failure_code=?, outcome_json=?, completed_at=?
                   WHERE actor_scope=? AND actor_id=? AND operation=?
                     AND idempotency_key=? AND status='CLAIMED'""",
                (
                    code,
                    outcome_json,
                    now,
                    *claim.command.identity,
                ),
            ).rowcount
            if updated != 1:
                raise TripDraftRevisionStoreError("TRIP_DRAFT_REVISION_UNAVAILABLE")

    def get_current(self, trip_id: UUID) -> TripDraftRevision:
        with self._connect() as connection:
            head = connection.execute(
                "SELECT * FROM trip_draft_heads WHERE trip_id=?",
                (str(trip_id),),
            ).fetchone()
            if (
                head is None
                or head["pending_revision"] is not None
                or head["current_revision"] < 1
            ):
                raise TripDraftRevisionStoreError("TRIP_DRAFT_REVISION_UNAVAILABLE")
            return self._load_revision(
                connection,
                draft_id=UUID(head["draft_id"]),
                revision=head["current_revision"],
            )

    def unresolved_failed_answer_attempts(
        self,
        *,
        trip_id: UUID,
        current_revision: int,
    ) -> tuple[UnresolvedAnswerAttempt, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT command.actor_scope, command.actor_id,
                          command.target_revision, command.failure_code
                   FROM trip_draft_commands AS command
                   JOIN trip_draft_heads AS head
                     ON head.draft_id = command.draft_id
                   WHERE head.trip_id=?
                     AND command.operation IN (
                         'INITIAL_ANSWER', 'MEMBER_ANSWER', 'ORGANIZER_ANSWER'
                     )
                     AND command.status='FAILED'
                     AND (
                         command.target_revision>?
                         OR NOT EXISTS (
                             SELECT 1
                             FROM trip_draft_commands AS successor
                             WHERE successor.draft_id = command.draft_id
                               AND successor.actor_scope = command.actor_scope
                               AND successor.actor_id = command.actor_id
                               AND successor.operation = command.operation
                               AND successor.status = 'COMPLETED'
                               AND successor.rowid > command.rowid
                               AND successor.target_revision >= command.target_revision
                         )
                     )
                   ORDER BY command.target_revision, command.rowid""",
                (str(trip_id), current_revision),
            ).fetchall()
        return tuple(
            UnresolvedAnswerAttempt(
                actor_scope=row["actor_scope"],
                actor_id=row["actor_id"],
                target_revision=int(row["target_revision"]),
                failure_code=row["failure_code"] or "TRIP_UNDERSTANDING_UNAVAILABLE",
            )
            for row in rows
        )


__all__ = [
    "AnswerCommand",
    "ClaimedCommand",
    "CommandClaim",
    "CommandInProgress",
    "CompletedCommand",
    "FailedCommand",
    "SqliteTripDraftRevisionRepository",
    "TripDraftRevisionStoreError",
]
