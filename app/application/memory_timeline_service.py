from __future__ import annotations

from uuid import UUID

from app.application.plan_service import PlanVersionService
from app.application.workflow_service import WorkflowService
from app.core.errors import AppError
from app.infrastructure.memory_media_reader import SqliteMemoryMediaReader
from app.schemas.execution import ExecutionEventType
from app.schemas.memory_timeline import (
    MemoryPhoto,
    MemoryTimeline,
    MemoryTimelineItem,
    MemoryTimelineItemKind,
    MemoryTimelineSummary,
)
from app.schemas.plan import PlanVersion, PlanVersionStatus
from app.schemas.workflow import ConstraintProfileState, ConstraintProfileStatus


_KIND_ORDER = {
    MemoryTimelineItemKind.PLAN_VERSION: 0,
    MemoryTimelineItemKind.CARE_CONFIRMED: 1,
    MemoryTimelineItemKind.TASK_STARTED: 2,
    MemoryTimelineItemKind.EXPENSE: 3,
    MemoryTimelineItemKind.TASK_COMPLETED: 4,
    MemoryTimelineItemKind.TASK_SKIPPED: 5,
    MemoryTimelineItemKind.PHOTO: 6,
}


class MemoryTimelineService:
    def __init__(
        self,
        *,
        workflow_service: WorkflowService,
        plan_service: PlanVersionService,
        media_reader: SqliteMemoryMediaReader,
    ) -> None:
        self._workflow_service = workflow_service
        self._plan_service = plan_service
        self._media_reader = media_reader

    def get(self, trip_id: UUID) -> MemoryTimeline:
        execution_summary = self._workflow_service.get_summary(trip_id)
        versions = self._plan_service.list_plan_versions(trip_id)
        current = next(
            plan for plan in versions if plan.status is PlanVersionStatus.CURRENT
        )
        care = self._optional_care(trip_id)
        photos = self._media_reader.list_active(trip_id)
        total_tasks = execution_summary.total_tasks
        completed_count = len(execution_summary.completed_task_ids)
        completion_rate = self._completion_rate(completed_count, total_tasks)

        items: list[MemoryTimelineItem] = []
        task_titles = self._task_titles(versions)
        for plan in versions:
            items.append(
                MemoryTimelineItem(
                    item_id=f"plan:{plan.plan_id}",
                    kind=MemoryTimelineItemKind.PLAN_VERSION,
                    occurred_at=plan.confirmed_at or plan.created_at,
                    title=f"行程方案 V{plan.version}：{plan.status.value}",
                    plan_version_id=plan.plan_id,
                    plan_version=plan.version,
                    plan_status=plan.status,
                    amount_cents=plan.metrics.total_cost_cents,
                )
            )

        if (
            care is not None
            and care.status is ConstraintProfileStatus.CONSTRAINT_CONFIRMED
            and care.confirmed_at is not None
        ):
            items.append(
                MemoryTimelineItem(
                    item_id=f"care:{trip_id}",
                    kind=MemoryTimelineItemKind.CARE_CONFIRMED,
                    occurred_at=care.confirmed_at,
                    title="关怀约束已确认",
                    assistance_profile=care.assistance_profile,
                )
            )

        completed_so_far: set[str] = set()
        actual_cost_so_far = 0
        events = sorted(
            execution_summary.events,
            key=lambda event: (event.occurred_at, str(event.event_id)),
        )
        for event in events:
            if event.event_type is ExecutionEventType.START:
                kind = MemoryTimelineItemKind.TASK_STARTED
                title = f"开始：{task_titles.get(event.task_id, event.task_id)}"
            elif event.event_type is ExecutionEventType.COMPLETE:
                kind = MemoryTimelineItemKind.TASK_COMPLETED
                completed_so_far.add(event.task_id)
                title = f"完成：{task_titles.get(event.task_id, event.task_id)}"
            elif event.event_type is ExecutionEventType.SKIP:
                kind = MemoryTimelineItemKind.TASK_SKIPPED
                title = f"跳过：{task_titles.get(event.task_id, event.task_id)}"
            else:
                kind = MemoryTimelineItemKind.EXPENSE
                actual_cost_so_far += event.amount_cents or 0
                title = f"费用：{task_titles.get(event.task_id, event.task_id)}"

            items.append(
                MemoryTimelineItem(
                    item_id=f"event:{event.event_id}",
                    kind=kind,
                    occurred_at=event.occurred_at,
                    title=title,
                    task_id=event.task_id,
                    event_id=event.event_id,
                    event_type=event.event_type,
                    plan_version_id=event.plan_version_id,
                    amount_cents=event.amount_cents,
                    cumulative_actual_cost_cents=(
                        actual_cost_so_far
                        if event.event_type is ExecutionEventType.EXPENSE
                        else None
                    ),
                    completion_rate_percent=(
                        self._completion_rate(
                            len(completed_so_far),
                            total_tasks,
                        )
                        if event.event_type is ExecutionEventType.COMPLETE
                        else None
                    ),
                )
            )

        for photo in photos:
            items.append(
                MemoryTimelineItem(
                    item_id=f"photo:{photo.media_id}",
                    kind=MemoryTimelineItemKind.PHOTO,
                    occurred_at=photo.created_at,
                    title=f"照片：{task_titles.get(photo.task_id, photo.task_id)}",
                    task_id=photo.task_id,
                    photo=MemoryPhoto(
                        media_id=photo.media_id,
                        task_id=photo.task_id,
                        data_url=photo.data_url,
                        mime_type=photo.mime_type,
                        byte_size=photo.byte_size,
                        created_at=photo.created_at,
                    ),
                )
            )

        items.sort(
            key=lambda item: (
                item.occurred_at,
                _KIND_ORDER[item.kind],
                item.item_id,
            )
        )
        return MemoryTimeline(
            trip_id=trip_id,
            summary=MemoryTimelineSummary(
                completed_task_count=completed_count,
                skipped_task_count=len(execution_summary.skipped_task_ids),
                total_task_count=total_tasks,
                completion_rate_percent=completion_rate,
                planned_cost_cents=execution_summary.planned_cost_cents,
                actual_cost_cents=execution_summary.actual_cost_cents,
                cost_difference_cents=execution_summary.difference_cents,
                currency=current.trip_snapshot.currency,
                current_plan_version=current.version,
                plan_change_count=max(0, len(versions) - 1),
                photo_count=len(photos),
                assistance_profile=(
                    care.assistance_profile if care is not None else None
                ),
            ),
            items=items,
        )

    def _optional_care(self, trip_id: UUID) -> ConstraintProfileState | None:
        try:
            return self._workflow_service.get_constraints(trip_id)
        except AppError as error:
            if error.code == "CONSTRAINT_PROFILE_NOT_FOUND":
                return None
            raise

    @staticmethod
    def _task_titles(versions: list[PlanVersion]) -> dict[str, str]:
        return {
            task.task_id: task.title
            for plan in versions
            for task in plan.days[0].tasks
        }

    @staticmethod
    def _completion_rate(completed: int, total: int) -> float:
        if total == 0:
            return 0.0
        return round(min(100.0, completed * 100 / total), 2)


__all__ = ["MemoryTimelineService"]
