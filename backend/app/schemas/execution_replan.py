from __future__ import annotations

from enum import Enum
import re
from typing import Annotated, Literal
from pydantic import Field, UUID4, model_validator

from app.domain.collaboration import TripFlowKind
from app.schemas.execution_adjustment import (
    ConfirmedExecutionAdjustment,
    EventConstraintSet,
    RemainingConstraintContext,
)
from app.schemas.plan import PlanV2DecisionResult, PlanVersion, PlanVersionDiff
from app.schemas.planning import RegisteredReplan
from app.schemas.trip import ContractModel
from app.services.replanning.models import (
    CandidateAssessment,
    ReplanValidationReport,
)


class ExecutionAdjustmentReplanRequest(ContractModel):
    """Strict S2-T021 command; all planning facts stay server-owned."""

    schema_version: Literal["1.0"]
    adjustment_event_id: UUID4 | None = None
    adjustment: ConfirmedExecutionAdjustment
    locked_task_ids: tuple[
        Annotated[str, Field(min_length=1, max_length=64)], ...
    ] = ()
    explain_differences: bool = True

    @model_validator(mode="after")
    def locked_tasks_must_be_unique(self) -> "ExecutionAdjustmentReplanRequest":
        if len(self.locked_task_ids) != len(set(self.locked_task_ids)):
            raise ValueError("lockedTaskIds must be unique")
        return self


class RegisteredExecutionAdjustmentReplan(ContractModel):
    """T021 output before T022 adds a deterministic Diff and explanation."""

    schema_version: Literal["1.0"] = "1.0"
    current_plan_id: UUID4
    replan: RegisteredReplan
    event_constraints: EventConstraintSet
    derived_context: RemainingConstraintContext


class ExecutionReplanReadinessBinding(ContractModel):
    """Immutable collaboration snapshot bound to an issued adjustment V2."""

    readiness_digest: Annotated[str, Field(min_length=6, max_length=64)]
    current_revision: Annotated[int | None, Field(ge=1)] = None
    flow_kind: TripFlowKind

    @model_validator(mode="after")
    def validate_flow_binding(self) -> "ExecutionReplanReadinessBinding":
        if self.flow_kind is TripFlowKind.LEGACY_SINGLE:
            if self.readiness_digest != "legacy" or self.current_revision is not None:
                raise ValueError("legacy readiness must use digest=legacy and no revision")
        elif (
            self.current_revision is None
            or re.fullmatch(r"[0-9a-f]{64}", self.readiness_digest) is None
        ):
            raise ValueError(
                "collaboration readiness requires a revision and SHA-256 digest"
            )
        return self


class DifferenceExplanationStatus(str, Enum):
    GENERATED = "GENERATED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_REQUESTED = "NOT_REQUESTED"


class DifferenceExplanationView(ContractModel):
    status: DifferenceExplanationStatus
    summary: Annotated[str, Field(min_length=1, max_length=600)] | None = None
    model: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    degraded_reason: Annotated[str, Field(min_length=1, max_length=120)] | None = None

    @model_validator(mode="after")
    def validate_explanation_state(self) -> "DifferenceExplanationView":
        if self.status is DifferenceExplanationStatus.GENERATED:
            if self.summary is None or self.degraded_reason is not None:
                raise ValueError("GENERATED explanation requires only summary")
        elif self.summary is not None or self.model is not None:
            raise ValueError("non-generated explanation cannot carry model output")
        return self


class ExecutionAdjustmentReplanPreview(ContractModel):
    """T022 structured payload; explanation is informational only."""

    schema_version: Literal["1.0"] = "1.0"
    outcome: Literal["SELECTED"] = "SELECTED"
    current_plan_id: UUID4
    current_plan_changed: Literal[False] = False
    candidate_plan: PlanVersion
    diff: PlanVersionDiff
    event_constraints: EventConstraintSet
    derived_context: RemainingConstraintContext
    frozen_task_ids: tuple[str, ...]
    assessments: tuple[CandidateAssessment, ...]
    validation_report: ReplanValidationReport
    explanation: DifferenceExplanationView


class ExecutionAdjustmentDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class ExecutionAdjustmentDecisionRequest(ContractModel):
    schema_version: Literal["1.0"]
    decision: ExecutionAdjustmentDecision


class ExecutionAdjustmentDecisionView(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    result: PlanV2DecisionResult


__all__ = [
    "ExecutionAdjustmentReplanRequest",
    "ExecutionAdjustmentDecision",
    "ExecutionAdjustmentDecisionRequest",
    "ExecutionAdjustmentDecisionView",
    "ExecutionAdjustmentReplanPreview",
    "ExecutionReplanReadinessBinding",
    "DifferenceExplanationStatus",
    "DifferenceExplanationView",
    "RegisteredExecutionAdjustmentReplan",
]
