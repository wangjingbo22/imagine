from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4, uuid5

from app.domain.parent_trip import (
    MAX_PARENT_TRIP_DAYS,
    MAX_PARENT_TRIP_PARTICIPANTS,
    ParentTripCreateRequest,
)


PARENT_ORGANIZER_NAMESPACE = UUID("83af3f62-c026-4fc5-9794-ecbc92c88044")


class ParentTripStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ParentTripActor:
    participant_id: UUID
    role: Literal["ORGANIZER", "MEMBER"]


class SqliteParentTripRepository:
    def __init__(
        self,
        database_path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_path = database_path
        self._clock = clock or (lambda: datetime.now(UTC))
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS parent_trips (
                parent_trip_id TEXT PRIMARY KEY, title TEXT NOT NULL, city_name TEXT NOT NULL,
                start_date TEXT NOT NULL, day_count INTEGER NOT NULL CHECK(day_count BETWEEN 2 AND 30),
                organizer_token_hash TEXT NOT NULL, created_at TEXT NOT NULL
            )""")
            # 旧版本把 2–3 天写进了 SQLite CHECK 约束。仅修改 Pydantic 无法让
            # 已存在的本地数据库接受更多天数，因此启动时检查旧表定义并迁移。
            parent_schema_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='parent_trips'"
            ).fetchone()
            parent_schema = str(parent_schema_row[0]) if parent_schema_row else ""
            if "BETWEEN 2 AND 3" in parent_schema.upper():
                # SQLite 不能直接删除 CHECK。这里在关闭外键校验的短事务中重建
                # 父表，并完整复制主键、凭证哈希和已有行程；子表名称与数据不变。
                connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute("PRAGMA legacy_alter_table=ON")
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute("ALTER TABLE parent_trips RENAME TO parent_trips_legacy_days")
                    connection.execute(f"""CREATE TABLE parent_trips (
                        parent_trip_id TEXT PRIMARY KEY, title TEXT NOT NULL, city_name TEXT NOT NULL,
                        start_date TEXT NOT NULL, day_count INTEGER NOT NULL
                            CHECK(day_count BETWEEN 2 AND {MAX_PARENT_TRIP_DAYS}),
                        organizer_token_hash TEXT NOT NULL, created_at TEXT NOT NULL
                    )""")
                    connection.execute("""INSERT INTO parent_trips
                        (parent_trip_id, title, city_name, start_date, day_count,
                         organizer_token_hash, created_at)
                        SELECT parent_trip_id, title, city_name, start_date, day_count,
                               organizer_token_hash, created_at
                        FROM parent_trips_legacy_days""")
                    connection.execute("DROP TABLE parent_trips_legacy_days")
                    connection.execute("COMMIT")
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
                finally:
                    connection.execute("PRAGMA legacy_alter_table=OFF")
                    connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("""CREATE TABLE IF NOT EXISTS parent_trip_days (
                parent_trip_id TEXT NOT NULL, day_index INTEGER NOT NULL,
                travel_date TEXT NOT NULL, budget_cents INTEGER NOT NULL,
                child_trip_id TEXT UNIQUE,
                PRIMARY KEY(parent_trip_id, day_index),
                FOREIGN KEY(parent_trip_id) REFERENCES parent_trips(parent_trip_id)
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS parent_trip_sync_state (
                parent_trip_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL CHECK(version >= 1),
                updated_at TEXT NOT NULL,
                FOREIGN KEY(parent_trip_id) REFERENCES parent_trips(parent_trip_id)
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS parent_trip_members (
                parent_trip_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                account_user_id TEXT,
                role TEXT NOT NULL CHECK(role IN ('ORGANIZER', 'MEMBER')),
                access_status TEXT NOT NULL CHECK(access_status IN
                    ('ORGANIZER_ACTIVE', 'INVITED', 'MEMBER_ACTIVE')),
                nickname TEXT NOT NULL,
                interests_json TEXT NOT NULL,
                budget_cap_cents INTEGER,
                profile_version INTEGER NOT NULL CHECK(profile_version >= 1),
                updated_at TEXT NOT NULL,
                PRIMARY KEY(parent_trip_id, participant_id),
                FOREIGN KEY(parent_trip_id) REFERENCES parent_trips(parent_trip_id)
            )""")
            member_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(parent_trip_members)")
            }
            if "account_user_id" not in member_columns:
                connection.execute(
                    "ALTER TABLE parent_trip_members ADD COLUMN account_user_id TEXT"
                )
            connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS
                ux_parent_trip_members_parent_account
                ON parent_trip_members(parent_trip_id, account_user_id)
                WHERE account_user_id IS NOT NULL
            """)
            connection.execute("""CREATE TABLE IF NOT EXISTS parent_trip_invitations (
                invitation_id TEXT PRIMARY KEY,
                parent_trip_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'REDEEMED')),
                created_at TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                redeemed_at TEXT,
                redeemed_idempotency_key TEXT,
                redeemed_session_id TEXT,
                UNIQUE(parent_trip_id, idempotency_key),
                UNIQUE(parent_trip_id, participant_id),
                FOREIGN KEY(parent_trip_id, participant_id)
                    REFERENCES parent_trip_members(parent_trip_id, participant_id)
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS parent_trip_member_sessions (
                session_id TEXT PRIMARY KEY,
                parent_trip_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                FOREIGN KEY(parent_trip_id, participant_id)
                    REFERENCES parent_trip_members(parent_trip_id, participant_id)
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

    @staticmethod
    def _matches(stored_hash: str, value: str) -> bool:
        return secrets.compare_digest(stored_hash, SqliteParentTripRepository._hash(value))

    @staticmethod
    def _derived_secret(key: str, message: str) -> str:
        digest = hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    @staticmethod
    def _request_digest(payload: dict[str, object]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _organizer_id(parent_trip_id: UUID) -> UUID:
        stable = uuid5(PARENT_ORGANIZER_NAMESPACE, str(parent_trip_id))
        return UUID(bytes=stable.bytes, version=4)

    def _ensure_collaboration(self, connection: sqlite3.Connection, parent_trip_id: UUID) -> None:
        now = self._clock().isoformat()
        parent_text = str(parent_trip_id)
        connection.execute(
            "INSERT OR IGNORE INTO parent_trip_sync_state VALUES (?, 1, ?)",
            (parent_text, now),
        )
        connection.execute(
            """INSERT OR IGNORE INTO parent_trip_members
            (parent_trip_id, participant_id, role, access_status, nickname,
             interests_json, budget_cap_cents, profile_version, updated_at)
            VALUES (?, ?, 'ORGANIZER', 'ORGANIZER_ACTIVE', '组织者', '[]', NULL, 1, ?)""",
            (parent_text, str(self._organizer_id(parent_trip_id)), now),
        )

    def _authorize_organizer(
        self,
        connection: sqlite3.Connection,
        parent_trip_id: UUID,
        token: str,
    ) -> sqlite3.Row:
        parent = connection.execute(
            "SELECT * FROM parent_trips WHERE parent_trip_id=?",
            (str(parent_trip_id),),
        ).fetchone()
        if parent is None:
            raise ParentTripStoreError("PARENT_TRIP_NOT_FOUND")
        if not self._matches(parent["organizer_token_hash"], token):
            raise ParentTripStoreError("PARENT_TRIP_PERMISSION_REQUIRED")
        self._ensure_collaboration(connection, parent_trip_id)
        return parent

    def _authenticate_member(
        self,
        connection: sqlite3.Connection,
        parent_trip_id: UUID,
        token: str | None,
    ) -> ParentTripActor:
        if not token:
            raise ParentTripStoreError("PARENT_MEMBER_SESSION_REQUIRED")
        row = connection.execute(
            """SELECT * FROM parent_trip_member_sessions
            WHERE parent_trip_id=? AND token_hash=?""",
            (str(parent_trip_id), self._hash(token)),
        ).fetchone()
        if row is None or not self._matches(row["token_hash"], token):
            raise ParentTripStoreError("PARENT_MEMBER_SESSION_INVALID")
        if row["revoked_at"]:
            raise ParentTripStoreError("PARENT_MEMBER_SESSION_INVALID")
        if datetime.fromisoformat(row["expires_at"]) <= self._clock():
            raise ParentTripStoreError("PARENT_MEMBER_SESSION_EXPIRED")
        connection.execute(
            "UPDATE parent_trip_member_sessions SET last_seen_at=? WHERE session_id=?",
            (self._clock().isoformat(), row["session_id"]),
        )
        return ParentTripActor(participant_id=UUID(row["participant_id"]), role="MEMBER")

    @staticmethod
    def _sync_row(connection: sqlite3.Connection, parent_trip_id: UUID) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM parent_trip_sync_state WHERE parent_trip_id=?",
            (str(parent_trip_id),),
        ).fetchone()
        if row is None:
            raise ParentTripStoreError("PARENT_TRIP_NOT_FOUND")
        return row

    def _bump_sync(self, connection: sqlite3.Connection, parent_trip_id: UUID) -> int:
        connection.execute(
            """UPDATE parent_trip_sync_state
            SET version=version+1, updated_at=? WHERE parent_trip_id=?""",
            (self._clock().isoformat(), str(parent_trip_id)),
        )
        return int(self._sync_row(connection, parent_trip_id)["version"])

    def create(self, request: ParentTripCreateRequest, token: str) -> None:
        parent_id = str(request.parent_trip_id)
        digest = self._hash(token)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT * FROM parent_trips WHERE parent_trip_id=?", (parent_id,)
                ).fetchone()
                if existing is not None:
                    if not secrets.compare_digest(existing["organizer_token_hash"], digest):
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
                    if not same:
                        raise ParentTripStoreError("PARENT_TRIP_IMMUTABLE")
                    self._ensure_collaboration(connection, request.parent_trip_id)
                    connection.execute("COMMIT")
                    return
                now = self._clock().isoformat()
                connection.execute(
                    """INSERT INTO parent_trips
                    (parent_trip_id, title, city_name, start_date, day_count,
                     organizer_token_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        parent_id,
                        request.title,
                        request.city_name,
                        request.start_date.isoformat(),
                        len(request.day_budget_cents),
                        digest,
                        now,
                    ),
                )
                for index, budget in enumerate(request.day_budget_cents):
                    connection.execute(
                        """INSERT INTO parent_trip_days
                        (parent_trip_id, day_index, travel_date, budget_cents, child_trip_id)
                        VALUES (?, ?, ?, ?, NULL)""",
                        (
                            parent_id,
                            index,
                            (request.start_date + timedelta(days=index)).isoformat(),
                            budget,
                        ),
                    )
                self._ensure_collaboration(connection, request.parent_trip_id)
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def authorized_rows(self, parent_trip_id: UUID, token: str):
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                parent = self._authorize_organizer(connection, parent_trip_id, token)
                days = connection.execute(
                    "SELECT * FROM parent_trip_days WHERE parent_trip_id=? ORDER BY day_index",
                    (str(parent_trip_id),),
                ).fetchall()
                connection.execute("COMMIT")
                return dict(parent), [dict(row) for row in days]
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

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
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._authorize_organizer(connection, parent_trip_id, token)
                row = connection.execute(
                    """SELECT child_trip_id FROM parent_trip_days
                    WHERE parent_trip_id=? AND day_index=?""",
                    (str(parent_trip_id), day_index),
                ).fetchone()
                if row is None:
                    raise ParentTripStoreError("PARENT_TRIP_DAY_NOT_FOUND")
                if row["child_trip_id"] is not None:
                    if row["child_trip_id"] == str(child_trip_id):
                        connection.execute("COMMIT")
                        return
                    raise ParentTripStoreError("PARENT_TRIP_DAY_IMMUTABLE")
                try:
                    connection.execute(
                        """UPDATE parent_trip_days SET child_trip_id=?
                        WHERE parent_trip_id=? AND day_index=?""",
                        (str(child_trip_id), str(parent_trip_id), day_index),
                    )
                except sqlite3.IntegrityError as error:
                    raise ParentTripStoreError("CHILD_TRIP_ALREADY_LINKED") from error
                self._bump_sync(connection, parent_trip_id)
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def update_day_budget(
        self,
        parent_trip_id: UUID,
        day_index: int,
        budget_cents: int,
        token: str,
    ) -> None:
        """原子更新一天的分配预算并推进协作同步版本。

        相同金额是幂等操作，不产生无意义版本；真正变化时成员轮询可通过新的
        sync version 及时看到预算调整。
        """
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._authorize_organizer(connection, parent_trip_id, token)
                row = connection.execute(
                    "SELECT budget_cents FROM parent_trip_days "
                    "WHERE parent_trip_id=? AND day_index=?",
                    (str(parent_trip_id), day_index),
                ).fetchone()
                if row is None:
                    raise ParentTripStoreError("PARENT_TRIP_DAY_NOT_FOUND")
                if int(row["budget_cents"]) != budget_cents:
                    connection.execute(
                        "UPDATE parent_trip_days SET budget_cents=? "
                        "WHERE parent_trip_id=? AND day_index=?",
                        (budget_cents, str(parent_trip_id), day_index),
                    )
                    self._bump_sync(connection, parent_trip_id)
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def create_invitation(
        self,
        *,
        parent_trip_id: UUID,
        organizer_token: str,
        expected_sync_version: int,
        expires_in_hours: int,
        idempotency_key: str,
    ) -> tuple[dict[str, object], str | None]:
        request_digest = self._request_digest({"expiresInHours": expires_in_hours})
        secret = self._derived_secret(
            organizer_token,
            f"parent-invitation:{parent_trip_id}:{idempotency_key}",
        )
        now = self._clock()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._authorize_organizer(connection, parent_trip_id, organizer_token)
                prior = connection.execute(
                    """SELECT * FROM parent_trip_invitations
                    WHERE parent_trip_id=? AND idempotency_key=?""",
                    (str(parent_trip_id), idempotency_key),
                ).fetchone()
                if prior is not None:
                    if prior["request_digest"] != request_digest:
                        raise ParentTripStoreError("PARENT_IDEMPOTENCY_KEY_REUSED")
                    sync_version = int(self._sync_row(connection, parent_trip_id)["version"])
                    connection.execute("COMMIT")
                    result = dict(prior)
                    result["sync_version"] = sync_version
                    available = (
                        prior["status"] == "ACTIVE"
                        and datetime.fromisoformat(prior["expires_at"]) > now
                    )
                    return result, secret if available else None

                current_version = int(self._sync_row(connection, parent_trip_id)["version"])
                if current_version != expected_sync_version:
                    raise ParentTripStoreError("PARENT_TRIP_VERSION_CONFLICT")
                count = int(connection.execute(
                    "SELECT COUNT(*) FROM parent_trip_members WHERE parent_trip_id=?",
                    (str(parent_trip_id),),
                ).fetchone()[0])
                if count >= MAX_PARENT_TRIP_PARTICIPANTS:
                    raise ParentTripStoreError("PARENT_TRIP_MEMBER_LIMIT")

                participant_id = uuid4()
                invitation_id = uuid4()
                expires_at = now + timedelta(hours=expires_in_hours)
                connection.execute(
                    """INSERT INTO parent_trip_members
                    (parent_trip_id, participant_id, role, access_status, nickname,
                     interests_json, budget_cap_cents, profile_version, updated_at)
                    VALUES (?, ?, 'MEMBER', 'INVITED', ?, '[]', NULL, 1, ?)""",
                    (
                        str(parent_trip_id),
                        str(participant_id),
                        f"待加入成员 {count}",
                        now.isoformat(),
                    ),
                )
                connection.execute(
                    """INSERT INTO parent_trip_invitations
                    (invitation_id, parent_trip_id, participant_id, token_hash,
                     expires_at, status, created_at, idempotency_key, request_digest,
                     redeemed_at, redeemed_idempotency_key, redeemed_session_id)
                    VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, NULL, NULL, NULL)""",
                    (
                        str(invitation_id),
                        str(parent_trip_id),
                        str(participant_id),
                        self._hash(secret),
                        expires_at.isoformat(),
                        now.isoformat(),
                        idempotency_key,
                        request_digest,
                    ),
                )
                sync_version = self._bump_sync(connection, parent_trip_id)
                connection.execute("COMMIT")
                return {
                    "invitation_id": str(invitation_id),
                    "parent_trip_id": str(parent_trip_id),
                    "participant_id": str(participant_id),
                    "expires_at": expires_at.isoformat(),
                    "status": "ACTIVE",
                    "sync_version": sync_version,
                }, secret
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def redeem_invitation(
        self,
        *,
        token: str,
        idempotency_key: str,
        account_user_id: UUID | None,
        display_name: str,
        interests: list[str],
    ) -> tuple[dict[str, object], str]:
        now = self._clock()
        token_hash = self._hash(token)
        account_text = str(account_user_id) if account_user_id else None
        session_secret = self._derived_secret(token, f"parent-session:{idempotency_key}")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                invitation = connection.execute(
                    "SELECT * FROM parent_trip_invitations WHERE token_hash=?",
                    (token_hash,),
                ).fetchone()
                if invitation is None or not self._matches(invitation["token_hash"], token):
                    raise ParentTripStoreError("PARENT_INVITATION_UNAVAILABLE")
                expires_at = datetime.fromisoformat(invitation["expires_at"])
                if expires_at <= now:
                    raise ParentTripStoreError("PARENT_INVITATION_EXPIRED")
                parent_trip_id = UUID(invitation["parent_trip_id"])
                self._ensure_collaboration(connection, parent_trip_id)
                member = connection.execute(
                    """SELECT * FROM parent_trip_members
                    WHERE parent_trip_id=? AND participant_id=?""",
                    (invitation["parent_trip_id"], invitation["participant_id"]),
                ).fetchone()
                if member is None:
                    raise ParentTripStoreError("PARENT_INVITATION_UNAVAILABLE")

                if invitation["status"] == "REDEEMED":
                    if invitation["redeemed_idempotency_key"] != idempotency_key:
                        raise ParentTripStoreError("PARENT_INVITATION_ALREADY_REDEEMED")
                    if member["account_user_id"] != account_text:
                        raise ParentTripStoreError("PARENT_INVITATION_ACCOUNT_MISMATCH")
                    session = connection.execute(
                        "SELECT * FROM parent_trip_member_sessions WHERE session_id=?",
                        (invitation["redeemed_session_id"],),
                    ).fetchone()
                    if session is None:
                        raise ParentTripStoreError("PARENT_MEMBER_SESSION_INVALID")
                    sync_version = int(self._sync_row(connection, parent_trip_id)["version"])
                    connection.execute("COMMIT")
                    return {
                        "session_id": session["session_id"],
                        "parent_trip_id": invitation["parent_trip_id"],
                        "participant_id": invitation["participant_id"],
                        "expires_at": session["expires_at"],
                        "sync_version": sync_version,
                    }, session_secret

                if member["account_user_id"] not in (None, account_text):
                    raise ParentTripStoreError("PARENT_INVITATION_ACCOUNT_MISMATCH")
                if account_text is not None:
                    existing_membership = connection.execute(
                        """SELECT participant_id FROM parent_trip_members
                        WHERE parent_trip_id=? AND account_user_id=? AND participant_id<>?""",
                        (
                            invitation["parent_trip_id"],
                            account_text,
                            invitation["participant_id"],
                        ),
                    ).fetchone()
                    if existing_membership is not None:
                        raise ParentTripStoreError("PARENT_ACCOUNT_ALREADY_MEMBER")

                session_id = uuid4()
                session_expires_at = now + timedelta(days=30)
                connection.execute(
                    """INSERT INTO parent_trip_member_sessions
                    (session_id, parent_trip_id, participant_id, token_hash, expires_at,
                     revoked_at, created_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, NULL, ?, ?)""",
                    (
                        str(session_id),
                        invitation["parent_trip_id"],
                        invitation["participant_id"],
                        self._hash(session_secret),
                        session_expires_at.isoformat(),
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                connection.execute(
                    """UPDATE parent_trip_invitations
                    SET status='REDEEMED', redeemed_at=?, redeemed_idempotency_key=?,
                        redeemed_session_id=? WHERE invitation_id=?""",
                    (
                        now.isoformat(),
                        idempotency_key,
                        str(session_id),
                        invitation["invitation_id"],
                    ),
                )
                connection.execute(
                    """UPDATE parent_trip_members
                    SET account_user_id=?, access_status='MEMBER_ACTIVE', nickname=?,
                        interests_json=?, updated_at=?
                    WHERE parent_trip_id=? AND participant_id=?""",
                    (
                        account_text,
                        display_name,
                        json.dumps(interests, ensure_ascii=False),
                        now.isoformat(),
                        invitation["parent_trip_id"],
                        invitation["participant_id"],
                    ),
                )
                sync_version = self._bump_sync(connection, parent_trip_id)
                connection.execute("COMMIT")
                return {
                    "session_id": str(session_id),
                    "parent_trip_id": invitation["parent_trip_id"],
                    "participant_id": invitation["participant_id"],
                    "expires_at": session_expires_at.isoformat(),
                    "sync_version": sync_version,
                }, session_secret
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def collaboration_rows(
        self,
        parent_trip_id: UUID,
        *,
        organizer_token: str | None = None,
        member_session_token: str | None = None,
    ) -> tuple[
        dict[str, object],
        list[dict[str, object]],
        ParentTripActor,
        dict[str, object],
        list[dict[str, object]],
    ]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if organizer_token:
                    parent = self._authorize_organizer(connection, parent_trip_id, organizer_token)
                    actor = ParentTripActor(
                        participant_id=self._organizer_id(parent_trip_id),
                        role="ORGANIZER",
                    )
                else:
                    parent = connection.execute(
                        "SELECT * FROM parent_trips WHERE parent_trip_id=?",
                        (str(parent_trip_id),),
                    ).fetchone()
                    if parent is None:
                        raise ParentTripStoreError("PARENT_TRIP_NOT_FOUND")
                    self._ensure_collaboration(connection, parent_trip_id)
                    actor = self._authenticate_member(
                        connection, parent_trip_id, member_session_token
                    )
                days = connection.execute(
                    "SELECT * FROM parent_trip_days WHERE parent_trip_id=? ORDER BY day_index",
                    (str(parent_trip_id),),
                ).fetchall()
                if actor.role == "ORGANIZER":
                    profiles = connection.execute(
                        """SELECT * FROM parent_trip_members WHERE parent_trip_id=?
                        ORDER BY CASE role WHEN 'ORGANIZER' THEN 0 ELSE 1 END,
                                 updated_at, participant_id""",
                        (str(parent_trip_id),),
                    ).fetchall()
                else:
                    profiles = connection.execute(
                        """SELECT * FROM parent_trip_members
                        WHERE parent_trip_id=? AND participant_id=?""",
                        (str(parent_trip_id), str(actor.participant_id)),
                    ).fetchall()
                sync = self._sync_row(connection, parent_trip_id)
                connection.execute("COMMIT")
                return (
                    dict(parent),
                    [dict(row) for row in days],
                    actor,
                    dict(sync),
                    [dict(row) for row in profiles],
                )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def update_member_profile(
        self,
        parent_trip_id: UUID,
        *,
        member_session_token: str,
        expected_sync_version: int,
        nickname: str,
        interests: list[str],
        budget_cap_cents: int | None,
    ) -> int:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                actor = self._authenticate_member(
                    connection, parent_trip_id, member_session_token
                )
                current_version = int(self._sync_row(connection, parent_trip_id)["version"])
                if current_version != expected_sync_version:
                    raise ParentTripStoreError("PARENT_TRIP_VERSION_CONFLICT")
                updated = connection.execute(
                    """UPDATE parent_trip_members
                    SET nickname=?, interests_json=?, budget_cap_cents=?,
                        profile_version=profile_version+1, updated_at=?
                    WHERE parent_trip_id=? AND participant_id=? AND role='MEMBER'""",
                    (
                        nickname,
                        json.dumps(interests, ensure_ascii=False, separators=(",", ":")),
                        budget_cap_cents,
                        self._clock().isoformat(),
                        str(parent_trip_id),
                        str(actor.participant_id),
                    ),
                ).rowcount
                if updated != 1:
                    raise ParentTripStoreError("PARENT_MEMBER_PERMISSION_REQUIRED")
                next_version = self._bump_sync(connection, parent_trip_id)
                connection.execute("COMMIT")
                return next_version
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise


__all__ = [
    "ParentTripActor",
    "ParentTripStoreError",
    "SqliteParentTripRepository",
]
