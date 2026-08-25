from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from app.domain.models import Place, Provenance, Route
from app.schemas.constraint import Constraint
from app.schemas.trip import (
    ContractModel,
    GeoPoint,
    SecondPrecisionTime,
    Trip,
    TripMode,
    TripStatus,
)
from app.services.route_risk import ValidationStatus

class CandidateTaskFact(ContractModel):
    """One selected same-city activity and its normalized T006 facts."""

    task_id: Annotated[str, Field(min_length=1, max_length=64)]
    order: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(min_length=1, max_length=120)]
    category: Annotated[str, Field(min_length=1, max_length=80)]
    start_at: SecondPrecisionTime
    end_at: SecondPrecisionTime
    end_location_text: Annotated[str, Field(min_length=1, max_length=120)]
    city_code: Annotated[str, Field(min_length=1, max_length=64)]
    place: Place
    route: Route
    elapsed_since_rest_minutes: Annotated[int, Field(ge=0)]
    note: Annotated[str, Field(max_length=500)] = ""

    @model_validator(mode="after")
    def validate_time_range(self) -> "CandidateTaskFact":
        if self.end_at <= self.start_at:
            raise ValueError("endAt must be later than startAt")
        return self


class CandidateEndpointFact(ContractModel):
    """Resolved GCJ02 coordinate for a Trip day start or end location."""

    location_text: Annotated[str, Field(min_length=1, max_length=120)]
    city_code: Annotated[str, Field(min_length=1, max_length=64)]
    location: GeoPoint
    provenance: Provenance


class CandidatePlanRequest(ContractModel):
    """Trusted planning input before any validation result has been accepted."""

    schema_version: Literal["1.0"]
    trip: Trip
    start_location: CandidateEndpointFact
    end_location: CandidateEndpointFact
    task_facts: tuple[CandidateTaskFact, ...] = Field(min_length=3, max_length=4)
    confirmed_constraints: tuple[Constraint, ...]

    @model_validator(mode="after")
    def validate_single_day_shape(self) -> "CandidatePlanRequest":
        if self.trip.mode is not TripMode.SINGLE:
            raise ValueError("T011 only supports SINGLE trips")
        if self.trip.status not in {
            TripStatus.CONSTRAINT_CONFIRMED,
            TripStatus.PLANNING,
            TripStatus.PLAN_REVIEW,
        }:
            raise ValueError("trip status must be ready for planning")
        if len(self.trip.participants) != 1 or len(self.trip.days) != 1:
            raise ValueError("T011 requires exactly one participant and one day")

        day = self.trip.days[0]
        if self.trip.start_date != self.trip.end_date or day.date != self.trip.start_date:
            raise ValueError("trip and plan facts must describe the same single day")
        if day.day_index != 0:
            raise ValueError("dayIndex must be 0 for the S1 single-day plan")
        if day.time_window.end <= day.time_window.start:
            raise ValueError("day timeWindow.end must be later than start")
        if day.daily_budget_cents > self.trip.total_budget_cents:
            raise ValueError("daily budget cannot exceed total budget")

        expected_orders = list(range(1, len(self.task_facts) + 1))
        if [item.order for item in self.task_facts] != expected_orders:
            raise ValueError("taskFacts must use contiguous order values starting at 1")
        if len({item.task_id for item in self.task_facts}) != len(self.task_facts):
            raise ValueError("taskId must be unique within taskFacts")
        if len({item.route.routeId for item in self.task_facts}) != len(
            self.task_facts
        ):
            raise ValueError("routeId must be unique within taskFacts")

        previous_end = day.time_window.start
        for item in self.task_facts:
            if item.start_at < day.time_window.start or item.end_at > day.time_window.end:
                raise ValueError("taskFacts must stay inside the trip day time window")
            if item.start_at < previous_end:
                raise ValueError("taskFacts must be ordered and must not overlap")
            previous_end = item.end_at
        return self


class CandidateConstraintResult(ContractModel):
    rule_id: Annotated[str, Field(min_length=1, max_length=120)]
    scope: Annotated[str, Field(min_length=1, max_length=120)]
    hardness: Literal["HARD", "SOFT"]
    status: ValidationStatus
    reference_id: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    observed: dict[str, JsonValue]
    suggestion: Annotated[str, Field(max_length=300)] | None = None


class CandidatePlanWarning(ContractModel):
    code: Literal["UNKNOWN_PRICE", "UNKNOWN_SOURCE"]
    severity: Literal["WARNING"] = "WARNING"
    resolution: Literal["NEEDS_CONFIRMATION"] = "NEEDS_CONFIRMATION"
    reference_id: Annotated[str, Field(min_length=1, max_length=160)]
    field: Annotated[str, Field(min_length=1, max_length=120)]
    message: Annotated[str, Field(min_length=1, max_length=300)]


