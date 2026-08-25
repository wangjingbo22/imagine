from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from app.application.planning_boundary_service import PlanningBoundaryService
from app.core.errors import AppError
from app.domain.models import ApiResponse
from app.schemas.planning import ReplanGenerationRequest
from app.schemas.validation_error import TripSchemaError, issues_from_pydantic
from app.services.planning.models import CandidatePlanRequest


router = APIRouter(prefix="/api/v1", tags=["服务端规划与重规划"])


def get_planning_boundary(request: Request) -> PlanningBoundaryService:
    service = request.app.state.planning_boundary_service
    if not isinstance(service, PlanningBoundaryService):
        raise AppError(
            code="PLANNING_BOUNDARY_UNAVAILABLE",
            message="服务端规划边界未配置",
            http_status=503,
            retryable=True,
        )
    return service


@router.get(
    "/trips/{trip_id}/planning-facts",
    summary="恢复当前服务端签发的规划事实",
    description=(
        "只返回 CURRENT PlanVersion（或尚未确认的签发 V1）对应的 "
        "CandidatePlanRequest；raw 未签发计划和摘要不一致均会被拒绝。"
    ),
)
async def get_planning_facts(
    trip_id: UUID,
    service: PlanningBoundaryService = Depends(get_planning_boundary),
) -> ApiResponse:
    return ApiResponse(data=service.get_planning_facts(trip_id))


@router.post(
    "/trips/{trip_id}/plan-versions/generate",
    summary="由服务端生成并登记 Plan V1",
    description=(
        "严格解析 CandidatePlanRequest，由 T011 重算 HARD 约束；仅完整 PASS "
        "候选会留下可信事实与摘要记录并登记为 PROPOSED。"
    ),
)
async def generate_plan_v1(
    trip_id: UUID,
    request: Request,
    service: PlanningBoundaryService = Depends(get_planning_boundary),
) -> ApiResponse:
    try:
        candidate_request = CandidatePlanRequest.model_validate_json(
            await request.body(),
            strict=True,
        )
    except ValidationError as error:
        raise TripSchemaError(issues_from_pydantic(error.errors())) from error
    return ApiResponse(data=service.generate_v1(trip_id, candidate_request))


@router.post(
    "/trips/{trip_id}/replans",
    summary="生成、选择并登记 Plan V2",
    description=(
        "读取服务端 CURRENT 与 ExecutionEvent，逐一执行 T011 校验，随后由 "
        "T018 选择最小扰动候选；只有 SELECTED 候选会登记为 PROPOSED。"
    ),
)
async def generate_plan_v2(
    trip_id: UUID,
    request: Request,
    service: PlanningBoundaryService = Depends(get_planning_boundary),
) -> ApiResponse:
    try:
        replan_request = ReplanGenerationRequest.model_validate_json(
            await request.body(),
            strict=True,
        )
    except ValidationError as error:
        raise TripSchemaError(issues_from_pydantic(error.errors())) from error
    return ApiResponse(data=service.generate_v2(trip_id, replan_request))


__all__ = ["router"]
