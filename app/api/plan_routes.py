from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.application.planning_boundary_service import PlanningBoundaryService
from app.application.plan_service import PlanVersionService
from app.core.errors import AppError
from app.domain.models import ApiResponse


router = APIRouter(prefix="/api/v1", tags=["PlanVersion 状态与 Diff"])


def get_plan_service(request: Request) -> PlanVersionService:
    return request.app.state.plan_version_service


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


def require_s2_organizer(trip_id: UUID, request: Request) -> None:
    request.app.state.collaboration_service.assert_planning_ready(
        trip_id, request.headers.get("X-Organizer-Token")
    )


@router.post(
    "/trips/{trip_id}/plan-versions",
    summary="拒绝客户端直接登记 PlanVersion",
    description="PlanVersion 只能由服务端 T011/T018 可信规划边界生成并登记。",
)
async def register_plan_version(
    trip_id: UUID,
) -> ApiResponse:
    raise AppError(
        code="PLAN_VERSION_DIRECT_REGISTRATION_FORBIDDEN",
        message=(
            "禁止客户端直接登记 PlanVersion；请使用服务端 V1 生成或 V2 重规划接口"
        ),
        http_status=403,
        retryable=False,
        errors=[{"tripId": str(trip_id)}],
    )


@router.post(
    "/trips/{trip_id}/plan-versions/{plan_id}/confirm",
    summary="确认 Plan V1",
    description="将 PROPOSED 原子迁移为唯一 CURRENT，并把 Trip 迁移到 CONFIRMED。",
)
async def confirm_plan_version(
    trip_id: UUID,
    plan_id: UUID,
    request: Request,
    service: PlanVersionService = Depends(get_plan_service),
    planning: PlanningBoundaryService = Depends(get_planning_boundary),
) -> ApiResponse:
    require_s2_organizer(trip_id, request)
    planning.require_v1_confirmation(trip_id, plan_id)
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
    summary="恢复 Trip 与 PlanVersion",
    description="用于刷新后恢复 Trip 状态、CURRENT 与待审核候选版本。",
)
async def get_trip(
    trip_id: UUID,
    service: PlanVersionService = Depends(get_plan_service),
) -> ApiResponse:
    return ApiResponse(data=service.get_trip_state(trip_id))


@router.get(
    "/trips/{trip_id}/plan-versions/{plan_id}/diff",
    summary="查看 V1/V2 Diff",
    description="由服务端比较不可变快照，返回地点、时间、路线、费用和关怀变化。",
)
async def get_plan_diff(
    trip_id: UUID,
    plan_id: UUID,
    service: PlanVersionService = Depends(get_plan_service),
) -> ApiResponse:
    return ApiResponse(data=service.get_diff(trip_id, plan_id))


@router.post(
    "/trips/{trip_id}/plan-versions/{plan_id}/accept",
    summary="接受 Plan V2",
    description="原子切换唯一 CURRENT，并将旧版本标记为 SUPERSEDED。",
)
async def accept_plan_v2(
    trip_id: UUID,
    plan_id: UUID,
    request: Request,
    service: PlanVersionService = Depends(get_plan_service),
    planning: PlanningBoundaryService = Depends(get_planning_boundary),
) -> ApiResponse:
    require_s2_organizer(trip_id, request)
    planning.require_v2_acceptance(trip_id, plan_id)
    return ApiResponse(data=service.accept_v2(trip_id, plan_id))


@router.post(
    "/trips/{trip_id}/plan-versions/{plan_id}/reject",
    summary="拒绝 Plan V2",
    description="将候选版本标记为 REJECTED，当前版本和执行状态保持不变。",
)
async def reject_plan_v2(
    trip_id: UUID,
    plan_id: UUID,
    request: Request,
    service: PlanVersionService = Depends(get_plan_service),
) -> ApiResponse:
    require_s2_organizer(trip_id, request)
    return ApiResponse(data=service.reject_v2(trip_id, plan_id))
