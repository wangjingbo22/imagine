from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from app.application.parent_trip_service import ParentTripService
from app.core.errors import AppError
from app.domain.models import ApiResponse
from app.domain.parent_trip import (
    ParentTripCreateRequest,
    ParentTripDayBudgetUpdate,
    ParentTripDayLinkRequest,
    ParentTripInvitationCreateRequest,
    ParentTripMemberProfileUpdate,
)


router = APIRouter(tags=["S3 多日父行程"])


def service(request: Request) -> ParentTripService:
    return request.app.state.parent_trip_service


def organizer_token(value: str | None) -> str:
    if value is None or not 32 <= len(value) <= 128:
        raise AppError(
            "PARENT_TRIP_PERMISSION_REQUIRED",
            "缺少父行程组织者凭证。",
            403,
            False,
        )
    return value


def member_session(value: str | None) -> str:
    if value is None or not 32 <= len(value) <= 128:
        raise AppError(
            "PARENT_MEMBER_SESSION_REQUIRED",
            "缺少父行程成员会话凭证。",
            401,
            False,
        )
    return value


def idempotency_key(request: Request) -> str:
    value = request.headers.get("Idempotency-Key")
    if (
        value is None
        or not 16 <= len(value) <= 128
        or any(ord(character) < 32 or ord(character) > 126 for character in value)
    ):
        raise AppError(
            "IDEMPOTENCY_KEY_REQUIRED",
            "Idempotency-Key 必须是 16 至 128 个 printable ASCII 字符。",
            422,
            False,
        )
    return value


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.post("/api/v3/parent-trips")
def create(
    payload: ParentTripCreateRequest,
    response: Response,
    x_parent_trip_token: str | None = Header(None),
    current: ParentTripService = Depends(service),
) -> ApiResponse:
    no_store(response)
    return ApiResponse(
        data=current.create(payload, organizer_token(x_parent_trip_token))
    )


@router.get("/api/v3/parent-trips/{parent_trip_id}")
def get(
    parent_trip_id: UUID,
    response: Response,
    x_parent_trip_token: str | None = Header(None),
    current: ParentTripService = Depends(service),
) -> ApiResponse:
    no_store(response)
    return ApiResponse(
        data=current.get(parent_trip_id, organizer_token(x_parent_trip_token))
    )


@router.put("/api/v3/parent-trips/{parent_trip_id}/days/{day_index}/child")
def link(
    parent_trip_id: UUID,
    day_index: int,
    payload: ParentTripDayLinkRequest,
    response: Response,
    x_parent_trip_token: str | None = Header(None),
    x_organizer_token: str | None = Header(None),
    current: ParentTripService = Depends(service),
) -> ApiResponse:
    no_store(response)
    if not x_organizer_token:
        raise AppError(
            "ORGANIZER_PERMISSION_REQUIRED",
            "缺少子行程组织者凭证。",
            403,
            False,
        )
    return ApiResponse(
        data=current.link_day(
            parent_trip_id,
            day_index,
            payload.child_trip_id,
            organizer_token(x_parent_trip_token),
            x_organizer_token,
        )
    )


@router.put("/api/v3/parent-trips/{parent_trip_id}/days/{day_index}/budget")
def update_day_budget(
    parent_trip_id: UUID,
    day_index: int,
    payload: ParentTripDayBudgetUpdate,
    response: Response,
    x_parent_trip_token: str | None = Header(None),
    current: ParentTripService = Depends(service),
) -> ApiResponse:
    """仅允许持有父行程组织者凭证的客户端修改指定日期预算。"""
    no_store(response)
    return ApiResponse(
        data=current.update_day_budget(
            parent_trip_id,
            day_index,
            payload,
            organizer_token(x_parent_trip_token),
        )
    )


@router.post("/api/v3/parent-trips/{parent_trip_id}/invitations")
def create_invitation(
    parent_trip_id: UUID,
    payload: ParentTripInvitationCreateRequest,
    request: Request,
    response: Response,
    x_parent_trip_token: str | None = Header(None),
    current: ParentTripService = Depends(service),
) -> ApiResponse:
    no_store(response)
    return ApiResponse(
        data=current.create_invitation(
            parent_trip_id,
            organizer_token=organizer_token(x_parent_trip_token),
            expected_sync_version=payload.expected_sync_version,
            expires_in_hours=payload.expires_in_hours,
            idempotency_key=idempotency_key(request),
        )
    )


@router.get("/api/v3/parent-trips/{parent_trip_id}/sync")
def sync(
    parent_trip_id: UUID,
    response: Response,
    x_parent_trip_token: str | None = Header(None),
    x_parent_member_session: str | None = Header(None),
    current: ParentTripService = Depends(service),
) -> ApiResponse:
    no_store(response)
    if bool(x_parent_trip_token) == bool(x_parent_member_session):
        raise AppError(
            "PARENT_AUTH_CONTEXT_INVALID",
            "组织者凭证与成员会话必须且只能提供一个。",
            401,
            False,
        )
    return ApiResponse(
        data=current.sync(
            parent_trip_id,
            organizer_token=(
                organizer_token(x_parent_trip_token)
                if x_parent_trip_token
                else None
            ),
            member_session_token=(
                member_session(x_parent_member_session)
                if x_parent_member_session
                else None
            ),
        )
    )


@router.put("/api/v3/parent-trips/{parent_trip_id}/member-profile")
def update_member_profile(
    parent_trip_id: UUID,
    payload: ParentTripMemberProfileUpdate,
    response: Response,
    x_parent_member_session: str | None = Header(None),
    current: ParentTripService = Depends(service),
) -> ApiResponse:
    no_store(response)
    return ApiResponse(
        data=current.update_member_profile(
            parent_trip_id,
            member_session_token=member_session(x_parent_member_session),
            request=payload,
        )
    )
