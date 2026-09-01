from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.application.account_service import AccountService
from app.application.parent_trip_service import ParentTripService
from app.core.errors import AppError
from app.domain.account import (
    CurrentUser,
    LoginRequest,
    LogoutResult,
    ProfileUpdateRequest,
    RegisterRequest,
    ModelSettingsUpdateRequest, ModelSettingsView,
)
from app.domain.models import ApiResponse
from app.domain.parent_trip import ParentTripInvitationRedeemRequest


ACCOUNT_COOKIE_NAME = "account_session"
ACCOUNT_COOKIE_PATH = "/api"

router = APIRouter(prefix="/api/v1/account", tags=["账户"])


def get_account_service(request: Request) -> AccountService:
    return request.app.state.account_service


def get_parent_trip_service(request: Request) -> ParentTripService:
    return request.app.state.parent_trip_service


def _token(request: Request) -> str | None:
    return request.cookies.get(ACCOUNT_COOKIE_NAME)


def _idempotency_key(request: Request) -> str:
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


def _set_cookie(response: Response, token: str, request: Request) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=ACCOUNT_COOKIE_NAME,
        value=token,
        max_age=settings.account_session_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path=ACCOUNT_COOKIE_PATH,
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.post("/register")
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    service: AccountService = Depends(get_account_service),
) -> ApiResponse[CurrentUser]:
    user, token = service.register(payload)
    _set_cookie(response, token, request)
    _no_store(response)
    return ApiResponse(data=user)


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: AccountService = Depends(get_account_service),
) -> ApiResponse[CurrentUser]:
    user, token = service.login(payload)
    _set_cookie(response, token, request)
    _no_store(response)
    return ApiResponse(data=user)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    service: AccountService = Depends(get_account_service),
) -> ApiResponse[LogoutResult]:
    service.logout(_token(request))
    response.delete_cookie(
        key=ACCOUNT_COOKIE_NAME,
        path=ACCOUNT_COOKIE_PATH,
    )
    _no_store(response)
    return ApiResponse(data=LogoutResult())


@router.get("/me")
async def me(
    request: Request,
    response: Response,
    service: AccountService = Depends(get_account_service),
) -> ApiResponse[CurrentUser]:
    _no_store(response)
    return ApiResponse(data=service.current_user(_token(request)))


@router.put("/me/profile")
async def update_profile(
    payload: ProfileUpdateRequest,
    request: Request,
    response: Response,
    service: AccountService = Depends(get_account_service),
) -> ApiResponse[CurrentUser]:
    _no_store(response)
    return ApiResponse(data=service.update_profile(_token(request), payload))

@router.get("/me/model-settings")
async def model_settings(request: Request, response: Response, service: AccountService = Depends(get_account_service)) -> ApiResponse[ModelSettingsView]:
    _no_store(response); return ApiResponse(data=service.model_settings(_token(request)))

@router.put("/me/model-settings")
async def update_model_settings(payload: ModelSettingsUpdateRequest, request: Request, response: Response, service: AccountService = Depends(get_account_service)) -> ApiResponse[ModelSettingsView]:
    _no_store(response); return ApiResponse(data=service.update_model_settings(_token(request), payload))

@router.delete("/me/model-settings")
async def delete_model_settings(request: Request, response: Response, service: AccountService = Depends(get_account_service)) -> ApiResponse[ModelSettingsView]:
    service.delete_model_settings(_token(request)); _no_store(response); return ApiResponse(data=ModelSettingsView(configured=False))


@router.post("/parent-trip-invitations/redeem")
async def redeem_parent_trip_invitation(
    payload: ParentTripInvitationRedeemRequest,
    request: Request,
    response: Response,
    account_service: AccountService = Depends(get_account_service),
    parent_trip_service: ParentTripService = Depends(get_parent_trip_service),
) -> ApiResponse:
    _no_store(response)
    user = account_service.current_user(_token(request))
    return ApiResponse(
        data=parent_trip_service.redeem_invitation(
            token=payload.token,
            idempotency_key=_idempotency_key(request),
            account_user_id=user.user_id,
            display_name=user.display_name,
            interests=user.interests,
        )
    )
