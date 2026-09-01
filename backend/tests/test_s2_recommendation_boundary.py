import json
from datetime import UTC, datetime

import pytest

from app.application.recommendation_service import MemberPreference, TrustedRecommendationService
from app.domain.models import Place, PriceFact, Provenance, SourceStatus
from app.domain.recommendation import CandidatePlace, CandidateRecommendation, FactRef, LlmRanking, MemberScore
from app.schemas.trip import GeoPoint


def _fact(place_id: str, name: str, *, category: str = "博物馆", price: int | None = 1000) -> FactRef:
    provenance = Provenance(sourceStatus=SourceStatus.ONLINE, fetchedAt=datetime.now(UTC))
    return FactRef(
        factRefId=f"amap:{place_id}",
        place=Place(
            placeId=place_id, name=name, cityCode="110000", location=GeoPoint(longitude=116.4, latitude=39.9),
            category=category,
            priceReference=PriceFact(amountCents=price, kind="门票", provenance=Provenance(sourceStatus=SourceStatus.UNKNOWN, fetchedAt=datetime.now(UTC)) if price is None else provenance),
            provenance=provenance,
        ),
    )


def test_facts_are_filtered_and_invalid_llm_ranking_falls_back() -> None:
    service = TrustedRecommendationService()
    candidates = service.issue_candidates(
        [_fact("a", "故宫"), _fact("b", "国博"), _fact("c", "避开景点")],
        interests=["博物馆"], must_visit=["故宫"], avoid_places=["避开景点"],
    )
    assert [item.place_id for item in candidates] == ["a", "b"]
    result = service.rank(candidates, LlmRanking(recommendations=[
        CandidateRecommendation(placeId="a", reason="想去"),
        CandidateRecommendation(placeId="a", reason="重复"),
    ]))
    assert result.used_deterministic_fallback is True
    assert [item.place_id for item in result.recommendations] == ["a", "b"]


def test_parent_memory_avoid_labels_match_provider_id_and_normalized_name() -> None:
    service = TrustedRecommendationService()

    candidates = service.issue_candidates(
        [
            _fact("remembered-id", "不同展示名"),
            _fact("other-id", "ＡＭＡＰ 博物馆"),
            _fact("branch-id", "AMAP 博物馆分馆"),
            _fact("kept-id", "城市公园"),
        ],
        interests=[],
        must_visit=[],
        avoid_places=["remembered-id", "AMAP 博物馆"],
    )

    assert [item.place_id for item in candidates] == ["branch-id", "kept-id"]


def test_valid_llm_ranking_is_only_allowed_place_ids_and_reasons() -> None:
    service = TrustedRecommendationService()
    candidates = service.issue_candidates([_fact("a", "故宫"), _fact("b", "国博")], interests=[], must_visit=[], avoid_places=[])
    result = service.rank(candidates, LlmRanking(recommendations=[CandidateRecommendation(placeId="b", reason="室内体验")]))
    assert result.used_deterministic_fallback is False
    assert result.recommendations[0].place_id == "b"


def test_non_json_or_extra_llm_fields_do_not_get_repaired_or_retried() -> None:
    service = TrustedRecommendationService()
    candidates = service.issue_candidates([_fact("a", "故宫")], interests=[], must_visit=[], avoid_places=[])
    result = service.rank_from_llm_json(candidates, '{"recommendations":[{"placeId":"a","reason":"x","price":1}]}')
    assert result.used_deterministic_fallback is True
    assert service.rank_from_llm_json(candidates, "not-json").used_deterministic_fallback is True


@pytest.mark.parametrize(
    "forbidden_reason",
    [
        "价格已经核验", "路线最短", "满意度最高", "PASS", "计划状态为 CURRENT",
        "PlanVersion 已创建",
    ],
)
def test_t031_forbidden_model_claims_fall_back_without_semantic_repair(
    forbidden_reason: str,
) -> None:
    service = TrustedRecommendationService()
    candidates = service.issue_candidates(
        [_fact("a", "故宫"), _fact("b", "国博")],
        interests=[],
        must_visit=[],
        avoid_places=[],
    )
    raw = json.dumps({
        "recommendations": [{"placeId": "a", "reason": forbidden_reason}],
    }, ensure_ascii=False)

    result = service.rank_from_llm_json(candidates, raw)

    assert result.used_deterministic_fallback is True
    assert [item.place_id for item in result.recommendations] == ["a", "b"]


