from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, UUID4

from .execution import ExecutionEvent
from .plan import PlanVersionReason, PlanVersionStatus
from .trip import AssistanceProfile, ContractModel, TripStatus


class ConstraintProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    CONSTRAINT_CONFIRMED = "CONSTRAINT_CONFIRMED"


class ConstraintProfileState(ContractModel):
    trip_id: UUID4
    status: ConstraintProfileStatus
    assistance_profile: AssistanceProfile
    updated_at: datetime
    confirmed_at: datetime | None = None


class PlanHistoryItem(ContractModel):
    plan_id: UUID4
    version: Annotated[int, Field(ge=1)]
    status: PlanVersionStatus
    reason: PlanVersionReason


class TripExecutionSummary(ContractModel):
    trip_id: UUID4
    trip_status: TripStatus
    planned_cost_cents: Annotated[int, Field(ge=0)]
    actual_cost_cents: Annotated[int, Field(ge=0)]
    difference_cents: int
    completed_task_ids: list[str]
    skipped_task_ids: list[str]
    total_tasks: Annotated[int, Field(ge=0)]
    current_plan_version: int
    plan_history: list[PlanHistoryItem]
    events: list[ExecutionEvent]


class ConstraintConfirmationResult(ContractModel):
    trip_id: UUID4
    status: Literal["CONSTRAINT_CONFIRMED"]
    assistance_profile: AssistanceProfile
    confirmed_at: datetime


__all__ = [
    "ConstraintConfirmationResult",
    "ConstraintProfileState",
    "ConstraintProfileStatus",
    "PlanHistoryItem",
    "TripExecutionSummary",
]
