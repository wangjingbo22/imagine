from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.trip import Participant, Preference, PreferenceType, Trip
from app.services.fairness import (
    DeterministicFairRecommendationService,
    FairRecommendationCandidate,
    FairnessInputError,
    NoFairCandidateError,
)
from app.services.planning.models import CandidatePlan, CandidatePlanRequest
from app.services.planning.planner import DeterministicCandidatePlanner


FIXTURE = Path(__file__).parent / "fixtures" / "planning" / "golden_candidate_plan.json"
DIGEST = "a" * 64


def _base_request() -> CandidatePlanRequest:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["request"]
    return CandidatePlanRequest.model_validate_json(
        json.dumps(raw, ensure_ascii=False),
        strict=True,
    )


def _base_plan() -> CandidatePlan:
    return DeterministicCandidatePlanner().generate(_base_request())


def _participant(
    nickname: str,
    interests: list[tuple[str, int]],
    *,
    must_visit: list[str] | None = None,
    avoid_places: list[str] | None = None,
    budget_cap_cents: int = 35_000,
) -> Participant:
    preferences = [
        Preference(
            type=PreferenceType.INTEREST,
            value=value,
            weight=weight,
            is_hard=False,
        )
        for value, weight in interests
    ]
    preferences.extend(
        Preference(
            type=PreferenceType.MUST_VISIT,
            value=value,
            weight=5,
            is_hard=True,
        )
        for value in must_visit or []
    )
    preferences.extend(
        Preference(
            type=PreferenceType.AVOID_PLACE,
            value=value,
            weight=5,
            is_hard=True,
        )
        for value in avoid_places or []
    )
    return Participant(
        participant_id=uuid4(),
        nickname=nickname,
        budget_cap_cents=budget_cap_cents,
        preferences=preferences,
        assistance_profile=None,
    )


def _trip(*participants: Participant) -> Trip:
    payload = _base_request().trip.model_dump(mode="json", by_alias=True)
    payload["mode"] = "GROUP" if 2 <= len(participants) <= 3 else "SINGLE"
    payload["participants"] = [
        participant.model_dump(mode="json", by_alias=True)
        for participant in participants
    ]
    return Trip.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )


