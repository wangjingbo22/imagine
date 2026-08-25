from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
import hashlib
from itertools import zip_longest
import json
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from app.schemas.execution import ExecutionEvent, ExecutionEventType
from app.schemas.plan import (
    PlanVersion,
    PlanVersionStatus,
    ProposedPlanVersion,
)
from app.services.route_risk import ValidationStatus

from .models import (
    CandidateAssessment,
    NoFeasibleReplan,
    RelaxationOption,
    ReplanCandidate,
    ReplanOutcome,
    ReplanRuleDomain,
    ReplanValidationReport,
    SelectedReplan,
)


RULE_NO_CANDIDATES = "REPLAN.CANDIDATE.NONE"
RULE_CANDIDATE_ID = "REPLAN.CANDIDATE.ID"
RULE_CANDIDATE_VERSION = "REPLAN.CANDIDATE.VERSION"
RULE_CANDIDATE_PARENT = "REPLAN.CANDIDATE.PARENT"
RULE_TRIP_SNAPSHOT = "REPLAN.TRIP.SNAPSHOT"
RULE_FROZEN_PREFIX = "REPLAN.PREFIX.IMMUTABLE"
RULE_VALIDATION_CANDIDATE = "REPLAN.VALIDATION.CANDIDATE"
RULE_VALIDATION_COVERAGE_PREFIX = "REPLAN.VALIDATION.COVERAGE."

_REQUIRED_VALIDATION_DOMAINS = tuple(ReplanRuleDomain)
_TERMINAL_EVENT_TYPES = frozenset(
    {ExecutionEventType.COMPLETE, ExecutionEventType.SKIP}
)


class ReplanningContractError(ValueError):
    """Fail-closed input or validator contract error."""

    def __init__(self, *, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        super().__init__(message)

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": self.path,
            "message": str(self),
        }


@runtime_checkable
class ReplanCandidateValidator(Protocol):
    """T011-compatible validation port; an adapter may wrap its final API."""

    def validate_candidate(
        self,
        *,
        current_plan: PlanVersion,
        candidate: ProposedPlanVersion,
        events: Sequence[ExecutionEvent],
    ) -> ReplanValidationReport: ...


@runtime_checkable
class ReplanCandidateSource(Protocol):
    """T017 input port; T018 deliberately does not generate plan candidates."""

    def generate_candidates(
        self,
        *,
        current_plan: PlanVersion,
        events: Sequence[ExecutionEvent],
        locked_task_ids: tuple[str, ...],
    ) -> Sequence[ReplanCandidate]: ...


@dataclass(frozen=True, slots=True)
class _EvaluatedCandidate:
    candidate: ReplanCandidate
    fingerprint: str
    modified_task_count: int | None
    report: ReplanValidationReport | None
    affected_rule_ids: tuple[str, ...]
    relaxations: tuple[RelaxationOption, ...]

    @property
    def feasible(self) -> bool:
        return not self.affected_rule_ids

    @property
    def rank_key(self) -> tuple[int, int, str, str]:
        assert self.modified_task_count is not None
        return (
            self.modified_task_count,
            self.candidate.satisfaction_loss,
            self.fingerprint,
            str(self.candidate.plan.plan_id),
        )


ModelT = TypeVar("ModelT", bound=BaseModel)


def _strict_clone(
    value: object,
    model_type: type[ModelT],
    *,
    path: str,
) -> ModelT:
    try:
        if not isinstance(value, model_type):
            raise TypeError(f"expected {model_type.__name__}")
        raw = value.model_dump_json(by_alias=True, warnings="none")
        return model_type.model_validate_json(raw, strict=True)
    except (
        AttributeError,
        PydanticSerializationError,
        TypeError,
        ValueError,
        ValidationError,
    ) as exc:
        raise ReplanningContractError(
            code="REPLAN_INPUT_INVALID",
            path=path,
            message=str(exc),
        ) from exc


def _candidate_fingerprint(plan: ProposedPlanVersion) -> str:
    payload = plan.model_dump(mode="json", by_alias=True)
    payload.pop("planId", None)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _modified_task_count(
    current_plan: PlanVersion,
    candidate: ProposedPlanVersion,
    *,
    prefix_length: int,
) -> int:
    current_suffix = current_plan.days[0].tasks[prefix_length:]
    candidate_suffix = candidate.days[0].tasks[prefix_length:]
    missing = object()
    return sum(
        left is missing or right is missing or left != right
        for left, right in zip_longest(
            current_suffix,
            candidate_suffix,
            fillvalue=missing,
        )
    )


