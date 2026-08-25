from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.domain.plan_guard import (
    StateTransitionViolation,
    require_plan_transition,
    require_trip_transition,
)
from app.domain.plan_diff import calculate_plan_diff
from app.schemas.plan import (
    ExecutionStartResult,
    PlanTransitionResult,
    PlanV2Decision,
    PlanV2DecisionResult,
    PlanVersion,
    PlanVersionDiff,
    PlanVersionStatus,
    ProposedPlanVersion,
    TripPlanState,
)
from app.schemas.trip import TripStatus


@dataclass(frozen=True, slots=True)
class PlanStoreError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


class SqlitePlanVersionRepository:
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
                CREATE TABLE IF NOT EXISTS trips (
                    trip_id TEXT PRIMARY KEY,
                    trip_status TEXT NOT NULL,
                    trip_snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_versions (
                    plan_id TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    FOREIGN KEY (trip_id) REFERENCES trips (trip_id),
                    UNIQUE (trip_id, version)
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_plan_versions_current
                ON plan_versions (trip_id)
                WHERE status = 'CURRENT'
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_plan_versions_trip_status
                ON plan_versions (trip_id, status, version)
                """
            )

    @staticmethod
    def _begin(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

    @staticmethod
    def _commit(connection: sqlite3.Connection) -> None:
        connection.execute("COMMIT")

    @staticmethod
    def _rollback(connection: sqlite3.Connection) -> None:
        if connection.in_transaction:
            connection.execute("ROLLBACK")

    @staticmethod
    def _plan_from_row(row: sqlite3.Row) -> PlanVersion:
        proposal = ProposedPlanVersion.model_validate_json(
            row["snapshot_json"],
            strict=True,
        )
        return PlanVersion(
            **proposal.model_dump(),
            status=PlanVersionStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            confirmed_at=(
                datetime.fromisoformat(row["confirmed_at"])
                if row["confirmed_at"]
                else None
            ),
        )

    def register_proposed(self, proposal: ProposedPlanVersion) -> PlanVersion:
        trip_id = str(proposal.trip_snapshot.trip_id)
        plan_id = str(proposal.plan_id)
        snapshot_json = proposal.model_dump_json(by_alias=True)
        trip_snapshot_json = proposal.trip_snapshot.model_dump_json(by_alias=True)
        now = datetime.now(UTC).isoformat()

        with closing(self._connect()) as connection:
            self._begin(connection)
            try:
                existing_plan = connection.execute(
                    "SELECT * FROM plan_versions WHERE plan_id = ?",
                    (plan_id,),
                ).fetchone()
                if existing_plan is not None:
                    if (
                        existing_plan["trip_id"] == trip_id
                        and existing_plan["snapshot_json"] == snapshot_json
                    ):
                        raise PlanStoreError(
                            "PLAN_VERSION_ALREADY_EXISTS",
                            "同一 PlanVersion 已写入，不允许重复登记",
                        )
                    raise PlanStoreError(
                        "PLAN_VERSION_IMMUTABLE",
                        "同一 planId 已保存为不同快照，PlanVersion 不允许原地修改",
                    )

                trip = connection.execute(
                    "SELECT * FROM trips WHERE trip_id = ?",
                    (trip_id,),
                ).fetchone()
                if proposal.version == 1:
                    if trip is None:
                        connection.execute(
                            """
                            INSERT INTO trips (
                                trip_id, trip_status, trip_snapshot_json,
                                created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                trip_id,
                                TripStatus.PLAN_REVIEW.value,
                                trip_snapshot_json,
                                now,
                                now,
                            ),
                        )
                    else:
                        if trip["trip_snapshot_json"] != trip_snapshot_json:
                            raise PlanStoreError(
                                "TRIP_SNAPSHOT_IMMUTABLE",
                                "同一 tripId 的规划输入快照不允许被替换",
                            )
                        if TripStatus(trip["trip_status"]) is not TripStatus.PLAN_REVIEW:
                            raise PlanStoreError(
                                "PLAN_STATE_TRANSITION_INVALID",
                                f"当前 Trip 状态 {trip['trip_status']} 不允许登记 Plan V1 候选",
                            )

                    current = connection.execute(
                        """
                        SELECT plan_id FROM plan_versions
                        WHERE trip_id = ? AND status = 'CURRENT'
                        """,
                        (trip_id,),
                    ).fetchone()
                    if current is not None:
                        raise PlanStoreError(
                            "PLAN_CURRENT_CONFLICT",
                            "同一 Trip 已存在 CURRENT 版本",
                        )
                else:
                    if trip is None:
                        raise PlanStoreError("TRIP_NOT_FOUND", "未找到 Trip")
                    if trip["trip_snapshot_json"] != trip_snapshot_json:
                        raise PlanStoreError(
                            "TRIP_SNAPSHOT_IMMUTABLE",
                            "Plan V2 必须沿用同一 Trip 的规划输入快照",
                        )
                    if TripStatus(trip["trip_status"]) is not TripStatus.EXECUTING:
                        raise PlanStoreError(
                            "PLAN_STATE_TRANSITION_INVALID",
                            f"当前 Trip 状态 {trip['trip_status']} 不允许登记 Plan V2 候选",
                        )
                    parent = connection.execute(
                        "SELECT * FROM plan_versions WHERE plan_id = ?",
                        (str(proposal.parent_id),),
                    ).fetchone()
                    if parent is None:
                        raise PlanStoreError(
                            "PLAN_PARENT_NOT_FOUND",
                            "未找到 Plan V2 的 parentId",
                        )
                    if parent["trip_id"] != trip_id:
                        raise PlanStoreError(
                            "PLAN_TRIP_MISMATCH",
                            "Plan V2 的 parentId 不属于同一 Trip",
                        )
                    if PlanVersionStatus(parent["status"]) is not PlanVersionStatus.CURRENT:
                        raise PlanStoreError(
                            "PLAN_PARENT_NOT_CURRENT",
                            "Plan V2 的 parentId 必须指向当前 CURRENT",
                        )

                connection.execute(
                    """
                    INSERT INTO plan_versions (
                        plan_id, trip_id, version, status, snapshot_json,
                        created_at, confirmed_at
                    ) VALUES (?, ?, ?, 'PROPOSED', ?, ?, NULL)
                    """,
                    (plan_id, trip_id, proposal.version, snapshot_json, now),
                )
                if proposal.version == 2:
                    connection.execute(
                        """
                        UPDATE trips
                        SET trip_status = 'REPLAN_REVIEW', updated_at = ?
                        WHERE trip_id = ? AND trip_status = 'EXECUTING'
                        """,
                        (now, trip_id),
                    )
                row = connection.execute(
                    "SELECT * FROM plan_versions WHERE plan_id = ?",
                    (plan_id,),
                ).fetchone()
                self._commit(connection)
                assert row is not None
                return self._plan_from_row(row)
            except sqlite3.IntegrityError as exc:
                self._rollback(connection)
                raise PlanStoreError(
                    "PLAN_VERSION_CONFLICT",
                    "PlanVersion 版本号或 CURRENT 唯一约束冲突",
                ) from exc
            except Exception:
                self._rollback(connection)
                raise

    def confirm(self, trip_id: UUID, plan_id: UUID) -> PlanTransitionResult:
        trip_text = str(trip_id)
        plan_text = str(plan_id)
        now = datetime.now(UTC).isoformat()

        with closing(self._connect()) as connection:
            self._begin(connection)
            try:
                plan = connection.execute(
                    "SELECT * FROM plan_versions WHERE plan_id = ?",
                    (plan_text,),
                ).fetchone()
                if plan is None:
                    raise PlanStoreError("PLAN_VERSION_NOT_FOUND", "未找到 PlanVersion")
                if plan["trip_id"] != trip_text:
                    raise PlanStoreError(
                        "PLAN_TRIP_MISMATCH",
                        "planId 不属于请求路径中的 tripId",
                    )
                if plan["version"] != 1:
                    raise PlanStoreError(
                        "PLAN_STATE_TRANSITION_INVALID",
                        "Plan V2 必须通过 accept 或 reject 决策，不能使用 confirm",
                    )

                trip = connection.execute(
                    "SELECT * FROM trips WHERE trip_id = ?",
                    (trip_text,),
                ).fetchone()
                if trip is None:
                    raise PlanStoreError("TRIP_NOT_FOUND", "未找到 Trip")

                plan_status = PlanVersionStatus(plan["status"])
                trip_status = TripStatus(trip["trip_status"])
                if plan_status is PlanVersionStatus.CURRENT:
                    self._commit(connection)
                    return PlanTransitionResult(
                        trip_id=trip_id,
                        plan_id=plan_id,
                        trip_status=trip_status,
                        plan_status=plan_status,
                    )

                try:
                    require_plan_transition(plan_status, PlanVersionStatus.CURRENT)
                    require_trip_transition(trip_status, TripStatus.CONFIRMED)
                except StateTransitionViolation as exc:
                    raise PlanStoreError(
                        "PLAN_STATE_TRANSITION_INVALID",
                        str(exc),
                    ) from exc

                current = connection.execute(
                    """
                    SELECT plan_id FROM plan_versions
                    WHERE trip_id = ? AND status = 'CURRENT'
                    """,
                    (trip_text,),
                ).fetchone()
                if current is not None:
                    raise PlanStoreError(
                        "PLAN_CURRENT_CONFLICT",
                        "同一 Trip 已存在 CURRENT 版本",
                    )

                connection.execute(
                    """
                    UPDATE plan_versions
                    SET status = 'CURRENT', confirmed_at = ?
                    WHERE plan_id = ? AND status = 'PROPOSED'
                    """,
                    (now, plan_text),
                )
                connection.execute(
                    """
                    UPDATE trips
                    SET trip_status = 'CONFIRMED', updated_at = ?
                    WHERE trip_id = ? AND trip_status = 'PLAN_REVIEW'
                    """,
                    (now, trip_text),
                )
                self._commit(connection)
                return PlanTransitionResult(
                    trip_id=trip_id,
                    plan_id=plan_id,
                    trip_status=TripStatus.CONFIRMED,
                    plan_status=PlanVersionStatus.CURRENT,
                )
            except sqlite3.IntegrityError as exc:
                self._rollback(connection)
                raise PlanStoreError(
                    "PLAN_CURRENT_CONFLICT",
                    "同一 Trip 只能存在一个 CURRENT 版本",
                ) from exc
            except Exception:
                self._rollback(connection)
                raise

    def start_execution(self, trip_id: UUID) -> ExecutionStartResult:
        trip_text = str(trip_id)
        now = datetime.now(UTC).isoformat()

        with closing(self._connect()) as connection:
            self._begin(connection)
            try:
                trip = connection.execute(
                    "SELECT * FROM trips WHERE trip_id = ?",
                    (trip_text,),
                ).fetchone()
                if trip is None:
                    raise PlanStoreError("TRIP_NOT_FOUND", "未找到 Trip")

                current_plan = connection.execute(
                    """
                    SELECT * FROM plan_versions
                    WHERE trip_id = ? AND status = 'CURRENT'
                    """,
                    (trip_text,),
                ).fetchone()
                if current_plan is None:
                    raise PlanStoreError(
                        "PLAN_NOT_CONFIRMED",
                        "未确认的 PROPOSED 方案不可开始执行",
                    )

                trip_status = TripStatus(trip["trip_status"])
                if trip_status is TripStatus.EXECUTING:
                    self._commit(connection)
                    return ExecutionStartResult(
                        trip_id=trip_id,
                        plan_id=UUID(current_plan["plan_id"]),
                        trip_status="EXECUTING",
                        plan_status="CURRENT",
                    )
                try:
                    require_trip_transition(trip_status, TripStatus.EXECUTING)
                except StateTransitionViolation as exc:
                    raise PlanStoreError(
                        "PLAN_STATE_TRANSITION_INVALID",
                        str(exc),
                    ) from exc

                connection.execute(
                    """
                    UPDATE trips
                    SET trip_status = 'EXECUTING', updated_at = ?
                    WHERE trip_id = ? AND trip_status = 'CONFIRMED'
                    """,
                    (now, trip_text),
                )
                self._commit(connection)
                return ExecutionStartResult(
                    trip_id=trip_id,
                    plan_id=UUID(current_plan["plan_id"]),
                    trip_status="EXECUTING",
                    plan_status="CURRENT",
                )
            except Exception:
                self._rollback(connection)
                raise

    def get_diff(self, trip_id: UUID, candidate_plan_id: UUID) -> PlanVersionDiff:
        trip_text = str(trip_id)
        candidate_text = str(candidate_plan_id)
        with closing(self._connect()) as connection:
            candidate_row = connection.execute(
                "SELECT * FROM plan_versions WHERE plan_id = ?",
                (candidate_text,),
            ).fetchone()
            if candidate_row is None:
                raise PlanStoreError("PLAN_VERSION_NOT_FOUND", "未找到候选 Plan V2")
            if candidate_row["trip_id"] != trip_text:
                raise PlanStoreError(
                    "PLAN_TRIP_MISMATCH",
                    "候选 Plan V2 不属于请求路径中的 tripId",
                )
            candidate = self._plan_from_row(candidate_row)
            if candidate.version != 2 or candidate.parent_id is None:
                raise PlanStoreError(
                    "PLAN_DIFF_REQUIRES_V2",
                    "Diff 只能用于包含 parentId 的 Plan V2",
                )
            base_row = connection.execute(
                "SELECT * FROM plan_versions WHERE plan_id = ?",
                (str(candidate.parent_id),),
            ).fetchone()
            if base_row is None:
                raise PlanStoreError("PLAN_PARENT_NOT_FOUND", "未找到 Plan V2 的父版本")
            base = self._plan_from_row(base_row)

        return calculate_plan_diff(base, candidate)

    def accept_v2(self, trip_id: UUID, candidate_plan_id: UUID) -> PlanV2DecisionResult:
        trip_text = str(trip_id)
        candidate_text = str(candidate_plan_id)
        now = datetime.now(UTC).isoformat()

        with closing(self._connect()) as connection:
            self._begin(connection)
            try:
                candidate = connection.execute(
                    "SELECT * FROM plan_versions WHERE plan_id = ?",
                    (candidate_text,),
                ).fetchone()
                if candidate is None:
                    raise PlanStoreError("PLAN_VERSION_NOT_FOUND", "未找到候选 Plan V2")
                if candidate["trip_id"] != trip_text:
                    raise PlanStoreError(
                        "PLAN_TRIP_MISMATCH",
                        "候选 Plan V2 不属于请求路径中的 tripId",
                    )
                if candidate["version"] != 2:
                    raise PlanStoreError(
                        "PLAN_DECISION_REQUIRES_V2",
                        "accept 只能用于 Plan V2",
                    )

                proposal = ProposedPlanVersion.model_validate_json(
                    candidate["snapshot_json"], strict=True
                )
                assert proposal.parent_id is not None
                base = connection.execute(
                    "SELECT * FROM plan_versions WHERE plan_id = ?",
                    (str(proposal.parent_id),),
                ).fetchone()
                if base is None:
                    raise PlanStoreError("PLAN_PARENT_NOT_FOUND", "未找到 Plan V2 的父版本")
                trip = connection.execute(
                    "SELECT * FROM trips WHERE trip_id = ?",
                    (trip_text,),
                ).fetchone()
                if trip is None:
                    raise PlanStoreError("TRIP_NOT_FOUND", "未找到 Trip")

                candidate_status = PlanVersionStatus(candidate["status"])
                base_status = PlanVersionStatus(base["status"])
                trip_status = TripStatus(trip["trip_status"])
                if candidate_status is PlanVersionStatus.CURRENT:
                    if (
                        base_status is not PlanVersionStatus.SUPERSEDED
                        or trip_status is not TripStatus.EXECUTING
                    ):
                        raise PlanStoreError(
                            "PLAN_STATE_TRANSITION_INVALID",
                            "已接受 Plan V2 的关联状态不一致",
                        )
                    self._commit(connection)
                    return PlanV2DecisionResult(
                        trip_id=trip_id,
                        candidate_plan_id=candidate_plan_id,
                        decision=PlanV2Decision.ACCEPTED,
                        trip_status="EXECUTING",
                        current_plan_id=candidate_plan_id,
                        candidate_status=PlanVersionStatus.CURRENT,
                        previous_current_status=PlanVersionStatus.SUPERSEDED,
                    )

                try:
                    require_plan_transition(candidate_status, PlanVersionStatus.CURRENT)
                    require_plan_transition(base_status, PlanVersionStatus.SUPERSEDED)
                    require_trip_transition(trip_status, TripStatus.EXECUTING)
                except StateTransitionViolation as exc:
                    raise PlanStoreError(
                        "PLAN_STATE_TRANSITION_INVALID",
                        str(exc),
                    ) from exc

                connection.execute(
                    "UPDATE plan_versions SET status = 'SUPERSEDED' WHERE plan_id = ? AND status = 'CURRENT'",
                    (str(proposal.parent_id),),
                )
                connection.execute(
                    "UPDATE plan_versions SET status = 'CURRENT', confirmed_at = ? WHERE plan_id = ? AND status = 'PROPOSED'",
                    (now, candidate_text),
                )
                connection.execute(
                    "UPDATE trips SET trip_status = 'EXECUTING', updated_at = ? WHERE trip_id = ? AND trip_status = 'REPLAN_REVIEW'",
                    (now, trip_text),
                )
                self._commit(connection)
                return PlanV2DecisionResult(
                    trip_id=trip_id,
                    candidate_plan_id=candidate_plan_id,
                    decision=PlanV2Decision.ACCEPTED,
                    trip_status="EXECUTING",
                    current_plan_id=candidate_plan_id,
                    candidate_status=PlanVersionStatus.CURRENT,
                    previous_current_status=PlanVersionStatus.SUPERSEDED,
                )
            except sqlite3.IntegrityError as exc:
                self._rollback(connection)
                raise PlanStoreError(
                    "PLAN_CURRENT_CONFLICT",
                    "接受 Plan V2 时唯一 CURRENT 约束冲突",
                ) from exc
            except Exception:
                self._rollback(connection)
                raise

    def reject_v2(self, trip_id: UUID, candidate_plan_id: UUID) -> PlanV2DecisionResult:
        trip_text = str(trip_id)
        candidate_text = str(candidate_plan_id)
        now = datetime.now(UTC).isoformat()

        with closing(self._connect()) as connection:
            self._begin(connection)
            try:
                candidate = connection.execute(
                    "SELECT * FROM plan_versions WHERE plan_id = ?",
                    (candidate_text,),
                ).fetchone()
                if candidate is None:
                    raise PlanStoreError("PLAN_VERSION_NOT_FOUND", "未找到候选 Plan V2")
                if candidate["trip_id"] != trip_text:
                    raise PlanStoreError(
                        "PLAN_TRIP_MISMATCH",
                        "候选 Plan V2 不属于请求路径中的 tripId",
                    )
                if candidate["version"] != 2:
                    raise PlanStoreError(
                        "PLAN_DECISION_REQUIRES_V2",
                        "reject 只能用于 Plan V2",
                    )
                proposal = ProposedPlanVersion.model_validate_json(
                    candidate["snapshot_json"], strict=True
                )
                assert proposal.parent_id is not None
                base = connection.execute(
                    "SELECT * FROM plan_versions WHERE plan_id = ?",
                    (str(proposal.parent_id),),
                ).fetchone()
                if base is None:
                    raise PlanStoreError("PLAN_PARENT_NOT_FOUND", "未找到 Plan V2 的父版本")
                trip = connection.execute(
                    "SELECT * FROM trips WHERE trip_id = ?",
                    (trip_text,),
                ).fetchone()
                if trip is None:
                    raise PlanStoreError("TRIP_NOT_FOUND", "未找到 Trip")

                candidate_status = PlanVersionStatus(candidate["status"])
                base_status = PlanVersionStatus(base["status"])
                trip_status = TripStatus(trip["trip_status"])
                if candidate_status is PlanVersionStatus.REJECTED:
                    if (
                        base_status is not PlanVersionStatus.CURRENT
                        or trip_status is not TripStatus.EXECUTING
                    ):
                        raise PlanStoreError(
                            "PLAN_STATE_TRANSITION_INVALID",
                            "已拒绝 Plan V2 的关联状态不一致",
                        )
                    self._commit(connection)
                    return PlanV2DecisionResult(
                        trip_id=trip_id,
                        candidate_plan_id=candidate_plan_id,
                        decision=PlanV2Decision.REJECTED,
                        trip_status="EXECUTING",
                        current_plan_id=UUID(base["plan_id"]),
                        candidate_status=PlanVersionStatus.REJECTED,
                        previous_current_status=PlanVersionStatus.CURRENT,
                    )

                try:
                    require_plan_transition(candidate_status, PlanVersionStatus.REJECTED)
                    require_trip_transition(trip_status, TripStatus.EXECUTING)
                except StateTransitionViolation as exc:
                    raise PlanStoreError(
                        "PLAN_STATE_TRANSITION_INVALID",
                        str(exc),
                    ) from exc
                if base_status is not PlanVersionStatus.CURRENT:
                    raise PlanStoreError(
                        "PLAN_PARENT_NOT_CURRENT",
                        "拒绝 Plan V2 时父版本必须仍为 CURRENT",
                    )

                connection.execute(
                    "UPDATE plan_versions SET status = 'REJECTED' WHERE plan_id = ? AND status = 'PROPOSED'",
                    (candidate_text,),
                )
                connection.execute(
                    "UPDATE trips SET trip_status = 'EXECUTING', updated_at = ? WHERE trip_id = ? AND trip_status = 'REPLAN_REVIEW'",
                    (now, trip_text),
                )
                self._commit(connection)
                return PlanV2DecisionResult(
                    trip_id=trip_id,
                    candidate_plan_id=candidate_plan_id,
                    decision=PlanV2Decision.REJECTED,
                    trip_status="EXECUTING",
                    current_plan_id=UUID(base["plan_id"]),
                    candidate_status=PlanVersionStatus.REJECTED,
                    previous_current_status=PlanVersionStatus.CURRENT,
                )
            except Exception:
                self._rollback(connection)
                raise

    def get_plan_version(self, trip_id: UUID, plan_id: UUID) -> PlanVersion:
        """Load one stored immutable snapshot, including terminal plan states."""

        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM plan_versions
                WHERE trip_id = ? AND plan_id = ?
                """,
                (str(trip_id), str(plan_id)),
            ).fetchone()
        if row is None:
            raise PlanStoreError(
                "PLAN_VERSION_NOT_FOUND",
                "未找到该 Trip 的 PlanVersion",
            )
        return self._plan_from_row(row)

    def get_trip_state(self, trip_id: UUID) -> TripPlanState:
        trip_text = str(trip_id)
        with closing(self._connect()) as connection:
            trip = connection.execute(
                "SELECT * FROM trips WHERE trip_id = ?",
                (trip_text,),
            ).fetchone()
            if trip is None:
                raise PlanStoreError("TRIP_NOT_FOUND", "未找到 Trip")
            rows = connection.execute(
                """
                SELECT * FROM plan_versions
                WHERE trip_id = ?
                ORDER BY version ASC, created_at ASC
                """,
                (trip_text,),
            ).fetchall()

        versions = [self._plan_from_row(row) for row in rows]
        current = next(
            (plan for plan in versions if plan.status is PlanVersionStatus.CURRENT),
            None,
        )
        proposed = [
            plan for plan in versions if plan.status is PlanVersionStatus.PROPOSED
        ]
        return TripPlanState(
            trip_id=trip_id,
            trip_status=TripStatus(trip["trip_status"]),
            current_plan=current,
            proposed_plans=proposed,
            events=[],
        )
