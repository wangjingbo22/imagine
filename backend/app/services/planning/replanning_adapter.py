from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import ValidationError

from app.schemas.execution import ExecutionEvent, ExecutionEventType
from app.schemas.plan import PlanVersion, ProposedPlanVersion
from app.services.replanning.models import (
    ReplanRuleCheck,
    ReplanRuleDomain,
    ReplanValidationReport,
)
from app.services.replanning.selector import (
    ReplanCandidateValidator,
    ReplanningContractError,
)
from app.services.route_risk import ValidationStatus

from .models import (
    CandidateConstraintResult,
    CandidatePlan,
    CandidatePlanRequest,
    CandidatePlanWarning,
)
from .planner import (
    CandidatePlanInputError,
    CandidatePlanRejected,
    DeterministicCandidatePlanner,
    candidate_to_proposed_plan_version_v2,
)


_STATUS_PRIORITY = {
    ValidationStatus.PASS: 0,
    ValidationStatus.WARNING: 1,
    ValidationStatus.NEEDS_CONFIRMATION: 2,
    ValidationStatus.FAIL: 3,
}
_RULE_EXECUTION_BUDGET = "REPLAN.BUDGET.ACTUAL_PLUS_REMAINING"


@runtime_checkable
class TrustedCandidateFactSource(Protocol):
    """Resolve the immutable T006/T007 facts used to create one V2 plan."""

    def get_candidate_request(
        self,
        candidate_plan_id: UUID,
    ) -> CandidatePlanRequest | None: ...


class T011ReplanCandidateValidator:
    """T018 adapter that recomputes from trusted facts instead of plan PASS fields."""

    def __init__(
        self,
        fact_source: TrustedCandidateFactSource,
        planner: DeterministicCandidatePlanner | None = None,
    ) -> None:
        if not isinstance(fact_source, TrustedCandidateFactSource):
            raise TypeError("fact_source must implement TrustedCandidateFactSource")
        self._fact_source = fact_source
        self._planner = planner or DeterministicCandidatePlanner()

    def validate_candidate(
        self,
        *,
        current_plan: PlanVersion,
        candidate: ProposedPlanVersion,
        events: Sequence[ExecutionEvent],
    ) -> ReplanValidationReport:
        current = _strict_model(current_plan, PlanVersion, path="currentPlan")
        proposed = _strict_model(candidate, ProposedPlanVersion, path="candidate")
        safe_events = tuple(
            _strict_model(event, ExecutionEvent, path=f"events[{index}]")
            for index, event in enumerate(events)
        )
        request = self._load_request(proposed.plan_id)

        try:
            generated = self._planner.generate(request)
        except CandidatePlanRejected as exc:
            return _replan_report(
                proposed.plan_id,
                exc.all_results,
                (),
            )
        except CandidatePlanInputError as exc:
            raise ReplanningContractError(
                code="T011_CANDIDATE_FACTS_INVALID",
                path=f"candidateFacts[{proposed.plan_id}].{exc.field}",
                message=str(exc),
            ) from exc

        execution_budget = _execution_budget_check(
            generated,
            safe_events,
        )
        report = _replan_report(
            proposed.plan_id,
            (*generated.constraint_results, execution_budget),
            generated.warnings,
        )
        if generated.warnings:
            return report

        try:
            expected = candidate_to_proposed_plan_version_v2(
                generated,
                request,
                current,
                reason=proposed.reason,
            )
        except CandidatePlanInputError as exc:
            raise ReplanningContractError(
                code="T011_CANDIDATE_FACTS_INVALID",
                path=f"candidateFacts[{proposed.plan_id}].{exc.field}",
                message=str(exc),
            ) from exc
        if expected != proposed:
            raise ReplanningContractError(
                code="T011_CANDIDATE_SNAPSHOT_MISMATCH",
                path=f"candidates[{proposed.plan_id}]",
                message=(
                    "ProposedPlanVersion does not equal the T011 result "
                    "recomputed from trusted facts"
                ),
            )
        return report

    def _load_request(self, plan_id: UUID) -> CandidatePlanRequest:
        try:
            value = self._fact_source.get_candidate_request(plan_id)
        except Exception as exc:
            raise ReplanningContractError(
                code="T011_CANDIDATE_FACT_SOURCE_FAILED",
                path=f"candidateFacts[{plan_id}]",
                message="trusted candidate fact source failed",
            ) from exc
        if value is None:
            raise ReplanningContractError(
                code="T011_CANDIDATE_FACTS_NOT_FOUND",
                path=f"candidateFacts[{plan_id}]",
                message="trusted candidate facts were not found",
            )
        return _strict_model(
            value,
            CandidatePlanRequest,
            path=f"candidateFacts[{plan_id}]",
        )


def _strict_model(value: object, model_type: type, *, path: str):
    try:
        if not isinstance(value, model_type):
            raise TypeError(f"expected {model_type.__name__}")
        raw = value.model_dump_json(by_alias=True, warnings="error")
        return model_type.model_validate_json(raw, strict=True)
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ReplanningContractError(
            code="T011_CANDIDATE_FACTS_INVALID",
            path=path,
            message=str(exc),
        ) from exc