class MinimumDisruptionSelector:
    """Pure T018 selection: protect the executed prefix, revalidate, then rank."""

    def __init__(self, validator: ReplanCandidateValidator) -> None:
        if not isinstance(validator, ReplanCandidateValidator):
            raise TypeError("validator must implement ReplanCandidateValidator")
        self._validator = validator

    def select(
        self,
        *,
        current_plan: PlanVersion,
        candidates: Sequence[ReplanCandidate],
        events: Sequence[ExecutionEvent] = (),
        locked_task_ids: Collection[str] = (),
    ) -> ReplanOutcome:
        current = _strict_clone(current_plan, PlanVersion, path="currentPlan")
        if current.status is not PlanVersionStatus.CURRENT:
            raise ReplanningContractError(
                code="REPLAN_CURRENT_REQUIRED",
                path="currentPlan.status",
                message="replanning requires the CURRENT PlanVersion",
            )

        safe_events = tuple(
            _strict_clone(event, ExecutionEvent, path=f"events[{index}]")
            for index, event in enumerate(events)
        )
        current_tasks = tuple(current.days[0].tasks)
        task_index = {task.task_id: index for index, task in enumerate(current_tasks)}
        self._validate_events(current, safe_events, task_index)
        locked = self._normalize_locked_task_ids(locked_task_ids, task_index)

        terminal_ids = {
            event.task_id
            for event in safe_events
            if event.event_type in _TERMINAL_EVENT_TYPES
        }
        protected_ids = terminal_ids | locked
        prefix_length = (
            max(task_index[task_id] for task_id in protected_ids) + 1
            if protected_ids
            else 0
        )
        frozen_task_ids = tuple(
            task.task_id for task in current_tasks[:prefix_length]
        )

        safe_candidates = tuple(
            _strict_clone(candidate, ReplanCandidate, path=f"candidates[{index}]")
            for index, candidate in enumerate(candidates)
        )
        candidate_ids = [candidate.plan.plan_id for candidate in safe_candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ReplanningContractError(
                code="REPLAN_DUPLICATE_CANDIDATE",
                path="candidates",
                message="candidate planId values must be unique",
            )

        if not safe_candidates:
            return NoFeasibleReplan(
                frozen_task_ids=frozen_task_ids,
                assessments=(),
                affected_rule_ids=(RULE_NO_CANDIDATES,),
                relaxations=(),
            )

        evaluated = tuple(
            self._evaluate_candidate(
                current=current,
                candidate=candidate,
                events=safe_events,
                prefix_length=prefix_length,
            )
            for candidate in safe_candidates
        )
        feasible = sorted(
            (item for item in evaluated if item.feasible),
            key=lambda item: item.rank_key,
        )
        infeasible = sorted(
            (item for item in evaluated if not item.feasible),
            key=lambda item: (
                str(item.candidate.plan.plan_id),
                item.fingerprint,
            ),
        )
        rank_by_id = {
            item.candidate.plan.plan_id: rank
            for rank, item in enumerate(feasible, start=1)
        }
        assessments = tuple(
            CandidateAssessment(
                candidate_plan_id=item.candidate.plan.plan_id,
                feasible=item.feasible,
                rank=rank_by_id.get(item.candidate.plan.plan_id),
                modified_task_count=item.modified_task_count,
                satisfaction_loss=item.candidate.satisfaction_loss,
                tie_break_key=item.fingerprint,
                affected_rule_ids=item.affected_rule_ids,
            )
            for item in (*feasible, *infeasible)
        )

        if feasible:
            selected = feasible[0]
            assert selected.report is not None
            return SelectedReplan(
                selected_plan=selected.candidate.plan,
                frozen_task_ids=frozen_task_ids,
                assessments=assessments,
                validation_report=selected.report,
            )

        affected_rule_ids = tuple(
            sorted(
                {
                    rule_id
                    for item in infeasible
                    for rule_id in item.affected_rule_ids
                }
            )
        )
        relaxations = tuple(
            sorted(
                (
                    relaxation
                    for item in infeasible
                    for relaxation in item.relaxations
                ),
                key=lambda item: (
                    str(item.candidate_plan_id),
                    item.domain.value,
                    item.rule_id,
                    item.description,
                ),
            )
        )
        return NoFeasibleReplan(
            frozen_task_ids=frozen_task_ids,
            assessments=assessments,
            affected_rule_ids=affected_rule_ids,
            relaxations=relaxations,
        )

    @staticmethod
    def _normalize_locked_task_ids(
        locked_task_ids: Collection[str],
        task_index: dict[str, int],
    ) -> set[str]:
        normalized: set[str] = set()
        for index, task_id in enumerate(locked_task_ids):
            if not isinstance(task_id, str) or not task_id.strip():
                raise ReplanningContractError(
                    code="REPLAN_LOCK_INVALID",
                    path=f"lockedTaskIds[{index}]",
                    message="locked task ids must be non-blank strings",
                )
            if task_id not in task_index:
                raise ReplanningContractError(
                    code="REPLAN_LOCK_TASK_NOT_FOUND",
                    path=f"lockedTaskIds[{index}]",
                    message=f"locked task {task_id!r} is not in the current plan",
                )
            normalized.add(task_id)
        return normalized

    @staticmethod
    def _validate_events(
        current: PlanVersion,
        events: Sequence[ExecutionEvent],
        task_index: dict[str, int],
    ) -> None:
        terminal_by_task: dict[str, ExecutionEventType] = {}
        trip_id = current.trip_snapshot.trip_id
        for index, event in enumerate(events):
            if event.trip_id != trip_id:
                raise ReplanningContractError(
                    code="REPLAN_EVENT_TRIP_MISMATCH",
                    path=f"events[{index}].tripId",
                    message="execution event belongs to another Trip",
                )
            if event.plan_version_id != current.plan_id:
                raise ReplanningContractError(
                    code="REPLAN_EVENT_PLAN_MISMATCH",
                    path=f"events[{index}].planVersionId",
                    message="execution event does not belong to the CURRENT plan",
                )
            if event.task_id not in task_index:
                raise ReplanningContractError(
                    code="REPLAN_EVENT_TASK_NOT_FOUND",
                    path=f"events[{index}].taskId",
                    message="execution event task is not in the CURRENT plan",
                )
            if event.event_type in _TERMINAL_EVENT_TYPES:
                previous = terminal_by_task.get(event.task_id)
                if previous is not None and previous is not event.event_type:
                    raise ReplanningContractError(
                        code="REPLAN_EVENT_TERMINAL_CONFLICT",
                        path=f"events[{index}].eventType",
                        message="task cannot be both COMPLETE and SKIP",
                    )
                terminal_by_task[event.task_id] = event.event_type

    def _evaluate_candidate(
        self,
        *,
        current: PlanVersion,
        candidate: ReplanCandidate,
        events: Sequence[ExecutionEvent],
        prefix_length: int,
    ) -> _EvaluatedCandidate:
        plan = candidate.plan
        fingerprint = _candidate_fingerprint(plan)
        structural_issues: list[str] = []
        if plan.plan_id == current.plan_id:
            structural_issues.append(RULE_CANDIDATE_ID)
        if plan.version != current.version + 1:
            structural_issues.append(RULE_CANDIDATE_VERSION)
        if plan.parent_id != current.plan_id:
            structural_issues.append(RULE_CANDIDATE_PARENT)
        if plan.trip_snapshot != current.trip_snapshot:
            structural_issues.append(RULE_TRIP_SNAPSHOT)

        current_prefix = current.days[0].tasks[:prefix_length]
        candidate_prefix = plan.days[0].tasks[:prefix_length]
        if len(candidate_prefix) != prefix_length or candidate_prefix != current_prefix:
            structural_issues.append(RULE_FROZEN_PREFIX)

        if structural_issues:
            return _EvaluatedCandidate(
                candidate=candidate,
                fingerprint=fingerprint,
                modified_task_count=None,
                report=None,
                affected_rule_ids=tuple(sorted(set(structural_issues))),
                relaxations=(),
            )

        modified_task_count = _modified_task_count(
            current,
            plan,
            prefix_length=prefix_length,
        )
        report = self._validator.validate_candidate(
            current_plan=current,
            candidate=plan,
            events=events,
        )
        safe_report = _strict_clone(
            report,
            ReplanValidationReport,
            path=f"validationReports[{plan.plan_id}]",
        )

        affected: list[str] = []
        relaxations: list[RelaxationOption] = []
        if safe_report.candidate_plan_id != plan.plan_id:
            affected.append(RULE_VALIDATION_CANDIDATE)

        hard_check_domains = {
            check.domain
            for check in safe_report.checks
            if check.hardness == "HARD"
        }
        for domain in _REQUIRED_VALIDATION_DOMAINS:
            if domain not in hard_check_domains:
                affected.append(f"{RULE_VALIDATION_COVERAGE_PREFIX}{domain.value}")

        for check in safe_report.checks:
            if check.hardness == "HARD" and check.status is not ValidationStatus.PASS:
                affected.append(check.rule_id)
                if check.relaxable:
                    assert check.relaxation_hint is not None
                    relaxations.append(
                        RelaxationOption(
                            candidate_plan_id=plan.plan_id,
                            rule_id=check.rule_id,
                            domain=check.domain,
                            description=check.relaxation_hint,
                        )
                    )

        return _EvaluatedCandidate(
            candidate=candidate,
            fingerprint=fingerprint,
            modified_task_count=modified_task_count,
            report=safe_report,
            affected_rule_ids=tuple(sorted(set(affected))),
            relaxations=tuple(
                sorted(
                    relaxations,
                    key=lambda item: (
                        item.domain.value,
                        item.rule_id,
                        item.description,
                    ),
                )
            ),
        )


class MinimumDisruptionReplanningService:
    """Compose a T017 candidate source with T018 selection and T011 checks."""

    def __init__(
        self,
        candidate_source: ReplanCandidateSource,
        validator: ReplanCandidateValidator,
    ) -> None:
        if not isinstance(candidate_source, ReplanCandidateSource):
            raise TypeError("candidate_source must implement ReplanCandidateSource")
        self._candidate_source = candidate_source
        self._selector = MinimumDisruptionSelector(validator)

    def replan(
        self,
        *,
        current_plan: PlanVersion,
        events: Sequence[ExecutionEvent] = (),
        locked_task_ids: Collection[str] = (),
    ) -> ReplanOutcome:
        current = _strict_clone(current_plan, PlanVersion, path="currentPlan")
        if current.status is not PlanVersionStatus.CURRENT:
            raise ReplanningContractError(
                code="REPLAN_CURRENT_REQUIRED",
                path="currentPlan.status",
                message="replanning requires the CURRENT PlanVersion",
            )
        safe_events = tuple(
            _strict_clone(event, ExecutionEvent, path=f"events[{index}]")
            for index, event in enumerate(events)
        )
        task_index = {
            task.task_id: index for index, task in enumerate(current.days[0].tasks)
        }
        MinimumDisruptionSelector._validate_events(
            current,
            safe_events,
            task_index,
        )
        locked = MinimumDisruptionSelector._normalize_locked_task_ids(
            locked_task_ids,
            task_index,
        )
        stable_locked = tuple(sorted(locked, key=task_index.__getitem__))
        candidates = self._candidate_source.generate_candidates(
            current_plan=current,
            events=safe_events,
            locked_task_ids=stable_locked,
        )
        if not isinstance(candidates, Sequence):
            raise ReplanningContractError(
                code="REPLAN_CANDIDATE_SOURCE_INVALID",
                path="candidates",
                message="T017 candidate source must return a Sequence",
            )
        return self._selector.select(
            current_plan=current,
            candidates=candidates,
            events=safe_events,
            locked_task_ids=stable_locked,
        )


__all__ = [
    "MinimumDisruptionReplanningService",
    "MinimumDisruptionSelector",
    "ReplanCandidateSource",
    "ReplanCandidateValidator",
    "ReplanningContractError",
    "RULE_CANDIDATE_ID",
    "RULE_CANDIDATE_PARENT",
    "RULE_CANDIDATE_VERSION",
    "RULE_FROZEN_PREFIX",
    "RULE_NO_CANDIDATES",
    "RULE_TRIP_SNAPSHOT",
    "RULE_VALIDATION_CANDIDATE",
    "RULE_VALIDATION_COVERAGE_PREFIX",
]
