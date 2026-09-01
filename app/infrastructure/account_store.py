from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from app.domain.account import CurrentUser, ProfileUpdateRequest, normalized_email


class AccountStoreError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class StoredUser:
    user_id: UUID
    email: str
    password_hash: str
    display_name: str
    home_city: str | None
    interests: list[str]

    def current_user(self) -> CurrentUser:
        return CurrentUser(
            user_id=self.user_id,
            email=self.email,
            display_name=self.display_name,
            home_city=self.home_city,
            interests=self.interests,
        )


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SqliteAccountRepository:
    def __init__(
        self,
        database_path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_path = database_path
        self._clock = clock or (lambda: datetime.now(UTC))
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
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    home_city TEXT,
                    interests_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS account_model_settings (
                user_id TEXT PRIMARY KEY, model TEXT NOT NULL, encrypted_api_key TEXT NOT NULL,
                updated_at TEXT NOT NULL, FOREIGN KEY (user_id) REFERENCES users (user_id))"""
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(account_model_settings)")}
            if "base_url" not in columns:
                connection.execute("ALTER TABLE account_model_settings ADD COLUMN base_url TEXT NOT NULL DEFAULT 'https://dashscope.aliyuncs.com/compatible-mode/v1'")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS account_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_account_sessions_user
                ON account_sessions (user_id, expires_at)
                """
            )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _user_from_row(row: sqlite3.Row) -> StoredUser:
        return StoredUser(
            user_id=UUID(row["user_id"]),
            email=row["email"],
            password_hash=row["password_hash"],
            display_name=row["display_name"],
            home_city=row["home_city"],
            interests=json.loads(row["interests_json"]),
        )

    def create_user(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        home_city: str | None = None,
        interests: list[str] | None = None,
        user_id: UUID | None = None,
    ) -> StoredUser:
        now = self._utc(self._clock()).isoformat()
        identity = user_id or uuid4()
        interest_values = interests or []
        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    """
                    INSERT INTO users (
                        user_id, email, password_hash, display_name, home_city,
                        interests_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(identity),
                        normalized_email(email),
                        password_hash,
                        display_name,
                        home_city,
                        json.dumps(interest_values, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM users WHERE user_id = ?", (str(identity),)
                ).fetchone()
        except sqlite3.IntegrityError as error:
            if "users.email" in str(error) or "UNIQUE constraint failed" in str(error):
                raise AccountStoreError("ACCOUNT_EMAIL_TAKEN") from error
            raise
        assert row is not None
        return self._user_from_row(row)

    def get_user_by_email(self, email: str) -> StoredUser | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email = ?",
                (normalized_email(email),),
            ).fetchone()
        return self._user_from_row(row) if row is not None else None

    def update_profile(
        self,
        user_id: UUID,
        profile: ProfileUpdateRequest,
    ) -> StoredUser:
        now = self._utc(self._clock()).isoformat()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE users
                SET display_name = ?, home_city = ?, interests_json = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (
                    profile.display_name,
                    profile.home_city,
                    json.dumps(profile.interests, ensure_ascii=False),
                    now,
                    str(user_id),
                ),
            )
            row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?", (str(user_id),)
            ).fetchone()
        if row is None:
            raise AccountStoreError("ACCOUNT_USER_NOT_FOUND")
        return self._user_from_row(row)

    def create_session(
        self,
        *,
        token: str,
        user_id: UUID,
        expires_at: datetime,
    ) -> None:
        now = self._utc(self._clock()).isoformat()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO account_sessions (
                    token_hash, user_id, created_at, expires_at, revoked_at
                ) VALUES (?, ?, ?, ?, NULL)
                """,
                (
                    hash_session_token(token),
                    str(user_id),
                    now,
                    self._utc(expires_at).isoformat(),
                ),
            )

    def get_user_by_session(
        self,
        token: str,
        *,
        now: datetime | None = None,
    ) -> StoredUser | None:
        current_time = self._utc(now or self._clock())
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT u.*
                FROM account_sessions AS s
                JOIN users AS u ON u.user_id = s.user_id
                WHERE s.token_hash = ?
                  AND s.revoked_at IS NULL
                  AND s.expires_at > ?
                """,
                (hash_session_token(token), current_time.isoformat()),
            ).fetchone()
        return self._user_from_row(row) if row is not None else None

    def revoke_session(self, token: str) -> None:
        now = self._utc(self._clock()).isoformat()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE account_sessions
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE token_hash = ?
                """,
                (now, hash_session_token(token)),
            )

    def save_model_settings(self, user_id: UUID, *, model: str, encrypted_api_key: str, base_url: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute("""INSERT INTO account_model_settings(user_id,model,encrypted_api_key,base_url,updated_at)
            VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET model=excluded.model, encrypted_api_key=excluded.encrypted_api_key, base_url=excluded.base_url, updated_at=excluded.updated_at""", (str(user_id), model, encrypted_api_key, base_url, self._utc(self._clock()).isoformat()))

    def get_model_settings(self, user_id: UUID) -> tuple[str, str, str] | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT model, encrypted_api_key, base_url FROM account_model_settings WHERE user_id = ?", (str(user_id),)).fetchone()
        return (row["model"], row["encrypted_api_key"], row["base_url"]) if row else None

    def delete_model_settings(self, user_id: UUID) -> None:
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM account_model_settings WHERE user_id = ?", (str(user_id),))
