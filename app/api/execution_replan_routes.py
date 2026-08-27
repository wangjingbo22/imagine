from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from app.api.planning_access import build_planning_access
from app.application.collaboration_ports import PlanningOperation
from app.application.execution_replan_service import ExecutionReplanService
from app.core.errors import AppError
from app.domain.models import ApiResponse
from app.schemas.execution_replan import (
    ExecutionAdjustmentDecisionRequest,
    ExecutionAdjustmentReplanRequest,
)
from app.schemas.validation_error import TripSchemaError, issues_from_pydantic


router = APIRouter(
    prefix="/api/v1",
    tags=["执行中迟到与疲劳调整"],
)


def get_execution_replan_service(request: Request) -> ExecutionReplanService:
    service = request.app.state.execution_replan_service
    if not isinstance(service, ExecutionReplanService):
        raise AppError(
            code="EXECUTION_REPLAN_UNAVAILABLE",
            message="执行中重规划服务未配置",
            http_status=503,
            retryable=True,
        )
    return service


@router.post(
    "/trips/{trip_id}/replans/from-adjustment",
    summary="从已确认迟到或疲劳事件生成 Plan V2 候选与 Diff",
    description=(
        "服务端恢复 CURRENT 和可信事实，冻结已完成、已开始、当前及显式锁定任务，"
        "重编译 T020 临时约束并重验全部 HARD；候选在接受前不覆盖 CURRENT。"
    ),
)
async def create_execution_replan_preview(
    trip_id: UUID,
    request: Request,
    service: ExecutionReplanService = Depends(get_execution_replan_service),
) -> ApiResponse:
    access = build_planning_access(request, trip_id, PlanningOperation.GENERATE_V2)
    try:
        command = ExecutionAdjustmentReplanRequest.model_validate_json(
            await request.body(),
            strict=True,
        )
    except ValidationError as error:
        raise TripSchemaError(issues_from_pydantic(error.errors())) from error
    return ApiResponse(
        data=await service.create_preview(trip_id, command, access=access)
    )


@router.post(
    "/trips/{trip_id}/replans/{plan_id}/decision",
    summary="接受或拒绝服务端签发的执行调整候选",
    description=(
        "接受复用 PlanVersion 原子切换；拒绝保持原 CURRENT。"
        "两种决策都拒绝未签发候选。"
    ),
)
async def decide_execution_replan(
    trip_id: UUID,
    plan_id: UUID,
    request: Request,
    service: ExecutionReplanService = Depends(get_execution_replan_service),
) -> ApiResponse:
    access = build_planning_access(request, trip_id, PlanningOperation.PLAN_DECISION)
    try:
        command = ExecutionAdjustmentDecisionRequest.model_validate_json(
            await request.body(),
            strict=True,
        )
    except ValidationError as error:
        raise TripSchemaError(issues_from_pydantic(error.errors())) from error
    return ApiResponse(
        data=service.decide(trip_id, plan_id, command, access=access)
    )


__all__ = ["router"]
