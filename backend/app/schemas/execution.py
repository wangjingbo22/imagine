from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import ConfigDict, Field, UUID4, model_validator

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

    task_id: Annotated[str, Field(min_length=1, max_length=64)]
    plan_version_id: UUID4
    event_type: ExecutionEventType
    amount_cents: Annotated[int, Field(ge=0)] | None = None
    idempotency_key: Annotated[str, Field(min_length=1, max_length=160)]

    @model_validator(mode="after")
    def validate_amount(self) -> "CreateExecutionEvent":
        if self.event_type is ExecutionEventType.EXPENSE:
            if self.amount_cents is None:
                raise ValueError("EXPENSE event requires amountCents")
        elif self.amount_cents is not None:
            raise ValueError("amountCents is only allowed for EXPENSE events")
        return self


class ExecutionEvent(ContractModel):
    event_id: UUID4
    trip_id: UUID4
    task_id: str
    plan_version_id: UUID4
    event_type: ExecutionEventType
    amount_cents: int | None = None
    idempotency_key: str
    occurred_at: datetime


__all__ = [
    "CreateExecutionEvent",
    "ExecutionEvent",
    "ExecutionEventType",
]
