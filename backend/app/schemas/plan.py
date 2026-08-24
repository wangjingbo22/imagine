from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, UUID4, model_validator

from .trip import ContractModel, Trip, TripStatus


NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PlanVersionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CURRENT = "CURRENT"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ConstraintHardness(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class ConstraintCheckStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"


class PlanSourceStatus(str, Enum):
    ONLINE = "ONLINE"
    VERIFIED_CACHE = "VERIFIED_CACHE"
    USER_CONFIRMED = "USER_CONFIRMED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class PlanTask(ContractModel):
    task_id: Annotated[str, Field(min_length=1, max_length=64)]
    order: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(min_length=1, max_length=120)]
    category: Annotated[str, Field(min_length=1, max_length=80)]
    time_range: Annotated[str, Field(min_length=1, max_length=80)]
    duration_minutes: Annotated[int, Field(ge=0, le=1_440)]
    transport: Annotated[str, Field(min_length=1, max_length=160)]
    cost_cents: Annotated[int, Field(ge=0)]
    walk_meters: Annotated[int, Field(ge=0)]
    note: Annotated[str, Field(max_length=500)] = ""


class PlanDay(ContractModel):
    day_index: Annotated[int, Field(ge=0)]
    date: date
    tasks: list[PlanTask] = Field(min_length=3, max_length=4)

    @model_validator(mode="after")
    def validate_task_order(self) -> "PlanDay":
        orders = [task.order for task in self.tasks]
        if orders != list(range(1, len(self.tasks) + 1)):
            raise ValueError("tasks must use contiguous order values starting at 1")
        if len({task.task_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("taskId must be unique within a plan day")
        return self


class PlanMetrics(ContractModel):
    total_cost_cents: Annotated[int, Field(ge=0)]
    buffer_cents: Annotated[int, Field(ge=0)]
    total_walk_meters: Annotated[int, Field(ge=0)]
    transfer_count: Annotated[int, Field(ge=0)]
    validation_status: Literal["PASS"]


class ConstraintSnapshot(ContractModel):
    rule_id: Annotated[str, Field(min_length=1, max_length=80)]
    scope: Annotated[str, Field(min_length=1, max_length=120)]
    hardness: ConstraintHardness
    status: ConstraintCheckStatus
    description: Annotated[str, Field(min_length=1, max_length=300)]
    details: dict[str, str] = Field(default_factory=dict)


class PlanSourceSnapshot(ContractModel):
    provider: Annotated[str, Field(min_length=1, max_length=80)]
    source_status: PlanSourceStatus
    fetched_at: datetime
    is_stale: bool = False
    reference_id: Annotated[str, Field(min_length=1, max_length=160)] | None = None


class ProposedPlanVersion(ContractModel):
    schema_version: Literal["1.0"]
    plan_id: UUID4
    trip_snapshot: Trip
    version: Literal[1]
    parent_id: None = None
    reason: Literal["INITIAL_PLAN"] = "INITIAL_PLAN"
    metrics: PlanMetrics
    days: list[PlanDay] = Field(min_length=1, max_length=1)
    constraints_snapshot: list[ConstraintSnapshot] = Field(min_length=1)
    sources_snapshot: list[PlanSourceSnapshot] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_v1_snapshot(self) -> "ProposedPlanVersion":
        if self.trip_snapshot.status is not TripStatus.PLAN_REVIEW:
            raise ValueError("tripSnapshot.status must be PLAN_REVIEW")

        trip_day = self.trip_snapshot.days[0]
        plan_day = self.days[0]
        if plan_day.day_index != trip_day.day_index or plan_day.date != trip_day.date:
            raise ValueError("plan day must match tripSnapshot.days[0]")

        tasks = plan_day.tasks
        task_cost = sum(task.cost_cents for task in tasks)
        task_walk = sum(task.walk_meters for task in tasks)
        if self.metrics.total_cost_cents != task_cost:
            raise ValueError("metrics.totalCostCents must equal the task cost sum")
        if self.metrics.total_walk_meters != task_walk:
            raise ValueError("metrics.totalWalkMeters must equal the task walk sum")

        expected_buffer = self.trip_snapshot.total_budget_cents - task_cost
        if expected_buffer < 0:
            raise ValueError("plan cost cannot exceed tripSnapshot.totalBudgetCents")
        if self.metrics.buffer_cents != expected_buffer:
            raise ValueError("metrics.bufferCents must equal remaining trip budget")

        if any(
            constraint.hardness is ConstraintHardness.HARD
            and constraint.status is not ConstraintCheckStatus.PASS
            for constraint in self.constraints_snapshot
        ):
            raise ValueError("all hard constraints must PASS before Plan V1 review")
        return self


class PlanVersion(ProposedPlanVersion):
    status: PlanVersionStatus
    created_at: datetime
    confirmed_at: datetime | None = None


class PlanTransitionResult(ContractModel):
    trip_id: UUID4
    plan_id: UUID4
    trip_status: TripStatus
    plan_status: PlanVersionStatus


class ExecutionStartResult(ContractModel):
    trip_id: UUID4
    plan_id: UUID4
    trip_status: Literal["EXECUTING"]
    plan_status: Literal["CURRENT"]


class TripPlanState(ContractModel):
    trip_id: UUID4
    trip_status: TripStatus
    current_plan: PlanVersion | None = None
    proposed_plans: list[PlanVersion] = Field(default_factory=list)
    events: list[dict[str, object]] = Field(default_factory=list)


__all__ = [
    "ConstraintCheckStatus",
    "ConstraintHardness",
    "ConstraintSnapshot",
    "ExecutionStartResult",
    "PlanDay",
    "PlanMetrics",
    "PlanSourceSnapshot",
    "PlanSourceStatus",
    "PlanTask",
    "PlanTransitionResult",
    "PlanVersion",
    "PlanVersionStatus",
    "ProposedPlanVersion",
    "TripPlanState",
]
