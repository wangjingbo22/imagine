from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.application.arrival_decision_service import ArrivalDecisionService
from app.domain.models import ApiResponse
from app.schemas.arrival_decision import ArrivalDecisionRequest


router = APIRouter(prefix="/api/v1", tags=["确定性到达判断"])


def get_arrival_decision_service(request: Request) -> ArrivalDecisionService:
    return request.app.state.arrival_decision_service


@router.post(
    "/trips/{trip_id}/arrival-decision",
    summary="计算距离并返回确定性到达判断",
)
async def decide_arrival(
    trip_id: UUID,
    payload: ArrivalDecisionRequest,
    service: ArrivalDecisionService = Depends(get_arrival_decision_service),
) -> ApiResponse:
    return ApiResponse(data=service.assess(trip_id, payload))


__all__ = ["router"]
