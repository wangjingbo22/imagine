from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from app.application.plan_service import PlanVersionService
from app.application.collaboration_ports import PlanningOperation, ReadinessPermit
from app.domain.collaboration import TripFlowKind
from app.schemas.execution import ExecutionEvent, ExecutionEventType
from app.schemas.plan import (
    PlanVersion,
    PlanVersionStatus,
    ProposedPlanVersion,
)
from app.services.replanning import (
    MinimumDisruptionReplanningService,
    MinimumDisruptionSelector,
    NoFeasibleReplan,
    ReplanCandidate,
    ReplanCandidateSource,
    ReplanCandidateValidator,
    ReplanRuleCheck,
    ReplanRuleDomain,
    ReplanValidationReport,
    ReplanningContractError,
    RULE_FROZEN_PREFIX,
    RULE_VALIDATION_COVERAGE_PREFIX,
    SelectedReplan,
)
from app.services.route_risk import ValidationStatus


def _legacy_permit(trip_id, operation: PlanningOperation) -> ReadinessPermit:
    return ReadinessPermit(
        trip_id=trip_id,
        readiness_digest="legacy",
        operation_id="minimum-disruption-legacy-0001",
        operation=operation,
        flow_kind=TripFlowKind.LEGACY_SINGLE,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )


FIXTURE_ROOT = Path(__file__).parent / "fixtures"
NO_FEASIBLE_SNAPSHOT = (
    Path(__file__).parent / "snapshots" / "t018_no_feasible.json"
)
CURRENT_PLAN_ID = UUID("20000000-0000-4000-8000-000000000001")


def build_current_plan() -> PlanVersion:
    trip = json.loads(
        (FIXTURE_ROOT / "trips" / "beijing.json").read_text(encoding="utf-8")
    )
    trip["status"] = "PLAN_REVIEW"
    payload = {
        "schemaVersion": "1.0",
        "planId": str(CURRENT_PLAN_ID),
        "tripSnapshot": trip,
        "version": 1,
        "parentId": None,
        "reason": "INITIAL_PLAN",
        "metrics": {
            "totalCostCents": 4_000,
            "bufferCents": 31_000,
            "totalWalkMeters": 400,
            "transferCount": 0,
            "validationStatus": "PASS",
        },
        "days": [
            {
                "dayIndex": 0,
                "date": "2026-09-05",
                "tasks": [
                    {
                        "taskId": f"task-{index}",
                        "order": index,
                        "title": f"任务 {index}",
                        "category": "测试",
                        "timeRange": f"{8 + index:02d}:00 — {9 + index:02d}:00",
                        "durationMinutes": 60,
                        "transport": "步行 100 米",
                        "costCents": 1_000,
                        "walkMeters": 100,
                        "note": "原计划",
                    }
                    for index in range(1, 5)
                ],
            }
        ],
        "constraintsSnapshot": [
            {
                "ruleId": "BUDGET.TOTAL",
                "scope": "TRIP",
                "hardness": "HARD",
                "status": "PASS",
                "description": "总预算通过",
                "details": {"budgetCents": "35000"},
            }
        ],
        "sourcesSnapshot": [
            {
                "provider": "TEST",
                "sourceStatus": "USER_CONFIRMED",
                "fetchedAt": "2026-08-25T09:00:00+08:00",
                "isStale": False,
                "referenceId": "t018-current",
            }
        ],
    }
    proposal = ProposedPlanVersion.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )
    return PlanVersion(
        **proposal.model_dump(),
        status=PlanVersionStatus.CURRENT,
        created_at=datetime(2026, 8, 25, 1, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 8, 25, 1, 5, tzinfo=UTC),
    )


def build_candidate(
    current: PlanVersion,
    plan_id: str,
    *,
    satisfaction_loss: int,
    changes: dict[int, dict[str, object]],
) -> ReplanCandidate:
    payload = current.model_dump(
        mode="json",
        by_alias=True,
        exclude={"status", "created_at", "confirmed_at"},
    )
    payload["planId"] = plan_id
    payload["version"] = 2
    payload["parentId"] = str(current.plan_id)
    payload["reason"] = "EXPENSE_CHANGE"
    for task_index, update in changes.items():
        payload["days"][0]["tasks"][task_index].update(update)
    plan = ProposedPlanVersion.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )
    return ReplanCandidate(plan=plan, satisfaction_loss=satisfaction_loss)


