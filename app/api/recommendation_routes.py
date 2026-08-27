from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.application.recommendation_service import (
    MemberPreference,
    ProviderFactRestoreError,
    RecommendationOrchestrationError,
    RecommendationOrchestrationService,
    TrustedRecommendationService,
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
    if not isinstance(service, RecommendationOrchestrationService):
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
    description=(
        "客户端只提交服务端签发的 factSetId/digest；服务恢复事实，调用千问白名单"
        "候选提议，重建真实路线后执行 HARD 与公平排序。模型超时、格式错误、摘要"
        "不匹配或越界 ID 会自动切换确定性枚举，最终只返回一个 3—4 任务方案。"
    ),
)
async def recommend_unique_plan(
    trip_id: UUID,
    command: RecommendationOrchestrationRequest,
    service: RecommendationOrchestrationService = Depends(
        get_recommendation_service
    ),
) -> ApiResponse[RecommendationOrchestrationResult]:
    try:
        result = await service.recommend(trip_id=trip_id, request=command)
    except RecommendationOrchestrationError as error:
        raise AppError(
            code=error.code,
            message=error.message,
            http_status=error.http_status,
        ) from error
    return ApiResponse[RecommendationOrchestrationResult](data=result)


@router.get("/api/v2/trips/{trip_id}/recommendations")
async def recommendations(trip_id: UUID, request: Request) -> ApiResponse:
    """Fetch provider facts only after the collaboration planning gate is open."""
    organizer_token = request.headers.get("X-Organizer-Token")
    collaboration = request.app.state.collaboration_service
    collaboration.assert_planning_ready(trip_id, organizer_token)
    state = collaboration.state(trip_id)
    parsed = [item.parsed for item in state.participants if item.parsed is not None]
    organizer = next(
        item.parsed
        for item in state.participants
        if item.is_organizer and item.parsed is not None
    )
    city = await request.app.state.location_service.resolve_city(organizer.city_name)
    interests = [interest for item in parsed for interest in item.interests]
    must_visit = [place for item in parsed for place in item.must_visit]
    avoid_places = [place for item in parsed for place in item.avoid_places]
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
    service = TrustedRecommendationService()
    candidates = service.issue_candidates(
        facts,
        interests=interests,
        must_visit=must_visit,
        avoid_places=avoid_places,
    )
    ranked = service.rank(candidates, None)
    return ApiResponse(
        data=service.choose_single_plan(
            ranked,
            facts,
            [
                MemberPreference(
                    participant_id=str(item.participant_id),
                    interests=tuple(item.parsed.interests),
                    must_visit=tuple(item.parsed.must_visit),
                )
                for item in state.participants
                if item.parsed is not None
            ],
        )
    )


__all__ = ["router"]
