from __future__ import annotations

import json

from app.schemas.plan import (
    ConstraintSnapshot,
    PlanDiffCategory,
    PlanDiffChangeType,
    PlanDiffItem,
    PlanMetricsDelta,
    PlanVersion,
    PlanVersionDiff,
)


def _change_type(before: object, after: object) -> PlanDiffChangeType:
    return (
        PlanDiffChangeType.RETAINED
        if before == after
        else PlanDiffChangeType.CHANGED
    )


def _care_value(constraint: ConstraintSnapshot) -> str:
    details = json.dumps(
        constraint.details,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        f"{constraint.status.value}｜{constraint.description}｜"
        f"{details}"
    )


def calculate_plan_diff(
    base: PlanVersion,
    candidate: PlanVersion,
) -> PlanVersionDiff:
    """Calculate a deterministic, server-owned V1/V2 comparison."""

    base_tasks = {task.task_id: task for task in base.days[0].tasks}
    candidate_tasks = {task.task_id: task for task in candidate.days[0].tasks}
    ordered_task_ids = [task.task_id for task in base.days[0].tasks]
    ordered_task_ids.extend(
        task.task_id
        for task in candidate.days[0].tasks
        if task.task_id not in base_tasks
    )

    items: list[PlanDiffItem] = []
    fields = (
        (PlanDiffCategory.PLACE, "地点", "title"),
        (PlanDiffCategory.TIME, "时间", "time_range"),
        (PlanDiffCategory.ROUTE, "路线", "transport"),
        (PlanDiffCategory.COST, "费用（分）", "cost_cents"),
    )
    for task_id in ordered_task_ids:
        old = base_tasks.get(task_id)
        new = candidate_tasks.get(task_id)
        if new is not None:
            task_title = new.title
        elif old is not None:
            task_title = old.title
        else:  # The ordered id list is built from one of these two maps.
            continue
        for category, label, field_name in fields:
            before = getattr(old, field_name) if old is not None else None
            after = getattr(new, field_name) if new is not None else None
            if old is None:
                change_type = PlanDiffChangeType.ADDED
            elif new is None:
                change_type = PlanDiffChangeType.REMOVED
            else:
                change_type = _change_type(before, after)
            items.append(
                PlanDiffItem(
                    category=category,
                    change_type=change_type,
                    key=f"task:{task_id}:{field_name}",
                    label=f"{task_title} · {label}",
                    before=before,
                    after=after,
                )
            )

    base_constraints = {
        constraint.rule_id: constraint
        for constraint in base.constraints_snapshot
    }
    candidate_constraints = {
        constraint.rule_id: constraint
        for constraint in candidate.constraints_snapshot
    }
    ordered_rule_ids = list(base_constraints)
    ordered_rule_ids.extend(
        rule_id
        for rule_id in candidate_constraints
        if rule_id not in base_constraints
    )
    for rule_id in ordered_rule_ids:
        old = base_constraints.get(rule_id)
        new = candidate_constraints.get(rule_id)
        before = _care_value(old) if old is not None else None
        after = _care_value(new) if new is not None else None
        if old is None:
            change_type = PlanDiffChangeType.ADDED
        elif new is None:
            change_type = PlanDiffChangeType.REMOVED
        else:
            change_type = _change_type(before, after)
        items.append(
            PlanDiffItem(
                category=PlanDiffCategory.CARE,
                change_type=change_type,
                key=f"constraint:{rule_id}",
                label=f"关怀约束 {rule_id}",
                before=before,
                after=after,
            )
        )

    return PlanVersionDiff(
        trip_id=base.trip_snapshot.trip_id,
        base_plan_id=base.plan_id,
        candidate_plan_id=candidate.plan_id,
        base_version=base.version,
        candidate_version=candidate.version,
        items=items,
        metrics_delta=PlanMetricsDelta(
            total_cost_cents=(
                candidate.metrics.total_cost_cents
                - base.metrics.total_cost_cents
            ),
            total_walk_meters=(
                candidate.metrics.total_walk_meters
                - base.metrics.total_walk_meters
            ),
            transfer_count=(
                candidate.metrics.transfer_count
                - base.metrics.transfer_count
            ),
        ),
    )
