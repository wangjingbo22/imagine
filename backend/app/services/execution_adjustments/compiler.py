from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import NamedTuple

from pydantic import ValidationError

from app.schemas.constraint import Constraint
from app.schemas.execution_adjustment import (
    EventConstraintSet,
    ExecutionAdjustmentReason,
    ExecutionAdjustmentType,
    ExecutionConstraintCompileRequest,
    FatigueLevel,
)


POLICY_VERSION = "S2-T020-1.0"


class FatiguePolicy(NamedTuple):
    remaining_walk_budget_meters: int
    max_segment_walk_meters: int
    rest_interval_minutes: int


# Project defaults. The PO still needs to freeze these three product thresholds.
FATIGUE_POLICIES = MappingProxyType(
    {
        FatigueLevel.MILD: FatiguePolicy(3000, 800, 60),
        FatigueLevel.MODERATE: FatiguePolicy(1500, 500, 45),
        FatigueLevel.SEVERE: FatiguePolicy(500, 200, 30),
    }
)


class ExecutionConstraintCompileError(ValueError):
    code = "EXECUTION_CONSTRAINT_INPUT_INVALID"


def compile_execution_constraints(
    request: ExecutionConstraintCompileRequest,
) -> EventConstraintSet:
    """Compile a transient, deterministic overlay without mutating domain state."""

    try:
        request = ExecutionConstraintCompileRequest.model_validate_json(
            request.model_dump_json(by_alias=True),
            strict=True,
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ExecutionConstraintCompileError(str(exc)) from exc

    event = request.event
    current = request.current_constraints
    if event.event_type is ExecutionAdjustmentType.LATE:
        assert event.late_minutes is not None
        assert current.remaining_time_minutes is not None
        effective = max(0, current.remaining_time_minutes - event.late_minutes)
        constraints = (
            Constraint(
                field="remaining.timeBudgetMinutes",
                operator="LTE",
                value=effective,
                scope="REMAINING_ITINERARY",
                hardness="HARD",
            ),
        )
        reasons = (
            ExecutionAdjustmentReason(
                reason_code="LATE_REMAINING_TIME_TIGHTENED",
                message=(
                    f"已确认迟到 {event.late_minutes} 分钟，剩余可用时间由 "
                    f"{current.remaining_time_minutes} 分钟收紧为 {effective} 分钟。"
                ),
            ),
        )
    else:
        assert event.fatigue_level is not None
        assert current.remaining_walk_budget_meters is not None
        assert current.max_segment_walk_meters is not None
        assert current.rest_interval_minutes is not None
        policy = FATIGUE_POLICIES[event.fatigue_level]
        remaining_walk = min(
            current.remaining_walk_budget_meters,
            policy.remaining_walk_budget_meters,
        )
        segment_walk = min(
            current.max_segment_walk_meters,
            policy.max_segment_walk_meters,
            remaining_walk,
        )
        rest_interval = min(
            current.rest_interval_minutes,
            policy.rest_interval_minutes,
        )
        constraints = (
            Constraint(
                field="remaining.walkBudgetMeters",
                operator="LTE",
                value=remaining_walk,
                scope="REMAINING_ITINERARY",
                hardness="HARD",
            ),
            Constraint(
                field="remaining.maxSegmentWalkMeters",
                operator="LTE",
                value=segment_walk,
                scope="REMAINING_ITINERARY",
                hardness="HARD",
            ),
            Constraint(
                field="remaining.restIntervalMinutes",
                operator="LTE",
                value=rest_interval,
                scope="REMAINING_ITINERARY",
                hardness="HARD",
            ),
        )
        reasons = (
            ExecutionAdjustmentReason(
                reason_code="FATIGUE_WALK_REST_TIGHTENED",
                message=(
                    f"已确认疲劳等级 {event.fatigue_level.value}，剩余步行上限调整为 "
                    f"{remaining_walk} 米、单段步行上限 {segment_walk} 米，"
                    f"每 {rest_interval} 分钟至少安排一次休息。"
                ),
            ),
        )

    return EventConstraintSet(
        source_event=event,
        constraints=constraints,
        reasons=reasons,
        input_digest=_input_digest(request),
    )


def _input_digest(request: ExecutionConstraintCompileRequest) -> str:
    canonical = json.dumps(
        {
            "policyVersion": POLICY_VERSION,
            "request": request.model_dump(mode="json", by_alias=True),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = [
    "FATIGUE_POLICIES",
    "ExecutionConstraintCompileError",
    "FatiguePolicy",
    "POLICY_VERSION",
    "compile_execution_constraints",
]