def terminal_event(
    current: PlanVersion,
    task_id: str = "task-1",
    *,
    event_type: ExecutionEventType = ExecutionEventType.COMPLETE,
) -> ExecutionEvent:
    suffix = int(task_id.rsplit("-", 1)[-1])
    return ExecutionEvent(
        event_id=UUID(f"30000000-0000-4000-8000-{suffix:012d}"),
        trip_id=current.trip_snapshot.trip_id,
        task_id=task_id,
        plan_version_id=current.plan_id,
        event_type=event_type,
        amount_cents=None,
        idempotency_key=f"terminal-{task_id}-{event_type.value}",
        occurred_at=datetime(2026, 8, 25, 2, suffix, tzinfo=UTC),
    )


def passing_report(plan_id: UUID) -> ReplanValidationReport:
    return ReplanValidationReport(
        candidate_plan_id=plan_id,
        checks=tuple(
            ReplanRuleCheck(
                rule_id=rule_id,
                domain=domain,
                hardness="HARD",
                status=ValidationStatus.PASS,
            )
            for domain, rule_id in (
                (ReplanRuleDomain.BUDGET, "BUDGET.TOTAL"),
                (ReplanRuleDomain.TIME, "TIME.WINDOW"),
                (ReplanRuleDomain.ROUTE, "ROUTE.FEASIBLE"),
                (ReplanRuleDomain.CARE, "CARE.CONSTRAINTS"),
            )
        ),
    )


def failing_report(
    plan_id: UUID,
    *,
    domain: ReplanRuleDomain,
    rule_id: str,
    status: ValidationStatus = ValidationStatus.FAIL,
    relaxable: bool = False,
    relaxation_hint: str | None = None,
) -> ReplanValidationReport:
    checks = list(passing_report(plan_id).checks)
    index = next(i for i, check in enumerate(checks) if check.domain is domain)
    checks[index] = ReplanRuleCheck(
        rule_id=rule_id,
        domain=domain,
        hardness="HARD",
        status=status,
        relaxable=relaxable,
        relaxation_hint=relaxation_hint,
    )
    return ReplanValidationReport(candidate_plan_id=plan_id, checks=tuple(checks))


class FakeValidator:
    def __init__(self, reports: dict[UUID, ReplanValidationReport]) -> None:
        self.reports = reports
        self.calls: list[UUID] = []

    def validate_candidate(
        self,
        *,
        current_plan: PlanVersion,
        candidate: ProposedPlanVersion,
        events: tuple[ExecutionEvent, ...],
    ) -> ReplanValidationReport:
        assert current_plan.status is PlanVersionStatus.CURRENT
        assert isinstance(events, tuple)
        self.calls.append(candidate.plan_id)
        return self.reports.get(candidate.plan_id, passing_report(candidate.plan_id))


class FakeCandidateSource:
    def __init__(self, candidates: tuple[ReplanCandidate, ...]) -> None:
        self.candidates = candidates
        self.calls: list[tuple[UUID, tuple[str, ...]]] = []

    def generate_candidates(
        self,
        *,
        current_plan: PlanVersion,
        events: tuple[ExecutionEvent, ...],
        locked_task_ids: tuple[str, ...],
    ) -> tuple[ReplanCandidate, ...]:
        assert isinstance(events, tuple)
        self.calls.append((current_plan.plan_id, locked_task_ids))
        return self.candidates


def test_t017_source_and_t011_validator_ports_compose_without_owning_their_logic():
    current = build_current_plan()
    valid = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000002",
        satisfaction_loss=3,
        changes={2: {"title": "仅修改未完成任务"}},
    )
    illegal_prefix = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000003",
        satisfaction_loss=0,
        changes={1: {"title": "错误修改锁定任务"}},
    )
    source = FakeCandidateSource((illegal_prefix, valid))
    validator = FakeValidator({})

    assert isinstance(source, ReplanCandidateSource)
    assert isinstance(validator, ReplanCandidateValidator)
    outcome = MinimumDisruptionReplanningService(source, validator).replan(
        current_plan=current,
        events=(terminal_event(current),),
        locked_task_ids=("task-2",),
    )

    assert isinstance(outcome, SelectedReplan)
    assert outcome.selected_plan == valid.plan
    assert outcome.frozen_task_ids == ("task-1", "task-2")
    assert outcome.selected_plan.days[0].tasks[:2] == current.days[0].tasks[:2]
    assert source.calls == [(current.plan_id, ("task-2",))]
    assert validator.calls == [valid.plan.plan_id]
    rejected = next(item for item in outcome.assessments if not item.feasible)
    assert rejected.affected_rule_ids == (RULE_FROZEN_PREFIX,)


