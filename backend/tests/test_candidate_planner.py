from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from app.application.plan_service import PlanVersionService
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.schemas.plan import PlanVersionStatus, ProposedPlanVersion
from app.services.planning import (
    CandidatePlan,
    CandidatePlanInputError,
    CandidatePlanRejected,
    CandidatePlanRequest,
    candidate_to_proposed_plan_version,
    generate_candidate_plan,
    generate_proposed_plan_version,
)
from app.services.route_risk import ValidationStatus


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "planning"
    / "golden_candidate_plan.json"
)


def _payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _request(payload: dict[str, object] | None = None) -> CandidatePlanRequest:
    raw = (payload or _payload())["request"]
    return CandidatePlanRequest.model_validate_json(
        json.dumps(raw, ensure_ascii=False, separators=(",", ":")),
        strict=True,
    )


def test_golden_same_city_facts_produce_the_reviewed_candidate() -> None:
    expected = _payload()["expected"]
    candidate = generate_candidate_plan(_request())

    assert candidate.candidate_id == expected["candidateId"]
    assert [item.task_id for item in candidate.tasks] == expected["taskIds"]
    assert [item.cost_cents for item in candidate.tasks] == expected["taskCostCents"]
    assert candidate.metrics.model_dump(mode="json", by_alias=True) == expected["metrics"]
    assert [item.rule_id for item in candidate.constraint_results] == expected[
        "constraintRuleIds"
    ]
    assert all(
        item.hardness == "HARD" and item.status is ValidationStatus.PASS
        for item in candidate.constraint_results
    )
    assert candidate.warnings == ()


@pytest.mark.parametrize(
    ("mutation", "expected_rule", "expected_reference"),
    [
        (
            lambda payload: payload["request"]["taskFacts"][0]["route"].update(
                {"walkingDistanceMeters": 1200}
            ),
            "CARE.ROUTE.WALK_SEGMENT_LIMIT",
            "route-home-museum",
        ),
        (
            lambda payload: payload["request"]["taskFacts"][2].update(
                {"startAt": "13:30:00", "endAt": "15:00:00"}
            ),
            "CARE.DAY.NAP_WINDOW",
            "task-park",
        ),
        (
            lambda payload: (
                payload["request"]["taskFacts"][-1].update(
                    {"endLocationText": "错误返程地点"}
                ),
                payload["request"]["taskFacts"][-1]["place"].update(
                    {"name": "错误返程地点"}
                ),
            ),
            "CARE.DAY.RETURN_BY",
            "task-return",
        ),
    ],
    ids=["route-walk", "nap-window", "return-location"],
)
def test_any_recomputed_hard_failure_returns_no_candidate(
    mutation,
    expected_rule: str,
    expected_reference: str,
) -> None:
    payload = _payload()
    mutation(payload)

    with pytest.raises(CandidatePlanRejected) as exc_info:
        generate_candidate_plan(_request(payload))

    assert exc_info.value.code == "CANDIDATE_PLAN_REJECTED"
    assert len(exc_info.value.results) == 1
    result = exc_info.value.results[0]
    assert result.rule_id == expected_rule
    assert result.status is ValidationStatus.FAIL
    assert result.reference_id == expected_reference


def test_integer_cent_amounts_are_recomputed_from_place_and_route_facts() -> None:
    original = generate_candidate_plan(_request())
    payload = _payload()
    route_price = payload["request"]["taskFacts"][0]["route"]["priceReference"]
    route_price["amountCents"] = 423

    changed = generate_candidate_plan(_request(payload))

    assert original.metrics.known_total_cost_cents == 13300
    assert changed.tasks[0].cost_cents == 5423
    assert changed.metrics.total_cost_cents == 13423
    assert changed.metrics.known_total_cost_cents == 13423
    assert changed.metrics.known_budget_buffer_cents == 18577
    assert changed.candidate_id != original.candidate_id


def test_non_integer_amount_is_rejected_at_the_fact_boundary() -> None:
    payload = _payload()
    payload["request"]["taskFacts"][0]["place"]["priceReference"][
        "amountCents"
    ] = 50.5

    with pytest.raises(ValidationError):
        _request(payload)


def test_unknown_price_is_not_zero_and_is_independently_confirmable() -> None:
    payload = _payload()
    price = payload["request"]["taskFacts"][0]["route"]["priceReference"]
    price["amountCents"] = None
    price["provenance"]["sourceStatus"] = "UNKNOWN"
    request = _request(payload)

    candidate = generate_candidate_plan(request)

    assert candidate.tasks[0].cost_cents is None
    assert candidate.tasks[0].known_cost_cents == 5000
    assert candidate.metrics.total_cost_cents is None
    assert candidate.metrics.known_total_cost_cents == 13000
    assert candidate.metrics.unknown_amount_count == 1
    assert candidate.metrics.validation_status == "NEEDS_CONFIRMATION"
    assert [item.model_dump(mode="json", by_alias=True) for item in candidate.warnings] == [
        {
            "code": "UNKNOWN_PRICE",
            "severity": "WARNING",
            "resolution": "NEEDS_CONFIRMATION",
            "referenceId": "task-museum.routePrice",
            "field": "priceReference.amountCents",
            "message": "价格未知，未计入已知金额小计",
        }
    ]
    assert all(
        item.hardness != "HARD" or item.status is ValidationStatus.PASS
        for item in candidate.constraint_results
    )

    with pytest.raises(CandidatePlanInputError) as exc_info:
        candidate_to_proposed_plan_version(candidate, request)
    assert exc_info.value.code == "CANDIDATE_CONFIRMATION_REQUIRED"