class CandidateTask(ContractModel):
    task_id: Annotated[str, Field(min_length=1, max_length=64)]
    order: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(min_length=1, max_length=120)]
    category: Annotated[str, Field(min_length=1, max_length=80)]
    time_range: Annotated[str, Field(min_length=1, max_length=80)]
    duration_minutes: Annotated[int, Field(ge=0, le=1_440)]
    transport: Annotated[str, Field(min_length=1, max_length=160)]
    cost_cents: Annotated[int | None, Field(ge=0)]
    known_cost_cents: Annotated[int, Field(ge=0)]
    unknown_amount_count: Annotated[int, Field(ge=0)]
    walk_meters: Annotated[int, Field(ge=0)]
    transfer_count: Annotated[int, Field(ge=0)]
    place_id: Annotated[str, Field(min_length=1, max_length=160)]
    route_id: Annotated[str, Field(min_length=1, max_length=160)]
    end_location_text: Annotated[str, Field(min_length=1, max_length=120)]
    note: Annotated[str, Field(max_length=500)] = ""

    @model_validator(mode="after")
    def validate_unknown_amount_shape(self) -> "CandidateTask":
        if (self.cost_cents is None) != (self.unknown_amount_count > 0):
            raise ValueError(
                "costCents must be null exactly when an amount is unknown"
            )
        if self.cost_cents is not None and self.cost_cents != self.known_cost_cents:
            raise ValueError("known task cost must equal costCents")
        return self


class CandidatePlanMetrics(ContractModel):
    total_cost_cents: Annotated[int | None, Field(ge=0)]
    known_total_cost_cents: Annotated[int, Field(ge=0)]
    unknown_amount_count: Annotated[int, Field(ge=0)]
    budget_limit_cents: Annotated[int, Field(ge=0)]
    known_budget_buffer_cents: Annotated[int, Field(ge=0)]
    total_walk_meters: Annotated[int, Field(ge=0)]
    transfer_count: Annotated[int, Field(ge=0)]
    validation_status: Literal["PASS", "NEEDS_CONFIRMATION"]


class CandidatePlan(ContractModel):
    """The single deterministic pre-review plan emitted by T011."""

    schema_version: Literal["1.0"]
    candidate_id: Annotated[str, Field(min_length=1, max_length=80)]
    trip_id: Annotated[str, Field(min_length=1, max_length=80)]
    city_code: Annotated[str, Field(min_length=1, max_length=64)]
    day_index: Literal[0]
    date: date
    tasks: tuple[CandidateTask, ...] = Field(min_length=3, max_length=4)
    metrics: CandidatePlanMetrics
    constraint_results: tuple[CandidateConstraintResult, ...] = Field(min_length=1)
    warnings: tuple[CandidatePlanWarning, ...]

    @model_validator(mode="after")
    def validate_recomputed_totals_and_status(self) -> "CandidatePlan":
        if [item.order for item in self.tasks] != list(
            range(1, len(self.tasks) + 1)
        ):
            raise ValueError("candidate tasks must retain contiguous order")
        if len({item.task_id for item in self.tasks}) != len(self.tasks):
            raise ValueError("candidate taskId values must be unique")

        known_total = sum(item.known_cost_cents for item in self.tasks)
        unknown_count = sum(item.unknown_amount_count for item in self.tasks)
        total_walk = sum(item.walk_meters for item in self.tasks)
        total_transfers = sum(item.transfer_count for item in self.tasks)
        if self.metrics.known_total_cost_cents != known_total:
            raise ValueError("metrics.knownTotalCostCents must be recomputed from tasks")
        if self.metrics.unknown_amount_count != unknown_count:
            raise ValueError("metrics.unknownAmountCount must be recomputed from tasks")
        if self.metrics.total_walk_meters != total_walk:
            raise ValueError("metrics.totalWalkMeters must be recomputed from tasks")
        if self.metrics.transfer_count != total_transfers:
            raise ValueError("metrics.transferCount must be recomputed from tasks")

        expected_total = None if unknown_count else known_total
        if self.metrics.total_cost_cents != expected_total:
            raise ValueError("totalCostCents must stay null while any amount is unknown")
        if self.metrics.known_budget_buffer_cents != (
            self.metrics.budget_limit_cents - known_total
        ):
            raise ValueError("knownBudgetBufferCents must use the recomputed subtotal")

        if any(
            item.hardness == "HARD" and item.status is not ValidationStatus.PASS
            for item in self.constraint_results
        ):
            raise ValueError("all HARD constraints must PASS before returning a candidate")

        expected_status = "NEEDS_CONFIRMATION" if self.warnings else "PASS"
        if self.metrics.validation_status != expected_status:
            raise ValueError("candidate status must reflect independent warnings")
        if unknown_count and not any(
            item.code == "UNKNOWN_PRICE" for item in self.warnings
        ):
            raise ValueError("every unknown amount requires an UNKNOWN_PRICE warning")
        return self


__all__ = [
    "CandidateConstraintResult",
    "CandidateEndpointFact",
    "CandidatePlan",
    "CandidatePlanMetrics",
    "CandidatePlanRequest",
    "CandidatePlanWarning",
    "CandidateTask",
    "CandidateTaskFact",
]
