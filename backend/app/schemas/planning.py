from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.schemas.plan import PlanVersion, PlanVersionReason
from app.schemas.trip import ContractModel
from app.services.planning.models import CandidatePlanRequest
from app.services.replanning.models import (
    CandidateAssessment,
    ReplanValidationReport,
)


class ReplanRequestCandidate(ContractModel):
    """One server-generated V2 alternative and its user-preference loss."""

    request: CandidatePlanRequest
    satisfaction_loss: Annotated[int, Field(ge=0)]


class ReplanGenerationRequest(ContractModel):
    """Strict HTTP input for server-side T011 + T018 replanning."""

    schema_version: Literal["1.0"]
    reason: PlanVersionReason
    locked_task_ids: tuple[
        Annotated[str, Field(min_length=1, max_length=64)], ...
    ] = ()
    candidates: tuple[ReplanRequestCandidate, ...] = Field(
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def validate_replan_request(self) -> "ReplanGenerationRequest":
        if self.reason is PlanVersionReason.INITIAL_PLAN:
            raise ValueError("Plan V2 reason cannot be INITIAL_PLAN")
        if len(self.locked_task_ids) != len(set(self.locked_task_ids)):
            raise ValueError("lockedTaskIds must be unique")
        return self


class RegisteredReplan(ContractModel):
    """A T018-selected V2 after it has been registered as PROPOSED."""

    outcome: Literal["SELECTED"] = "SELECTED"
    plan: PlanVersion
    disruption_score: Annotated[int, Field(ge=0)]
    satisfaction_loss: Annotated[int, Field(ge=0)]
    frozen_task_ids: tuple[str, ...]
    assessments: tuple[CandidateAssessment, ...]
    validation_report: ReplanValidationReport


__all__ = [
    "RegisteredReplan",
    "ReplanGenerationRequest",
    "ReplanRequestCandidate",
]