def test_ranking_uses_modification_count_before_satisfaction_loss():
    current = build_current_plan()
    one_high_loss = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000004",
        satisfaction_loss=10,
        changes={1: {"title": "一项高损失"}},
    )
    two_low_loss = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000005",
        satisfaction_loss=0,
        changes={1: {"title": "第一项"}, 2: {"title": "第二项"}},
    )
    one_low_loss = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000006",
        satisfaction_loss=5,
        changes={2: {"title": "一项低损失"}},
    )
    validator = FakeValidator({})

    outcome = MinimumDisruptionSelector(validator).select(
        current_plan=current,
        candidates=(two_low_loss, one_high_loss, one_low_loss),
        events=(terminal_event(current),),
    )

    assert isinstance(outcome, SelectedReplan)
    assert outcome.selected_plan.plan_id == one_low_loss.plan.plan_id
    assert [item.candidate_plan_id for item in outcome.assessments] == [
        one_low_loss.plan.plan_id,
        one_high_loss.plan.plan_id,
        two_low_loss.plan.plan_id,
    ]
    assert [item.modified_task_count for item in outcome.assessments] == [1, 1, 2]
    assert [item.rank for item in outcome.assessments] == [1, 2, 3]
    assert set(validator.calls) == {
        one_high_loss.plan.plan_id,
        two_low_loss.plan.plan_id,
        one_low_loss.plan.plan_id,
    }


def test_equal_scores_use_stable_tie_break_independent_of_input_order():
    current = build_current_plan()
    left = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000007",
        satisfaction_loss=4,
        changes={1: {"title": "候选甲"}},
    )
    right = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000008",
        satisfaction_loss=4,
        changes={1: {"title": "候选乙"}},
    )

    first = MinimumDisruptionSelector(FakeValidator({})).select(
        current_plan=current,
        candidates=(left, right),
        events=(terminal_event(current),),
    )
    second = MinimumDisruptionSelector(FakeValidator({})).select(
        current_plan=current,
        candidates=(right, left),
        events=(terminal_event(current),),
    )

    assert isinstance(first, SelectedReplan)
    assert isinstance(second, SelectedReplan)
    assert first.selected_plan.plan_id == second.selected_plan.plan_id
    assert first.assessments == second.assessments
    assert first.model_dump_json(by_alias=True) == second.model_dump_json(by_alias=True)


def test_hard_failure_is_rejected_before_ranking_and_next_candidate_is_selected():
    current = build_current_plan()
    best_score_but_unsafe = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000009",
        satisfaction_loss=0,
        changes={1: {"title": "风险最优分"}},
    )
    safe_but_more_changes = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000010",
        satisfaction_loss=50,
        changes={1: {"title": "安全一"}, 2: {"title": "安全二"}},
    )
    validator = FakeValidator(
        {
            best_score_but_unsafe.plan.plan_id: failing_report(
                best_score_but_unsafe.plan.plan_id,
                domain=ReplanRuleDomain.ROUTE,
                rule_id="CARE.ROUTE.WALK_SEGMENT_LIMIT",
            )
        }
    )

    outcome = MinimumDisruptionSelector(validator).select(
        current_plan=current,
        candidates=(best_score_but_unsafe, safe_but_more_changes),
        events=(terminal_event(current),),
    )

    assert isinstance(outcome, SelectedReplan)
    assert outcome.selected_plan.plan_id == safe_but_more_changes.plan.plan_id
    unsafe = next(
        item
        for item in outcome.assessments
        if item.candidate_plan_id == best_score_but_unsafe.plan.plan_id
    )
    assert not unsafe.feasible
    assert unsafe.affected_rule_ids == ("CARE.ROUTE.WALK_SEGMENT_LIMIT",)


def test_missing_hard_pass_domain_and_needs_confirmation_are_not_pass():
    current = build_current_plan()
    missing_care = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000011",
        satisfaction_loss=1,
        changes={1: {"title": "缺少关怀报告"}},
    )
    needs_confirmation = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000012",
        satisfaction_loss=1,
        changes={2: {"title": "设施待确认"}},
    )
    incomplete = passing_report(missing_care.plan.plan_id)
    incomplete = ReplanValidationReport(
        candidate_plan_id=incomplete.candidate_plan_id,
        checks=tuple(
            ReplanRuleCheck(
                rule_id=check.rule_id,
                domain=check.domain,
                hardness="SOFT",
                status=ValidationStatus.PASS,
            )
            if check.domain is ReplanRuleDomain.CARE
            else check
            for check in incomplete.checks
        ),
    )
    validator = FakeValidator(
        {
            missing_care.plan.plan_id: incomplete,
            needs_confirmation.plan.plan_id: failing_report(
                needs_confirmation.plan.plan_id,
                domain=ReplanRuleDomain.CARE,
                rule_id="CARE.ROUTE.FACILITY_EVIDENCE",
                status=ValidationStatus.NEEDS_CONFIRMATION,
            ),
        }
    )

    outcome = MinimumDisruptionSelector(validator).select(
        current_plan=current,
        candidates=(needs_confirmation, missing_care),
        events=(terminal_event(current),),
    )

    assert isinstance(outcome, NoFeasibleReplan)
    assert outcome.selected_plan is None
    assert outcome.affected_rule_ids == (
        "CARE.ROUTE.FACILITY_EVIDENCE",
        f"{RULE_VALIDATION_COVERAGE_PREFIX}CARE",
    )


