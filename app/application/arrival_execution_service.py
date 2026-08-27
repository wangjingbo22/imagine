from __future__ import annotations

from uuid import UUID

from app.application.arrival_decision_service import ArrivalDecisionService
from app.application.workflow_service import WorkflowService
from app.core.errors import AppError
from app.schemas.arrival_decision import (
    ArrivalDecisionRequest,
    ArrivalDecisionResult,
    LocationAttemptOutcome,
)
from app.schemas.arrival_execution import CreateArrivalExecutionEventRequest
from app.schemas.execution import (
    ArrivalEvidenceSnapshot,
    CreateArrivalExecutionEvent,
    ExecutionEvent,
    ExecutionEventType,
)


class ArrivalExecutionService:
    """Converts a verified ARRIVED decision into the unified event stream."""

    def __init__(
        self,
        decision_service: ArrivalDecisionService,
        workflow_service: WorkflowService,
    ) -> None:
        self._decision_service = decision_service
        self._workflow_service = workflow_service

    def complete_from_arrival(
        self,
        trip_id: UUID,
        request: CreateArrivalExecutionEventRequest,
    ) -> ExecutionEvent:
        decision = self._decision_service.assess(
            trip_id,
            ArrivalDecisionRequest(
                task_id=request.task_id,
                target_location=request.target_location,
                attempt_outcome=LocationAttemptOutcome.EVIDENCE,
                source=request.source,
                arrival_evidence_id=request.arrival_evidence_id,
            ),
        )
        if decision.result is not ArrivalDecisionResult.ARRIVED:
            raise AppError(
                code="ARRIVAL_CONFIRMATION_REQUIRED",
                message="定位证据未达到自动完成任务条件",
                http_status=409,
                retryable=False,
                errors=[
                    {
                        "path": "arrivalDecision",
                        "code": decision.result.value,
                        "message": decision.message,
                    }
                ],
            )
        assert decision.arrival_evidence_id is not None
        assert decision.distance_meters is not None
        assert decision.accuracy is not None
        return self._workflow_service.create_arrival_event(
            trip_id,
            CreateArrivalExecutionEvent(
                task_id=request.task_id,
                plan_version_id=request.plan_version_id,
                event_type=ExecutionEventType.COMPLETE,
                idempotency_key=request.idempotency_key,
                occurred_at=request.occurred_at,
                arrival_evidence=ArrivalEvidenceSnapshot(
                    evidence_id=decision.arrival_evidence_id,
                    distance_meters=decision.distance_meters,
                    accuracy=decision.accuracy,
                    result=decision.result,
                    source=decision.source,
                    reason_code="WITHIN_ARRIVAL_THRESHOLD",
                ),
            ),
        )

    def restore(self, trip_id: UUID) -> list[ExecutionEvent]:
        return self._workflow_service.list_events(trip_id)


__all__ = ["ArrivalExecutionService"]
