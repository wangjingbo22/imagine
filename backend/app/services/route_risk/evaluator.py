from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from app.schemas.constraint import Constraint

from .models import (
    RouteRiskInput,
    RouteRiskReport,
    RouteRiskResult,
    RouteSegmentRiskFacts,
    ValidationStatus,
    WalkType,
)


FIELD_WALK_SEGMENT: Final = "walkLimits.maxContinuousMeters"
FIELD_WALK_DAILY: Final = "walkLimits.maxDailyMeters"
FIELD_MAX_TRANSFERS: Final = "maxTransfers"
FIELD_REST_INTERVAL: Final = "restInterval"
FIELD_AVOID_STAIRS: Final = "avoidStairs"

RULE_WALK_SEGMENT: Final = "CARE.ROUTE.WALK_SEGMENT_LIMIT"
RULE_WALK_DAILY: Final = "CARE.ROUTE.WALK_DAILY_LIMIT"
RULE_TRANSFERS: Final = "CARE.ROUTE.TRANSFER_LIMIT"
RULE_REST: Final = "CARE.ROUTE.REST_INTERVAL"
RULE_STAIRS: Final = "CARE.ROUTE.STAIRS_FORBIDDEN"
RULE_UNSUPPORTED: Final = "CARE.ROUTE.UNSUPPORTED_CONSTRAINT"

_FIELD_ALIASES: Final = {
    # The product document calls this a segment limit while T003 currently
    # serializes maxContinuousMeters.  Accepting the documented synonym keeps
    # the adapter compatible without changing either team's schema.
    "walkLimits.maxSegmentMeters": FIELD_WALK_SEGMENT,
    FIELD_WALK_SEGMENT: FIELD_WALK_SEGMENT,
    FIELD_WALK_DAILY: FIELD_WALK_DAILY,
    FIELD_MAX_TRANSFERS: FIELD_MAX_TRANSFERS,
    FIELD_REST_INTERVAL: FIELD_REST_INTERVAL,
    FIELD_AVOID_STAIRS: FIELD_AVOID_STAIRS,
}

_RULE_ORDER: Final = (
    FIELD_AVOID_STAIRS,
    FIELD_WALK_SEGMENT,
    FIELD_WALK_DAILY,
    FIELD_MAX_TRANSFERS,
    FIELD_REST_INTERVAL,
)

_STATUS_PRIORITY: Final = {
    ValidationStatus.PASS: 0,
    ValidationStatus.WARNING: 1,
    ValidationStatus.NEEDS_CONFIRMATION: 2,
    ValidationStatus.FAIL: 3,
}


class RouteRiskContractError(ValueError):
    """Raised when a hard route rule cannot be evaluated safely."""

    def __init__(
        self,
        *,
        code: str,
        field: str,
        message: str,
    ) -> None:
        self.code = code
        self.field = field
        super().__init__(message)

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field": self.field,
            "message": str(self),
        }


def evaluate_route_risk(
    route: RouteRiskInput,
    constraints: Sequence[Constraint],
) -> RouteRiskReport:
    """Evaluate care-route facts without I/O, time, randomness or LLM calls."""

    known, unsupported_soft = _normalize_constraints(constraints)
    results: list[RouteRiskResult] = []

    for field in _RULE_ORDER:
        constraint = known.get(field)
        if constraint is None:
            continue
        if field == FIELD_AVOID_STAIRS:
            results.append(_evaluate_stairs(route, constraint))
        elif field == FIELD_WALK_SEGMENT:
            results.append(_evaluate_segment_walk(route, constraint))
        elif field == FIELD_WALK_DAILY:
            results.append(_evaluate_daily_walk(route, constraint))
        elif field == FIELD_MAX_TRANSFERS:
            results.append(_evaluate_transfers(route, constraint))
        elif field == FIELD_REST_INTERVAL:
            results.append(_evaluate_rest(route, constraint))

    for constraint in unsupported_soft:
        results.append(
            RouteRiskResult(
                rule_id=RULE_UNSUPPORTED,
                status=ValidationStatus.WARNING,
                route_segment=None,
                observed={
                    "field": constraint.field,
                    "scope": constraint.scope,
                },
                suggestion="The unsupported soft route rule requires review",
            )
        )

    overall = max(
        (result.status for result in results),
        key=_STATUS_PRIORITY.__getitem__,
        default=ValidationStatus.PASS,
    )
    return RouteRiskReport(status=overall, results=tuple(results))


