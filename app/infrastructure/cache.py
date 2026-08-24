import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CacheRecord:
    payload: dict[str, Any]
    fetched_at: datetime
    expires_at: datetime

    @property
    def is_stale(self) -> bool:
        return datetime.now(UTC) > self.expires_at


class SqliteProviderCache:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_cache (
                    provider TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    city_code TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (provider, operation, city_code, request_hash)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_provider_cache_city
                ON provider_cache (provider, city_code, operation)
                """
            )

    @staticmethod
    def request_hash(parameters: dict[str, Any]) -> str:
        normalized = json.dumps(
            parameters,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def put(
        self,
        *,
        provider: str,
        operation: str,
        city_code: str,
        parameters: dict[str, Any],
        payload: dict[str, Any],
        ttl_seconds: int,
        fetched_at: datetime | None = None,
    ) -> CacheRecord:
        fetched_at = fetched_at or datetime.now(UTC)
        expires_at = fetched_at + timedelta(seconds=ttl_seconds)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO provider_cache (
                    provider, operation, city_code, request_hash,
                    payload_json, fetched_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, operation, city_code, request_hash)
                DO UPDATE SET
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                """,
                (
                    provider,
                    operation,
                    city_code,
                    self.request_hash(parameters),
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    fetched_at.isoformat(),
                    expires_at.isoformat(),
                ),
            )
        return CacheRecord(payload, fetched_at, expires_at)

    def get(
        self,
        *,
        provider: str,
        operation: str,
        city_code: str,
        parameters: dict[str, Any],
    ) -> CacheRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json, fetched_at, expires_at
                FROM provider_cache
                WHERE provider = ? AND operation = ?
                  AND city_code = ? AND request_hash = ?
                """,
                (
                    provider,
                    operation,
                    city_code,
                    self.request_hash(parameters),
                ),
            ).fetchone()
        if row is None:
            return None
        return CacheRecord(
            payload=json.loads(row["payload_json"]),
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
        )
