from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.application.arrival_execution_service import ArrivalExecutionService
from app.domain.models import ApiResponse
from app.schemas.arrival_execution import CreateArrivalExecutionEventRequest


router = APIRouter(prefix="/api/v1", tags=["到达证据执行事件"])


def get_arrival_execution_service(request: Request) -> ArrivalExecutionService:
    return request.app.state.arrival_execution_service


@router.post(
    "/trips/{trip_id}/arrival-events",
    summary="用已核验到达证据幂等完成任务",
)
async def create_arrival_event(
    trip_id: UUID,
    payload: CreateArrivalExecutionEventRequest,
    service: ArrivalExecutionService = Depends(get_arrival_execution_service),
) -> ApiResponse:
    return ApiResponse(data=service.complete_from_arrival(trip_id, payload))


@router.get(
    "/trips/{trip_id}/arrival-events",
    summary="从统一事件流恢复到达完成记录",
)
async def restore_arrival_events(
    trip_id: UUID,
    service: ArrivalExecutionService = Depends(get_arrival_execution_service),
) -> ApiResponse:
    events = [
        event
        for event in service.restore(trip_id)
        if event.arrival_evidence is not None
    ]
    return ApiResponse(data=events)


__all__ = ["router"]
