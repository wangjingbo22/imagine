from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.application.collaboration_service import CollaborationService
from app.core.errors import AppError
from app.domain.collaboration import (
    InvitationCreateRequest,
    InvitationRedeemRequest,
    ParticipantConversationRequest,
    ParticipantMutationRequest,
    ResolveConfirmationItemRequest,
)
from app.domain.models import ApiResponse


router = APIRouter(prefix="/api/v2", tags=["S2 成员确认与硬冲突"])


def service(request: Request) -> CollaborationService:
    return request.app.state.collaboration_service


def require_idempotency_key(request: Request) -> str:
    value = request.headers.get("Idempotency-Key")
    if value is None or not 16 <= len(value) <= 128 or any(
        not 32 <= ord(char) <= 126 for char in value
    ):
        raise AppError(
            "IDEMPOTENCY_KEY_REQUIRED",
            "Idempotency-Key 必须是 16 至 128 个 printable ASCII 字符",
            400,
            False,
        )
    return value


def require_member_session(request: Request) -> str:
    token = request.headers.get("X-Participant-Session")
    if not token:
        raise AppError("PARTICIPANT_SESSION_REQUIRED", "缺少成员会话凭证", 401, False)
    return token


def require_organizer_token(request: Request) -> str:
    token = request.headers.get("X-Organizer-Token")
    if not token:
        raise AppError("ORGANIZER_PERMISSION_REQUIRED", "缺少组织者凭证", 403, False)
    return token


@router.post("/trips/conversations")
async def create_organizer() -> ApiResponse:
    raise AppError(
        code="TRIP_DRAFT_REVISION_UNAVAILABLE",
        message="该入口等待 T002 TripDraftRevision 接力",
        http_status=503,
        retryable=True,
    )


@router.post("/trips/{trip_id}/participants/{participant_id}/invitations")
async def create_invitation(
    trip_id: UUID,
    participant_id: UUID,
    payload: InvitationCreateRequest,
    request: Request,
    response: Response,
    current: CollaborationService = Depends(service),
) -> ApiResponse:
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(data=current.create_invitation(
        trip_id=trip_id,
        participant_id=participant_id,
        organizer_token=require_organizer_token(request),
        expected_version=payload.expected_version,
        idempotency_key=require_idempotency_key(request),
        expires_in_hours=payload.expires_in_hours,
    ))


@router.post("/participant-invitations/redeem")
async def redeem_invitation(
    payload: InvitationRedeemRequest,
    request: Request,
    response: Response,
    current: CollaborationService = Depends(service),
) -> ApiResponse:
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(data=current.redeem_invitation(
        token=payload.token,
        idempotency_key=require_idempotency_key(request),
    ))


@router.get("/member-session")
async def member_session(
    request: Request,
    current: CollaborationService = Depends(service),
) -> ApiResponse:
    return ApiResponse(data=current.member_view(require_member_session(request)))


@router.put("/member-session/conversation")
async def submit_member(
    payload: ParticipantConversationRequest,
    request: Request,
    current: CollaborationService = Depends(service),
) -> ApiResponse:
    return ApiResponse(data=await current.submit_member(
        session_token=require_member_session(request),
        request=payload,
        idempotency_key=require_idempotency_key(request),
    ))


@router.post("/member-session/confirm")
async def confirm_member(
    payload: ParticipantMutationRequest,
    request: Request,
    current: CollaborationService = Depends(service),
) -> ApiResponse:
    return ApiResponse(data=current.confirm_member(
        session_token=require_member_session(request),
        request=payload,
        idempotency_key=require_idempotency_key(request),
    ))


@router.post("/member-session/confirmation-items/{item_id}/resolve")
async def resolve_member_issue(
    item_id: str,
    payload: ResolveConfirmationItemRequest,
    request: Request,
    response: Response,
    current: CollaborationService = Depends(service),
) -> ApiResponse:
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(data=current.resolve_member_issue(
        session_token=require_member_session(request),
        item_id=item_id,
        request=payload,
        idempotency_key=require_idempotency_key(request),
    ))


@router.post("/trips/{trip_id}/participants/{participant_id}/confirm")
async def confirm_organizer(
    trip_id: UUID,
    participant_id: UUID,
    payload: ParticipantMutationRequest,
    request: Request,
    current: CollaborationService = Depends(service),
) -> ApiResponse:
    return ApiResponse(data=current.confirm_organizer(
        trip_id=trip_id,
        participant_id=participant_id,
        organizer_token=require_organizer_token(request),
        request=payload,
        idempotency_key=require_idempotency_key(request),
    ))


@router.get("/trips/{trip_id}/collaboration")
async def state(
    trip_id: UUID,
    request: Request,
    current: CollaborationService = Depends(service),
) -> ApiResponse:
    return ApiResponse(data=current.organizer_state(
        trip_id,
        require_organizer_token(request),
    ))


@router.post("/trips/{trip_id}/confirmation-items/{item_id}/resolve")
async def resolve_organizer_issue(
    trip_id: UUID,
    item_id: str,
    payload: ResolveConfirmationItemRequest,
    request: Request,
    response: Response,
    current: CollaborationService = Depends(service),
) -> ApiResponse:
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(data=current.resolve_organizer_issue(
        trip_id=trip_id,
        item_id=item_id,
        request=payload,
        organizer_token=require_organizer_token(request),
        idempotency_key=require_idempotency_key(request),
    ))


@router.delete("/trips/{trip_id}/participants/{participant_id}/invitations/{invitation_id}")
async def revoke_invitation(
    trip_id: UUID,
    participant_id: UUID,
    invitation_id: UUID,
    expected_version: int = Query(ge=1, alias="expectedVersion"),
    request: Request = None,  # type: ignore[assignment]
    current: CollaborationService = Depends(service),
) -> ApiResponse:
    if request is None:  # pragma: no cover - FastAPI always injects Request
        raise AppError("ORGANIZER_PERMISSION_REQUIRED", "缺少组织者凭证", 403, False)
    return ApiResponse(data=current.revoke_invitation(
        trip_id=trip_id,
        participant_id=participant_id,
        invitation_id=invitation_id,
        organizer_token=require_organizer_token(request),
        expected_version=expected_version,
        idempotency_key=require_idempotency_key(request),
    ))
