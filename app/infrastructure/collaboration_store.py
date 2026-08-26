from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.domain.collaboration import (
    CollaborationConflict, CollaborationParticipant, CollaborationState, CollaborationStatus,
    InvitationConversation, InvitationCreated, ParticipantConfirmationStatus,
)
from app.domain.trip_draft import ParsedTripFields


class CollaborationStoreError(RuntimeError):
    pass


class SqliteCollaborationRepository:
    def __init__(self, database_path: Path) -> None:
        self._path = database_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, isolation_level=None, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS collaboration_sessions (
                trip_id TEXT PRIMARY KEY, organizer_participant_id TEXT NOT NULL,
                status TEXT NOT NULL, expected_participants INTEGER NOT NULL DEFAULT 1,
                organizer_token_hash TEXT, created_at TEXT NOT NULL)""")
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(collaboration_sessions)")}
            if "expected_participants" not in columns:
                connection.execute("ALTER TABLE collaboration_sessions ADD COLUMN expected_participants INTEGER NOT NULL DEFAULT 1")
            if "organizer_token_hash" not in columns:
                connection.execute("ALTER TABLE collaboration_sessions ADD COLUMN organizer_token_hash TEXT")
            connection.execute("""CREATE TABLE IF NOT EXISTS collaboration_participants (
                trip_id TEXT NOT NULL, participant_id TEXT NOT NULL, display_name TEXT,
                status TEXT NOT NULL, is_organizer INTEGER NOT NULL, parsed_json TEXT,
                PRIMARY KEY (trip_id, participant_id))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS participant_invitations (
                token_hash TEXT PRIMARY KEY, trip_id TEXT NOT NULL, participant_id TEXT NOT NULL,
                expires_at TEXT NOT NULL, revoked_at TEXT, accepted_at TEXT)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS collaboration_conflict_resolutions (
                trip_id TEXT NOT NULL, conflict_id TEXT NOT NULL, relaxation TEXT NOT NULL,
                resolved_at TEXT NOT NULL, PRIMARY KEY (trip_id, conflict_id))""")

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_session(
        self,
        trip_id: UUID,
        organizer_id: UUID,
        parsed: ParsedTripFields,
        expected_participants: int,
    ) -> tuple[CollaborationState, str]:
        organizer_token = secrets.token_urlsafe(32)
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("INSERT INTO collaboration_sessions (trip_id, organizer_participant_id, status, expected_participants, organizer_token_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)", (str(trip_id), str(organizer_id), CollaborationStatus.INVITING.value, expected_participants, self._token_hash(organizer_token), now))
                connection.execute("INSERT INTO collaboration_participants VALUES (?, ?, ?, ?, ?, ?)", (str(trip_id), str(organizer_id), "组织者", ParticipantConfirmationStatus.CONFIRMED.value, 1, parsed.model_dump_json(by_alias=True)))
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get_state(trip_id), organizer_token

    def _assert_organizer(self, trip_id: UUID, organizer_access_token: str | None) -> None:
        with closing(self._connect()) as connection:
            session = connection.execute("SELECT organizer_token_hash FROM collaboration_sessions WHERE trip_id = ?", (str(trip_id),)).fetchone()
        if session is None:
            raise CollaborationStoreError("COLLABORATION_NOT_FOUND")
        if not organizer_access_token or not secrets.compare_digest(session["organizer_token_hash"] or "", self._token_hash(organizer_access_token)):
            raise CollaborationStoreError("ORGANIZER_PERMISSION_REQUIRED")

    def create_invitation(self, trip_id: UUID, organizer_access_token: str | None, *, ttl_hours: int = 72) -> InvitationCreated:
        self._assert_organizer(trip_id, organizer_access_token)
        participant_id = uuid4()
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)
        with closing(self._connect()) as connection:
            session = connection.execute("SELECT expected_participants FROM collaboration_sessions WHERE trip_id = ?", (str(trip_id),)).fetchone()
            if session is None:
                raise CollaborationStoreError("COLLABORATION_NOT_FOUND")
            invited = connection.execute(
                "SELECT COUNT(*) AS count FROM collaboration_participants WHERE trip_id = ?",
                (str(trip_id),),
            ).fetchone()["count"]
            if invited >= session["expected_participants"]:
                raise CollaborationStoreError("INVITATION_CAPACITY_REACHED")
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("INSERT INTO collaboration_participants VALUES (?, ?, ?, ?, ?, ?)", (str(trip_id), str(participant_id), None, ParticipantConfirmationStatus.INVITED.value, 0, None))
                connection.execute("INSERT INTO participant_invitations VALUES (?, ?, ?, ?, NULL, NULL)", (self._token_hash(token), str(trip_id), str(participant_id), expires_at.isoformat()))
                connection.execute("UPDATE collaboration_sessions SET status = ? WHERE trip_id = ?", (CollaborationStatus.COLLECTING_MEMBERS.value, str(trip_id)))
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return InvitationCreated(participant_id=participant_id, invitation_url=f"/join/{token}", expires_at=expires_at)

    def invitation(self, token: str) -> InvitationConversation:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM participant_invitations WHERE token_hash = ?", (self._token_hash(token),)).fetchone()
            if row is None or row["revoked_at"] or row["accepted_at"]:
                raise CollaborationStoreError("INVITATION_INVALID")
            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at <= datetime.now(UTC):
                raise CollaborationStoreError("INVITATION_EXPIRED")
            participant = connection.execute("SELECT status FROM collaboration_participants WHERE trip_id = ? AND participant_id = ?", (row["trip_id"], row["participant_id"])).fetchone()
            organizer = connection.execute(
                "SELECT parsed_json FROM collaboration_participants WHERE trip_id = ? AND is_organizer = 1",
                (row["trip_id"],),
            ).fetchone()
        assert participant is not None
        if organizer is None or organizer["parsed_json"] is None:
            raise CollaborationStoreError("SHARED_TRIP_MISSING")
        return InvitationConversation(
            trip_id=UUID(row["trip_id"]),
            participant_id=UUID(row["participant_id"]),
            expires_at=expires_at,
            status=ParticipantConfirmationStatus(participant["status"]),
            shared_trip=ParsedTripFields.model_validate_json(organizer["parsed_json"]),
        )

    def submit_invitation(self, token: str, parsed: ParsedTripFields) -> CollaborationState:
        invite = self.invitation(token)
        with closing(self._connect()) as connection:
            connection.execute("UPDATE collaboration_participants SET parsed_json = ?, status = ? WHERE trip_id = ? AND participant_id = ?", (parsed.model_dump_json(by_alias=True), ParticipantConfirmationStatus.DRAFT.value, str(invite.trip_id), str(invite.participant_id)))
        return self.get_state(invite.trip_id)

    def confirm_invitation(self, token: str) -> CollaborationState:
        invite = self.invitation(token)
        with closing(self._connect()) as connection:
            participant = connection.execute("SELECT parsed_json FROM collaboration_participants WHERE trip_id = ? AND participant_id = ?", (str(invite.trip_id), str(invite.participant_id))).fetchone()
            if participant is None or participant["parsed_json"] is None:
                raise CollaborationStoreError("PARTICIPANT_DRAFT_MISSING")
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("UPDATE collaboration_participants SET status = ? WHERE trip_id = ? AND participant_id = ?", (ParticipantConfirmationStatus.CONFIRMED.value, str(invite.trip_id), str(invite.participant_id)))
                connection.execute("UPDATE participant_invitations SET accepted_at = ? WHERE token_hash = ?", (datetime.now(UTC).isoformat(), self._token_hash(token)))
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get_state(invite.trip_id)

    def revoke_invitation(self, trip_id: UUID, participant_id: UUID, organizer_access_token: str | None) -> CollaborationState:
        self._assert_organizer(trip_id, organizer_access_token)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                updated = connection.execute(
                    "UPDATE participant_invitations SET revoked_at = ? WHERE trip_id = ? AND participant_id = ? AND accepted_at IS NULL AND revoked_at IS NULL",
                    (datetime.now(UTC).isoformat(), str(trip_id), str(participant_id)),
                ).rowcount
                if updated != 1:
                    raise CollaborationStoreError("INVITATION_NOT_REVOCABLE")
                connection.execute(
                    "UPDATE collaboration_participants SET status = ? WHERE trip_id = ? AND participant_id = ?",
                    (ParticipantConfirmationStatus.REVOKED.value, str(trip_id), str(participant_id)),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get_state(trip_id)

    def get_state(self, trip_id: UUID) -> CollaborationState:
        with closing(self._connect()) as connection:
            session = connection.execute("SELECT * FROM collaboration_sessions WHERE trip_id = ?", (str(trip_id),)).fetchone()
            if session is None:
                raise CollaborationStoreError("COLLABORATION_NOT_FOUND")
            rows = connection.execute("SELECT * FROM collaboration_participants WHERE trip_id = ? ORDER BY is_organizer DESC, participant_id", (str(trip_id),)).fetchall()
        participants = [CollaborationParticipant(participant_id=UUID(row["participant_id"]), display_name=row["display_name"], status=ParticipantConfirmationStatus(row["status"]), is_organizer=bool(row["is_organizer"]), parsed=ParsedTripFields.model_validate_json(row["parsed_json"]) if row["parsed_json"] else None) for row in rows]
        status = CollaborationStatus(session["status"])
        expected_participants = int(session["expected_participants"])
        conflicts = self._conflicts(participants)
        with closing(self._connect()) as connection:
            resolved = {row["conflict_id"] for row in connection.execute(
                "SELECT conflict_id FROM collaboration_conflict_resolutions WHERE trip_id = ?",
                (str(trip_id),),
            )}
        conflicts = [conflict for conflict in conflicts if conflict.conflict_id not in resolved]
        if len(participants) == expected_participants and all(item.status is ParticipantConfirmationStatus.CONFIRMED for item in participants):
            status = CollaborationStatus.CONFLICT_REVIEW if conflicts else CollaborationStatus.READY_TO_PLAN
        return CollaborationState(trip_id=trip_id, organizer_participant_id=UUID(session["organizer_participant_id"]), status=status, expected_participants=expected_participants, participants=participants, conflicts=conflicts)

    def resolve_conflict(self, trip_id: UUID, conflict_id: str, relaxation: str, organizer_access_token: str | None) -> CollaborationState:
        self._assert_organizer(trip_id, organizer_access_token)
        conflict = next((item for item in self.get_state(trip_id).conflicts if item.conflict_id == conflict_id), None)
        if conflict is None:
            raise CollaborationStoreError("CONFLICT_NOT_FOUND")
        if relaxation not in conflict.allowed_relaxations:
            raise CollaborationStoreError("CONFLICT_RELAXATION_INVALID")
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO collaboration_conflict_resolutions VALUES (?, ?, ?, ?)",
                (str(trip_id), conflict_id, relaxation, datetime.now(UTC).isoformat()),
            )
        return self.get_state(trip_id)

    def assert_planning_ready(self, trip_id: UUID, organizer_access_token: str | None) -> None:
        """Allow legacy trips; gate only trips created in the S2 collaboration flow."""
        with closing(self._connect()) as connection:
            session = connection.execute(
                "SELECT organizer_token_hash FROM collaboration_sessions WHERE trip_id = ?",
                (str(trip_id),),
            ).fetchone()
        if session is None:
            return
        if not organizer_access_token or not secrets.compare_digest(
            session["organizer_token_hash"] or "", self._token_hash(organizer_access_token)
        ):
            raise CollaborationStoreError("ORGANIZER_PERMISSION_REQUIRED")
        state = self.get_state(trip_id)
        if state.status is not CollaborationStatus.READY_TO_PLAN:
            raise CollaborationStoreError("COLLABORATION_NOT_READY_TO_PLAN")

    @staticmethod
    def _conflicts(participants: list[CollaborationParticipant]) -> list[CollaborationConflict]:
        conflicts: list[CollaborationConflict] = []
        for required_by in participants:
            if required_by.parsed is None:
                continue
            required = {item.casefold() for item in required_by.parsed.must_visit}
            for avoiding_by in participants:
                if avoiding_by.participant_id == required_by.participant_id or avoiding_by.parsed is None:
                    continue
                overlap = required & {item.casefold() for item in avoiding_by.parsed.avoid_places}
                for place in sorted(overlap):
                    conflicts.append(CollaborationConflict(conflict_id=f"must-avoid-{required_by.participant_id}-{avoiding_by.participant_id}-{place}", participant_ids=[required_by.participant_id, avoiding_by.participant_id], rule_id="MUST_VISIT_AVOID_PLACE", message=f"{place} 被一名成员设为必去、另一名成员设为避开", suggestion="由组织者确认保留必去或移除避开限制", allowed_relaxations=["KEEP_MUST_VISIT", "REMOVE_AVOID"]))
        organizer = next((item for item in participants if item.is_organizer and item.parsed), None)
        if organizer and organizer.parsed:
            for participant in participants:
                if participant.is_organizer or participant.parsed is None:
                    continue
                if participant.parsed.city_name and organizer.parsed.city_name and participant.parsed.city_name.casefold() != organizer.parsed.city_name.casefold():
                    conflicts.append(CollaborationConflict(conflict_id=f"city-{participant.participant_id}", participant_ids=[organizer.participant_id, participant.participant_id], rule_id="CITY_MISMATCH", message="成员填写的城市与组织者行程城市不一致", suggestion="请统一采用组织者城市或返回成员对话修正", allowed_relaxations=["USE_ORGANIZER_CITY"]))
                if participant.parsed.travel_date and organizer.parsed.travel_date and participant.parsed.travel_date != organizer.parsed.travel_date:
                    conflicts.append(CollaborationConflict(conflict_id=f"date-{participant.participant_id}", participant_ids=[organizer.participant_id, participant.participant_id], rule_id="TRAVEL_DATE_MISMATCH", message="成员填写的日期与组织者行程日期不一致", suggestion="请统一采用组织者日期或返回成员对话修正", allowed_relaxations=["USE_ORGANIZER_DATE"]))
        return conflicts
