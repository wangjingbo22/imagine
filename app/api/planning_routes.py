from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from app.application.planning_boundary_service import PlanningBoundaryService
from app.core.errors import AppError
from app.domain.models import ApiResponse
from app.schemas.planning import EventDrivenReplanRequest, ReplanGenerationRequest
from app.schemas.validation_error import TripSchemaError, issues_from_pydantic
from app.services.planning.models import (
    CandidatePlanRequest,
    CandidateReviewConfirmationRequest,
)


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


def require_s2_planning_ready(trip_id: UUID, request: Request) -> None:
    """S1 legacy trips pass through; S2 collaboration trips require organizer proof."""
    request.app.state.collaboration_service.assert_planning_ready(
        trip_id,
        request.headers.get("X-Organizer-Token"),
    )


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
    require_s2_planning_ready(trip_id, request)
    try:
        candidate_request = CandidatePlanRequest.model_validate_json(
            await request.body(),
            strict=True,
        )
    except ValidationError as error:
        raise TripSchemaError(issues_from_pydantic(error.errors())) from error
    return ApiResponse(data=service.generate_v1(trip_id, candidate_request))


@router.get(
    "/trips/{trip_id}/plan-reviews/{review_id}",
    summary="恢复待确认的候选事实",
    description="返回服务端持久化的价格、设施和来源确认清单。",
)
async def get_plan_review(
    trip_id: UUID,
    review_id: str,
    service: PlanningBoundaryService = Depends(get_planning_boundary),
) -> ApiResponse:
    return ApiResponse(data=service.get_review(trip_id, review_id))


@router.post(
    "/trips/{trip_id}/plan-reviews/{review_id}/confirm",
    summary="确认候选事实并签发 Plan V1",
    description=(
        "逐项验证用户确认，将来源标记为 USER_CONFIRMED，服务端重新计算全部约束；"
        "只有完整 PASS 才签发 Plan V1。重复提交相同内容保持幂等。"
    ),
)
async def confirm_plan_review(
    trip_id: UUID,
    review_id: str,
    request: Request,
    service: PlanningBoundaryService = Depends(get_planning_boundary),
) -> ApiResponse:
    try:
        confirmation = CandidateReviewConfirmationRequest.model_validate_json(
            await request.body(),
            strict=True,
        )
    except ValidationError as error:
        raise TripSchemaError(issues_from_pydantic(error.errors())) from error
    return ApiResponse(
        data=service.confirm_review(trip_id, review_id, confirmation)
    )


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
    require_s2_planning_ready(trip_id, request)
    try:
        replan_request = ReplanGenerationRequest.model_validate_json(
            await request.body(),
            strict=True,
        )
    except ValidationError as error:
        raise TripSchemaError(issues_from_pydantic(error.errors())) from error
    return ApiResponse(data=service.generate_v2(trip_id, replan_request))


@router.post(
    "/trips/{trip_id}/replans/from-events",
    summary="Generate Plan V2 from persisted execution events",
    description=(
        "S1-T017 EXPENSE_CHANGE boundary. The browser sends no candidates, "
        "locked ids, facts, or free-text feedback."
    ),
)
async def generate_plan_v2_from_events(
    trip_id: UUID,
    request: Request,
    service: PlanningBoundaryService = Depends(get_planning_boundary),
) -> ApiResponse:
    require_s2_planning_ready(trip_id, request)
    try:
        replan_request = EventDrivenReplanRequest.model_validate_json(
            await request.body(),
            strict=True,
        )
    except ValidationError as error:
        raise TripSchemaError(issues_from_pydantic(error.errors())) from error
    return ApiResponse(data=service.generate_v2_from_events(trip_id, replan_request))


__all__ = ["router"]
