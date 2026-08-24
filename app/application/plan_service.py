from __future__ import annotations

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


class PlanVersionService:
    """Application boundary for immutable PlanVersion and state decisions."""

    def __init__(self, repository: SqlitePlanVersionRepository) -> None:
        self.repository = repository

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

    def get_trip_state(self, trip_id: UUID) -> TripPlanState:
        try:
            return self.repository.get_trip_state(trip_id)
        except PlanStoreError as error:
            raise self._as_app_error(error) from error
