from uuid import UUID

from fastapi import APIRouter, Request

from app.application.recommendation_service import MemberPreference, TrustedRecommendationService
from app.domain.models import ApiResponse
from app.domain.recommendation import FactRef


router = APIRouter(prefix="/api/v2", tags=["S2 可信候选推荐"])


@router.get("/trips/{trip_id}/recommendations")
async def recommendations(trip_id: UUID, request: Request) -> ApiResponse:
    """Fetch provider facts only after the collaboration planning gate is open."""
    organizer_token = request.headers.get("X-Organizer-Token")
    collaboration = request.app.state.collaboration_service
    collaboration.assert_planning_ready(trip_id, organizer_token)
    state = collaboration.state(trip_id)
    parsed = [item.parsed for item in state.participants if item.parsed is not None]
    organizer = next(item.parsed for item in state.participants if item.is_organizer and item.parsed is not None)
    city = await request.app.state.location_service.resolve_city(organizer.city_name)
    interests = [interest for item in parsed for interest in item.interests]
    must_visit = [place for item in parsed for place in item.must_visit]
    avoid_places = [place for item in parsed for place in item.avoid_places]
    places = await request.app.state.location_service.search_places(
        city.cityContext,
        keywords=" ".join(interests) or "景点",
        types=[], page=1, page_size=25,
    )
    facts = [FactRef(factRefId=f"AMAP:{place.placeId}", place=place) for place in places.places]
    service = TrustedRecommendationService()
    candidates = service.issue_candidates(facts, interests=interests, must_visit=must_visit, avoid_places=avoid_places)
    ranked = service.rank(candidates, None)
    return ApiResponse(data=service.choose_single_plan(
        ranked,
        facts,
        [MemberPreference(
            participant_id=str(item.participant_id),
            interests=tuple(item.parsed.interests),
            must_visit=tuple(item.parsed.must_visit),
        ) for item in state.participants if item.parsed is not None],
    ))


__all__ = ["router"]
