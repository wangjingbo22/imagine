from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from app.application.workflow_service import WorkflowService
from app.domain.models import ApiResponse
from app.schemas.execution import CreateExecutionEvent
from app.schemas.trip import AssistanceProfile
from app.schemas.validation_error import TripSchemaError, issues_from_pydantic


router = APIRouter(prefix="/api/v1", tags=["关怀约束与执行事件"])


def get_workflow_service(request: Request) -> WorkflowService:
    return request.app.state.workflow_service


@router.put("/trips/{trip_id}/constraints", summary="保存关怀约束草稿")
async def save_constraints(
    trip_id: UUID,
    request: Request,
    service: WorkflowService = Depends(get_workflow_service),
) -> ApiResponse:
    try:
        profile = AssistanceProfile.model_validate_json(
            await request.body(),
            strict=True,
        )
    except ValidationError as error:
        raise TripSchemaError(issues_from_pydantic(error.errors())) from error
    return ApiResponse(data=service.save_constraint_draft(trip_id, profile))


@router.post("/trips/{trip_id}/constraints/confirm", summary="确认关怀约束")
async def confirm_constraints(
    trip_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
) -> ApiResponse:
    return ApiResponse(data=service.confirm_constraints(trip_id))


@router.get("/trips/{trip_id}/constraints", summary="恢复关怀约束状态")
async def get_constraints(
    trip_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
) -> ApiResponse:
    return ApiResponse(data=service.get_constraints(trip_id))


@router.post("/trips/{trip_id}/events", summary="创建执行事件")
async def create_execution_event(
    trip_id: UUID,
    event: CreateExecutionEvent,
    service: WorkflowService = Depends(get_workflow_service),
) -> ApiResponse:
    return ApiResponse(data=service.create_event(trip_id, event))


@router.get("/trips/{trip_id}/events", summary="查询执行事件")
async def list_execution_events(
    trip_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
) -> ApiResponse:
    return ApiResponse(data=service.list_events(trip_id))


@router.get("/trips/{trip_id}/summary", summary="获取基础旅行总结")
async def get_trip_summary(
    trip_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
) -> ApiResponse:
    return ApiResponse(data=service.get_summary(trip_id))
