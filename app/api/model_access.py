from __future__ import annotations

from typing import TypeAlias

from fastapi import Request

from app.core.errors import AppError


AccountModelCredentials: TypeAlias = tuple[str, str, str]


def require_account_model_credentials(request: Request) -> AccountModelCredentials:
    token = request.cookies.get("account_session")
    credentials = request.app.state.account_service.user_model_credentials(token)
    if credentials is None:
        raise AppError(
            code="ACCOUNT_MODEL_CONFIGURATION_REQUIRED",
            message="请先在模型设置中绑定 API Key 后再生成行程",
            http_status=403,
            retryable=False,
        )
    return credentials


__all__ = ["AccountModelCredentials", "require_account_model_credentials"]