@pytest.mark.parametrize(
    "recommendations",
    [
        [{"placeId": "a", "reason": "室内体验"}, {"placeId": "a", "reason": "重复"}],
        [{"placeId": "forged", "reason": "伪造地点"}],
    ],
)
def test_t031_duplicate_or_out_of_allowlist_ids_fall_back(
    recommendations: list[dict[str, str]],
) -> None:
    service = TrustedRecommendationService()
    candidates = service.issue_candidates(
        [_fact("a", "故宫"), _fact("b", "国博")],
        interests=[],
        must_visit=[],
        avoid_places=[],
    )

    result = service.rank_from_llm_json(
        candidates,
        json.dumps({"recommendations": recommendations}, ensure_ascii=False),
    )

    assert result.used_deterministic_fallback is True


def test_single_plan_exposes_member_scores_and_unknown_provider_facts() -> None:
    service = TrustedRecommendationService()
    facts = [_fact("a", "故宫", price=None), _fact("b", "国博")]
    bundle = service.rank(service.issue_candidates(facts, interests=[], must_visit=[], avoid_places=[]), None)
    result = service.choose_single_plan(bundle, facts, [
        MemberPreference(participant_id="member-a", interests=("博物馆",), must_visit=("故宫",)),
        MemberPreference(participant_id="member-b", interests=("博物馆",), must_visit=("国博",)),
    ])
    assert result.trusted_plan is not None
    assert {task.place_id for task in result.trusted_plan.tasks} == {"a", "b"}
    assert result.trusted_plan.lowest_member_score == min(item.score for item in result.trusted_plan.member_scores)
    assert "价格尚未由高德提供" in result.trusted_plan.unknown_facts[0]
    assert result.trusted_plan.compromises


def test_fairness_key_prefers_higher_lowest_member_score() -> None:
    tasks = [CandidatePlace(factRefId="AMAP:a", placeId="a", name="A")]
    facts = {"a": _fact("a", "A")}
    balanced = [MemberScore(participantId=str(index), score=80) for index in range(3)]
    unequal = [MemberScore(participantId=str(index), score=score) for index, score in enumerate((95, 95, 50))]
    assert TrustedRecommendationService._fairness_sort_key(tasks, balanced, facts) < TrustedRecommendationService._fairness_sort_key(tasks, unequal, facts)


def test_member_score_uses_traceable_interest_deductions_instead_of_fixed_70() -> None:
    tasks = [
        CandidatePlace(
            factRefId="AMAP:museum",
            placeId="museum",
            name="城市历史博物馆",
            category="科教文化服务;博物馆",
        )
    ]

    scores = TrustedRecommendationService._score_members(
        tasks,
        [
            MemberPreference(
                participant_id="history-member",
                interests=("历史文化",),
                must_visit=(),
            ),
            MemberPreference(
                participant_id="food-member",
                interests=("美食",),
                must_visit=(),
            ),
        ],
    )

    assert [item.score for item in scores] == [100, 80]
    assert scores[0].reasons == ["兴趣覆盖 1/1"]
    assert scores[1].penalty_rule_ids == ["FAIR.INTEREST.UNMET"]
    assert "扣 20 分" in scores[1].reasons[1]


def test_member_score_without_soft_preferences_is_explicitly_not_penalized() -> None:
    tasks = [CandidatePlace(factRefId="AMAP:a", placeId="a", name="公园")]

    score = TrustedRecommendationService._score_members(
        tasks,
        [MemberPreference(participant_id="member", interests=(), must_visit=())],
    )[0]

    assert score.score == 100
    assert score.reasons == ["未设置软兴趣，当前不扣兴趣分"]
