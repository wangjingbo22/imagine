from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Collection

from app.schemas.execution import ExecutionEvent, ExecutionEventType
from app.schemas.execution_adjustment import (
    ConfirmedExecutionAdjustment,
    ExecutionAdjustmentType,
    RemainingConstraintContext,
)
from app.schemas.plan import PlanVersion
from app.services.planning.models import CandidatePlanRequest


@dataclass(frozen=True, slots=True)
class ExecutionReplanProjection:
    frozen_task_ids: tuple[str, ...]
    actual_spent_cents: int
    remaining_context: RemainingConstraintContext


class ExecutionReplanContextError(ValueError):
    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


def project_execution_adjustment(
    *,
    current_plan: PlanVersion,
    current_request: CandidatePlanRequest,
    events: Collection[ExecutionEvent],
    adjustment: ConfirmedExecutionAdjustment,
    locked_task_ids: Collection[str] = (),
) -> ExecutionReplanProjection:
    """Derive T020 baselines only from CURRENT and server-restored facts."""

    tasks = tuple(current_plan.days[0].tasks)
    facts = tuple(current_request.task_facts)
    task_index = {task.task_id: index for index, task in enumerate(tasks)}
    if tuple(task_index) != tuple(fact.task_id for fact in facts):
        raise ExecutionReplanContextError(
            "S2_T021_CURRENT_FACTS_MISMATCH",
            "currentPlan.days[0].tasks",
            "CURRENT tasks do not match the server-restored planning facts",
        )
    source_index = task_index.get(adjustment.task_id)
    if source_index is None:
        raise ExecutionReplanContextError(
            "S2_T021_EVENT_TASK_NOT_FOUND",
            "adjustment.taskId",
            "confirmed adjustment task is absent from CURRENT",
        )

    frozen_indexes = set(range(source_index + 1))
    terminal_source = False
    started_source = False
    actual_spent_cents = 0
    terminal_by_task: dict[str, ExecutionEventType] = {}
    for index, event in enumerate(events):
        if event.trip_id != current_plan.trip_snapshot.trip_id:
            raise ExecutionReplanContextError(
                "S2_T021_EVENT_TRIP_MISMATCH",
                f"events[{index}].tripId",
                "execution event belongs to another Trip",
            )
        if event.plan_version_id != current_plan.plan_id:
            raise ExecutionReplanContextError(
                "S2_T021_EVENT_PLAN_MISMATCH",
                f"events[{index}].planVersionId",
                "execution event does not belong to CURRENT",
            )
        event_index = task_index.get(event.task_id)
        if event_index is None:
            raise ExecutionReplanContextError(
                "S2_T021_EXECUTION_TASK_NOT_FOUND",
                f"events[{index}].taskId",
                "execution event task is absent from CURRENT",
            )
        if event.event_type is ExecutionEventType.EXPENSE:
            if event.amount_cents is None:
                raise ExecutionReplanContextError(
                    "S2_T021_EXPENSE_AMOUNT_REQUIRED",
                    f"events[{index}].amountCents",
                    "EXPENSE event requires amountCents",
                )
            actual_spent_cents += event.amount_cents
            continue
        frozen_indexes.add(event_index)
        if (
            event.event_type is ExecutionEventType.START
            and event.task_id == adjustment.task_id
        ):
            started_source = True
        if event.event_type in {ExecutionEventType.COMPLETE, ExecutionEventType.SKIP}:
            previous = terminal_by_task.get(event.task_id)
            if previous is not None and previous is not event.event_type:
                raise ExecutionReplanContextError(
                    "S2_T021_TERMINAL_EVENT_CONFLICT",
                    f"events[{index}].eventType",
                    "one task cannot be both COMPLETE and SKIP",
                )
            terminal_by_task[event.task_id] = event.event_type
            if event.task_id == adjustment.task_id:
                terminal_source = True

    if terminal_source:
        raise ExecutionReplanContextError(
            "S2_T021_EVENT_TASK_TERMINAL",
            "adjustment.taskId",
            "a completed or skipped task cannot be the adjustment source",
        )
    if not started_source:
        raise ExecutionReplanContextError(
            "S2_T021_EVENT_TASK_NOT_STARTED",
            "adjustment.taskId",
            "the confirmed adjustment must refer to an officially started task",
        )

    for index, task_id in enumerate(locked_task_ids):
        locked_index = task_index.get(task_id)
        if locked_index is None:
            raise ExecutionReplanContextError(
                "S2_T021_LOCKED_TASK_NOT_FOUND",
                f"lockedTaskIds[{index}]",
                "locked task is absent from CURRENT",
            )
        frozen_indexes.add(locked_index)

    prefix_length = max(frozen_indexes) + 1
    if prefix_length >= len(tasks):
        raise ExecutionReplanContextError(
            "S2_T021_SUFFIX_EMPTY",
            "adjustment.taskId",
            "no unfinished suffix remains after freezing the current task",
        )
    frozen_task_ids = tuple(task.task_id for task in tasks[:prefix_length])

    if adjustment.event_type is ExecutionAdjustmentType.LATE:
        day_end = current_request.trip.days[0].time_window.end
        anchor_end = facts[prefix_length - 1].end_at
        remaining = max(0, _minute_of_day(day_end) - _minute_of_day(anchor_end))
        context = RemainingConstraintContext(remaining_time_minutes=remaining)
    else:
        remaining_tasks = tasks[prefix_length:]
        remaining_facts = facts[prefix_length:]
        planned_remaining_walk = sum(task.walk_meters for task in remaining_tasks)
        frozen_walk = sum(task.walk_meters for task in tasks[:prefix_length])

        daily_caps = [
            profile.walk_limits.max_daily_meters
            for participant in current_request.trip.participants
            if (profile := participant.assistance_profile) is not None
            and profile.walk_limits.max_daily_meters is not None
        ]
        if daily_caps:
            remaining_walk = min(
                planned_remaining_walk,
                max(0, min(daily_caps) - frozen_walk),
            )
        else:
            remaining_walk = planned_remaining_walk

        segment_caps = [
            profile.walk_limits.max_continuous_meters
            for participant in current_request.trip.participants
            if (profile := participant.assistance_profile) is not None
            and profile.walk_limits.max_continuous_meters is not None
        ]
        planned_max_segment = max(task.walk_meters for task in remaining_tasks)
        max_segment = min(segment_caps) if segment_caps else planned_max_segment
        max_segment = max(1, min(max_segment, max(1, remaining_walk)))

        rest_caps = [
            profile.rest_interval
            for participant in current_request.trip.participants
            if (profile := participant.assistance_profile) is not None
            and profile.rest_interval is not None
        ]
        day = current_request.trip.days[0]
        day_minutes = max(
            1,
            _minute_of_day(day.time_window.end)
            - _minute_of_day(day.time_window.start),
        )
        rest_interval = min(rest_caps) if rest_caps else day_minutes
        # Ensure the restored facts are still meaningful for the derived baseline.
        if not remaining_facts:
            raise ExecutionReplanContextError(
                "S2_T021_SUFFIX_FACTS_EMPTY",
                "currentFacts.taskFacts",
                "no trusted facts remain after the frozen prefix",
            )
        context = RemainingConstraintContext(
            remaining_walk_budget_meters=remaining_walk,
            max_segment_walk_meters=max_segment,
            rest_interval_minutes=rest_interval,
        )

    return ExecutionReplanProjection(
        frozen_task_ids=frozen_task_ids,
        actual_spent_cents=actual_spent_cents,
        remaining_context=context,
    )


def _minute_of_day(value: time) -> int:
    return value.hour * 60 + value.minute


__all__ = [
    "ExecutionReplanContextError",
    "ExecutionReplanProjection",
    "project_execution_adjustment",
]
