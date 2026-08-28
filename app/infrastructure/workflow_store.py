from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from app.infrastructure.plan_store import PlanStoreError
from app.domain.collaboration import TripFlowKind
from app.infrastructure.trip_flow_store import ensure_trip_flow_schema, register_trip_flow
from app.schemas.execution import (
    ActualBudgetSummary,
    ArrivalEvidenceSnapshot,
    CreateArrivalExecutionEvent,
    CreateExecutionEvent,
    ExecutionEvent,
    ExecutionEventType,
)
from app.schemas.execution_adjustment import (
    ConfirmedExecutionAdjustmentEvent,
    CreateConfirmedExecutionAdjustmentEvent,
    ExecutionAdjustmentType,
    FatigueLevel,
)
from app.schemas.plan import PlanVersion, PlanVersionStatus, ProposedPlanVersion
from app.schemas.trip import (
    AssistanceProfile,
    CreateSingleDayTrip,
    Trip,
    TripStatus,
)
from app.schemas.workflow import (
    ConstraintConfirmationResult,
    ConstraintProfileState,
    ConstraintProfileStatus,
    PlanHistoryItem,
    TripExecutionSummary,
)


class SqliteWorkflowRepository:
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
            ensure_trip_flow_schema(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS constraint_profiles (
                    trip_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    confirmed_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS confirmed_trip_inputs (
                    trip_id TEXT PRIMARY KEY,
                    trip_json TEXT NOT NULL,
                    semantic_json TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_events (
                    event_id TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    plan_version_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    amount_cents INTEGER,
                    arrival_evidence_json TEXT,
                    idempotency_key TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (trip_id, idempotency_key)
                )
                """
            )
            event_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(execution_events)"
                ).fetchall()
            }
            if "created_at" not in event_columns:
                connection.execute(
                    "ALTER TABLE execution_events ADD COLUMN created_at TEXT"
                )
            if "arrival_evidence_json" not in event_columns:
                connection.execute(
                    "ALTER TABLE execution_events "
                    "ADD COLUMN arrival_evidence_json TEXT"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_execution_events_trip_time
                ON execution_events (trip_id, occurred_at, event_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_execution_events_trip_task
                ON execution_events (trip_id, task_id, event_type)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_adjustment_events (
                    event_id TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    plan_version_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    late_minutes INTEGER,
                    fatigue_level TEXT,
                    idempotency_key TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (trip_id, idempotency_key)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_adjustment_events_trip_time
                ON execution_adjustment_events (trip_id, occurred_at, event_id)
                """
            )

    @staticmethod
    def _constraint_from_row(row: sqlite3.Row) -> ConstraintProfileState:
        return ConstraintProfileState(
            trip_id=UUID(row["trip_id"]),
            status=ConstraintProfileStatus(row["status"]),
            assistance_profile=AssistanceProfile.model_validate_json(
                row["profile_json"],
                strict=True,
            ),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            confirmed_at=(
                datetime.fromisoformat(row["confirmed_at"])
                if row["confirmed_at"]
                else None
            ),
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> ExecutionEvent:
        return ExecutionEvent(
            event_id=UUID(row["event_id"]),
            trip_id=UUID(row["trip_id"]),
            task_id=row["task_id"],
            plan_version_id=UUID(row["plan_version_id"]),
            event_type=ExecutionEventType(row["event_type"]),
            amount_cents=row["amount_cents"],
            arrival_evidence=(
                ArrivalEvidenceSnapshot.model_validate_json(
                    row["arrival_evidence_json"],
                    strict=True,
                )
                if row["arrival_evidence_json"]
                else None
            ),
            idempotency_key=row["idempotency_key"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
        )

    @staticmethod
    def _adjustment_event_from_row(
        row: sqlite3.Row,
    ) -> ConfirmedExecutionAdjustmentEvent:
        return ConfirmedExecutionAdjustmentEvent(
            event_id=UUID(row["event_id"]),
            trip_id=UUID(row["trip_id"]),
            task_id=row["task_id"],
            plan_version_id=UUID(row["plan_version_id"]),
            event_type=ExecutionAdjustmentType(row["event_type"]),
            late_minutes=row["late_minutes"],
            fatigue_level=(
                FatigueLevel(row["fatigue_level"])
                if row["fatigue_level"] is not None
                else None
            ),
            idempotency_key=row["idempotency_key"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
        )

    @staticmethod
    def _confirmed_trip_semantic_json(trip: CreateSingleDayTrip) -> str:
        """Canonical comparison that ignores only the parser-owned participant UUID."""

        payload = trip.model_dump(mode="json", by_alias=True)
        payload["participants"][0].pop("participantId")
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _planning_trip_json(trip: Trip) -> str:
        """Normalize only the DRAFT -> PLANNING hand-off between T002 and T011."""

        payload = trip.model_dump(mode="json", by_alias=True)
        if payload["status"] == TripStatus.DRAFT.value:
            payload["status"] = TripStatus.PLANNING.value
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def confirm_trip(self, trip: CreateSingleDayTrip) -> CreateSingleDayTrip:
        """Persist one authoritative Trip, with semantic retry idempotency."""

        trip_text = str(trip.trip_id)
        trip_json = trip.model_dump_json(by_alias=True)
        semantic_json = self._confirmed_trip_semantic_json(trip)
        confirmed_at = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM confirmed_trip_inputs WHERE trip_id = ?",
                    (trip_text,),
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO confirmed_trip_inputs (
                            trip_id, trip_json, semantic_json, confirmed_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (trip_text, trip_json, semantic_json, confirmed_at),
                    )
                    row = connection.execute(
                        "SELECT * FROM confirmed_trip_inputs WHERE trip_id = ?",
                        (trip_text,),
                    ).fetchone()
                elif row["semantic_json"] != semantic_json:
                    raise PlanStoreError(
                        "CONFIRMED_TRIP_CONFLICT",
                        "同一 tripId 已确认过不同的 Trip 内容，不允许覆盖",
                    )
                register_trip_flow(connection, trip.trip_id, TripFlowKind.LEGACY_SINGLE)
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

        assert row is not None
        return CreateSingleDayTrip.model_validate_json(
            row["trip_json"],
            strict=True,
        )

    def require_confirmed_trip(
        self,
        trip_id: UUID,
        planning_trip: Trip,
    ) -> None:
        """Require T011 input to match the exact Trip confirmed by T002."""

        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT trip_json FROM confirmed_trip_inputs WHERE trip_id = ?",
                (str(trip_id),),
            ).fetchone()
        if row is None:
            raise PlanStoreError(
                "TRIP_NOT_CONFIRMED",
                "Trip 尚未通过行程草稿确认，不允许进入规划",
            )

        confirmed = CreateSingleDayTrip.model_validate_json(
            row["trip_json"],
            strict=True,
        )
        if (
            confirmed.trip_id != trip_id
            or planning_trip.trip_id != trip_id
            or self._planning_trip_json(confirmed)
            != self._planning_trip_json(planning_trip)
        ):
            raise PlanStoreError(
                "CONFIRMED_TRIP_MISMATCH",
                "CandidatePlanRequest.trip 与已确认 Trip 不一致",
            )

    def save_constraint_draft(
        self,
        trip_id: UUID,
        profile: AssistanceProfile,
    ) -> ConstraintProfileState:
        trip_text = str(trip_id)
        profile_json = profile.model_dump_json(by_alias=True)
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM constraint_profiles WHERE trip_id = ?",
                (trip_text,),
            ).fetchone()
            if (
                existing is not None
                and existing["profile_json"] == profile_json
                and existing["status"] == ConstraintProfileStatus.CONSTRAINT_CONFIRMED.value
            ):
                connection.execute("COMMIT")
                return self._constraint_from_row(existing)

            connection.execute(
                """
                INSERT INTO constraint_profiles (
                    trip_id, status, profile_json, updated_at, confirmed_at
                ) VALUES (?, 'DRAFT', ?, ?, NULL)
                ON CONFLICT(trip_id) DO UPDATE SET
                    status = 'DRAFT',
                    profile_json = excluded.profile_json,
                    updated_at = excluded.updated_at,
                    confirmed_at = NULL
                """,
                (trip_text, profile_json, now),
            )
            row = connection.execute(
                "SELECT * FROM constraint_profiles WHERE trip_id = ?",
                (trip_text,),
            ).fetchone()
            connection.execute("COMMIT")
        assert row is not None
        return self._constraint_from_row(row)

    def confirm_constraints(self, trip_id: UUID) -> ConstraintConfirmationResult:
        trip_text = str(trip_id)
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM constraint_profiles WHERE trip_id = ?",
                (trip_text,),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise PlanStoreError(
                    "CONSTRAINT_PROFILE_NOT_FOUND",
                    "未找到待确认的 AssistanceProfile",
                )
            if row["status"] != ConstraintProfileStatus.CONSTRAINT_CONFIRMED.value:
                connection.execute(
                    """
                    UPDATE constraint_profiles
                    SET status = 'CONSTRAINT_CONFIRMED',
                        confirmed_at = ?,
                        updated_at = ?
                    WHERE trip_id = ? AND status = 'DRAFT'
                    """,
                    (now, now, trip_text),
                )
                row = connection.execute(
                    "SELECT * FROM constraint_profiles WHERE trip_id = ?",
                    (trip_text,),
                ).fetchone()
            connection.execute("COMMIT")
        assert row is not None and row["confirmed_at"]
        profile = AssistanceProfile.model_validate_json(row["profile_json"], strict=True)
        return ConstraintConfirmationResult(
            trip_id=trip_id,
            status="CONSTRAINT_CONFIRMED",
            assistance_profile=profile,
            confirmed_at=datetime.fromisoformat(row["confirmed_at"]),
        )

    def get_constraints(self, trip_id: UUID) -> ConstraintProfileState:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM constraint_profiles WHERE trip_id = ?",
                (str(trip_id),),
            ).fetchone()
        if row is None:
            raise PlanStoreError(
                "CONSTRAINT_PROFILE_NOT_FOUND",
                "未找到 AssistanceProfile",
            )
        return self._constraint_from_row(row)

    def require_constraint_confirmed(
        self,
        trip_id: UUID,
        profile: AssistanceProfile | None,
    ) -> None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM constraint_profiles WHERE trip_id = ?",
                (str(trip_id),),
            ).fetchone()
        if row is None:
            raise PlanStoreError(
                "CONSTRAINTS_NOT_CONFIRMED",
                "AssistanceProfile 尚未保存并确认，不允许进入规划",
            )
        if row["status"] != ConstraintProfileStatus.CONSTRAINT_CONFIRMED.value:
            raise PlanStoreError(
                "CONSTRAINTS_NOT_CONFIRMED",
                "AssistanceProfile 尚未确认，不允许进入规划",
            )
        expected_json = profile.model_dump_json(by_alias=True) if profile else None
        if expected_json != row["profile_json"]:
            raise PlanStoreError(
                "CONSTRAINT_PROFILE_MISMATCH",
                "Plan 使用的 AssistanceProfile 与已确认内容不一致",
            )

    def create_event(
        self,
        trip_id: UUID,
        request: CreateExecutionEvent | CreateArrivalExecutionEvent,
    ) -> ExecutionEvent:
        trip_text = str(trip_id)
        occurred_at = request.occurred_at.astimezone(UTC).isoformat()
        updated_at = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                """
                SELECT * FROM execution_events
                WHERE trip_id = ? AND idempotency_key = ?
                """,
                (trip_text, request.idempotency_key),
            ).fetchone()
            if duplicate is not None:
                event = self._event_from_row(duplicate)
                same_payload = (
                    event.task_id == request.task_id
                    and event.plan_version_id == request.plan_version_id
                    and event.event_type is request.event_type
                    and event.amount_cents == request.amount_cents
                    and event.arrival_evidence
                    == getattr(request, "arrival_evidence", None)
                )
                if not same_payload:
                    connection.execute("ROLLBACK")
                    raise PlanStoreError(
                        "EVENT_IDEMPOTENCY_CONFLICT",
                        "相同 idempotencyKey 已用于不同事件",
                    )
                connection.execute("COMMIT")
                return event

            trip = connection.execute(
                "SELECT trip_status FROM trips WHERE trip_id = ?",
                (trip_text,),
            ).fetchone()
            if trip is None:
                connection.execute("ROLLBACK")
                raise PlanStoreError("TRIP_NOT_FOUND", "未找到 Trip")
            if TripStatus(trip["trip_status"]) is not TripStatus.EXECUTING:
                connection.execute("ROLLBACK")
                raise PlanStoreError(
                    "EXECUTION_STATE_INVALID",
                    "只有 EXECUTING 状态允许写入执行事件",
                )

            plan_row = connection.execute(
                """
                SELECT * FROM plan_versions
                WHERE trip_id = ? AND status = 'CURRENT'
                """,
                (trip_text,),
            ).fetchone()
            if plan_row is None:
                connection.execute("ROLLBACK")
                raise PlanStoreError("PLAN_NOT_CONFIRMED", "未找到 CURRENT PlanVersion")
            if plan_row["plan_id"] != str(request.plan_version_id):
                connection.execute("ROLLBACK")
                raise PlanStoreError(
                    "EVENT_PLAN_NOT_CURRENT",
                    "事件 planVersionId 必须指向当前 CURRENT",
                )
            plan = ProposedPlanVersion.model_validate_json(
                plan_row["snapshot_json"],
                strict=True,
            )
            task_ids = {task.task_id for task in plan.days[0].tasks}
            if request.task_id not in task_ids:
                connection.execute("ROLLBACK")
                raise PlanStoreError(
                    "EVENT_TASK_NOT_FOUND",
                    "taskId 不属于当前 PlanVersion",
                )

            if request.event_type in {
                ExecutionEventType.COMPLETE,
                ExecutionEventType.SKIP,
            }:
                terminal = connection.execute(
                    """
                    SELECT event_type FROM execution_events
                    WHERE trip_id = ? AND task_id = ?
                      AND event_type IN ('COMPLETE', 'SKIP')
                    LIMIT 1
                    """,
                    (trip_text, request.task_id),
                ).fetchone()
                if terminal is not None:
                    connection.execute("ROLLBACK")
                    raise PlanStoreError(
                        "TASK_ALREADY_TERMINAL",
                        f"任务已处于 {terminal['event_type']} 终态",
                    )

            event_id = uuid4()
            connection.execute(
                """
                INSERT INTO execution_events (
                    event_id, trip_id, task_id, plan_version_id, event_type,
                    amount_cents, arrival_evidence_json, idempotency_key,
                    occurred_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event_id),
                    trip_text,
                    request.task_id,
                    str(request.plan_version_id),
                    request.event_type.value,
                    request.amount_cents,
                    (
                        request.arrival_evidence.model_dump_json(by_alias=True)
                        if isinstance(request, CreateArrivalExecutionEvent)
                        else None
                    ),
                    request.idempotency_key,
                    occurred_at,
                    updated_at,
                ),
            )

            if request.event_type in {
                ExecutionEventType.COMPLETE,
                ExecutionEventType.SKIP,
            }:
                terminal_rows = connection.execute(
                    """
                    SELECT DISTINCT task_id FROM execution_events
                    WHERE trip_id = ? AND event_type IN ('COMPLETE', 'SKIP')
                    """,
                    (trip_text,),
                ).fetchall()
                terminal_ids = {row["task_id"] for row in terminal_rows}
                if task_ids <= terminal_ids:
                    connection.execute(
                        """
                        UPDATE trips SET trip_status = 'COMPLETED', updated_at = ?
                        WHERE trip_id = ? AND trip_status = 'EXECUTING'
                        """,
                        (updated_at, trip_text),
                    )

            row = connection.execute(
                "SELECT * FROM execution_events WHERE event_id = ?",
                (str(event_id),),
            ).fetchone()
            connection.execute("COMMIT")
        assert row is not None
        return self._event_from_row(row)

    def list_events(self, trip_id: UUID) -> list[ExecutionEvent]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM execution_events
                WHERE trip_id = ?
                ORDER BY occurred_at ASC, event_id ASC
                """,
                (str(trip_id),),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def create_adjustment_event(
        self,
        trip_id: UUID,
        request: CreateConfirmedExecutionAdjustmentEvent,
    ) -> ConfirmedExecutionAdjustmentEvent:
        """Persist one confirmed LATE/FATIGUE event with legacy idempotency rules."""

        trip_text = str(trip_id)
        occurred_at = request.occurred_at.astimezone(UTC).isoformat()
        created_at = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                """
                SELECT * FROM execution_adjustment_events
                WHERE trip_id = ? AND idempotency_key = ?
                """,
                (trip_text, request.idempotency_key),
            ).fetchone()
            if duplicate is not None:
                event = self._adjustment_event_from_row(duplicate)
                same_payload = (
                    event.task_id == request.task_id
                    and event.plan_version_id == request.plan_version_id
                    and event.event_type is request.event_type
                    and event.late_minutes == request.late_minutes
                    and event.fatigue_level == request.fatigue_level
                    and event.occurred_at.astimezone(UTC)
                    == request.occurred_at.astimezone(UTC)
                )
                if not same_payload:
                    connection.execute("ROLLBACK")
                    raise PlanStoreError(
                        "EVENT_IDEMPOTENCY_CONFLICT",
                        "相同 idempotencyKey 已用于不同事件",
                    )
                connection.execute("COMMIT")
                return event

            trip = connection.execute(
                "SELECT trip_status FROM trips WHERE trip_id = ?",
                (trip_text,),
            ).fetchone()
            if trip is None:
                connection.execute("ROLLBACK")
                raise PlanStoreError("TRIP_NOT_FOUND", "未找到 Trip")
            if TripStatus(trip["trip_status"]) is not TripStatus.EXECUTING:
                connection.execute("ROLLBACK")
                raise PlanStoreError(
                    "EXECUTION_STATE_INVALID",
                    "只有 EXECUTING 状态允许写入执行事件",
                )

            plan_row = connection.execute(
                """
                SELECT * FROM plan_versions
                WHERE trip_id = ? AND status = 'CURRENT'
                """,
                (trip_text,),
            ).fetchone()
            if plan_row is None:
                connection.execute("ROLLBACK")
                raise PlanStoreError("PLAN_NOT_CONFIRMED", "未找到 CURRENT PlanVersion")
            if plan_row["plan_id"] != str(request.plan_version_id):
                connection.execute("ROLLBACK")
                raise PlanStoreError(
                    "EVENT_PLAN_NOT_CURRENT",
                    "事件 planVersionId 必须指向当前 CURRENT",
                )
            plan = ProposedPlanVersion.model_validate_json(
                plan_row["snapshot_json"],
                strict=True,
            )
            if request.task_id not in {
                task.task_id for task in plan.days[0].tasks
            }:
                connection.execute("ROLLBACK")
                raise PlanStoreError(
                    "EVENT_TASK_NOT_FOUND",
                    "taskId 不属于当前 PlanVersion",
                )

            event_id = uuid4()
            connection.execute(
                """
                INSERT INTO execution_adjustment_events (
                    event_id, trip_id, task_id, plan_version_id, event_type,
                    late_minutes, fatigue_level, idempotency_key,
                    occurred_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event_id),
                    trip_text,
                    request.task_id,
                    str(request.plan_version_id),
                    request.event_type.value,
                    request.late_minutes,
                    (
                        request.fatigue_level.value
                        if request.fatigue_level is not None
                        else None
                    ),
                    request.idempotency_key,
                    occurred_at,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM execution_adjustment_events WHERE event_id = ?",
                (str(event_id),),
            ).fetchone()
            connection.execute("COMMIT")
        assert row is not None
        return self._adjustment_event_from_row(row)

    def list_adjustment_events(
        self,
        trip_id: UUID,
    ) -> list[ConfirmedExecutionAdjustmentEvent]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM execution_adjustment_events
                WHERE trip_id = ?
                ORDER BY occurred_at ASC, event_id ASC
                """,
                (str(trip_id),),
            ).fetchall()
        return [self._adjustment_event_from_row(row) for row in rows]

    def get_adjustment_event(
        self,
        trip_id: UUID,
        event_id: UUID,
    ) -> ConfirmedExecutionAdjustmentEvent:
        """Return a confirmed adjustment only from the requested Trip."""

        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM execution_adjustment_events
                WHERE trip_id = ? AND event_id = ?
                """,
                (str(trip_id), str(event_id)),
            ).fetchone()
        if row is None:
            # Deliberately use the same response for a missing event and an
            # event owned by another Trip so callers cannot cross Trip scope.
            raise PlanStoreError(
                "ADJUSTMENT_EVENT_NOT_FOUND",
                "未找到已确认执行调整事件",
            )
        return self._adjustment_event_from_row(row)

    def get_budget_summary(self, trip_id: UUID) -> ActualBudgetSummary:
        trip_text = str(trip_id)
        with closing(self._connect()) as connection:
            plan_row = connection.execute(
                """
                SELECT * FROM plan_versions
                WHERE trip_id = ? AND status = 'CURRENT'
                """,
                (trip_text,),
            ).fetchone()
            if plan_row is None:
                raise PlanStoreError("PLAN_NOT_CONFIRMED", "未找到 CURRENT PlanVersion")
        plan = ProposedPlanVersion.model_validate_json(
            plan_row["snapshot_json"],
            strict=True,
        )
        events = self.list_events(trip_id)
        expenses = [
            event.amount_cents
            for event in events
            if event.event_type is ExecutionEventType.EXPENSE
            and event.amount_cents is not None
        ]
        actual_spent_cents = sum(expenses)
        planned_budget_cents = plan.trip_snapshot.total_budget_cents
        return ActualBudgetSummary(
            trip_id=trip_id,
            plan_version_id=plan.plan_id,
            planned_budget_cents=planned_budget_cents,
            actual_spent_cents=actual_spent_cents,
            remaining_budget_cents=planned_budget_cents - actual_spent_cents,
            expense_event_count=len(expenses),
        )

    def get_summary(self, trip_id: UUID) -> TripExecutionSummary:
        trip_text = str(trip_id)
        with closing(self._connect()) as connection:
            trip = connection.execute(
                "SELECT trip_status FROM trips WHERE trip_id = ?",
                (trip_text,),
            ).fetchone()
            if trip is None:
                raise PlanStoreError("TRIP_NOT_FOUND", "未找到 Trip")
            plan_rows = connection.execute(
                """
                SELECT * FROM plan_versions
                WHERE trip_id = ?
                ORDER BY version ASC, created_at ASC
                """,
                (trip_text,),
            ).fetchall()
            current_row = next(
                (
                    row
                    for row in plan_rows
                    if PlanVersionStatus(row["status"]) is PlanVersionStatus.CURRENT
                ),
                None,
            )
            if current_row is None:
                raise PlanStoreError("PLAN_NOT_CONFIRMED", "未找到 CURRENT PlanVersion")

        current = ProposedPlanVersion.model_validate_json(
            current_row["snapshot_json"],
            strict=True,
        )
        events = self.list_events(trip_id)
        completed = sorted(
            {event.task_id for event in events if event.event_type is ExecutionEventType.COMPLETE}
        )
        skipped = sorted(
            {event.task_id for event in events if event.event_type is ExecutionEventType.SKIP}
        )
        actual_cost = sum(
            event.amount_cents or 0
            for event in events
            if event.event_type is ExecutionEventType.EXPENSE
        )
        history: list[PlanHistoryItem] = []
        for row in plan_rows:
            proposal = ProposedPlanVersion.model_validate_json(
                row["snapshot_json"],
                strict=True,
            )
            history.append(
                PlanHistoryItem(
                    plan_id=proposal.plan_id,
                    version=proposal.version,
                    status=PlanVersionStatus(row["status"]),
                    reason=proposal.reason,
                )
            )
        return TripExecutionSummary(
            trip_id=trip_id,
            trip_status=TripStatus(trip["trip_status"]),
            planned_cost_cents=current.metrics.total_cost_cents,
            actual_cost_cents=actual_cost,
            difference_cents=actual_cost - current.metrics.total_cost_cents,
            completed_task_ids=completed,
            skipped_task_ids=skipped,
            total_tasks=len(current.days[0].tasks),
            current_plan_version=current.version,
            plan_history=history,
            events=events,
        )