def _normalize_constraints(
    constraints: Sequence[Constraint],
) -> tuple[dict[str, Constraint], tuple[Constraint, ...]]:
    known: dict[str, Constraint] = {}
    unsupported_soft: list[Constraint] = []

    for constraint in constraints:
        canonical_field = _FIELD_ALIASES.get(constraint.field)
        if canonical_field is not None:
            if canonical_field in known:
                raise RouteRiskContractError(
                    code="DUPLICATE_ROUTE_CONSTRAINT",
                    field=constraint.field,
                    message=(
                        "More than one constraint targets the same route rule"
                    ),
                )
            known[canonical_field] = constraint
            continue

        if not _is_route_scope(constraint.scope):
            continue
        if constraint.hardness == "HARD":
            raise RouteRiskContractError(
                code="UNSUPPORTED_HARD_ROUTE_CONSTRAINT",
                field=constraint.field,
                message=(
                    "Unknown hard route constraint cannot be treated as passing"
                ),
            )
        unsupported_soft.append(constraint)

    unsupported_soft.sort(key=lambda item: (item.field, item.scope))
    return known, tuple(unsupported_soft)


def _is_route_scope(scope: str) -> bool:
    normalized = scope.strip().upper()
    return normalized == "SEGMENT" or normalized.startswith("ROUTE")


def _evaluate_stairs(
    route: RouteRiskInput,
    constraint: Constraint,
) -> RouteRiskResult:
    if constraint.operator != "EQ" or type(constraint.value) is not bool:
        _raise_invalid_rule(constraint, expected="EQ with a boolean value")

    if constraint.value is False:
        return _pass_result(
            rule_id=RULE_STAIRS,
            observed={"avoidStairs": False},
        )

    stairs = _first_segment_with_type(route, WalkType.STAIRS)
    if stairs is not None:
        return _violation_result(
            constraint,
            rule_id=RULE_STAIRS,
            segment=stairs,
            observed={"walkTypes": [item.value for item in stairs.walk_types]},
            suggestion="Choose a route without known stairs",
        )

    unknown = _first_segment_with_type(route, WalkType.UNKNOWN)
    if unknown is not None:
        return RouteRiskResult(
            rule_id=RULE_STAIRS,
            status=ValidationStatus.NEEDS_CONFIRMATION,
            route_segment=unknown.route_segment,
            observed={"walkTypes": [item.value for item in unknown.walk_types]},
            suggestion="Confirm whether the route contains stairs",
        )

    return _pass_result(
        rule_id=RULE_STAIRS,
        observed={"avoidStairs": True, "knownStairs": False},
    )


def _evaluate_segment_walk(
    route: RouteRiskInput,
    constraint: Constraint,
) -> RouteRiskResult:
    limit = _integer_lte_limit(constraint)
    offending = next(
        (
            segment
            for segment in route.segments
            if segment.walking_distance_meters > limit
        ),
        None,
    )
    observed_max = max(
        segment.walking_distance_meters for segment in route.segments
    )
    if offending is None:
        return _pass_result(
            rule_id=RULE_WALK_SEGMENT,
            observed={
                "maxWalkingDistanceMeters": observed_max,
                "limitMeters": limit,
            },
        )
    return _violation_result(
        constraint,
        rule_id=RULE_WALK_SEGMENT,
        segment=offending,
        observed={
            "walkingDistanceMeters": offending.walking_distance_meters,
            "limitMeters": limit,
        },
        suggestion="Use a shorter walking segment",
    )


