from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.application.arrival_evidence_service import ArrivalEvidenceService
from app.domain.models import ApiResponse
from app.schemas.arrival_evidence import CreateArrivalEvidence


router = APIRouter(prefix="/api/v1", tags=["一次定位与到达证据"])


def get_arrival_evidence_service(request: Request) -> ArrivalEvidenceService:
    return request.app.state.arrival_evidence_service


@router.post(
    "/trips/{trip_id}/arrival-evidence",
    summary="保存一次到达定位证据",
)
async def save_arrival_evidence(
    trip_id: UUID,
    payload: CreateArrivalEvidence,
    service: ArrivalEvidenceService = Depends(get_arrival_evidence_service),
) -> ApiResponse:
    return ApiResponse(data=service.save(trip_id, payload))


@router.get(
    "/trips/{trip_id}/arrival-evidence/{evidence_id}",
    summary="按证据 ID 恢复到达定位证据",
)
async def get_arrival_evidence(
    trip_id: UUID,
    evidence_id: UUID,
    service: ArrivalEvidenceService = Depends(get_arrival_evidence_service),
) -> ApiResponse:
    return ApiResponse(data=service.get(trip_id, evidence_id))


@router.get(
    "/trips/{trip_id}/arrival-evidence",
    summary="查询一次定位证据",
)
async def list_arrival_evidence(
    trip_id: UUID,
    task_id: str | None = Query(default=None, alias="taskId"),
    service: ArrivalEvidenceService = Depends(get_arrival_evidence_service),
) -> ApiResponse:
    return ApiResponse(
        data=service.list_for_trip(trip_id, task_id=task_id)
    )


__all__ = ["router"]
