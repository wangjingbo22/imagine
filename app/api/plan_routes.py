from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from app.application.plan_service import PlanVersionService
from app.domain.models import ApiResponse
from app.schemas.plan import ProposedPlanVersion
from app.schemas.validation_error import (
    TripSchemaError,
    ValidationIssue,
    issues_from_pydantic,
)


router = APIRouter(prefix="/api/v1", tags=["Plan V1 确认与状态守卫"])


def get_plan_service(request: Request) -> PlanVersionService:
    return request.app.state.plan_version_service


@router.post(
    "/trips/{trip_id}/plan-versions",
    summary="登记待确认的 Plan V1",
    description="校验并持久化不可变的方案、约束快照和可信来源快照。",
)
async def register_plan_version(
    trip_id: UUID,
    request: Request,
    service: PlanVersionService = Depends(get_plan_service),
) -> ApiResponse:
    try:
        proposal = ProposedPlanVersion.model_validate_json(
            await request.body(),
            strict=True,
        )
    except ValidationError as error:
        raise TripSchemaError(issues_from_pydantic(error.errors())) from error

    if proposal.trip_snapshot.trip_id != trip_id:
        raise TripSchemaError(
            [
                ValidationIssue(
                    path="tripSnapshot.tripId",
                    code="trip_id_mismatch",
                    message="tripSnapshot.tripId 必须与请求路径中的 tripId 一致",
                )
            ]
        )
    return ApiResponse(data=service.register_proposed(proposal))


@router.post(
    "/trips/{trip_id}/plan-versions/{plan_id}/confirm",
    summary="确认 Plan V1",
    description="将 PROPOSED 原子迁移为唯一 CURRENT，并把 Trip 迁移到 CONFIRMED。",
)
async def confirm_plan_version(
    trip_id: UUID,
    plan_id: UUID,
    service: PlanVersionService = Depends(get_plan_service),
) -> ApiResponse:
    return ApiResponse(data=service.confirm(trip_id, plan_id))


@router.post(
    "/trips/{trip_id}/execution/start",
    summary="开始执行行程",
    description="只有存在 CURRENT Plan V1 且 Trip 已确认时才允许开始执行。",
)
async def start_execution(
    trip_id: UUID,
    service: PlanVersionService = Depends(get_plan_service),
) -> ApiResponse:
    return ApiResponse(data=service.start_execution(trip_id))


@router.get(
    "/trips/{trip_id}",
    summary="恢复 Trip 与 Plan V1",
    description="用于刷新后恢复 Trip 状态、任务、金额、城市编码和单日输入快照。",
)
async def get_trip(
    trip_id: UUID,
    service: PlanVersionService = Depends(get_plan_service),
) -> ApiResponse:
    return ApiResponse(data=service.get_trip_state(trip_id))
