from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, UUID4, model_validator

from app.schemas.plan import ProposedPlanVersion
from app.schemas.trip import ContractModel
from app.services.route_risk import ValidationStatus


NonBlankText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ReplanRuleDomain(str, Enum):
    BUDGET = "BUDGET"
    TIME = "TIME"
    ROUTE = "ROUTE"
    CARE = "CARE"


class ReplanRuleCheck(ContractModel):
    """One deterministic T011 validation fact consumed by T018."""

    rule_id: Annotated[str, Field(min_length=1, max_length=120)]
    domain: ReplanRuleDomain
    hardness: Literal["HARD", "SOFT"]
    status: ValidationStatus
    relaxable: bool = False
    relaxation_hint: Annotated[str, Field(min_length=1, max_length=300)] | None = None

    @model_validator(mode="after")
    def validate_relaxation_hint(self) -> "ReplanRuleCheck":
        if self.relaxable and self.relaxation_hint is None:
            raise ValueError("relaxable checks require relaxationHint")
        if not self.relaxable and self.relaxation_hint is not None:
            raise ValueError("non-relaxable checks cannot provide relaxationHint")
        return self


class ReplanValidationReport(ContractModel):
    """Candidate-scoped budget/time/route/care revalidation report."""

    candidate_plan_id: UUID4
    checks: tuple[ReplanRuleCheck, ...] = Field(min_length=1)


class ReplanCandidate(ContractModel):
    """T017 candidate plus its deterministic preference-loss score."""

    plan: ProposedPlanVersion
    satisfaction_loss: Annotated[int, Field(ge=0)]


class RelaxationOption(ContractModel):
    candidate_plan_id: UUID4
    rule_id: Annotated[str, Field(min_length=1, max_length=120)]
    domain: ReplanRuleDomain
    description: Annotated[str, Field(min_length=1, max_length=300)]


class CandidateAssessment(ContractModel):
    candidate_plan_id: UUID4
    feasible: bool
    rank: Annotated[int | None, Field(ge=1)] = None
    modified_task_count: Annotated[int | None, Field(ge=0)] = None
    satisfaction_loss: Annotated[int, Field(ge=0)]
    tie_break_key: Annotated[
        str,
        Field(pattern=r"^[0-9a-f]{64}$"),
    ]
    affected_rule_ids: tuple[NonBlankText, ...] = ()

    @model_validator(mode="after")
    def validate_rank(self) -> "CandidateAssessment":
        if self.feasible and (self.rank is None or self.modified_task_count is None):
            raise ValueError("feasible candidate assessments require rank and modification count")
        if not self.feasible and self.rank is not None:
            raise ValueError("infeasible candidate assessments cannot have a rank")
        return self


class SelectedReplan(ContractModel):
    status: Literal["SELECTED"] = "SELECTED"
    selected_plan: ProposedPlanVersion
    frozen_task_ids: tuple[NonBlankText, ...]
    assessments: tuple[CandidateAssessment, ...]
    validation_report: ReplanValidationReport


class NoFeasibleReplan(ContractModel):
    status: Literal["NO_FEASIBLE_CANDIDATE"] = "NO_FEASIBLE_CANDIDATE"
    selected_plan: None = None
    frozen_task_ids: tuple[NonBlankText, ...]
    assessments: tuple[CandidateAssessment, ...]
    affected_rule_ids: tuple[NonBlankText, ...]
    relaxations: tuple[RelaxationOption, ...]


ReplanOutcome = SelectedReplan | NoFeasibleReplan


__all__ = [
    "CandidateAssessment",
    "NoFeasibleReplan",
    "RelaxationOption",
    "ReplanCandidate",
    "ReplanOutcome",
    "ReplanRuleCheck",
    "ReplanRuleDomain",
    "ReplanValidationReport",
    "SelectedReplan",
]
