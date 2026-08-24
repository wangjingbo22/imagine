from __future__ import annotations

from dataclasses import dataclass

from app.schemas.plan import PlanVersionStatus
from app.schemas.trip import TripStatus


@dataclass(frozen=True, slots=True)
class StateTransitionViolation(ValueError):
    aggregate: str
    current: str
    target: str

    def __str__(self) -> str:
        return f"{self.aggregate} cannot transition from {self.current} to {self.target}"


TRIP_TRANSITIONS: dict[TripStatus, frozenset[TripStatus]] = {
    TripStatus.DRAFT: frozenset({TripStatus.CONSTRAINT_CONFIRMED}),
    TripStatus.CONSTRAINT_CONFIRMED: frozenset({TripStatus.DRAFT, TripStatus.PLANNING}),
    TripStatus.PLANNING: frozenset({TripStatus.DRAFT, TripStatus.PLAN_REVIEW}),
    TripStatus.PLAN_REVIEW: frozenset({TripStatus.DRAFT, TripStatus.CONFIRMED}),
    TripStatus.CONFIRMED: frozenset({TripStatus.EXECUTING}),
    TripStatus.EXECUTING: frozenset({TripStatus.REPLAN_REVIEW, TripStatus.COMPLETED}),
    TripStatus.REPLAN_REVIEW: frozenset({TripStatus.EXECUTING}),
    TripStatus.COMPLETED: frozenset(),
}

PLAN_VERSION_TRANSITIONS: dict[PlanVersionStatus, frozenset[PlanVersionStatus]] = {
    PlanVersionStatus.PROPOSED: frozenset(
        {PlanVersionStatus.CURRENT, PlanVersionStatus.REJECTED}
    ),
    PlanVersionStatus.CURRENT: frozenset({PlanVersionStatus.SUPERSEDED}),
    PlanVersionStatus.REJECTED: frozenset(),
    PlanVersionStatus.SUPERSEDED: frozenset(),
}


def require_trip_transition(current: TripStatus, target: TripStatus) -> None:
    if target not in TRIP_TRANSITIONS[current]:
        raise StateTransitionViolation("Trip", current.value, target.value)


def require_plan_transition(
    current: PlanVersionStatus,
    target: PlanVersionStatus,
) -> None:
    if target not in PLAN_VERSION_TRANSITIONS[current]:
        raise StateTransitionViolation("PlanVersion", current.value, target.value)