def test_no_feasible_result_matches_snapshot_and_does_not_mutate_inputs():
    current = build_current_plan()
    route_blocked = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000013",
        satisfaction_loss=2,
        changes={1: {"title": "路线受阻"}},
    )
    care_blocked = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000014",
        satisfaction_loss=3,
        changes={2: {"title": "设施受阻"}},
    )
    candidates = (route_blocked, care_blocked)
    before = copy.deepcopy(candidates)
    validator = FakeValidator(
        {
            route_blocked.plan.plan_id: failing_report(
                route_blocked.plan.plan_id,
                domain=ReplanRuleDomain.ROUTE,
                rule_id="CARE.ROUTE.TRANSFER_LIMIT",
                relaxable=True,
                relaxation_hint="可在用户确认后将最大换乘数从 2 调整为 3",
            ),
            care_blocked.plan.plan_id: failing_report(
                care_blocked.plan.plan_id,
                domain=ReplanRuleDomain.CARE,
                rule_id="CARE.ROUTE.STAIRS_FORBIDDEN",
            ),
        }
    )

    outcome = MinimumDisruptionSelector(validator).select(
        current_plan=current,
        candidates=candidates,
        events=(terminal_event(current),),
    )

    assert isinstance(outcome, NoFeasibleReplan)
    assert outcome.selected_plan is None
    assert outcome.affected_rule_ids == (
        "CARE.ROUTE.STAIRS_FORBIDDEN",
        "CARE.ROUTE.TRANSFER_LIMIT",
    )
    assert len(outcome.relaxations) == 1
    assert outcome.relaxations[0].rule_id == "CARE.ROUTE.TRANSFER_LIMIT"
    assert candidates == before
    assert NO_FEASIBLE_SNAPSHOT.read_text(encoding="utf-8") == (
        outcome.model_dump_json(by_alias=True, indent=2) + "\n"
    )


def test_selected_plan_is_direct_input_to_existing_plan_version_service():
    current = build_current_plan()
    candidate = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000015",
        satisfaction_loss=1,
        changes={1: {"title": "可登记候选"}},
    )
    outcome = MinimumDisruptionSelector(FakeValidator({})).select(
        current_plan=current,
        candidates=(candidate,),
        events=(terminal_event(current),),
    )
    assert isinstance(outcome, SelectedReplan)

    class RecordingRepository:
        def __init__(self) -> None:
            self.proposal: ProposedPlanVersion | None = None

        def register_proposed(
            self,
            proposal: ProposedPlanVersion,
        ) -> ProposedPlanVersion:
            self.proposal = proposal
            return proposal

    repository = RecordingRepository()
    service = PlanVersionService(cast(object, repository))
    returned = service.register_proposed(
        outcome.selected_plan,
        readiness_permit=_legacy_permit(
            outcome.selected_plan.trip_snapshot.trip_id,
            PlanningOperation.GENERATE_V2,
        ),
    )

    assert returned is outcome.selected_plan
    assert repository.proposal is outcome.selected_plan


def test_mutated_candidate_and_stale_event_fail_before_validation():
    current = build_current_plan()
    candidate = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000016",
        satisfaction_loss=1,
        changes={1: {"title": "候选"}},
    )
    candidate.satisfaction_loss = -1
    validator = FakeValidator({})

    with pytest.raises(ReplanningContractError) as mutated:
        MinimumDisruptionSelector(validator).select(
            current_plan=current,
            candidates=(candidate,),
            events=(terminal_event(current),),
        )
    assert mutated.value.code == "REPLAN_INPUT_INVALID"
    assert validator.calls == []

    valid_candidate = build_candidate(
        current,
        "20000000-0000-4000-8000-000000000017",
        satisfaction_loss=1,
        changes={1: {"title": "候选"}},
    )
    stale = terminal_event(current).model_copy(
        update={"plan_version_id": UUID("20000000-0000-4000-8000-000000000099")}
    )
    with pytest.raises(ReplanningContractError) as stale_error:
        MinimumDisruptionSelector(validator).select(
            current_plan=current,
            candidates=(valid_candidate,),
            events=(stale,),
        )
    assert stale_error.value.code == "REPLAN_EVENT_PLAN_MISMATCH"
    assert validator.calls == []
