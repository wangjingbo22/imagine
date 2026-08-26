from fastapi import APIRouter, Depends, Request, Response

from app.application.execution_event_draft_service import (
    ExecutionEventDraftService,
)
from app.schemas.execution_adjustment import (
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
