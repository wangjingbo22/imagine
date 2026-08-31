from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, UUID4

from .execution import ExecutionEventType
from .plan import PlanVersionStatus
from .trip import AssistanceProfile, ContractModel


class MemoryTimelineItemKind(str, Enum):
    PLAN_VERSION = "PLAN_VERSION"
    CARE_CONFIRMED = "CARE_CONFIRMED"
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_SKIPPED = "TASK_SKIPPED"
    EXPENSE = "EXPENSE"
    PHOTO = "PHOTO"


class MemoryPhoto(ContractModel):
    media_id: UUID4
    task_id: str
    data_url: str
    mime_type: str
    byte_size: Annotated[int, Field(gt=0)]
    created_at: datetime


class MemoryTimelineItem(ContractModel):
    item_id: str
    kind: MemoryTimelineItemKind
    occurred_at: datetime
    title: str
    task_id: str | None = None
    event_id: UUID4 | None = None
    event_type: ExecutionEventType | None = None
    plan_version_id: UUID4 | None = None
    plan_version: Annotated[int, Field(ge=1)] | None = None
    plan_status: PlanVersionStatus | None = None
    amount_cents: Annotated[int, Field(ge=0)] | None = None
    cumulative_actual_cost_cents: Annotated[int, Field(ge=0)] | None = None
    completion_rate_percent: Annotated[float, Field(ge=0, le=100)] | None = None
    assistance_profile: AssistanceProfile | None = None
    photo: MemoryPhoto | None = None


class MemoryParticipantCare(ContractModel):
    participant_id: UUID4
    nickname: str
    assistance_profile: AssistanceProfile | None = None


class MemoryTimelineSummary(ContractModel):
    completed_task_count: Annotated[int, Field(ge=0)]
    skipped_task_count: Annotated[int, Field(ge=0)]
    total_task_count: Annotated[int, Field(ge=0)]
    completion_rate_percent: Annotated[float, Field(ge=0, le=100)]
    planned_cost_cents: Annotated[int, Field(ge=0)]
    actual_cost_cents: Annotated[int, Field(ge=0)]
    cost_difference_cents: int
    currency: Literal["CNY"]
    current_plan_version: Annotated[int, Field(ge=1)]
    plan_change_count: Annotated[int, Field(ge=0)]
    photo_count: Annotated[int, Field(ge=0)]
    participant_care_results: list[MemoryParticipantCare] = Field(
        default_factory=list
    )
    # Retained for the original single-person T017 consumer. A group must not
    # collapse distinct long-term profiles into one fabricated profile.
    assistance_profile: AssistanceProfile | None = None


class MemoryTimeline(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    trip_id: UUID4
    summary: MemoryTimelineSummary
    items: list[MemoryTimelineItem]


__all__ = [
    "MemoryPhoto",
    "MemoryParticipantCare",
    "MemoryTimeline",
    "MemoryTimelineItem",
    "MemoryTimelineItemKind",
    "MemoryTimelineSummary",
]
