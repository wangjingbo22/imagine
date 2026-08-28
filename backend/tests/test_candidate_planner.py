from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from app.application.plan_service import PlanVersionService
from app.application.collaboration_ports import PlanningOperation, ReadinessPermit
from app.domain.collaboration import TripFlowKind
from app.domain.models import FacilityType
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.schemas.plan import PlanVersion, PlanVersionStatus, ProposedPlanVersion
from app.services.planning import (
    CandidatePlan,
    CandidatePlanInputError,
    CandidatePlanRejected,
    CandidatePlanRequest,
    candidate_to_proposed_plan_version,
    candidate_to_proposed_plan_version_v2,
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


def _legacy_permit(trip_id, operation: PlanningOperation) -> ReadinessPermit:
    return ReadinessPermit(
        trip_id=trip_id,
        readiness_digest="legacy",
        operation_id="candidate-planner-legacy-0001",
        operation=operation,
        flow_kind=TripFlowKind.LEGACY_SINGLE,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )


def _payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _request(payload: dict[str, object] | None = None) -> CandidatePlanRequest:
    raw = (payload or _payload())["request"]
    return CandidatePlanRequest.model_validate_json(
        json.dumps(raw, ensure_ascii=False, separators=(",", ":")),
        strict=True,
    )


def _payload_for_trip_shape(mode: str, participant_count: int) -> dict[str, object]:
    payload = deepcopy(_payload())
    trip = payload["request"]["trip"]
    participants = trip["participants"]
    while len(participants) < participant_count:
        clone = deepcopy(participants[-1])
        clone["participantId"] = (
            f"10000000-0000-4000-8000-{len(participants) + 100:012d}"
        )
        clone["nickname"] = f"Member {len(participants) + 1}"
        participants.append(clone)
    trip["mode"] = mode
    trip["participants"] = participants[:participant_count]
    return payload


def _group_request(participant_count: int = 2) -> CandidatePlanRequest:
    return _request(_payload_for_trip_shape("GROUP", participant_count))


@pytest.mark.parametrize(
    ("mode", "participant_count"),
    [("SINGLE", 1), ("GROUP", 2), ("GROUP", 3)],
    ids=["single-one", "group-two", "group-three"],
)
def test_candidate_plan_request_accepts_the_mode_participant_matrix(
    mode: str,
    participant_count: int,
) -> None:
    request = _request(_payload_for_trip_shape(mode, participant_count))

    assert request.trip.mode.value == mode
    assert len(request.trip.participants) == participant_count


@pytest.mark.parametrize(
    ("mode", "participant_count"),
    [
        ("SINGLE", 0),
        ("SINGLE", 2),
        ("SINGLE", 3),
        ("GROUP", 0),
        ("GROUP", 1),
        ("GROUP", 4),
    ],
    ids=[
        "single-zero",
        "single-two",
        "single-three",
        "group-zero",
        "group-one",
        "group-four",
    ],
)
def test_candidate_plan_request_rejects_invalid_mode_participant_matrix(
    mode: str,
    participant_count: int,
) -> None:
    with pytest.raises(ValidationError):
        _request(_payload_for_trip_shape(mode, participant_count))


def test_candidate_planner_revalidates_model_copy_shape_bypass() -> None:
    valid_request = _request()
    invalid_trip = valid_request.trip.model_copy(
        update={
            "participants": [
                *valid_request.trip.participants,
                valid_request.trip.participants[0],
            ]
        }
    )
    invalid_request = valid_request.model_copy(update={"trip": invalid_trip})

    with pytest.raises(CandidatePlanInputError) as captured:
        generate_candidate_plan(invalid_request)

    assert captured.value.code == "CANDIDATE_PLAN_INPUT_INVALID"


@pytest.mark.parametrize("participant_count", [2, 3])
def test_group_candidate_plan_is_deterministic_for_two_or_three_members(
    participant_count: int,
) -> None:
    request = _group_request(participant_count)

    first = generate_candidate_plan(request)
    second = generate_candidate_plan(request)

    assert first == second
    assert len(request.trip.participants) == participant_count


@pytest.mark.parametrize("participant_count", [2, 3])
def test_group_candidate_can_be_bridged_to_plan_version(
    participant_count: int,
) -> None:
    request = _group_request(participant_count)
    candidate = generate_candidate_plan(request)

    proposal = candidate_to_proposed_plan_version(candidate, request)

    assert proposal.trip_snapshot.mode.value == "GROUP"
    assert [item.participant_id for item in proposal.trip_snapshot.participants] == [
        item.participant_id for item in request.trip.participants
    ]


@pytest.mark.parametrize("participant_count", [2, 3])
def test_group_candidate_can_enter_the_v2_plan_version_bridge(
    participant_count: int,
) -> None:
    request = _group_request(participant_count)
    candidate = generate_candidate_plan(request)
    v1 = candidate_to_proposed_plan_version(candidate, request)
    current = PlanVersion.model_validate({
        **v1.model_dump(),
        "status": PlanVersionStatus.CURRENT,
        "created_at": datetime.now(UTC),
    })

    proposal = candidate_to_proposed_plan_version_v2(candidate, request, current)

    assert proposal.version == 2
    assert proposal.trip_snapshot == current.trip_snapshot


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
    hard_results = [
        item for item in candidate.constraint_results if item.hardness == "HARD"
    ]
    facility_results = [
        item
        for item in candidate.constraint_results
        if item.rule_id.startswith("T010.FACILITY.")
    ]
    assert all(item.status is ValidationStatus.PASS for item in hard_results)
    assert len(facility_results) == 16
    assert all(
        item.hardness == "SOFT" and item.status is ValidationStatus.PASS
        for item in facility_results
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


def test_missing_facility_evidence_is_not_treated_as_pass() -> None:
    payload = _payload()
    payload["request"]["taskFacts"][0]["route"]["facilityEvidence"] = []
    request = _request(payload)

    candidate = generate_candidate_plan(request)

    assert candidate.metrics.validation_status == "NEEDS_CONFIRMATION"
    assert {item.reference_id for item in candidate.warnings} == {
        f"task-museum.routeFacility.{facility_type.value}"
        for facility_type in FacilityType
    }
    assert all(item.code == "UNKNOWN_FACILITY" for item in candidate.warnings)
    assert all("缺少" in item.message for item in candidate.warnings)
    assert all(
        item.hardness != "HARD" or item.status is ValidationStatus.PASS
        for item in candidate.constraint_results
    )

    with pytest.raises(CandidatePlanInputError) as exc_info:
        candidate_to_proposed_plan_version(candidate, request)
    assert exc_info.value.code == "CANDIDATE_CONFIRMATION_REQUIRED"


@pytest.mark.parametrize("shape", ["partial", "duplicate"])
def test_partial_or_duplicate_facility_types_cannot_be_treated_as_pass(
    shape: str,
) -> None:
    payload = _payload()
    evidence = payload["request"]["taskFacts"][0]["route"]["facilityEvidence"]
    if shape == "partial":
        payload["request"]["taskFacts"][0]["route"]["facilityEvidence"] = [
            evidence[0]
        ]
    else:
        evidence.append(deepcopy(evidence[0]))

    request = _request(payload)
    candidate = generate_candidate_plan(request)

    assert candidate.metrics.validation_status == "NEEDS_CONFIRMATION"
    facility_warnings = [
        item for item in candidate.warnings if item.code == "UNKNOWN_FACILITY"
    ]
    if shape == "partial":
        assert {item.reference_id for item in facility_warnings} == {
            f"task-museum.routeFacility.{facility_type.value}"
            for facility_type in (
                FacilityType.RAMP,
                FacilityType.NURSING_ROOM,
                FacilityType.ACCESSIBLE_ENTRANCE,
            )
        }
    else:
        assert [item.reference_id for item in facility_warnings] == [
            "task-museum.routeFacility.ELEVATOR"
        ]
        assert "重复" in facility_warnings[0].message

    with pytest.raises(CandidatePlanInputError) as exc_info:
        candidate_to_proposed_plan_version(candidate, request)
    assert exc_info.value.code == "CANDIDATE_CONFIRMATION_REQUIRED"


@pytest.mark.parametrize(
    ("facility_status", "source_status"),
    [
        ("NEEDS_CONFIRMATION", "ONLINE"),
        ("PASS", "UNKNOWN"),
    ],
    ids=["status-needs-confirmation", "source-unknown"],
)
def test_each_unconfirmed_facility_fact_has_an_independent_warning(
    facility_status: str,
    source_status: str,
) -> None:
    payload = _payload()
    evidence = payload["request"]["taskFacts"][0]["route"]["facilityEvidence"][0]
    evidence["status"] = facility_status
    evidence["provenance"]["sourceStatus"] = source_status

    candidate = generate_candidate_plan(_request(payload))

    facility_warnings = [
        item for item in candidate.warnings if item.code == "UNKNOWN_FACILITY"
    ]
    assert len(facility_warnings) == 1
    assert facility_warnings[0].reference_id == "task-museum.routeFacility.ELEVATOR"
    assert facility_warnings[0].field == "route.facilityEvidence.ELEVATOR"
    assert facility_warnings[0].resolution == "NEEDS_CONFIRMATION"
    assert candidate.metrics.validation_status == "NEEDS_CONFIRMATION"
    facility_result = next(
        item
        for item in candidate.constraint_results
        if item.rule_id == "T010.FACILITY.task-museum.ELEVATOR"
    )
    assert facility_result.hardness == "SOFT"
    assert facility_result.status is ValidationStatus.NEEDS_CONFIRMATION


def test_confirmed_facility_failure_is_preserved_as_a_soft_plan_snapshot() -> None:
    payload = _payload()
    evidence = payload["request"]["taskFacts"][0]["route"]["facilityEvidence"][0]
    evidence["status"] = "FAIL"
    evidence["message"] = "该路线没有可用电梯"
    request = _request(payload)

    candidate = generate_candidate_plan(request)

    assert candidate.metrics.validation_status == "PASS"
    assert candidate.warnings == ()
    facility_result = next(
        item
        for item in candidate.constraint_results
        if item.rule_id == "T010.FACILITY.task-museum.ELEVATOR"
    )
    assert facility_result.hardness == "SOFT"
    assert facility_result.status is ValidationStatus.FAIL
    assert facility_result.observed["message"] == "该路线没有可用电梯"

    proposal = candidate_to_proposed_plan_version(candidate, request)
    snapshot = next(
        item
        for item in proposal.constraints_snapshot
        if item.rule_id == "T010.FACILITY.task-museum.ELEVATOR"
    )
    assert snapshot.hardness.value == "SOFT"
    assert snapshot.status.value == "FAIL"
    assert snapshot.details["message"] == "该路线没有可用电梯"


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
    expected_facility_sources = {
        (
            f"{task.task_id}.routeFacility.{evidence.facilityType.value}"
        ): evidence.provenance
        for task in request.task_facts
        for evidence in task.route.facilityEvidence
    }
    actual_facility_sources = {
        item.reference_id: item
        for item in proposal.sources_snapshot
        if item.reference_id is not None and ".routeFacility." in item.reference_id
    }
    assert set(actual_facility_sources) == set(expected_facility_sources)
    for reference_id, provenance in expected_facility_sources.items():
        snapshot = actual_facility_sources[reference_id]
        assert snapshot.provider == provenance.provider
        assert snapshot.source_status.value == provenance.sourceStatus.value
        assert snapshot.fetched_at == provenance.fetchedAt
        assert snapshot.is_stale == provenance.isStale

    service = PlanVersionService(
        SqlitePlanVersionRepository(tmp_path / "plans.sqlite3")
    )
    stored = service.register_proposed(
        proposal,
        readiness_permit=_legacy_permit(
            proposal.trip_snapshot.trip_id,
            PlanningOperation.GENERATE_V1,
        ),
    )
    assert stored.status is PlanVersionStatus.PROPOSED
    assert stored.plan_id == proposal.plan_id
    assert stored.model_dump(exclude={"status", "created_at", "confirmed_at"}) == (
        proposal.model_dump()
    )
