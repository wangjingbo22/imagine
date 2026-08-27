from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError

from app.schemas.plan import PlanVersion, ProposedPlanVersion
from app.services.planning.models import CandidatePlan, CandidatePlanRequest


BoundaryKind = Literal["V1", "V2"]


@dataclass(frozen=True, slots=True)
class TrustedPlanningStoreError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def proposal_digest(plan: ProposedPlanVersion | PlanVersion) -> str:
    """Hash only the immutable proposal; storage transition fields are excluded."""

    payload = plan.model_dump(mode="json", by_alias=True)
    payload.pop("status", None)
    payload.pop("createdAt", None)
    payload.pop("confirmedAt", None)
    canonical = _canonical_json(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SqliteTrustedPlanningRepository:
    """Server-owned facts and issuance evidence for generated plans.

    A VALIDATED row is usable by T011 during T018 selection, but only an ISSUED
    row may cross an HTTP confirmation/acceptance boundary.
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            isolation_level=None,
            timeout=5,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trusted_plan_issuances (
                    plan_id TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL,
                    plan_version INTEGER NOT NULL CHECK (plan_version IN (1, 2)),
                    boundary_kind TEXT NOT NULL CHECK (boundary_kind IN ('V1', 'V2')),
                    proposal_digest TEXT NOT NULL,
                    candidate_facts_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    issuance_state TEXT NOT NULL
                        CHECK (issuance_state IN ('VALIDATED', 'ISSUED')),
                    created_at TEXT NOT NULL,
                    issued_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trusted_plan_issuances_trip
                ON trusted_plan_issuances (trip_id, boundary_kind, issuance_state)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS candidate_plan_reviews (
                    review_id TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    review_state TEXT NOT NULL
                        CHECK (review_state IN ('PENDING', 'CONFIRMED')),
                    confirmation_digest TEXT,
                    confirmed_request_json TEXT,
                    issued_plan_id TEXT,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candidate_plan_reviews_trip
                ON candidate_plan_reviews (trip_id, review_state)
                """
            )

    def stage_review(
        self,
        *,
        review_id: str,
        request: CandidatePlanRequest,
        candidate: CandidatePlan,
    ) -> dict[str, Any]:
        request_json = _canonical_json(
            request.model_dump(mode="json", by_alias=True)
        )
        candidate_json = _canonical_json(
            candidate.model_dump(mode="json", by_alias=True)
        )
        request_digest = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM candidate_plan_reviews WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO candidate_plan_reviews (
                            review_id, trip_id, candidate_id, request_digest,
                            request_json, candidate_json, review_state,
                            confirmation_digest, confirmed_request_json,
                            issued_plan_id, created_at, confirmed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', NULL, NULL, NULL, ?, NULL)
                        """,
                        (
                            review_id,
                            str(request.trip.trip_id),
                            candidate.candidate_id,
                            request_digest,
                            request_json,
                            candidate_json,
                            now,
                        ),
                    )
                    row = connection.execute(
                        "SELECT * FROM candidate_plan_reviews WHERE review_id = ?",
                        (review_id,),
                    ).fetchone()
                elif (
                    row["trip_id"] != str(request.trip.trip_id)
                    or row["candidate_id"] != candidate.candidate_id
                    or row["request_digest"] != request_digest
                    or row["request_json"] != request_json
                    or row["candidate_json"] != candidate_json
                ):
                    raise TrustedPlanningStoreError(
                        "PLANNING_REVIEW_CONFLICT",
                        "同一 reviewId 已绑定到不同的候选事实",
                    )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        assert row is not None
        return dict(row)

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM candidate_plan_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def mark_review_confirmed(
        self,
        *,
        review_id: str,
        confirmation_digest: str,
        confirmed_request: CandidatePlanRequest,
        issued_plan_id: UUID,
    ) -> dict[str, Any]:
        confirmed_request_json = _canonical_json(
            confirmed_request.model_dump(mode="json", by_alias=True)
        )
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM candidate_plan_reviews WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
                if row is None:
                    raise TrustedPlanningStoreError(
                        "PLANNING_REVIEW_NOT_FOUND",
                        "未找到待确认的候选计划",
                    )
                if row["review_state"] == "CONFIRMED":
                    if (
                        row["confirmation_digest"] != confirmation_digest
                        or row["confirmed_request_json"] != confirmed_request_json
                        or row["issued_plan_id"] != str(issued_plan_id)
                    ):
                        raise TrustedPlanningStoreError(
                            "PLANNING_REVIEW_ALREADY_CONFIRMED",
                            "候选计划已使用不同的确认内容完成签发",
                        )
                    connection.execute("COMMIT")
                    return dict(row)
                connection.execute(
                    """
                    UPDATE candidate_plan_reviews
                    SET review_state = 'CONFIRMED', confirmation_digest = ?,
                        confirmed_request_json = ?, issued_plan_id = ?, confirmed_at = ?
                    WHERE review_id = ?
                    """,
                    (
                        confirmation_digest,
                        confirmed_request_json,
                        str(issued_plan_id),
                        now,
                        review_id,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM candidate_plan_reviews WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        assert row is not None
        return dict(row)

    def stage_candidate(
        self,
        *,
        plan: ProposedPlanVersion,
        request: CandidatePlanRequest,
        boundary_kind: BoundaryKind,
        validation: dict[str, Any],
    ) -> None:
        expected_version = 1 if boundary_kind == "V1" else 2
        if plan.version != expected_version:
            raise TrustedPlanningStoreError(
                "PLANNING_TRUST_RECORD_INVALID",
                f"{boundary_kind} 签发记录与 PlanVersion.version 不一致",
            )
        if request.trip.trip_id != plan.trip_snapshot.trip_id:
            raise TrustedPlanningStoreError(
                "PLANNING_TRUST_RECORD_INVALID",
                "候选事实与 PlanVersion 不属于同一 Trip",
            )

        values = {
            "plan_id": str(plan.plan_id),
            "trip_id": str(plan.trip_snapshot.trip_id),
            "plan_version": plan.version,
            "boundary_kind": boundary_kind,
            "proposal_digest": proposal_digest(plan),
            "candidate_facts_json": _canonical_json(
                request.model_dump(mode="json", by_alias=True)
            ),
            "validation_json": _canonical_json(validation),
        }
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT * FROM trusted_plan_issuances WHERE plan_id = ?",
                    (values["plan_id"],),
                ).fetchone()
                if existing is not None:
                    comparable = (
                        existing["trip_id"],
                        existing["plan_version"],
                        existing["boundary_kind"],
                        existing["proposal_digest"],
                        existing["candidate_facts_json"],
                        existing["validation_json"],
                    )
                    expected = (
                        values["trip_id"],
                        values["plan_version"],
                        values["boundary_kind"],
                        values["proposal_digest"],
                        values["candidate_facts_json"],
                        values["validation_json"],
                    )
                    if comparable != expected:
                        raise TrustedPlanningStoreError(
                            "PLANNING_TRUST_RECORD_CONFLICT",
                            "同一 planId 已绑定到不同的服务端事实、提案或验证证据",
                        )
                    connection.execute("COMMIT")
                    return

                connection.execute(
                    """
                    INSERT INTO trusted_plan_issuances (
                        plan_id, trip_id, plan_version, boundary_kind,
                        proposal_digest, candidate_facts_json, validation_json,
                        issuance_state, created_at, issued_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'VALIDATED', ?, NULL)
                    """,
                    (
                        values["plan_id"],
                        values["trip_id"],
                        values["plan_version"],
                        values["boundary_kind"],
                        values["proposal_digest"],
                        values["candidate_facts_json"],
                        values["validation_json"],
                        now,
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def mark_issued(
        self,
        plan: PlanVersion,
        *,
        validation: dict[str, Any] | None = None,
    ) -> None:
        plan_id = str(plan.plan_id)
        digest = proposal_digest(plan)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM trusted_plan_issuances WHERE plan_id = ?",
                    (plan_id,),
                ).fetchone()
                if row is None:
                    raise TrustedPlanningStoreError(
                        "PLANNING_TRUST_RECORD_NOT_FOUND",
                        "签发前未找到服务端验证记录",
                    )
                if row["proposal_digest"] != digest:
                    raise TrustedPlanningStoreError(
                        "PLANNING_PROPOSAL_DIGEST_MISMATCH",
                        "已登记 PlanVersion 与服务端验证提案摘要不一致",
                    )
                validation_json = (
                    _canonical_json(validation)
                    if validation is not None
                    else row["validation_json"]
                )
                if validation_json != row["validation_json"]:
                    raise TrustedPlanningStoreError(
                        "PLANNING_VALIDATION_EVIDENCE_CONFLICT",
                        "签发时的验证证据与已暂存的不可变证据不一致",
                    )
                connection.execute(
                    """
                    UPDATE trusted_plan_issuances
                    SET issuance_state = 'ISSUED', issued_at = ?
                    WHERE plan_id = ?
                    """,
                    (datetime.now(UTC).isoformat(), plan_id),
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def get_candidate_request(
        self,
        candidate_plan_id: UUID,
    ) -> CandidatePlanRequest | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT candidate_facts_json
                FROM trusted_plan_issuances
                WHERE plan_id = ?
                """,
                (str(candidate_plan_id),),
            ).fetchone()
        if row is None:
            return None
        try:
            return CandidatePlanRequest.model_validate_json(
                row["candidate_facts_json"],
                strict=True,
            )
        except ValidationError as exc:
            raise TrustedPlanningStoreError(
                "PLANNING_FACTS_INVALID",
                "服务端保存的候选事实无法通过严格校验",
            ) from exc

    def require_issued(
        self,
        *,
        trip_id: UUID,
        plan: PlanVersion,
        boundary_kind: BoundaryKind,
    ) -> None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM trusted_plan_issuances WHERE plan_id = ?",
                (str(plan.plan_id),),
            ).fetchone()
        if row is None or row["issuance_state"] != "ISSUED":
            raise TrustedPlanningStoreError(
                "PLANNING_PLAN_NOT_ISSUED",
                "该 PlanVersion 未由服务端规划边界签发，不能确认或接受",
            )
        expected_version = 1 if boundary_kind == "V1" else 2
        if (
            row["trip_id"] != str(trip_id)
            or row["boundary_kind"] != boundary_kind
            or row["plan_version"] != expected_version
            or plan.trip_snapshot.trip_id != trip_id
            or plan.version != expected_version
        ):
            raise TrustedPlanningStoreError(
                "PLANNING_ISSUANCE_SCOPE_MISMATCH",
                "签发记录与请求中的 Trip 或 PlanVersion 边界不一致",
            )
        if row["proposal_digest"] != proposal_digest(plan):
            raise TrustedPlanningStoreError(
                "PLANNING_PROPOSAL_DIGEST_MISMATCH",
                "PlanVersion 快照与服务端签发时的提案摘要不一致",
            )

    def get_issued_validation(
        self,
        *,
        trip_id: UUID,
        plan: PlanVersion,
        boundary_kind: BoundaryKind,
    ) -> dict[str, Any]:
        """Return immutable validation evidence after full issuance checks."""

        self.require_issued(
            trip_id=trip_id,
            plan=plan,
            boundary_kind=boundary_kind,
        )
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT validation_json FROM trusted_plan_issuances WHERE plan_id = ?",
                (str(plan.plan_id),),
            ).fetchone()
        if row is None:
            raise TrustedPlanningStoreError(
                "PLANNING_TRUST_RECORD_NOT_FOUND",
                "签发验证证据不存在",
            )
        try:
            value = json.loads(row["validation_json"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TrustedPlanningStoreError(
                "PLANNING_VALIDATION_EVIDENCE_INVALID",
                "签发验证证据不是有效 JSON",
            ) from exc
        if not isinstance(value, dict):
            raise TrustedPlanningStoreError(
                "PLANNING_VALIDATION_EVIDENCE_INVALID",
                "签发验证证据必须是对象",
            )
        return value


__all__ = [
    "SqliteTrustedPlanningRepository",
    "TrustedPlanningStoreError",
    "proposal_digest",
]
