from __future__ import annotations

from collections.abc import Sequence

from app.schemas.execution import ExecutionEvent
from app.schemas.execution_adjustment import EventConstraintSet
from app.schemas.plan import PlanVersion, ProposedPlanVersion
from app.services.planning.replanning_adapter import TrustedCandidateFactSource
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


_TIME_BUDGET = "remaining.timeBudgetMinutes"
_WALK_BUDGET = "remaining.walkBudgetMeters"
_MAX_SEGMENT = "remaining.maxSegmentWalkMeters"
_REST_INTERVAL = "remaining.restIntervalMinutes"
_SUPPORTED_FIELDS = {
    _TIME_BUDGET,
    _WALK_BUDGET,
    _MAX_SEGMENT,
    _REST_INTERVAL,
}


class EventConstraintReplanValidator:
    """Add transient T020 checks after the normal T011 four-domain replay."""

    def __init__(
        self,
        *,
        base_validator: ReplanCandidateValidator,
        fact_source: TrustedCandidateFactSource,
        event_constraints: EventConstraintSet,
        frozen_task_ids: Sequence[str],
    ) -> None:
        if not isinstance(base_validator, ReplanCandidateValidator):
            raise TypeError("base_validator must implement ReplanCandidateValidator")
        if not isinstance(fact_source, TrustedCandidateFactSource):
            raise TypeError("fact_source must implement TrustedCandidateFactSource")
        self._base_validator = base_validator
        self._fact_source = fact_source
        self._event_constraints = event_constraints
        self._frozen_task_ids = tuple(frozen_task_ids)

    def validate_candidate(
        self,
        *,
        current_plan: PlanVersion,
        candidate: ProposedPlanVersion,
        events: Sequence[ExecutionEvent],
    ) -> ReplanValidationReport:
        base = self._base_validator.validate_candidate(
            current_plan=current_plan,
            candidate=candidate,
            events=events,
        )
        request = self._fact_source.get_candidate_request(candidate.plan_id)
        if request is None:
            raise ReplanningContractError(
                code="S2_T021_TRUSTED_FACTS_NOT_FOUND",
                path=f"candidateFacts[{candidate.plan_id}]",
                message="trusted candidate facts are required for transient checks",
            )

        fact_ids = tuple(item.task_id for item in request.task_facts)
        try:
            frozen_indexes = tuple(fact_ids.index(item) for item in self._frozen_task_ids)
        except ValueError as error:
            raise ReplanningContractError(
                code="S2_T021_FROZEN_FACT_MISMATCH",
                path="frozenTaskIds",
                message="a frozen task is absent from trusted candidate facts",
            ) from error
        prefix_length = max(frozen_indexes) + 1 if frozen_indexes else 0
        suffix_plan = tuple(candidate.days[0].tasks[prefix_length:])
        suffix_facts = tuple(request.task_facts[prefix_length:])
        if not suffix_plan or len(suffix_plan) != len(suffix_facts):
            raise ReplanningContractError(
                code="S2_T021_SUFFIX_FACT_MISMATCH",
                path="candidate.days[0].tasks",
                message="candidate suffix must match trusted suffix facts",
            )

        checks = tuple(
            _evaluate_constraint(
                constraint.field,
                _integer_limit(constraint.value, field=constraint.field),
                suffix_plan=suffix_plan,
                suffix_facts=suffix_facts,
                anchor_end=(
                    request.task_facts[prefix_length - 1].end_at
                    if prefix_length
                    else request.trip.days[0].time_window.start
                ),
            )
            for constraint in self._event_constraints.constraints
        )
        return ReplanValidationReport(
            candidate_plan_id=base.candidate_plan_id,
            checks=(*base.checks, *checks),
        )


def _integer_limit(value: object, *, field: str) -> int:
    if field not in _SUPPORTED_FIELDS:
        raise ReplanningContractError(
            code="S2_T021_EVENT_CONSTRAINT_UNSUPPORTED",
            path="eventConstraints.constraints.field",
            message=f"unsupported transient constraint field {field!r}",
        )
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReplanningContractError(
            code="S2_T021_EVENT_CONSTRAINT_INVALID",
            path=f"eventConstraints.{field}",
            message="transient constraint value must be a non-negative integer",
        )
    return value


def _evaluate_constraint(
    field: str,
    limit: int,
    *,
    suffix_plan: Sequence,
    suffix_facts: Sequence,
    anchor_end,
) -> ReplanRuleCheck:
    if field == _TIME_BUDGET:
        last = suffix_facts[-1].end_at
        observed = (
            last.hour * 60 + last.minute
            - (anchor_end.hour * 60 + anchor_end.minute)
        )
        domain = ReplanRuleDomain.TIME
        hint = "缩短剩余活动、提前返程或确认更晚的结束时间"
    elif field == _WALK_BUDGET:
        observed = sum(item.walk_meters for item in suffix_plan)
        domain = ReplanRuleDomain.CARE
        hint = "减少剩余步行路段或改用更省力的交通方式"
    elif field == _MAX_SEGMENT:
        observed = max(item.walk_meters for item in suffix_plan)
        domain = ReplanRuleDomain.CARE
        hint = "替换最长步行路段或增加接驳方式"
    else:
        observed = max(item.elapsed_since_rest_minutes for item in suffix_facts)
        domain = ReplanRuleDomain.CARE
        hint = "缩短连续活动时间并在剩余后缀增加休息"

    status = ValidationStatus.PASS if observed <= limit else ValidationStatus.FAIL
    return ReplanRuleCheck(
        rule_id=f"S2-T020.{field}",
        domain=domain,
        hardness="HARD",
        status=status,
        relaxable=status is ValidationStatus.FAIL,
        relaxation_hint=hint if status is ValidationStatus.FAIL else None,
    )


assert issubclass(EventConstraintReplanValidator, ReplanCandidateValidator)


__all__ = ["EventConstraintReplanValidator"]
