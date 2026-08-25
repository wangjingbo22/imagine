from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, alias_generators

from app.schemas.trip import CreateSingleDayTrip


class DraftContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class DraftAssistanceInput(DraftContractModel):
    max_segment_walk_meters: int = Field(default=500, ge=100)
    max_transfers: int = Field(default=2, ge=0)
    rest_interval_minutes: int = Field(default=90, ge=1)


class TripDraftParseRequest(DraftContractModel):
    schema_version: Literal["1.0"] = "1.0"
    natural_language_request: str = Field(min_length=1, max_length=1000)
    reference_date: date | None = None
    city_name: str | None = None
    travel_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    budget_cents: int | None = Field(default=None, ge=0)
    interests: list[str] = Field(default_factory=list)
    must_visit: list[str] = Field(default_factory=list)
    avoid_places: list[str] = Field(default_factory=list)
    assistance_mode: Literal[
        "standard", "family", "low-mobility", "assisted"
    ] = "standard"
    assistance_profile: DraftAssistanceInput = Field(
        default_factory=DraftAssistanceInput
    )


class ConfirmationItem(DraftContractModel):
    item_id: str
    path: str
    code: Literal["missing", "ambiguous", "conflict", "invalid"]
    message: str
    candidates: list[str] = Field(default_factory=list)


class ParsedTripFields(DraftContractModel):
    city_name: str | None = None
    travel_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    budget_cents: int | None = None
    interests: list[str] = Field(default_factory=list)
    must_visit: list[str] = Field(default_factory=list)
    avoid_places: list[str] = Field(default_factory=list)


class TripDraftParseResult(DraftContractModel):
    trip_id: str
    status: Literal["DRAFT"] = "DRAFT"
    parsed: ParsedTripFields
    confirmation_items: list[ConfirmationItem]
    can_plan: bool
    trip: CreateSingleDayTrip | None = None


__all__ = [
    "ConfirmationItem",
    "DraftAssistanceInput",
    "ParsedTripFields",
    "TripDraftParseRequest",
    "TripDraftParseResult",
]
