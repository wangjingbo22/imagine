from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.schemas.execution import ExecutionEvent, ExecutionEventType
from app.schemas.plan import PlanVersion, PlanVersionStatus, ProposedPlanVersion
from app.schemas.workflow import TripExecutionSummary


class SummaryTraceError(ValueError):
    """Raised when a summary number cannot be reproduced from persisted facts."""


@dataclass(frozen=True, slots=True)
class SummaryNumberTrace:
    """Stable references that explain one integer in the public summary JSON."""

    path: str
    value: int
    task_ids: tuple[str, ...]
    event_ids: tuple[UUID, ...]
    plan_version_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if not self.plan_version_ids:
            raise SummaryTraceError(f"{self.path} has no planVersionId evidence")


def _unique_strings(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _unique_uuids(values: list[UUID]) -> tuple[UUID, ...]:
    return tuple(sorted(set(values), key=str))


def _expense_events(events: list[ExecutionEvent]) -> list[ExecutionEvent]:
    return [event for event in events if event.event_type is ExecutionEventType.EXPENSE]


def _task_ids_by_plan(
    summary: TripExecutionSummary,
    current_plan: PlanVersion,
    plan_versions: Sequence[ProposedPlanVersion],
) -> dict[UUID, set[str]]:
    plans_by_id: dict[UUID, ProposedPlanVersion] = {}
    for plan in plan_versions:
        if not isinstance(plan, ProposedPlanVersion):
            raise SummaryTraceError("planVersions must contain PlanVersion snapshots")
        if plan.plan_id in plans_by_id:
            raise SummaryTraceError("planVersions contains a duplicate planId")
        if plan.trip_snapshot.trip_id != summary.trip_id:
            raise SummaryTraceError("historical PlanVersion belongs to another trip")
        plans_by_id[plan.plan_id] = plan

    history_by_id = {item.plan_id: item for item in summary.plan_history}
    if len(history_by_id) != len(summary.plan_history):
        raise SummaryTraceError("planHistory contains a duplicate planId")
    if set(plans_by_id) != set(history_by_id):
        raise SummaryTraceError("planVersions must exactly cover planHistory")

    for plan_id, item in history_by_id.items():
        if plans_by_id[plan_id].version != item.version:
            raise SummaryTraceError("historical PlanVersion identity is inconsistent")

    persisted_current = plans_by_id.get(current_plan.plan_id)
    if persisted_current is None:
        raise SummaryTraceError("current PlanVersion snapshot is absent from planVersions")
    current_payload = current_plan.model_dump(
        exclude={"status", "created_at", "confirmed_at"}
    )
    if persisted_current.model_dump(
        exclude={"status", "created_at", "confirmed_at"}
    ) != current_payload:
        raise SummaryTraceError("current PlanVersion snapshot is inconsistent")

    return {
        plan_id: {task.task_id for task in plan.days[0].tasks}
        for plan_id, plan in plans_by_id.items()
    }


def _validate_summary(
    summary: TripExecutionSummary,
    current_plan: PlanVersion,
    plan_versions: Sequence[ProposedPlanVersion],
) -> tuple[list[str], list[ExecutionEvent]]:
    if summary.trip_id != current_plan.trip_snapshot.trip_id:
        raise SummaryTraceError("summary tripId does not match the current PlanVersion")

    current_history = [
        item for item in summary.plan_history if item.status is PlanVersionStatus.CURRENT
    ]
    if len(current_history) != 1:
        raise SummaryTraceError("summary must contain exactly one CURRENT PlanVersion")
    if (
        current_history[0].plan_id != current_plan.plan_id
        or current_history[0].version != current_plan.version
        or summary.current_plan_version != current_plan.version
    ):
        raise SummaryTraceError("current PlanVersion identity is inconsistent")

    current_task_ids = [task.task_id for task in current_plan.days[0].tasks]
    if summary.planned_cost_cents != current_plan.metrics.total_cost_cents:
        raise SummaryTraceError("plannedCostCents does not match the current PlanVersion")
    if summary.total_tasks != len(current_task_ids):
        raise SummaryTraceError("totalTasks does not match the current PlanVersion")

    task_ids_by_plan = _task_ids_by_plan(summary, current_plan, plan_versions)
    for event in summary.events:
        if event.trip_id != summary.trip_id:
            raise SummaryTraceError("event tripId does not match the summary")
        plan_task_ids = task_ids_by_plan.get(event.plan_version_id)
        if plan_task_ids is None:
            raise SummaryTraceError("event references a PlanVersion absent from planHistory")
        if event.task_id not in plan_task_ids:
            raise SummaryTraceError(
                "event taskId does not belong to its referenced PlanVersion"
            )

    expense_events = _expense_events(summary.events)
    actual_cost = sum(event.amount_cents or 0 for event in expense_events)
    if summary.actual_cost_cents != actual_cost:
        raise SummaryTraceError("actualCostCents does not match EXPENSE events")
    if summary.difference_cents != actual_cost - summary.planned_cost_cents:
        raise SummaryTraceError("differenceCents is not actual minus planned")

    completed = sorted(
        {
            event.task_id
            for event in summary.events
            if event.event_type is ExecutionEventType.COMPLETE
        }
    )
    skipped = sorted(
        {
            event.task_id
            for event in summary.events
            if event.event_type is ExecutionEventType.SKIP
        }
    )
    if summary.completed_task_ids != completed:
        raise SummaryTraceError("completedTaskIds does not match COMPLETE events")
    if summary.skipped_task_ids != skipped:
        raise SummaryTraceError("skippedTaskIds does not match SKIP events")
    if set(completed) & set(skipped):
        raise SummaryTraceError("one task cannot be both completed and skipped")

    return current_task_ids, expense_events


def trace_summary_numbers(
    summary: TripExecutionSummary,
    current_plan: PlanVersion,
    plan_versions: Sequence[ProposedPlanVersion],
) -> tuple[SummaryNumberTrace, ...]:
    """Reproduce every integer exposed by ``TripExecutionSummary``.

    The adapter is intentionally read-only. It consumes the real summary response
    plus every immutable PlanVersion snapshot in ``planHistory``, and emits
    task/event/plan identifiers for every public numeric field, including nested
    event amounts and history versions. A mismatch fails closed instead of
    producing partial evidence.
    """

    current_task_ids, expense_events = _validate_summary(
        summary,
        current_plan,
        plan_versions,
    )
    current_plan_ids = (current_plan.plan_id,)
    expense_task_ids = _unique_strings([event.task_id for event in expense_events])
    expense_event_ids = _unique_uuids([event.event_id for event in expense_events])
    expense_plan_ids = _unique_uuids(
        [event.plan_version_id for event in expense_events] + [current_plan.plan_id]
    )

    traces: list[SummaryNumberTrace] = [
        SummaryNumberTrace(
            path="plannedCostCents",
            value=summary.planned_cost_cents,
            task_ids=tuple(current_task_ids),
            event_ids=(),
            plan_version_ids=current_plan_ids,
        ),
        SummaryNumberTrace(
            path="actualCostCents",
            value=summary.actual_cost_cents,
            task_ids=expense_task_ids,
            event_ids=expense_event_ids,
            plan_version_ids=expense_plan_ids,
        ),
        SummaryNumberTrace(
            path="differenceCents",
            value=summary.difference_cents,
            task_ids=_unique_strings(current_task_ids + list(expense_task_ids)),
            event_ids=expense_event_ids,
            plan_version_ids=expense_plan_ids,
        ),
        SummaryNumberTrace(
            path="totalTasks",
            value=summary.total_tasks,
            task_ids=tuple(current_task_ids),
            event_ids=(),
            plan_version_ids=current_plan_ids,
        ),
        SummaryNumberTrace(
            path="currentPlanVersion",
            value=summary.current_plan_version,
            task_ids=(),
            event_ids=(),
            plan_version_ids=current_plan_ids,
        ),
    ]

    for index, item in enumerate(summary.plan_history):
        traces.append(
            SummaryNumberTrace(
                path=f"planHistory[{index}].version",
                value=item.version,
                task_ids=(),
                event_ids=(),
                plan_version_ids=(item.plan_id,),
            )
        )

    for index, event in enumerate(summary.events):
        if event.amount_cents is None:
            continue
        traces.append(
            SummaryNumberTrace(
                path=f"events[{index}].amountCents",
                value=event.amount_cents,
                task_ids=(event.task_id,),
                event_ids=(event.event_id,),
                plan_version_ids=(event.plan_version_id,),
            )
        )

    paths = [trace.path for trace in traces]
    if len(paths) != len(set(paths)):
        raise SummaryTraceError("numeric trace paths must be unique")
    return tuple(traces)


__all__ = [
    "SummaryNumberTrace",
    "SummaryTraceError",
    "trace_summary_numbers",
]
