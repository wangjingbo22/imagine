from datetime import UTC, datetime

from app.application.recommendation_service import TrustedRecommendationService
from app.domain.models import Place, PriceFact, Provenance, SourceStatus
from app.domain.recommendation import CandidateRecommendation, FactRef, LlmRanking
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