def _evaluate_daily_walk(
    route: RouteRiskInput,
    constraint: Constraint,
) -> RouteRiskResult:
    limit = _integer_lte_limit(constraint)
    cumulative = 0
    offending: RouteSegmentRiskFacts | None = None
    for segment in route.segments:
        cumulative += segment.walking_distance_meters
        if cumulative > limit and offending is None:
            offending = segment

    if offending is None:
        return _pass_result(
            rule_id=RULE_WALK_DAILY,
            observed={"dailyWalkingMeters": cumulative, "limitMeters": limit},
        )
    return _violation_result(
        constraint,
        rule_id=RULE_WALK_DAILY,
        segment=offending,
        observed={"dailyWalkingMeters": cumulative, "limitMeters": limit},
        suggestion="Reduce total walking distance",
    )


def _evaluate_transfers(
    route: RouteRiskInput,
    constraint: Constraint,
) -> RouteRiskResult:
    limit = _integer_lte_limit(constraint)
    offending = next(
        (
            segment
            for segment in route.segments
            if segment.cumulative_transfers > limit
        ),
        None,
    )
    observed_max = max(segment.cumulative_transfers for segment in route.segments)
    if offending is None:
        return _pass_result(
            rule_id=RULE_TRANSFERS,
            observed={"transfers": observed_max, "limit": limit},
        )
    return _violation_result(
        constraint,
        rule_id=RULE_TRANSFERS,
        segment=offending,
        observed={"transfers": offending.cumulative_transfers, "limit": limit},
        suggestion="Choose a route with fewer transfers",
    )


def _evaluate_rest(
    route: RouteRiskInput,
    constraint: Constraint,
) -> RouteRiskResult:
    limit = _integer_lte_limit(constraint)
    offending = next(
        (
            segment
            for segment in route.segments
            if segment.elapsed_since_rest_minutes > limit
        ),
        None,
    )
    observed_max = max(
        segment.elapsed_since_rest_minutes for segment in route.segments
    )
    if offending is None:
        return _pass_result(
            rule_id=RULE_REST,
            observed={"minutesSinceRest": observed_max, "limitMinutes": limit},
        )
    return _violation_result(
        constraint,
        rule_id=RULE_REST,
        segment=offending,
        observed={
            "minutesSinceRest": offending.elapsed_since_rest_minutes,
            "limitMinutes": limit,
        },
        suggestion="Insert a rest before this route segment",
    )


def _integer_lte_limit(constraint: Constraint) -> int:
    if constraint.operator != "LTE" or type(constraint.value) is not int:
        _raise_invalid_rule(constraint, expected="LTE with an integer value")
    assert type(constraint.value) is int
    if constraint.value < 0:
        _raise_invalid_rule(constraint, expected="a non-negative integer limit")
    return constraint.value


def _raise_invalid_rule(constraint: Constraint, *, expected: str) -> None:
    raise RouteRiskContractError(
        code="INVALID_ROUTE_CONSTRAINT",
        field=constraint.field,
        message=f"Route constraint requires {expected}",
    )


def _first_segment_with_type(
    route: RouteRiskInput,
    walk_type: WalkType,
) -> RouteSegmentRiskFacts | None:
    return next(
        (
            segment
            for segment in route.segments
            if walk_type in segment.walk_types
        ),
        None,
    )


def _violation_result(
    constraint: Constraint,
    *,
    rule_id: str,
    segment: RouteSegmentRiskFacts,
    observed: dict[str, object],
    suggestion: str,
) -> RouteRiskResult:
    status = (
        ValidationStatus.FAIL
        if constraint.hardness == "HARD"
        else ValidationStatus.WARNING
    )
    return RouteRiskResult(
        rule_id=rule_id,
        status=status,
        route_segment=segment.route_segment,
        observed=observed,
        suggestion=suggestion,
    )


def _pass_result(
    *,
    rule_id: str,
    observed: dict[str, object],
) -> RouteRiskResult:
    return RouteRiskResult(
        rule_id=rule_id,
        status=ValidationStatus.PASS,
        route_segment=None,
        observed=observed,
    )


__all__ = [
    "FIELD_AVOID_STAIRS",
    "FIELD_MAX_TRANSFERS",
    "FIELD_REST_INTERVAL",
    "FIELD_WALK_DAILY",
    "FIELD_WALK_SEGMENT",
    "RouteRiskContractError",
    "evaluate_route_risk",
]