def _candidate(
    candidate_id: str,
    labels: tuple[str, str, str],
    *,
    cost_cents: int = 12_000,
    detour_meters: int = 1_000,
    digest: str = DIGEST,
) -> FairRecommendationCandidate:
    payload = _base_plan().model_dump(mode="python")
    payload["candidate_id"] = candidate_id
    tasks = list(payload["tasks"])[: len(labels)]
    split_costs = [cost_cents // 3, cost_cents // 3, cost_cents - 2 * (cost_cents // 3)]
    for index, (task, label, task_cost) in enumerate(zip(tasks, labels, split_costs)):
        task["title"] = label
        task["category"] = label
        task["end_location_text"] = label
        task["place_id"] = f"place-{candidate_id}-{index}"
        task["cost_cents"] = task_cost
        task["known_cost_cents"] = task_cost
        task["unknown_amount_count"] = 0
    payload["tasks"] = tuple(tasks)
    payload["metrics"]["total_cost_cents"] = cost_cents
    payload["metrics"]["known_total_cost_cents"] = cost_cents
    payload["metrics"]["unknown_amount_count"] = 0
    payload["metrics"]["total_walk_meters"] = sum(
        task["walk_meters"] for task in tasks
    )
    payload["metrics"]["transfer_count"] = sum(
        task["transfer_count"] for task in tasks
    )
    payload["metrics"]["known_budget_buffer_cents"] = (
        payload["metrics"]["budget_limit_cents"] - cost_cents
    )
    plan = CandidatePlan.model_validate(payload)
    return FairRecommendationCandidate(
        plan=plan,
        provider_fact_digest=digest,
        detour_meters=detour_meters,
    )


def _two_member_trip() -> Trip:
    return _trip(
        _participant("成员甲", [("博物馆", 5), ("公园", 4)]),
        _participant("成员乙", [("美食", 5), ("购物", 4)]),
    )


def test_maximum_minimum_score_precedes_average_score() -> None:
    service = DeterministicFairRecommendationService()
    polarized = _candidate("candidate-polarized", ("博物馆", "公园", "购物"))
    balanced = _candidate("candidate-balanced", ("博物馆", "美食", "其它"))

    decision = service.select_unique(
        trip=_two_member_trip(),
        candidates=[polarized, balanced],
    )

    assert decision.selected_plan.candidate_id == "candidate-balanced"
    assert decision.selected_evaluation.minimum_score == 84
    assert decision.selected_evaluation.average_score == 84
    assert [item.score for item in decision.selected_evaluation.participant_scores] == [84, 84]


def test_three_member_group_emits_one_score_per_member() -> None:
    trip = _trip(
        _participant("成员甲", [("博物馆", 5)]),
        _participant("成员乙", [("美食", 5)]),
        _participant("成员丙", [("公园", 5)]),
    )

    decision = DeterministicFairRecommendationService().select_unique(
        trip=trip,
        candidates=[_candidate("candidate-three-members", ("博物馆", "美食", "公园"))],
    )

    assert trip.mode.value == "GROUP"
    assert [
        item.participant_id for item in decision.selected_evaluation.participant_scores
    ] == [participant.participant_id for participant in trip.participants]


def test_average_score_precedes_cost_when_minimum_ties() -> None:
    service = DeterministicFairRecommendationService()
    lower_average = _candidate(
        "candidate-lower-average",
        ("博物馆", "美食", "其它"),
        cost_cents=5_000,
    )
    higher_average = _candidate(
        "candidate-higher-average",
        ("博物馆", "公园", "美食"),
        cost_cents=20_000,
    )

    decision = service.select_unique(
        trip=_two_member_trip(),
        candidates=[lower_average, higher_average],
    )

    assert decision.selected_plan.candidate_id == "candidate-higher-average"
    assert decision.selected_evaluation.minimum_score == 84
    assert decision.selected_evaluation.average_score == 92


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (
            {"candidate_id": "candidate-expensive", "cost_cents": 15_000, "detour_meters": 500},
            {"candidate_id": "candidate-cheap", "cost_cents": 10_000, "detour_meters": 5_000},
            "candidate-cheap",
        ),
        (
            {"candidate_id": "candidate-detour", "cost_cents": 10_000, "detour_meters": 2_000},
            {"candidate_id": "candidate-direct", "cost_cents": 10_000, "detour_meters": 500},
            "candidate-direct",
        ),
        (
            {"candidate_id": "candidate-b", "cost_cents": 10_000, "detour_meters": 500},
            {"candidate_id": "candidate-a", "cost_cents": 10_000, "detour_meters": 500},
            "candidate-a",
        ),
    ],
)
def test_cost_then_detour_then_stable_id(
    left: dict[str, int | str],
    right: dict[str, int | str],
    expected: str,
) -> None:
    service = DeterministicFairRecommendationService()
    labels = ("博物馆", "公园", "美食购物")
    candidates = [
        _candidate(labels=labels, **left),
        _candidate(labels=labels, **right),
    ]

    decision = service.select_unique(trip=_two_member_trip(), candidates=candidates)

    assert decision.selected_plan.candidate_id == expected


def test_hard_must_visit_and_avoid_candidates_do_not_participate() -> None:
    trip = _trip(
        _participant(
            "组织者",
            [("历史", 5)],
            must_visit=["故宫"],
            avoid_places=["酒吧"],
        )
    )
    missing_must = _candidate("candidate-missing", ("博物馆", "公园", "餐厅"))
    contains_avoid = _candidate("candidate-avoid", ("故宫", "酒吧", "公园"))
    valid = _candidate("candidate-valid", ("故宫历史", "公园", "餐厅"))

    decision = DeterministicFairRecommendationService().select_unique(
        trip=trip,
        candidates=[missing_must, contains_avoid, valid],
    )

    assert decision.selected_plan.candidate_id == "candidate-valid"
    assert {item.rule_id for item in decision.hard_rejections} == {
        "FAIR.HARD.MUST_VISIT_MISSING",
        "FAIR.HARD.AVOID_PLACE_PRESENT",
    }


def test_all_hard_failures_return_no_winner() -> None:
    trip = _trip(_participant("组织者", [], must_visit=["故宫"]))

    with pytest.raises(NoFairCandidateError) as captured:
        DeterministicFairRecommendationService().select_unique(
            trip=trip,
            candidates=[_candidate("candidate-invalid", ("公园", "餐厅", "商场"))],
        )

    assert captured.value.code == "NO_FAIR_CANDIDATE"
    assert captured.value.rejections[0].rule_id == "FAIR.HARD.MUST_VISIT_MISSING"


