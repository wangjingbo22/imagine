from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from app.application.collaboration_ports import PlanningAccess
from app.application.plan_service import PlanVersionService
from app.application.planning_boundary_service import PlanningBoundaryService
from app.infrastructure.bailian_replan_explanation import ReplanExplanationError
from app.schemas.execution_replan import (
    DifferenceExplanationStatus,
    DifferenceExplanationView,
    ExecutionAdjustmentDecisionRequest,
    ExecutionAdjustmentDecisionView,
    ExecutionAdjustmentReplanPreview,
    ExecutionAdjustmentReplanRequest,
)
from app.schemas.plan import PlanVersionDiff
from app.schemas.replan_explanation import ReplanDifferenceExplanation


class ReplanExplanationGateway(Protocol):
    async def explain(
        self,
        diff: PlanVersionDiff,
    ) -> ReplanDifferenceExplanation: ...


class ExecutionReplanService:
    """S2-T021/T022 orchestration; the model never controls plan state."""

    def __init__(
        self,
        *,
        planning_service: PlanningBoundaryService,
        plan_service: PlanVersionService,
        explanation_gateway: ReplanExplanationGateway | None = None,
    ) -> None:
        self.planning_service = planning_service
        self.plan_service = plan_service
        self.explanation_gateway = explanation_gateway

    async def create_preview(
        self,
        trip_id: UUID,
        request: ExecutionAdjustmentReplanRequest,
        *,
        access: PlanningAccess,
    ) -> ExecutionAdjustmentReplanPreview:
        generated = self.planning_service.generate_v2_from_adjustment(
            trip_id,
            request,
            access=access,
        )
        candidate = generated.replan.plan
        # Candidate and Diff are frozen before any best-effort model call.
        diff = self.plan_service.get_diff(trip_id, candidate.plan_id)
        explanation = await self._explain(diff, requested=request.explain_differences)
        return ExecutionAdjustmentReplanPreview(
            current_plan_id=generated.current_plan_id,
            candidate_plan=candidate,
            diff=diff,
            event_constraints=generated.event_constraints,
            derived_context=generated.derived_context,
            frozen_task_ids=generated.replan.frozen_task_ids,
            assessments=generated.replan.assessments,
            validation_report=generated.replan.validation_report,
            explanation=explanation,
        )

    def decide(
        self,
        trip_id: UUID,
        plan_id: UUID,
        request: ExecutionAdjustmentDecisionRequest,
        *,
        access: PlanningAccess,
    ) -> ExecutionAdjustmentDecisionView:
        # Evidence revalidation and the state transition share one readiness
        # lease, so requirements cannot change between the two operations.
        result = self.planning_service.decide_adjustment_v2(
            trip_id,
            plan_id,
            decision=request.decision,
            access=access,
        )
        return ExecutionAdjustmentDecisionView(result=result)

    async def _explain(
        self,
        diff: PlanVersionDiff,
        *,
        requested: bool,
    ) -> DifferenceExplanationView:
        if not requested:
            return DifferenceExplanationView(
                status=DifferenceExplanationStatus.NOT_REQUESTED,
            )
        if self.explanation_gateway is None:
            return DifferenceExplanationView(
                status=DifferenceExplanationStatus.UNAVAILABLE,
                degraded_reason="EXPLAINER_NOT_CONFIGURED",
            )
        try:
            value = await self.explanation_gateway.explain(diff)
            safe = ReplanDifferenceExplanation.model_validate_json(
                value.model_dump_json(by_alias=True, warnings="error"),
                strict=True,
            )
        except ReplanExplanationError as error:
            return DifferenceExplanationView(
                status=DifferenceExplanationStatus.UNAVAILABLE,
                degraded_reason=error.code,
            )
        except (AttributeError, TypeError, ValueError, ValidationError):
            return DifferenceExplanationView(
                status=DifferenceExplanationStatus.UNAVAILABLE,
                degraded_reason="EXPLAINER_INVALID_RESULT",
            )
        except Exception:
            # Provider/network failures never get authority over structured data.
            return DifferenceExplanationView(
                status=DifferenceExplanationStatus.UNAVAILABLE,
                degraded_reason="EXPLAINER_FAILED",
            )
        return DifferenceExplanationView(
            status=DifferenceExplanationStatus.GENERATED,
            summary=safe.summary,
            model=safe.model,
        )


__all__ = [
    "ExecutionReplanService",
    "ReplanExplanationGateway",
]
