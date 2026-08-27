from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.application.memory_timeline_service import MemoryTimelineService
from app.domain.models import ApiResponse


router = APIRouter(prefix="/api/v1", tags=["旅行回忆时间线"])


def get_memory_timeline_service(request: Request) -> MemoryTimelineService:
    return request.app.state.memory_timeline_service


@router.get(
    "/trips/{trip_id}/memory-timeline",
    summary="按实际发生时间聚合旅行回忆",
)
async def get_memory_timeline(
    trip_id: UUID,
    service: MemoryTimelineService = Depends(get_memory_timeline_service),
) -> ApiResponse:
    return ApiResponse(data=service.get(trip_id))


__all__ = ["router"]
