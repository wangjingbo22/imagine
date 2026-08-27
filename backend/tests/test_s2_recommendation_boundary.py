from datetime import UTC, datetime

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