def _replan_report(
    plan_id: UUID,
    results: Sequence[CandidateConstraintResult],
    warnings: Sequence[CandidatePlanWarning],
) -> ReplanValidationReport:
    checks: list[ReplanRuleCheck] = []
    present_domains: set[ReplanRuleDomain] = set()

    for result in results:
        domain = _result_domain(result)
        present_domains.add(domain)
        checks.append(
            ReplanRuleCheck(
                rule_id=result.rule_id,
                domain=domain,
                hardness=result.hardness,
                status=result.status,
                relaxable=(
                    result.status is not ValidationStatus.PASS
                    and result.suggestion is not None
                ),
                relaxation_hint=(
                    result.suggestion
                    if result.status is not ValidationStatus.PASS
                    else None
                ),
            )
        )

    if any(item.code == "UNKNOWN_PRICE" for item in warnings):
        present_domains.add(ReplanRuleDomain.BUDGET)
        checks.append(
            ReplanRuleCheck(
                rule_id="T011.BUDGET.UNKNOWN_PRICE",
                domain=ReplanRuleDomain.BUDGET,
                hardness="HARD",
                status=ValidationStatus.NEEDS_CONFIRMATION,
                relaxable=True,
                relaxation_hint=(
                    "Confirm every unknown price before accepting the replanned budget"
                ),
            )
        )

    care_statuses = [
        item.status for item in results if item.rule_id.startswith("CARE.")
    ]
    if any(item.code == "UNKNOWN_SOURCE" for item in warnings):
        care_statuses.append(ValidationStatus.NEEDS_CONFIRMATION)
    care_status = max(
        care_statuses,
        key=_STATUS_PRIORITY.__getitem__,
        default=ValidationStatus.PASS,
    )
    checks.append(
        ReplanRuleCheck(
            rule_id="T011.CARE.AGGREGATE",
            domain=ReplanRuleDomain.CARE,
            hardness="HARD",
            status=care_status,
            relaxable=(
                care_status is not ValidationStatus.PASS
                and any(item.code == "UNKNOWN_SOURCE" for item in warnings)
            ),
            relaxation_hint=(
                "Confirm unknown route or place sources before selecting Plan V2"
                if care_status is not ValidationStatus.PASS
                and any(item.code == "UNKNOWN_SOURCE" for item in warnings)
                else None
            ),
        )
    )
    present_domains.add(ReplanRuleDomain.CARE)

    for domain in ReplanRuleDomain:
        if domain not in present_domains:
            checks.append(
                ReplanRuleCheck(
                    rule_id=f"T011.{domain.value}.NO_APPLICABLE_RULE",
                    domain=domain,
                    hardness="HARD",
                    status=ValidationStatus.PASS,
                )
            )

    return ReplanValidationReport(
        candidate_plan_id=plan_id,
        checks=tuple(checks),
    )


def _result_domain(result: CandidateConstraintResult) -> ReplanRuleDomain:
    if result.rule_id.startswith("PLAN.BUDGET"):
        return ReplanRuleDomain.BUDGET
    if result.rule_id.startswith("CARE.DAY"):
        return ReplanRuleDomain.TIME
    return ReplanRuleDomain.ROUTE


def _execution_budget_check(
    candidate: CandidatePlan,
    events: Sequence[ExecutionEvent],
) -> CandidateConstraintResult:
    """Project final spend without counting already incurred task cost twice."""

    expense_by_task: dict[str, int] = {}
    terminal_task_ids: set[str] = set()
    for event in events:
        if event.event_type is ExecutionEventType.EXPENSE:
            assert event.amount_cents is not None
            expense_by_task[event.task_id] = (
                expense_by_task.get(event.task_id, 0) + event.amount_cents
            )
        elif event.event_type in {
            ExecutionEventType.COMPLETE,
            ExecutionEventType.SKIP,
        }:
            terminal_task_ids.add(event.task_id)

    actual_spent = sum(expense_by_task.values())
    known_remaining = sum(
        max(task.known_cost_cents - expense_by_task.get(task.task_id, 0), 0)
        for task in candidate.tasks
        if task.task_id not in terminal_task_ids
    )
    projected_total = actual_spent + known_remaining
    budget_limit = candidate.metrics.budget_limit_cents
    status = (
        ValidationStatus.PASS
        if projected_total <= budget_limit
        else ValidationStatus.FAIL
    )
    return CandidateConstraintResult(
        rule_id=_RULE_EXECUTION_BUDGET,
        scope="TRIP",
        hardness="HARD",
        status=status,
        observed={
            "actualSpentCents": actual_spent,
            "knownRemainingPlanCents": known_remaining,
            "projectedTotalCents": projected_total,
            "budgetLimitCents": budget_limit,
        },
        suggestion=(
            None
            if status is ValidationStatus.PASS
            else "Reduce remaining planned costs or confirm a larger budget cap"
        ),
    )


assert issubclass(T011ReplanCandidateValidator, ReplanCandidateValidator)


__all__ = [
    "T011ReplanCandidateValidator",
    "TrustedCandidateFactSource",
]
