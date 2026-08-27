from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.core.errors import AppError
from app.infrastructure.plan_store import PlanStoreError, SqlitePlanVersionRepository
from app.schemas.plan import (
    ExecutionStartResult,
    PlanTransitionResult,
    PlanV2DecisionResult,
    PlanVersion,
    PlanVersionDiff,
    ProposedPlanVersion,
    TripPlanState,
)

if TYPE_CHECKING:
    from app.application.workflow_service import WorkflowService


class PlanVersionService:
    """Application boundary for immutable PlanVersion and state decisions."""

    def __init__(
        self,
        repository: SqlitePlanVersionRepository,
        workflow_service: WorkflowService | None = None,
    ) -> None:
        self.repository = repository
        self.workflow_service = workflow_service

    @staticmethod
    def _as_app_error(error: PlanStoreError) -> AppError:
        if error.code in {
            "TRIP_NOT_FOUND",
            "PLAN_VERSION_NOT_FOUND",
            "PLAN_PARENT_NOT_FOUND",
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

    def register_proposed(self, proposal: ProposedPlanVersion) -> PlanVersion:
        if self.workflow_service is not None and proposal.version == 1:
            self.workflow_service.require_constraint_confirmed(
                proposal.trip_snapshot.trip_id,
                proposal.trip_snapshot.participants[0].assistance_profile,
            )
        try:
            return self.repository.register_proposed(proposal)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def confirm(self, trip_id: UUID, plan_id: UUID) -> PlanTransitionResult:
        try:
            return self.repository.confirm(trip_id, plan_id)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def start_execution(self, trip_id: UUID) -> ExecutionStartResult:
        try:
            return self.repository.start_execution(trip_id)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def get_diff(self, trip_id: UUID, plan_id: UUID) -> PlanVersionDiff:
        try:
            return self.repository.get_diff(trip_id, plan_id)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def accept_v2(self, trip_id: UUID, plan_id: UUID) -> PlanV2DecisionResult:
        try:
            return self.repository.accept_v2(trip_id, plan_id)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def reject_v2(self, trip_id: UUID, plan_id: UUID) -> PlanV2DecisionResult:
        try:
            return self.repository.reject_v2(trip_id, plan_id)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def get_plan_version(self, trip_id: UUID, plan_id: UUID) -> PlanVersion:
        try:
            return self.repository.get_plan_version(trip_id, plan_id)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def list_plan_versions(self, trip_id: UUID) -> list[PlanVersion]:
        try:
            return self.repository.list_plan_versions(trip_id)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error

    def get_trip_state(self, trip_id: UUID) -> TripPlanState:
        try:
            state = self.repository.get_trip_state(trip_id)
            if self.workflow_service is None:
                return state
            return state.model_copy(
                update={
                    "events": self.workflow_service.list_events(trip_id),
                    "actual_budget": (
                        self.workflow_service.get_budget_summary(trip_id)
                        if state.current_plan is not None
                        else None
                    ),
                }
            )
        except PlanStoreError as error:
            raise self._as_app_error(error) from error