def test_fixed_input_returns_exactly_one_deterministic_candidate() -> None:
    request = _request()

    first = generate_candidate_plan(request)
    second = generate_candidate_plan(request)

    assert type(first) is CandidatePlan
    assert "candidates" not in CandidatePlan.model_fields
    assert first == second
    assert first.model_dump_json(by_alias=True) == second.model_dump_json(by_alias=True)


def test_both_three_and_four_task_shapes_return_one_candidate() -> None:
    four = generate_candidate_plan(_request())
    payload = _payload()
    del payload["request"]["taskFacts"][2]
    payload["request"]["taskFacts"][-1]["order"] = 3
    payload["request"]["taskFacts"][-1]["route"]["origin"] = payload[
        "request"
    ]["taskFacts"][1]["place"]["location"]
    three = generate_candidate_plan(_request(payload))

    assert type(four) is CandidatePlan and len(four.tasks) == 4
    assert type(three) is CandidatePlan and len(three.tasks) == 3


@pytest.mark.parametrize("count", [2, 5])
def test_task_count_outside_three_to_four_is_rejected(count: int) -> None:
    payload = _payload()
    facts = payload["request"]["taskFacts"]
    if count == 2:
        payload["request"]["taskFacts"] = facts[:2]
    else:
        extra = deepcopy(facts[-1])
        extra["taskId"] = "task-extra"
        extra["route"]["routeId"] = "route-extra"
        extra["order"] = 5
        payload["request"]["taskFacts"] = [*facts, extra]

    with pytest.raises(ValidationError):
        _request(payload)


def test_cross_city_facts_and_tampered_confirmed_constraints_fail_closed() -> None:
    cross_city = _payload()
    cross_city["request"]["taskFacts"][0]["place"]["cityCode"] = "310000"
    with pytest.raises(CandidatePlanInputError) as city_error:
        generate_candidate_plan(_request(cross_city))
    assert city_error.value.code == "CROSS_CITY_FACT"

    tampered = _payload()
    del tampered["request"]["confirmedConstraints"][0]
    with pytest.raises(CandidatePlanInputError) as constraint_error:
        generate_candidate_plan(_request(tampered))
    assert constraint_error.value.code == "CONFIRMED_CONSTRAINTS_MISMATCH"


@pytest.mark.parametrize(
    ("mutation", "expected_code", "expected_field"),
    [
        (
            lambda payload: payload["request"]["taskFacts"][0]["route"].update(
                {"durationSeconds": 7_200}
            ),
            "ROUTE_SCHEDULE_INVALID",
            "taskFacts[0].route.durationSeconds",
        ),
        (
            lambda payload: payload["request"]["taskFacts"][1]["route"].update(
                {"origin": {"longitude": 120.0, "latitude": 30.0}}
            ),
            "ROUTE_CHAIN_INVALID",
            "taskFacts[1].route.origin",
        ),
        (
            lambda payload: (
                payload["request"]["taskFacts"][-1]["place"].update(
                    {"location": {"longitude": 116.5, "latitude": 39.8}}
                ),
                payload["request"]["taskFacts"][-1]["route"].update(
                    {"destination": {"longitude": 116.5, "latitude": 39.8}}
                ),
            ),
            "RETURN_ENDPOINT_MISMATCH",
            "taskFacts[-1].route.destination",
        ),
    ],
    ids=[
        "route-does-not-fit-before-task",
        "route-chain-is-disconnected",
        "return-text-cannot-mask-wrong-coordinate",
    ],
)
def test_route_timeline_and_continuity_fail_closed(
    mutation,
    expected_code: str,
    expected_field: str,
) -> None:
    payload = _payload()
    mutation(payload)

    with pytest.raises(CandidatePlanInputError) as exc_info:
        generate_candidate_plan(_request(payload))

    assert exc_info.value.code == expected_code
    assert exc_info.value.field == expected_field


def test_pass_candidate_converts_and_registers_without_schema_translation(
    tmp_path: Path,
) -> None:
    request = _request()
    candidate = generate_candidate_plan(request)

    proposal = candidate_to_proposed_plan_version(candidate, request)
    direct = generate_proposed_plan_version(request)

    assert type(proposal) is ProposedPlanVersion
    assert proposal == direct
    expected = _payload()["expected"]
    assert str(proposal.plan_id) == expected["proposedPlanId"]
    assert proposal.trip_snapshot.status.value == "PLAN_REVIEW"
    assert proposal.metrics.total_cost_cents == 13300
    assert [item.cost_cents for item in proposal.days[0].tasks] == [
        5300,
        6500,
        1200,
        300,
    ]
    assert all(item.status.value == "PASS" for item in proposal.constraints_snapshot)
    assert len(proposal.sources_snapshot) == expected["proposedSourceCount"]

    service = PlanVersionService(SqlitePlanVersionRepository(tmp_path / "plans.sqlite3"))
    stored = service.register_proposed(proposal)
    assert stored.status is PlanVersionStatus.PROPOSED
    assert stored.plan_id == proposal.plan_id
    assert stored.model_dump(exclude={"status", "created_at", "confirmed_at"}) == (
        proposal.model_dump()
    )
