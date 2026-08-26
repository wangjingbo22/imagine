from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.application.recommendation_service import (
    RecommendationOrchestrationError,
    RecommendationOrchestrationService,
)
from app.core.errors import AppError
from app.domain.models import ApiResponse
from app.services.recommendation import (
    RecommendationOrchestrationRequest,
    RecommendationOrchestrationResult,
)


router = APIRouter(prefix="/api/v1", tags=["多人公平推荐编排"])


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


@router.post(
    "/trips/{trip_id}/recommendations",
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


__all__ = ["router"]
