from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.planning_access import build_planning_access
from app.application.collaboration_ports import PlanningOperation
from app.application.recommendation_service import (
    MemberPreference,
    ProviderFactRestoreError,
    RecommendationOrchestrationError,
    RecommendationOrchestrationService,
)
from app.core.errors import AppError
from app.domain.models import ApiResponse
from app.domain.recommendation import FactRef
from app.infrastructure.provider_fact_registry import SqliteProviderFactRegistry
from app.services.recommendation import (
    ProviderFactSetSummary,
    RecommendationOrchestrationRequest,
    RecommendationOrchestrationResult,
)


router = APIRouter(tags=["S2 可信候选推荐"])


def get_recommendation_service(
    request: Request,
) -> RecommendationOrchestrationService:
    service = request.app.state.recommendation_service
    if not isinstance(service, RecommendationOrchestrationService) or (
        service.readiness_guard is not request.app.state.collaboration_readiness_guard
    ):
        raise AppError(
            code="RECOMMENDATION_SERVICE_UNAVAILABLE",
            message="推荐编排依赖尚未配置",
            http_status=503,
            retryable=True,
        )
    return service


def get_provider_fact_registry(request: Request) -> SqliteProviderFactRegistry:
    registry = request.app.state.provider_fact_registry
    if not isinstance(registry, SqliteProviderFactRegistry):
        raise AppError(
            code="PROVIDER_FACT_REGISTRY_UNAVAILABLE",
            message="FactRef 注册表尚未配置",
            http_status=503,
            retryable=True,
        )
    return registry


@router.get(
    "/api/v1/trips/{trip_id}/provider-fact-sets/{fact_set_id}",
    summary="核验服务端签发的 FactRef 摘要",
    description=(
        "只按 factSetId/digest 恢复服务端快照并返回来源摘要；不接受客户端"
        "内嵌地点、路线、价格或 Provenance。"
    ),
)
async def get_provider_fact_set_summary(
    trip_id: UUID,
    fact_set_id: str,
    provider_fact_digest: str = Query(alias="providerFactDigest"),
    registry: SqliteProviderFactRegistry = Depends(get_provider_fact_registry),
) -> ApiResponse[ProviderFactSetSummary]:
    try:
        snapshot = registry.restore_snapshot(trip_id, fact_set_id)
    except ProviderFactRestoreError as error:
        raise AppError(
            code=error.code,
            message=error.message,
            http_status=409,
        ) from error
    if snapshot.provider_fact_digest != provider_fact_digest:
        raise AppError(
            code="PROVIDER_FACT_DIGEST_MISMATCH",
            message="请求摘要与服务端签发的 FactRef 摘要不一致",
            http_status=409,
        )
    return ApiResponse[ProviderFactSetSummary](data=snapshot.summary())


@router.post(
    "/api/v1/trips/{trip_id}/recommendations",
    summary="从服务端 FactRef 生成唯一公平推荐",
)
async def recommend_unique_plan(
    trip_id: UUID,
    command: RecommendationOrchestrationRequest,
    http_request: Request,
    service: RecommendationOrchestrationService = Depends(
        get_recommendation_service
    ),
) -> ApiResponse[RecommendationOrchestrationResult]:
    access = build_planning_access(
        http_request, trip_id, PlanningOperation.RECOMMENDATION
    )
    try:
        result = await service.recommend(
            trip_id=trip_id,
            request=command,
            access=access,
        )
    except RecommendationOrchestrationError as error:
        raise AppError(
            code=error.code,
            message=error.message,
            http_status=error.http_status,
        ) from error
    return ApiResponse[RecommendationOrchestrationResult](data=result)


@router.get("/api/v2/trips/{trip_id}/recommendations")
async def recommendations(trip_id: UUID, request: Request) -> ApiResponse:
    """Build recommendations only from the guarded current revision."""
    organizer_token = request.headers.get("X-Organizer-Token")
    access = build_planning_access(
        request, trip_id, PlanningOperation.RECOMMENDATION
    )
    guard = request.app.state.collaboration_readiness_guard
    collaboration = request.app.state.collaboration_service
    with guard.operation(access):
        revision = collaboration.ready_revision(trip_id, organizer_token)
        # Resolve the shared v1/v2 orchestrator only after the authoritative
        # collaboration check, so an unavailable T002 revision still stops all
        # Provider/model calls with its original error.
        orchestration = get_recommendation_service(request)
        trip = revision.understanding.trip
        city = await request.app.state.location_service.resolve_city(
            trip.city_name or ""
        )
        members = revision.understanding.participants
        interests = [interest for item in members for interest in item.interests]
        must_visit = [place for item in members for place in item.must_visit]
        avoid_places = [place for item in members for place in item.avoid_places]
        places = await request.app.state.location_service.search_places(
            city.cityContext,
            keywords=" ".join(interests) or "景点",
            types=[],
            page=1,
            page_size=25,
        )
        facts = [
            FactRef(factRefId=f"AMAP:{place.placeId}", place=place)
            for place in places.places
        ]
        member_preferences = [
            MemberPreference(
                participant_id=str(revision.member_bindings[item.member_key]),
                interests=tuple(item.interests),
                must_visit=tuple(item.must_visit),
            )
            for item in members
        ]
        care_need_labels = [
            label
            for item in members
            if item.care_draft is not None
            for label in (
                item.care_draft.assistance_type_hint,
                "避开楼梯" if item.care_draft.avoid_stairs else None,
            )
            if label is not None
        ]
        try:
            bundle = await orchestration.recommend_preview_from_provider_facts(
                trip_id=trip_id,
                facts=facts,
                city_code=city.cityContext.city_code,
                interests=interests,
                must_visit=must_visit,
                avoid_places=avoid_places,
                care_need_labels=care_need_labels,
                members=member_preferences,
            )
        except RecommendationOrchestrationError as error:
            raise AppError(
                code=error.code,
                message=error.message,
                http_status=error.http_status,
            ) from error
        return ApiResponse(data=bundle)


__all__ = ["router"]
