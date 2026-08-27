from __future__ import annotations

import hashlib
import sqlite3
import json
import secrets
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from app.application.collaboration_ports import TripDraftRevisionView
from app.domain.collaboration import (
    InvitationCreated,
    InvitationRedeemed,
    OrganizerBootstrapResult,
    TripFlowKind,
)
from app.domain.collaboration_digest import canonical_sha256
from app.infrastructure.trip_flow_store import ensure_trip_flow_schema
from app.infrastructure.trip_flow_store import register_trip_flow


class CollaborationStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CollaborationActor:
    session_id: UUID | None
    trip_id: UUID
    participant_id: UUID
    role: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ConfirmationRecord:
    participant_id: UUID
    confirmed_revision: int | None
    confirmed_shared_digest: str | None
    confirmed_member_digest: str | None


@dataclass(frozen=True, slots=True)
class StoredCollaboration:
    trip_id: UUID
    organizer_participant_id: UUID
    current_revision: int
    version: int
    policy_version: str
    confirmations: Mapping[UUID, ConfirmationRecord]


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

    @staticmethod
    def _new_secret() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def _token_hash(secret: str) -> str:
        return hashlib.sha256(secret.encode("ascii")).hexdigest()

    @classmethod
    def _matches(cls, stored_hash: str, secret: str) -> bool:
        try:
            candidate = cls._token_hash(secret)
        except UnicodeEncodeError:
            return False
        return secrets.compare_digest(stored_hash, candidate)

    def bootstrap_collaboration(
        self,
        revision: TripDraftRevisionView,
        idempotency_key: str,
    ) -> OrganizerBootstrapResult:
        del idempotency_key
        organizer_id = revision.member_bindings.get("member-1")
        if organizer_id is None:
            raise CollaborationStoreError("BINDING_INVALID")
        participant_keys = [item.member_key for item in revision.understanding.participants]
        if participant_keys != [f"member-{index}" for index in range(1, len(participant_keys) + 1)]:
            raise CollaborationStoreError("BINDING_INVALID")
        organizer_secret = self._new_secret()
        now = self._clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT 1 FROM collaboration_sessions WHERE trip_id = ?",
                    (str(revision.trip_id),),
                ).fetchone()
                if existing is not None:
                    raise CollaborationStoreError("COLLABORATION_ALREADY_EXISTS")
                connection.execute(
                    """INSERT INTO collaboration_sessions
                    (trip_id, organizer_participant_id, status, expected_participants,
                     organizer_token_hash, created_at, draft_id, current_revision,
                     version, policy_version, readiness_digest, updated_at)
                    VALUES (?, ?, 'DRAFT_CONVERSATION', ?, ?, ?, ?, ?, 1,
                            'S2-T003.1', NULL, ?)""",
                    (
                        str(revision.trip_id),
                        str(organizer_id),
                        len(participant_keys),
                        self._token_hash(organizer_secret),
                        now.isoformat(),
                        str(revision.draft_id),
                        revision.revision,
                        now.isoformat(),
                    ),
                )
                for participant in revision.understanding.participants:
                    participant_id = revision.member_bindings[participant.member_key]
                    role = "ORGANIZER" if participant.member_key == "member-1" else "MEMBER"
                    connection.execute(
                        """INSERT INTO collaboration_participants
                        (trip_id, participant_id, display_name, status, is_organizer,
                         parsed_json, member_key, role, confirmed_revision,
                         confirmed_shared_digest, confirmed_member_digest, updated_at)
                        VALUES (?, ?, ?, 'DRAFT', ?, NULL, ?, ?, NULL, NULL, NULL, ?)""",
                        (
                            str(revision.trip_id),
                            str(participant_id),
                            participant.nickname,
                            int(participant.member_key == "member-1"),
                            participant.member_key,
                            role,
                            now.isoformat(),
                        ),
                    )
                register_trip_flow(connection, revision.trip_id, TripFlowKind.COLLABORATION_V2)
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return OrganizerBootstrapResult(
            tripId=revision.trip_id,
            organizerParticipantId=organizer_id,
            organizerToken=organizer_secret,
            organizerTokenAvailable=True,
            collaborationVersion=1,
        )

    def _organizer_actor(self, token: str | None) -> CollaborationActor:
        if not token:
            raise CollaborationStoreError("ORGANIZER_PERMISSION_REQUIRED")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT trip_id, organizer_participant_id, organizer_token_hash "
                "FROM collaboration_sessions"
            ).fetchall()
        for row in rows:
            if self._matches(row["organizer_token_hash"] or "", token):
                return CollaborationActor(
                    session_id=None,
                    trip_id=UUID(row["trip_id"]),
                    participant_id=UUID(row["organizer_participant_id"]),
                    role="ORGANIZER",
                    expires_at=self._clock() + timedelta(days=30),
                )
        raise CollaborationStoreError("ORGANIZER_PERMISSION_REQUIRED")

    def authenticate_organizer(self, token: str | None) -> CollaborationActor:
        return self._organizer_actor(token)

    def create_invitation(
        self,
        *,
        trip_id: UUID,
        participant_id: UUID,
        organizer_token: str | None,
        expected_version: int,
        idempotency_key: str,
        expires_in_hours: int = 72,
    ) -> InvitationCreated:
        del idempotency_key
        actor = self._organizer_actor(organizer_token)
        if actor.trip_id != trip_id:
            raise CollaborationStoreError("ORGANIZER_PERMISSION_REQUIRED")
        now = self._clock()
        token = self._new_secret()
        invitation_id = uuid4()
        expires_at = now + timedelta(hours=expires_in_hours)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                session = connection.execute(
                    "SELECT * FROM collaboration_sessions WHERE trip_id = ?",
                    (str(trip_id),),
                ).fetchone()
                if session is None:
                    raise CollaborationStoreError("COLLABORATION_NOT_FOUND")
                if session["organizer_participant_id"] == str(participant_id):
                    raise CollaborationStoreError("ORGANIZER_SELF_INVITE_FORBIDDEN")
                if session["version"] != expected_version:
                    raise CollaborationStoreError("COLLABORATION_VERSION_STALE")
                participant = connection.execute(
                    "SELECT member_key, status FROM collaboration_participants "
                    "WHERE trip_id = ? AND participant_id = ?",
                    (str(trip_id), str(participant_id)),
                ).fetchone()
                if participant is None or participant["member_key"] is None:
                    raise CollaborationStoreError("PARTICIPANT_NOT_BOUND")
                active = connection.execute(
                    "SELECT 1 FROM participant_invitations "
                    "WHERE trip_id = ? AND participant_id = ? AND status = 'ACTIVE'",
                    (str(trip_id), str(participant_id)),
                ).fetchone()
                if active is not None:
                    raise CollaborationStoreError("INVITATION_ALREADY_ACTIVE")
                next_version = expected_version + 1
                connection.execute(
                    """INSERT INTO participant_invitations
                    (token_hash, trip_id, participant_id, expires_at, revoked_at,
                     accepted_at, invitation_id, status, created_at, redeemed_at,
                     redeemed_session_id, version)
                    VALUES (?, ?, ?, ?, NULL, NULL, ?, 'ACTIVE', ?, NULL, NULL, 1)""",
                    (
                        self._token_hash(token),
                        str(trip_id),
                        str(participant_id),
                        expires_at.isoformat(),
                        str(invitation_id),
                        now.isoformat(),
                    ),
                )
                connection.execute(
                    "UPDATE collaboration_sessions SET version = ?, status = 'INVITING', updated_at = ? WHERE trip_id = ?",
                    (next_version, now.isoformat(), str(trip_id)),
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return InvitationCreated(
            invitationId=invitation_id,
            tripId=trip_id,
            participantId=participant_id,
            invitationUrl=f"/join#token={token}",
            expiresAt=expires_at,
            linkAvailable=True,
            collaborationVersion=next_version,
        )

    def inspect_invitation(self, raw_token: str) -> tuple[UUID, UUID]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT trip_id, participant_id, status, expires_at, revoked_at "
                "FROM participant_invitations WHERE token_hash = ?",
                (self._token_hash(raw_token),),
            ).fetchone()
        if row is None or row["status"] == "REVOKED" or row["revoked_at"]:
            raise CollaborationStoreError("INVITATION_UNAVAILABLE")
        if row["status"] == "REDEEMED":
            raise CollaborationStoreError("INVITATION_ALREADY_REDEEMED")
        if row["status"] != "ACTIVE":
            raise CollaborationStoreError("INVITATION_UNAVAILABLE")
        if datetime.fromisoformat(row["expires_at"]) <= self._clock():
            raise CollaborationStoreError("INVITATION_EXPIRED")
        return UUID(row["trip_id"]), UUID(row["participant_id"])

    def redeem_invitation(
        self,
        raw_token: str,
        idempotency_key: str,
    ) -> InvitationRedeemed:
        token_hash = self._token_hash(raw_token)
        request_digest = canonical_sha256({"tokenHash": token_hash})
        now = self._clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                prior = connection.execute(
                    "SELECT request_digest, result_json FROM collaboration_idempotency "
                    "WHERE actor_scope='INVITATION' AND actor_id=? AND operation='REDEEM_INVITATION' "
                    "AND idempotency_key=?",
                    (token_hash, idempotency_key),
                ).fetchone()
                if prior is not None:
                    if prior["request_digest"] != request_digest:
                        raise CollaborationStoreError("IDEMPOTENCY_KEY_REUSED")
                    result = json.loads(prior["result_json"])
                    connection.execute("COMMIT")
                    return InvitationRedeemed(
                        sessionId=result["sessionId"],
                        participantSessionToken=None,
                        tripId=result["tripId"],
                        participantId=result["participantId"],
                        expiresAt=result["expiresAt"],
                        sessionTokenAvailable=False,
                    )
                row = connection.execute(
                    "SELECT * FROM participant_invitations WHERE token_hash = ?",
                    (token_hash,),
                ).fetchone()
                if row is None or row["status"] == "REVOKED" or row["revoked_at"]:
                    raise CollaborationStoreError("INVITATION_UNAVAILABLE")
                if row["status"] == "REDEEMED":
                    raise CollaborationStoreError("INVITATION_ALREADY_REDEEMED")
                if row["status"] != "ACTIVE":
                    raise CollaborationStoreError("INVITATION_UNAVAILABLE")
                if datetime.fromisoformat(row["expires_at"]) <= now:
                    raise CollaborationStoreError("INVITATION_EXPIRED")
                session_id = uuid4()
                session_secret = self._new_secret()
                session_expiry = now + min(timedelta(days=7), timedelta(days=30))
                updated = connection.execute(
                    "UPDATE participant_invitations SET status='REDEEMED', accepted_at=?, "
                    "redeemed_at=?, redeemed_session_id=?, version=version+1 "
                    "WHERE invitation_id=? AND status='ACTIVE'",
                    (now.isoformat(), now.isoformat(), str(session_id), row["invitation_id"]),
                ).rowcount
                if updated != 1:
                    raise CollaborationStoreError("INVITATION_ALREADY_REDEEMED")
                connection.execute(
                    "INSERT INTO collaboration_actor_sessions VALUES (?, ?, ?, 'MEMBER', ?, ?, NULL, ?, ?)",
                    (
                        str(session_id),
                        row["trip_id"],
                        row["participant_id"],
                        self._token_hash(session_secret),
                        session_expiry.isoformat(),
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                result = {
                    "sessionId": str(session_id),
                    "tripId": row["trip_id"],
                    "participantId": row["participant_id"],
                    "expiresAt": session_expiry.isoformat(),
                }
                connection.execute(
                    """INSERT INTO collaboration_idempotency
                    (actor_scope, actor_id, operation, idempotency_key, request_digest,
                     resource_id, result_json, completed_at)
                    VALUES ('INVITATION', ?, 'REDEEM_INVITATION', ?, ?, ?, ?, ?)""",
                    (
                        token_hash,
                        idempotency_key,
                        request_digest,
                        str(session_id),
                        json.dumps(result, sort_keys=True, separators=(",", ":")),
                        now.isoformat(),
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return InvitationRedeemed(
            sessionId=session_id,
            participantSessionToken=session_secret,
            tripId=UUID(row["trip_id"]),
            participantId=UUID(row["participant_id"]),
            expiresAt=session_expiry,
            sessionTokenAvailable=True,
        )

    def authenticate_participant(self, token: str | None) -> CollaborationActor:
        if not token:
            raise CollaborationStoreError("PARTICIPANT_SESSION_REQUIRED")
        token_hash = self._token_hash(token)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM collaboration_actor_sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if row is None or not self._matches(row["token_hash"], token):
                raise CollaborationStoreError("PARTICIPANT_SESSION_INVALID")
            if row["revoked_at"]:
                raise CollaborationStoreError("PARTICIPANT_SESSION_REVOKED")
            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at <= self._clock():
                raise CollaborationStoreError("PARTICIPANT_SESSION_EXPIRED")
            connection.execute(
                "UPDATE collaboration_actor_sessions SET last_seen_at=? WHERE session_id=?",
                (self._clock().isoformat(), row["session_id"]),
            )
        return CollaborationActor(
            session_id=UUID(row["session_id"]),
            trip_id=UUID(row["trip_id"]),
            participant_id=UUID(row["participant_id"]),
            role=row["role"],
            expires_at=expires_at,
        )

    def get_stored(self, trip_id: UUID) -> StoredCollaboration:
        with self._connect() as connection:
            session = connection.execute(
                "SELECT trip_id, organizer_participant_id, current_revision, version, policy_version "
                "FROM collaboration_sessions WHERE trip_id=?",
                (str(trip_id),),
            ).fetchone()
            if session is None:
                raise CollaborationStoreError("COLLABORATION_NOT_FOUND")
            rows = connection.execute(
                "SELECT participant_id, confirmed_revision, confirmed_shared_digest, "
                "confirmed_member_digest FROM collaboration_participants WHERE trip_id=?",
                (str(trip_id),),
            ).fetchall()
        return StoredCollaboration(
            trip_id=trip_id,
            organizer_participant_id=UUID(session["organizer_participant_id"]),
            current_revision=int(session["current_revision"] or 1),
            version=int(session["version"] or 1),
            policy_version=session["policy_version"] or "S2-T003.1",
            confirmations={
                UUID(row["participant_id"]): ConfirmationRecord(
                    participant_id=UUID(row["participant_id"]),
                    confirmed_revision=row["confirmed_revision"],
                    confirmed_shared_digest=row["confirmed_shared_digest"],
                    confirmed_member_digest=row["confirmed_member_digest"],
                )
                for row in rows
            },
        )

    def begin_idempotent_operation(
        self,
        *,
        actor_scope: str,
        actor_id: str,
        operation: str,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, object] | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                prior = connection.execute(
                    "SELECT request_digest, result_json FROM collaboration_idempotency "
                    "WHERE actor_scope=? AND actor_id=? AND operation=? AND idempotency_key=?",
                    (actor_scope, actor_id, operation, idempotency_key),
                ).fetchone()
                if prior is not None:
                    if prior["request_digest"] != request_digest:
                        raise CollaborationStoreError("IDEMPOTENCY_KEY_REUSED")
                    connection.execute("COMMIT")
                    return json.loads(prior["result_json"]) if prior["result_json"] else None
                connection.execute(
                    """INSERT INTO collaboration_idempotency
                    (actor_scope, actor_id, operation, idempotency_key, request_digest)
                    VALUES (?, ?, ?, ?, ?)""",
                    (actor_scope, actor_id, operation, idempotency_key, request_digest),
                )
                connection.execute("COMMIT")
                return None
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def complete_idempotent_operation(
        self,
        *,
        actor_scope: str,
        actor_id: str,
        operation: str,
        idempotency_key: str,
        result: Mapping[str, object],
    ) -> None:
        now = self._clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                updated = connection.execute(
                    "UPDATE collaboration_idempotency SET result_json=?, completed_at=? "
                    "WHERE actor_scope=? AND actor_id=? AND operation=? AND idempotency_key=?",
                    (
                        json.dumps(dict(result), sort_keys=True, separators=(",", ":")),
                        now.isoformat(),
                        actor_scope,
                        actor_id,
                        operation,
                        idempotency_key,
                    ),
                ).rowcount
                if updated != 1:
                    raise CollaborationStoreError("IDEMPOTENCY_OPERATION_NOT_FOUND")
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def confirmation_records(self, trip_id: UUID) -> dict[UUID, ConfirmationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT participant_id, confirmed_revision, confirmed_shared_digest, "
                "confirmed_member_digest FROM collaboration_participants WHERE trip_id=?",
                (str(trip_id),),
            ).fetchall()
        return {
            UUID(row["participant_id"]): ConfirmationRecord(
                participant_id=UUID(row["participant_id"]),
                confirmed_revision=row["confirmed_revision"],
                confirmed_shared_digest=row["confirmed_shared_digest"],
                confirmed_member_digest=row["confirmed_member_digest"],
            )
            for row in rows
        }

    def record_confirmation(
        self,
        *,
        trip_id: UUID,
        participant_id: UUID,
        revision: int,
        shared_digest: str,
        member_digest: str,
        expected_version: int,
        idempotency_key: str,
    ) -> int:
        request_digest = canonical_sha256({
            "tripId": str(trip_id),
            "participantId": str(participant_id),
            "revision": revision,
            "sharedDigest": shared_digest,
            "memberDigest": member_digest,
            "expectedVersion": expected_version,
        })
        now = self._clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                prior = connection.execute(
                    "SELECT request_digest, result_json FROM collaboration_idempotency "
                    "WHERE actor_scope='PARTICIPANT' AND actor_id=? AND operation='CONFIRM' "
                    "AND idempotency_key=?",
                    (str(participant_id), idempotency_key),
                ).fetchone()
                if prior is not None:
                    if prior["request_digest"] != request_digest:
                        raise CollaborationStoreError("IDEMPOTENCY_KEY_REUSED")
                    result = json.loads(prior["result_json"])
                    connection.execute("COMMIT")
                    return int(result["collaborationVersion"])
                session = connection.execute(
                    "SELECT version FROM collaboration_sessions WHERE trip_id=?",
                    (str(trip_id),),
                ).fetchone()
                if session is None:
                    raise CollaborationStoreError("COLLABORATION_NOT_FOUND")
                if session["version"] != expected_version:
                    raise CollaborationStoreError("COLLABORATION_VERSION_STALE")
                participant = connection.execute(
                    "SELECT 1 FROM collaboration_participants WHERE trip_id=? AND participant_id=?",
                    (str(trip_id), str(participant_id)),
                ).fetchone()
                if participant is None:
                    raise CollaborationStoreError("PARTICIPANT_NOT_BOUND")
                next_version = expected_version + 1
                updated = connection.execute(
                    "UPDATE collaboration_sessions SET version=?, updated_at=? "
                    "WHERE trip_id=? AND version=?",
                    (next_version, now.isoformat(), str(trip_id), expected_version),
                ).rowcount
                if updated != 1:
                    raise CollaborationStoreError("COLLABORATION_VERSION_STALE")
                connection.execute(
                    "UPDATE collaboration_participants SET status='CONFIRMED', confirmed_revision=?, "
                    "confirmed_shared_digest=?, confirmed_member_digest=?, updated_at=? "
                    "WHERE trip_id=? AND participant_id=?",
                    (
                        revision,
                        shared_digest,
                        member_digest,
                        now.isoformat(),
                        str(trip_id),
                        str(participant_id),
                    ),
                )
                result_json = json.dumps(
                    {"collaborationVersion": next_version},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                connection.execute(
                    """INSERT INTO collaboration_idempotency
                    (actor_scope, actor_id, operation, idempotency_key, request_digest,
                     resource_id, result_json, completed_at)
                    VALUES ('PARTICIPANT', ?, 'CONFIRM', ?, ?, ?, ?, ?)""",
                    (
                        str(participant_id),
                        idempotency_key,
                        request_digest,
                        str(trip_id),
                        result_json,
                        now.isoformat(),
                    ),
                )
                connection.execute("COMMIT")
                return next_version
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def advance_revision(
        self,
        *,
        trip_id: UUID,
        before_revision: int,
        after_revision: int,
        expected_version: int,
        actor_scope: str,
        actor_id: str,
        idempotency_key: str,
    ) -> int:
        if after_revision <= before_revision:
            raise CollaborationStoreError("DRAFT_REVISION_STALE")
        request_digest = canonical_sha256({
            "tripId": str(trip_id),
            "beforeRevision": before_revision,
            "afterRevision": after_revision,
            "expectedVersion": expected_version,
        })
        now = self._clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                prior = connection.execute(
                    "SELECT request_digest, result_json FROM collaboration_idempotency "
                    "WHERE actor_scope=? AND actor_id=? AND operation='ADVANCE_REVISION' "
                    "AND idempotency_key=?",
                    (actor_scope, actor_id, idempotency_key),
                ).fetchone()
                if prior is not None:
                    if prior["request_digest"] != request_digest:
                        raise CollaborationStoreError("IDEMPOTENCY_KEY_REUSED")
                    result = json.loads(prior["result_json"])
                    connection.execute("COMMIT")
                    return int(result["collaborationVersion"])
                active = connection.execute(
                    "SELECT 1 FROM collaboration_operation_leases "
                    "WHERE trip_id=? AND completed_at IS NULL AND expires_at>?",
                    (str(trip_id), now.isoformat()),
                ).fetchone()
                if active is not None:
                    raise CollaborationStoreError("COLLABORATION_OPERATION_IN_PROGRESS")
                row = connection.execute(
                    "SELECT current_revision, version FROM collaboration_sessions WHERE trip_id=?",
                    (str(trip_id),),
                ).fetchone()
                if row is None:
                    raise CollaborationStoreError("COLLABORATION_NOT_FOUND")
                if row["version"] != expected_version:
                    raise CollaborationStoreError("COLLABORATION_VERSION_STALE")
                if row["current_revision"] != before_revision:
                    raise CollaborationStoreError("DRAFT_REVISION_STALE")
                next_version = expected_version + 1
                updated = connection.execute(
                    "UPDATE collaboration_sessions SET current_revision=?, version=?, updated_at=? "
                    "WHERE trip_id=? AND current_revision=? AND version=?",
                    (
                        after_revision,
                        next_version,
                        now.isoformat(),
                        str(trip_id),
                        before_revision,
                        expected_version,
                    ),
                ).rowcount
                if updated != 1:
                    raise CollaborationStoreError("COLLABORATION_VERSION_STALE")
                result_json = json.dumps(
                    {"collaborationVersion": next_version},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                connection.execute(
                    """INSERT INTO collaboration_idempotency
                    (actor_scope, actor_id, operation, idempotency_key, request_digest,
                     resource_id, result_json, completed_at)
                    VALUES (?, ?, 'ADVANCE_REVISION', ?, ?, ?, ?, ?)""",
                    (
                        actor_scope,
                        actor_id,
                        idempotency_key,
                        request_digest,
                        str(trip_id),
                        result_json,
                        now.isoformat(),
                    ),
                )
                connection.execute("COMMIT")
                return next_version
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def record_resolution_audit(
        self,
        *,
        trip_id: UUID,
        item_id: str,
        relaxation_id: str,
        actor_id: str,
        before_revision: int,
        after_revision: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO collaboration_resolution_audit
                (audit_id, trip_id, item_id, relaxation_id, actor_id,
                 before_revision, after_revision, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()),
                    str(trip_id),
                    item_id,
                    relaxation_id,
                    actor_id,
                    before_revision,
                    after_revision,
                    self._clock().isoformat(),
                ),
            )


__all__ = ["CollaborationStoreError", "SqliteCollaborationRepository"]
