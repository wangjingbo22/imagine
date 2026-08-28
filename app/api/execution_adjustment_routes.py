from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.application.execution_event_draft_service import (
    ExecutionEventDraftService,
)
from app.application.workflow_service import WorkflowService
from app.domain.models import ApiResponse
from app.schemas.execution_adjustment import (
    CreateConfirmedExecutionAdjustmentEvent,
    EventConstraintSet,
    ExecutionConstraintCompileRequest,
    ExecutionEventDraft,
    ExecutionEventParseRequest,
)
from app.services.execution_adjustments import compile_execution_constraints


router = APIRouter(
    prefix="/api/v1/execution-adjustments",
    tags=["执行中迟到与疲劳调整"],
)


def get_execution_event_draft_service(request: Request) -> ExecutionEventDraftService:
    return request.app.state.execution_event_draft_service


def get_workflow_service(request: Request) -> WorkflowService:
    return request.app.state.workflow_service


@router.post(
    "/parse",
    response_model=ExecutionEventDraft,
    summary="解析迟到或疲劳事件草稿",
    description=(
        "百炼仅提取零写入草稿；歧义、超时或无模型时返回固定确认表单，"
        "不会写 ExecutionEvent、关怀画像、约束或 PlanVersion。"
    ),
)
async def parse_execution_adjustment(
    payload: ExecutionEventParseRequest,
    response: Response,
    service: ExecutionEventDraftService = Depends(
        get_execution_event_draft_service
    ),
) -> ExecutionEventDraft:
    outcome = await service.parse(payload)
    response.headers["X-Recognition-Source"] = outcome.recognition_source
    if outcome.recognition_model:
        response.headers["X-Recognition-Model"] = outcome.recognition_model
    if outcome.degraded_reason:
        response.headers["X-Degraded-Reason"] = outcome.degraded_reason
    return outcome.draft


@router.post(
    "/trips/{trip_id}/events",
    summary="确认并保存迟到或疲劳执行事件",
    description=(
        "草稿解析保持零写入；只有用户确认后的 LATE/FATIGUE 才会保存。"
        "同一 Trip 下相同 idempotencyKey 与相同内容返回原事件，不同内容返回冲突。"
    ),
)
async def create_confirmed_execution_adjustment_event(
    trip_id: UUID,
    event: CreateConfirmedExecutionAdjustmentEvent,
    service: WorkflowService = Depends(get_workflow_service),
) -> ApiResponse:
    return ApiResponse(data=service.create_adjustment_event(trip_id, event))


@router.get(
    "/trips/{trip_id}/events",
    summary="查询已确认的迟到或疲劳执行事件",
)
async def list_confirmed_execution_adjustment_events(
    trip_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
) -> ApiResponse:
    return ApiResponse(data=service.list_adjustment_events(trip_id))


@router.post(
    "/compile",
    response_model=EventConstraintSet,
    summary="把已确认事件转换为临时剩余约束",
    description=(
        "纯函数式转换；输出供 S2-T021 消费，不修改 T007 长期约束、"
        "AssistanceProfile 或 PlanVersion 状态。"
    ),
)
async def compile_confirmed_execution_adjustment(
    payload: ExecutionConstraintCompileRequest,
) -> EventConstraintSet:
    return compile_execution_constraints(payload)


__all__ = ["router"]
