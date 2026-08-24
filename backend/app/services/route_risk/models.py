from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import Field, JsonValue

from app.schemas.trip import ContractModel


class WalkType(str, Enum):
    LEVEL = "LEVEL"
    STAIRS = "STAIRS"
    ELEVATOR = "ELEVATOR"
    RAMP = "RAMP"
    UNKNOWN = "UNKNOWN"


class ValidationStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    FAIL = "FAIL"


class RouteSegmentRiskFacts(ContractModel):
    """Provider-independent facts needed by the T009 risk matrix.

    T006 may adapt its RouteSnapshot into this DTO.  Keeping that conversion
    outside the evaluator prevents provider fields and network behavior from
    entering deterministic validation.
    """

    route_segment: Annotated[str, Field(min_length=1, max_length=120)]
    walking_distance_meters: Annotated[int, Field(ge=0)]
    cumulative_transfers: Annotated[int, Field(ge=0)]
    elapsed_since_rest_minutes: Annotated[int, Field(ge=0)]
    walk_types: Annotated[tuple[WalkType, ...], Field(min_length=1)]


class RouteRiskInput(ContractModel):
    segments: tuple[RouteSegmentRiskFacts, ...] = Field(min_length=1)


class RouteRiskResult(ContractModel):
    rule_id: Annotated[str, Field(min_length=1, max_length=120)]
    status: ValidationStatus
    route_segment: str | None
    observed: dict[str, JsonValue]
    suggestion: str | None = None


class RouteRiskReport(ContractModel):
    status: ValidationStatus
    results: tuple[RouteRiskResult, ...]


__all__ = [
    "RouteRiskInput",
    "RouteRiskReport",
    "RouteRiskResult",
    "RouteSegmentRiskFacts",
    "ValidationStatus",
    "WalkType",
]
