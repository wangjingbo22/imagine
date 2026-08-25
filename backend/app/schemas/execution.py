from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictInt, UUID4, model_validator

from .trip import ContractModel


class ExecutionEventType(str, Enum):
    START = "START"
    COMPLETE = "COMPLETE"
    SKIP = "SKIP"
    EXPENSE = "EXPENSE"


class CreateExecutionEvent(ContractModel):
    model_config = ConfigDict(
        alias_generator=ContractModel.model_config["alias_generator"],
        populate_by_name=True,
        extra="forbid",
        strict=False,
        str_strip_whitespace=True,
        loc_by_alias=True,
    )

    schema_version: Literal["1.0"] = "1.0"
    task_id: Annotated[str, Field(min_length=1, max_length=64)]
    plan_version_id: UUID4
    event_type: ExecutionEventType
    amount_cents: Annotated[StrictInt, Field(ge=0)] | None = None
    idempotency_key: Annotated[str, Field(min_length=1, max_length=160)]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_amount(self) -> "CreateExecutionEvent":
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurredAt must include a timezone")
        if self.event_type is ExecutionEventType.EXPENSE:
            if self.amount_cents is None:
                raise ValueError("EXPENSE event requires amountCents")
        elif self.amount_cents is not None:
            raise ValueError("amountCents is only allowed for EXPENSE events")
        return self


class ExecutionEvent(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: UUID4
    trip_id: UUID4
    task_id: str
    plan_version_id: UUID4
    event_type: ExecutionEventType
    amount_cents: int | None = None
    idempotency_key: str
    occurred_at: datetime


class ActualBudgetSummary(ContractModel):
    trip_id: UUID4
    plan_version_id: UUID4 | None = None
    planned_budget_cents: Annotated[int, Field(ge=0)]
    actual_spent_cents: Annotated[int, Field(ge=0)]
    remaining_budget_cents: int
    expense_event_count: Annotated[int, Field(ge=0)]


__all__ = [
    "ActualBudgetSummary",
    "CreateExecutionEvent",
    "ExecutionEvent",
    "ExecutionEventType",
]
