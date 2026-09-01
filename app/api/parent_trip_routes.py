from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from app.application.parent_trip_service import ParentTripService
from app.core.errors import AppError
from app.domain.models import ApiResponse
from app.domain.parent_trip import ParentTripCreateRequest, ParentTripDayLinkRequest

router = APIRouter(prefix="/api/v3/parent-trips", tags=["S3 多日父行程"])

def service(request: Request) -> ParentTripService: return request.app.state.parent_trip_service
def token(value: str | None) -> str:
    if value is None or not 32 <= len(value) <= 128:
        raise AppError("PARENT_TRIP_PERMISSION_REQUIRED", "缺少父行程组织者凭证。", 403, False)
    return value

@router.post("")
def create(payload: ParentTripCreateRequest, x_parent_trip_token: str | None = Header(None),
           current: ParentTripService = Depends(service)) -> ApiResponse:
    return ApiResponse(data=current.create(payload, token(x_parent_trip_token)))

@router.get("/{parent_trip_id}")
def get(parent_trip_id: UUID, x_parent_trip_token: str | None = Header(None),
        current: ParentTripService = Depends(service)) -> ApiResponse:
    return ApiResponse(data=current.get(parent_trip_id, token(x_parent_trip_token)))

@router.put("/{parent_trip_id}/days/{day_index}/child")
def link(parent_trip_id: UUID, day_index: int, payload: ParentTripDayLinkRequest,
         x_parent_trip_token: str | None = Header(None),
         x_organizer_token: str | None = Header(None),
         current: ParentTripService = Depends(service)) -> ApiResponse:
    if not x_organizer_token: raise AppError("ORGANIZER_PERMISSION_REQUIRED", "缺少子行程组织者凭证。", 403, False)
    return ApiResponse(data=current.link_day(parent_trip_id, day_index, payload.child_trip_id,
        token(x_parent_trip_token), x_organizer_token))
