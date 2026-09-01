from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.application.account_service import AccountService
from app.domain.account import (
    CurrentUser,
    LoginRequest,
    LogoutResult,
    ProfileUpdateRequest,
    RegisterRequest,
)
from app.domain.models import ApiResponse


ACCOUNT_COOKIE_NAME = "account_session"
ACCOUNT_COOKIE_PATH = "/api/v1/account"

router = APIRouter(prefix="/api/v1/account", tags=["账户"])


def get_account_service(request: Request) -> AccountService:
    return request.app.state.account_service


def _token(request: Request) -> str | None:
    return request.cookies.get(ACCOUNT_COOKIE_NAME)


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
