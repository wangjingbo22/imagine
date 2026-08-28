from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from app.application.recommendation_service import ProviderFactRestoreError
from app.domain.models import Place, Route
from app.services.recommendation import (
    ProviderFactBundle,
    ProviderFactIssueDraft,
    ProviderFactReferenceSummary,
    ProviderFactSetSummary,
    ProviderFactSnapshot,
)


class ProviderFactIssuanceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)  # type: ignore[union-attr]
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class SqliteProviderFactRegistry:
    """Immutable T006 registry for server-issued AMAP/cache fact sets."""

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
                CREATE TABLE IF NOT EXISTS provider_fact_sets (
                    fact_set_id TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL,
                    provider_fact_digest TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    UNIQUE (trip_id, provider_fact_digest)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_fact_refs (
                    fact_set_id TEXT NOT NULL,
                    fact_ref_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('PLACE', 'ROUTE')),
                    provider_object_id TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source_status TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    is_stale INTEGER NOT NULL CHECK (is_stale IN (0, 1)),
                    PRIMARY KEY (fact_set_id, fact_ref_id),
                    FOREIGN KEY (fact_set_id)
                        REFERENCES provider_fact_sets(fact_set_id)
                        ON DELETE RESTRICT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_provider_fact_sets_trip
                ON provider_fact_sets (trip_id, issued_at)
                """
            )

    @staticmethod
    def content_digest(draft: ProviderFactIssueDraft) -> str:
        return _sha256(draft)

    @staticmethod
    def _reference_for_place(place: Place) -> ProviderFactReferenceSummary:
        payload_digest = _sha256(place)
        return ProviderFactReferenceSummary(
            fact_ref_id=f"AMAP:{payload_digest[:24]}",
            kind="PLACE",
            provider_object_id=place.placeId,
            payload_digest=payload_digest,
            source_status=place.provenance.sourceStatus,
            fetched_at=place.provenance.fetchedAt,
            is_stale=place.provenance.isStale,
        )

    @staticmethod
    def _reference_for_route(route: Route) -> ProviderFactReferenceSummary:
        payload_digest = _sha256(route)
        return ProviderFactReferenceSummary(
            fact_ref_id=f"fact-route-{payload_digest[:24]}",
            kind="ROUTE",
            provider_object_id=route.routeId,
            payload_digest=payload_digest,
            source_status=route.provenance.sourceStatus,
            fetched_at=route.provenance.fetchedAt,
            is_stale=route.provenance.isStale,
        )

    @classmethod
    def _references(
        cls,
        draft: ProviderFactIssueDraft,
    ) -> tuple[ProviderFactReferenceSummary, ...]:
        places = sorted(draft.places, key=lambda item: item.placeId)
        routes = sorted(draft.routes, key=lambda item: item.routeId)
        references = tuple(
            [cls._reference_for_place(item) for item in places]
            + [cls._reference_for_route(item) for item in routes]
        )
        fact_ref_ids = [item.fact_ref_id for item in references]
        if len(fact_ref_ids) != len(set(fact_ref_ids)):
            raise ProviderFactIssuanceError(
                "PROVIDER_FACT_REF_COLLISION",
                "服务端生成了重复 FactRef，事实集未写入",
            )
        return references

    def issue(
        self,
        draft: ProviderFactIssueDraft,
        *,
        issued_at: datetime | None = None,
    ) -> ProviderFactSetSummary:
        """Atomically sign and store a validated server-created fact snapshot."""

        # Re-validate at the persistence boundary so model_copy/construct cannot
        # bypass the Provider/cache provenance checks.
        try:
            trusted_draft = ProviderFactIssueDraft.model_validate_json(
                draft.model_dump_json(by_alias=True),
                strict=True,
            )
        except (ValidationError, ValueError, TypeError) as error:
            raise ProviderFactIssuanceError(
                "PROVIDER_FACT_ISSUANCE_INVALID",
                "地点、路线、价格或来源不是可信 Provider/cache 事实",
            ) from error

        digest = self.content_digest(trusted_draft)
        fact_set_id = f"fact-set-{digest[:24]}"
        resolved_issued_at = (issued_at or datetime.now(UTC)).astimezone(UTC)
        references = self._references(trusted_draft)
        snapshot = ProviderFactSnapshot(
            fact_set_id=fact_set_id,
            provider_fact_digest=digest,
            issued_at=resolved_issued_at,
            draft=trusted_draft,
            references=references,
        )
        snapshot_json = snapshot.model_dump_json(by_alias=True)
        payloads = self._payloads_by_reference(trusted_draft, references)

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    """
                    SELECT snapshot_json FROM provider_fact_sets
                    WHERE trip_id = ? AND provider_fact_digest = ?
                    """,
                    (str(trusted_draft.trip.trip_id), digest),
                ).fetchone()
                if existing is not None:
                    existing_snapshot = self._parse_and_verify_snapshot(
                        existing["snapshot_json"],
                    )
                    connection.execute("COMMIT")
                    return existing_snapshot.summary()

                connection.execute(
                    """
                    INSERT INTO provider_fact_sets (
                        fact_set_id, trip_id, provider_fact_digest,
                        snapshot_json, issued_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        fact_set_id,
                        str(trusted_draft.trip.trip_id),
                        digest,
                        snapshot_json,
                        resolved_issued_at.isoformat(),
                    ),
                )
                for reference in references:
                    payload = payloads[reference.fact_ref_id]
                    connection.execute(
                        """
                        INSERT INTO provider_fact_refs (
                            fact_set_id, fact_ref_id, kind, provider_object_id,
                            payload_digest, payload_json, source_status,
                            fetched_at, is_stale
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            fact_set_id,
                            reference.fact_ref_id,
                            reference.kind,
                            reference.provider_object_id,
                            reference.payload_digest,
                            _canonical_json(payload),
                            reference.source_status.value,
                            reference.fetched_at.isoformat(),
                            int(reference.is_stale),
                        ),
                    )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return snapshot.summary()

    def restore(self, trip_id: UUID, fact_set_id: str) -> ProviderFactBundle:
        return self.restore_snapshot(trip_id, fact_set_id).as_bundle()

    def restore_snapshot(
        self,
        trip_id: UUID,
        fact_set_id: str,
    ) -> ProviderFactSnapshot:
        with closing(self._connect()) as connection:
            set_row = connection.execute(
                "SELECT * FROM provider_fact_sets WHERE fact_set_id = ?",
                (fact_set_id,),
            ).fetchone()
            if set_row is None:
                raise ProviderFactRestoreError(
                    "PROVIDER_FACT_SET_NOT_FOUND",
                    "未找到服务端签发的 FactRef 集合",
                )
            if set_row["trip_id"] != str(trip_id):
                raise ProviderFactRestoreError(
                    "PROVIDER_FACT_TRIP_MISMATCH",
                    "FactRef 集合不属于当前 Trip",
                )
            ref_rows = connection.execute(
                """
                SELECT * FROM provider_fact_refs
                WHERE fact_set_id = ? ORDER BY kind, fact_ref_id
                """,
                (fact_set_id,),
            ).fetchall()

        snapshot = self._parse_and_verify_snapshot(set_row["snapshot_json"])
        if (
            snapshot.fact_set_id != set_row["fact_set_id"]
            or snapshot.provider_fact_digest != set_row["provider_fact_digest"]
            or str(snapshot.draft.trip.trip_id) != set_row["trip_id"]
            or snapshot.issued_at.isoformat() != set_row["issued_at"]
        ):
            raise ProviderFactRestoreError(
                "PROVIDER_FACT_INTEGRITY_ERROR",
                "FactRef 集合元数据与服务端签发快照不一致",
            )
        self._verify_reference_rows(snapshot, ref_rows)
        return snapshot

    @classmethod
    def _parse_and_verify_snapshot(cls, raw: str) -> ProviderFactSnapshot:
        try:
            snapshot = ProviderFactSnapshot.model_validate_json(raw, strict=True)
        except (ValidationError, ValueError, TypeError) as error:
            raise ProviderFactRestoreError(
                "PROVIDER_FACT_INTEGRITY_ERROR",
                "服务端 FactRef 快照结构已损坏",
            ) from error
        expected_digest = cls.content_digest(snapshot.draft)
        expected_id = f"fact-set-{expected_digest[:24]}"
        if (
            snapshot.provider_fact_digest != expected_digest
            or snapshot.fact_set_id != expected_id
            or snapshot.references != cls._references(snapshot.draft)
        ):
            raise ProviderFactRestoreError(
                "PROVIDER_FACT_INTEGRITY_ERROR",
                "地点、路线、价格或来源摘要与服务端签发值不一致",
            )
        return snapshot

    @staticmethod
    def _payloads_by_reference(
        draft: ProviderFactIssueDraft,
        references: tuple[ProviderFactReferenceSummary, ...],
    ) -> dict[str, Place | Route]:
        places = {item.placeId: item for item in draft.places}
        routes = {item.routeId: item for item in draft.routes}
        return {
            reference.fact_ref_id: (
                places[reference.provider_object_id]
                if reference.kind == "PLACE"
                else routes[reference.provider_object_id]
            )
            for reference in references
        }

    @classmethod
    def _verify_reference_rows(
        cls,
        snapshot: ProviderFactSnapshot,
        rows: list[sqlite3.Row],
    ) -> None:
        payloads = cls._payloads_by_reference(
            snapshot.draft,
            snapshot.references,
        )
        expected = {
            reference.fact_ref_id: (
                reference,
                _canonical_json(payloads[reference.fact_ref_id]),
            )
            for reference in snapshot.references
        }
        if {row["fact_ref_id"] for row in rows} != set(expected):
            raise ProviderFactRestoreError(
                "PROVIDER_FACT_INTEGRITY_ERROR",
                "FactRef 注册表与签发快照不一致",
            )
        for row in rows:
            reference, payload_json = expected[row["fact_ref_id"]]
            if (
                row["kind"] != reference.kind
                or row["provider_object_id"] != reference.provider_object_id
                or row["payload_digest"] != reference.payload_digest
                or row["payload_json"] != payload_json
                or row["source_status"] != reference.source_status.value
                or row["fetched_at"] != reference.fetched_at.isoformat()
                or bool(row["is_stale"]) != reference.is_stale
            ):
                raise ProviderFactRestoreError(
                    "PROVIDER_FACT_INTEGRITY_ERROR",
                    "FactRef 地点、路线、价格或来源记录已被篡改",
                )


__all__ = ["ProviderFactIssuanceError", "SqliteProviderFactRegistry"]
