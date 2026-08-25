from __future__ import annotations

from uuid import UUID

from app.core.errors import AppError
from app.infrastructure.plan_store import PlanStoreError
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.schemas.execution import CreateExecutionEvent, ExecutionEvent
from app.schemas.trip import AssistanceProfile
from app.schemas.workflow import (
    ConstraintConfirmationResult,
    ConstraintProfileState,
    TripExecutionSummary,
)


class WorkflowService:
    def __init__(self, repository: SqliteWorkflowRepository) -> None:
        self.repository = repository

    @staticmethod
    def _as_app_error(error: PlanStoreError) -> AppError:
        if error.code in {
            "TRIP_NOT_FOUND",
            "CONSTRAINT_PROFILE_NOT_FOUND",
            "EVENT_TASK_NOT_FOUND",
        }:
            status = 404
        else:
            status = 409
        return AppError(
            code=error.code,
            message=error.message,
            http_status=status,
            retryable=False,
        )

    def save_constraint_draft(
        self,
        trip_id: UUID,
        profile: AssistanceProfile,
    ) -> ConstraintProfileState:
        try:
            return self.repository.save_constraint_draft(trip_id, profile)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def confirm_constraints(self, trip_id: UUID) -> ConstraintConfirmationResult:
        try:
            return self.repository.confirm_constraints(trip_id)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def get_constraints(self, trip_id: UUID) -> ConstraintProfileState:
        try:
            return self.repository.get_constraints(trip_id)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def require_constraint_confirmed(
        self,
        trip_id: UUID,
        profile: AssistanceProfile | None,
    ) -> None:
        try:
            self.repository.require_constraint_confirmed(trip_id, profile)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def create_event(
        self,
        trip_id: UUID,
        request: CreateExecutionEvent,
    ) -> ExecutionEvent:
        try:
            return self.repository.create_event(trip_id, request)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def list_events(self, trip_id: UUID) -> list[ExecutionEvent]:
        return self.repository.list_events(trip_id)

    def get_summary(self, trip_id: UUID) -> TripExecutionSummary:
        try:
            return self.repository.get_summary(trip_id)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error
