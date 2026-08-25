from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import UUID

import pytest

from app.application.plan_service import PlanVersionService
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.schemas.execution import ExecutionEvent, ExecutionEventType
from app.schemas.plan import (
    PlanVersion,
    PlanVersionReason,
    PlanVersionStatus,
    ProposedPlanVersion,
)
from app.schemas.trip import TripStatus
from app.services.planning import (
    CandidatePlanRequest,
    T011ReplanCandidateValidator,
    TrustedCandidateFactSource,
    candidate_to_proposed_plan_version_v2,
    generate_candidate_plan,
    generate_proposed_plan_version,
)
from app.services.replanning import (
    MinimumDisruptionSelector,
    NoFeasibleReplan,
    ReplanCandidate,
    ReplanRuleDomain,
    ReplanningContractError,
    SelectedReplan,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "planning"
    / "golden_candidate_plan.json"
)


class InMemoryTrustedFacts:
    def __init__(self, records: dict[UUID, CandidatePlanRequest]) -> None:
        self.records = records

    def get_candidate_request(
        self,
        candidate_plan_id: UUID,
    ) -> CandidatePlanRequest | None:
        return self.records.get(candidate_plan_id)


def _fixture_payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _request(payload: dict[str, object]) -> CandidatePlanRequest:
    return CandidatePlanRequest.model_validate_json(
        json.dumps(
            payload["request"],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        strict=True,
    )


def _current_v1(tmp_path: Path) -> tuple[PlanVersionService, PlanVersion]:
    request = _request(_fixture_payload())
    service = PlanVersionService(
        SqlitePlanVersionRepository(tmp_path / "plan_versions.sqlite3")
    )
    proposed = service.register_proposed(generate_proposed_plan_version(request))
    service.confirm(proposed.trip_snapshot.trip_id, proposed.plan_id)
    service.start_execution(proposed.trip_snapshot.trip_id)
    current = service.get_trip_state(proposed.trip_snapshot.trip_id).current_plan
    assert current is not None
    assert current.status is PlanVersionStatus.CURRENT
    return service, current


def _v2_request(*, route_price_cents: int = 400) -> CandidatePlanRequest:
    payload = _fixture_payload()
    first = payload["request"]["taskFacts"][0]
    first["title"] = "参观城市博物馆（调整后）"
    first["route"]["priceReference"]["amountCents"] = route_price_cents
    return _request(payload)


def _v2_plan(
    request: CandidatePlanRequest,
    current: PlanVersion,
) -> ProposedPlanVersion:
    candidate = generate_candidate_plan(request)
    return candidate_to_proposed_plan_version_v2(
        candidate,
        request,
        current,
        reason=PlanVersionReason.EXPENSE_CHANGE,
    )


def _event(
    current: PlanVersion,
    *,
    suffix: int,
    task_id: str,
    event_type: ExecutionEventType,
    amount_cents: int | None = None,
) -> ExecutionEvent:
    return ExecutionEvent(
        event_id=UUID(f"40000000-0000-4000-8000-{suffix:012d}"),
        trip_id=current.trip_snapshot.trip_id,
        task_id=task_id,
        plan_version_id=current.plan_id,
        event_type=event_type,
        amount_cents=amount_cents,
        idempotency_key=f"day2-{suffix}",
        occurred_at=datetime(2026, 8, 25, 3, suffix, tzinfo=UTC),
    )


def test_t011_v1_to_t018_selection_to_real_v2_registration(
    tmp_path: Path,
) -> None:
    service, current = _current_v1(tmp_path)
    request = _v2_request()
    proposed_v2 = _v2_plan(request, current)
    facts = InMemoryTrustedFacts({proposed_v2.plan_id: request})

    assert isinstance(facts, TrustedCandidateFactSource)
    outcome = MinimumDisruptionSelector(
        T011ReplanCandidateValidator(facts)
    ).select(
        current_plan=current,
        candidates=(ReplanCandidate(plan=proposed_v2, satisfaction_loss=1),),
    )

    assert isinstance(outcome, SelectedReplan)
    assert outcome.selected_plan == proposed_v2
    assert {
        check.domain for check in outcome.validation_report.checks
    } == set(ReplanRuleDomain)
    assert all(
        check.hardness == "HARD" and check.status.value == "PASS"
        for check in outcome.validation_report.checks
    )

    stored = service.register_proposed(outcome.selected_plan)
    state = service.get_trip_state(current.trip_snapshot.trip_id)

    assert stored.status is PlanVersionStatus.PROPOSED
    assert stored.version == 2
    assert stored.parent_id == current.plan_id
    assert state.trip_status is TripStatus.REPLAN_REVIEW
    assert state.current_plan is not None
    assert state.current_plan.plan_id == current.plan_id
    assert [item.plan_id for item in state.proposed_plans] == [stored.plan_id]


def test_missing_trusted_facts_fail_before_t018_can_select(
    tmp_path: Path,
) -> None:
    _, current = _current_v1(tmp_path)
    request = _v2_request()
    proposed_v2 = _v2_plan(request, current)

    with pytest.raises(ReplanningContractError) as exc_info:
        MinimumDisruptionSelector(
            T011ReplanCandidateValidator(InMemoryTrustedFacts({}))
        ).select(
            current_plan=current,
            candidates=(ReplanCandidate(plan=proposed_v2, satisfaction_loss=0),),
        )

    assert exc_info.value.code == "T011_CANDIDATE_FACTS_NOT_FOUND"


def test_fact_snapshot_tampering_fails_closed_even_when_all_snapshot_checks_pass(
    tmp_path: Path,
) -> None:
    _, current = _current_v1(tmp_path)
    original_request = _v2_request(route_price_cents=400)
    proposed_v2 = _v2_plan(original_request, current)
    tampered_request = _v2_request(route_price_cents=401)

    with pytest.raises(ReplanningContractError) as exc_info:
        MinimumDisruptionSelector(
            T011ReplanCandidateValidator(
                InMemoryTrustedFacts({proposed_v2.plan_id: tampered_request})
            )
        ).select(
            current_plan=current,
            candidates=(ReplanCandidate(plan=proposed_v2, satisfaction_loss=0),),
        )

    assert exc_info.value.code == "T011_CANDIDATE_SNAPSHOT_MISMATCH"
    assert all(
        item.status.value == "PASS" for item in proposed_v2.constraints_snapshot
    )


def test_recomputed_hard_failure_rejects_forged_pass_snapshot(
    tmp_path: Path,
) -> None:
    _, current = _current_v1(tmp_path)
    valid_request = _v2_request()
    proposed_v2 = _v2_plan(valid_request, current)

    payload = _fixture_payload()
    payload["request"]["taskFacts"][0]["title"] = "参观城市博物馆（调整后）"
    payload["request"]["taskFacts"][0]["route"]["priceReference"][
        "amountCents"
    ] = 400
    payload["request"]["taskFacts"][0]["route"][
        "walkingDistanceMeters"
    ] = 1200
    unsafe_facts = _request(payload)

    outcome = MinimumDisruptionSelector(
        T011ReplanCandidateValidator(
            InMemoryTrustedFacts({proposed_v2.plan_id: unsafe_facts})
        )
    ).select(
        current_plan=current,
        candidates=(ReplanCandidate(plan=proposed_v2, satisfaction_loss=0),),
    )

    assert isinstance(outcome, NoFeasibleReplan)
    assert "CARE.ROUTE.WALK_SEGMENT_LIMIT" in outcome.affected_rule_ids
    assert any(
        item.rule_id == "CARE.ROUTE.WALK_SEGMENT_LIMIT"
        and item.description == "Use a shorter walking segment"
        for item in outcome.relaxations
    )
    assert all(
        item.status.value == "PASS" for item in proposed_v2.constraints_snapshot
    )


def test_execution_expense_is_recomputed_with_remaining_plan_budget(
    tmp_path: Path,
) -> None:
    _, current = _current_v1(tmp_path)
    request = _v2_request()
    proposed_v2 = _v2_plan(request, current)
    expense = _event(
        current,
        suffix=1,
        task_id="task-museum",
        event_type=ExecutionEventType.EXPENSE,
        amount_cents=30_000,
    )

    outcome = MinimumDisruptionSelector(
        T011ReplanCandidateValidator(
            InMemoryTrustedFacts({proposed_v2.plan_id: request})
        )
    ).select(
        current_plan=current,
        candidates=(ReplanCandidate(plan=proposed_v2, satisfaction_loss=0),),
        events=(expense,),
    )

    assert isinstance(outcome, NoFeasibleReplan)
    assert "REPLAN.BUDGET.ACTUAL_PLUS_REMAINING" in outcome.affected_rule_ids
    assert any(
        item.rule_id == "REPLAN.BUDGET.ACTUAL_PLUS_REMAINING"
        and "larger budget cap" in item.description
        for item in outcome.relaxations
    )


def test_terminal_task_expense_is_not_counted_again_as_remaining_cost(
    tmp_path: Path,
) -> None:
    _, current = _current_v1(tmp_path)
    request = _request(_fixture_payload())
    proposed_v2 = _v2_plan(request, current)
    events = (
        _event(
            current,
            suffix=2,
            task_id="task-museum",
            event_type=ExecutionEventType.EXPENSE,
            amount_cents=5_300,
        ),
        _event(
            current,
            suffix=3,
            task_id="task-museum",
            event_type=ExecutionEventType.COMPLETE,
        ),
    )

    outcome = MinimumDisruptionSelector(
        T011ReplanCandidateValidator(
            InMemoryTrustedFacts({proposed_v2.plan_id: request})
        )
    ).select(
        current_plan=current,
        candidates=(ReplanCandidate(plan=proposed_v2, satisfaction_loss=0),),
        events=events,
    )

    assert isinstance(outcome, SelectedReplan)
    assert outcome.frozen_task_ids == ("task-museum",)
    budget_checks = [
        item
        for item in outcome.validation_report.checks
        if item.rule_id == "REPLAN.BUDGET.ACTUAL_PLUS_REMAINING"
    ]
    assert len(budget_checks) == 1
    assert budget_checks[0].status.value == "PASS"
