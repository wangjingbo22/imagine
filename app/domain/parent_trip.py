from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, UUID4, model_validator

from app.domain.collaboration import CollaborationModel


class ParentTripCreateRequest(CollaborationModel):
    schema_version: Literal["1.0"]
    parent_trip_id: UUID4
    title: str = Field(min_length=1, max_length=80)
    city_name: str = Field(min_length=1, max_length=80)
    start_date: date
    day_budget_cents: list[Annotated[int, Field(ge=0, le=100_000_000)]] = Field(
        min_length=2, max_length=3
    )


class ParentTripDay(CollaborationModel):
    day_index: int = Field(ge=0, le=2)
    date: date
    budget_cents: int = Field(ge=0)
    child_trip_id: UUID4 | None = None
    child_budget_cents: int | None = Field(default=None, ge=0)
    planned_cost_cents: int | None = Field(default=None, ge=0)
    actual_spent_cents: int | None = Field(default=None, ge=0)
    remaining_budget_cents: int | None = None
    child_status: str = "NOT_CREATED"
    cost_status: Literal["NOT_AVAILABLE", "PLANNED", "ACTUAL_RECORDED"] = "NOT_AVAILABLE"


class ParentTrip(CollaborationModel):
    schema_version: Literal["1.0"] = "1.0"
    parent_trip_id: UUID4
    title: str
    city_name: str
    start_date: date
    end_date: date
    total_budget_cents: int = Field(ge=0)
    planned_cost_cents: int | None = Field(default=None, ge=0)
    actual_spent_cents: int | None = Field(default=None, ge=0)
    days: list[ParentTripDay] = Field(min_length=2, max_length=3)


class ParentTripDayLinkRequest(CollaborationModel):
    schema_version: Literal["1.0"]
    child_trip_id: UUID4


__all__ = [
    "ParentTrip", "ParentTripCreateRequest", "ParentTripDay", "ParentTripDayLinkRequest",
]