def test_scores_have_traceable_rule_id_deductions() -> None:
    trip = _trip(_participant("成员甲", [("博物馆", 5), ("公园", 2)]))
    candidate = _candidate("candidate-score", ("博物馆", "餐厅", "商场"))

    decision = DeterministicFairRecommendationService().select_unique(
        trip=trip,
        candidates=[candidate],
    )

    score = decision.selected_evaluation.participant_scores[0]
    assert score.score == 92
    assert len(score.deductions) == 1
    assert score.deductions[0].rule_id == "FAIR.INTEREST.UNMET"
    assert score.deductions[0].points == 8
    assert score.deductions[0].preference_value == "公园"


def test_score_is_clamped_to_zero_after_traceable_deductions() -> None:
    trip = _trip(
        _participant(
            "成员甲",
            [(f"未满足兴趣{index}", 5) for index in range(1, 7)],
        )
    )
    candidate = _candidate("candidate-zero", ("博物馆", "餐厅", "商场"))

    decision = DeterministicFairRecommendationService().select_unique(
        trip=trip,
        candidates=[candidate],
    )

    score = decision.selected_evaluation.participant_scores[0]
    assert score.score == 0
    assert sum(item.points for item in score.deductions) == 120
    assert {item.rule_id for item in score.deductions} == {"FAIR.INTEREST.UNMET"}


def test_budget_cap_failure_is_excluded_as_hard_rule() -> None:
    trip = _trip(_participant("成员甲", [], budget_cap_cents=10_000))
    over_budget = _candidate("candidate-over-budget", ("公园", "餐厅", "商场"))
    affordable = _candidate(
        "candidate-affordable",
        ("公园", "餐厅", "商场"),
        cost_cents=9_000,
    )

    decision = DeterministicFairRecommendationService().select_unique(
        trip=trip,
        candidates=[over_budget, affordable],
    )

    assert decision.selected_plan.candidate_id == "candidate-affordable"
    assert decision.hard_rejections[0].candidate_id == "candidate-over-budget"
    assert decision.hard_rejections[0].rule_id == "FAIR.HARD.BUDGET_CAP_EXCEEDED"


def test_repeated_run_returns_same_winner_and_payload() -> None:
    service = DeterministicFairRecommendationService()
    trip = _two_member_trip()
    candidates = [
        _candidate("candidate-b", ("博物馆", "公园", "美食购物")),
        _candidate("candidate-a", ("博物馆", "公园", "美食购物")),
    ]

    first = service.select_unique(trip=trip, candidates=candidates)
    second = service.select_unique(trip=trip, candidates=list(reversed(candidates)))

    assert first == second
    assert first.selected_plan.candidate_id == "candidate-a"


@pytest.mark.parametrize(
    "untrusted_field",
    ["satisfactionLoss", "satisfaction_loss", "selectionRationale"],
)
def test_untrusted_ranking_fields_are_rejected_by_strict_contract(
    untrusted_field: str,
) -> None:
    payload = _candidate(
        "candidate-contract",
        ("博物馆", "公园", "美食购物"),
    ).model_dump(mode="python")
    payload[untrusted_field] = 0

    with pytest.raises(ValidationError) as captured:
        FairRecommendationCandidate.model_validate(payload)

    assert captured.value.errors()[0]["type"] == "extra_forbidden"


def test_public_candidate_schema_has_no_client_owned_score_or_model_wording() -> None:
    schema = json.dumps(
        FairRecommendationCandidate.model_json_schema(),
        ensure_ascii=False,
    )

    assert "satisfactionLoss" not in schema
    assert "satisfaction_loss" not in schema
    assert "selectionRationale" not in schema


def test_mixed_provider_fact_digests_are_rejected_before_ranking() -> None:
    with pytest.raises(FairnessInputError) as captured:
        DeterministicFairRecommendationService().select_unique(
            trip=_two_member_trip(),
            candidates=[
                _candidate("candidate-a", ("博物馆", "公园", "美食购物")),
                _candidate(
                    "candidate-b",
                    ("博物馆", "公园", "美食购物"),
                    digest="b" * 64,
                ),
            ],
        )

    assert captured.value.code == "PROVIDER_FACT_DIGEST_MISMATCH"
