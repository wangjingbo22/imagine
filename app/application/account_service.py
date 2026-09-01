from __future__ import annotations

import secrets
import ipaddress
import socket
from urllib.parse import urlparse
from cryptography.fernet import Fernet, InvalidToken
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

from app.core.errors import AppError
from app.domain.account import (
    CurrentUser,
    LoginRequest,
    ProfileUpdateRequest,
    ModelSettingsUpdateRequest,
    ModelSettingsView,
    RegisterRequest,
    normalized_email,
)
from app.infrastructure.account_store import (
    AccountStoreError,
    SqliteAccountRepository,
)

MAX_SESSION_TTL_DAYS = 14


def validate_public_model_base_url(value: str) -> str:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as error:
        raise AppError(
            "ACCOUNT_MODEL_BASE_URL_INVALID",
            "模型 API 地址必须是有效的 HTTPS 地址",
            422,
            False,
        ) from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise AppError("ACCOUNT_MODEL_BASE_URL_INVALID", "模型 API 地址必须是有效的 HTTPS 地址", 422, False)
    if parsed.query or parsed.fragment or port not in (None, 443):
        raise AppError("ACCOUNT_MODEL_BASE_URL_FORBIDDEN", "该地址不在允许的公共 HTTPS 服务范围内", 422, False)
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname == "localhost":
        raise AppError("ACCOUNT_MODEL_BASE_URL_FORBIDDEN", "该地址不在允许的公共 HTTPS 服务范围内", 422, False)
    try:
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except (socket.gaierror, ValueError) as error:
        raise AppError("ACCOUNT_MODEL_ENDPOINT_UNAVAILABLE", "暂时无法连接模型服务，请稍后重试", 503, True) from error
    if not addresses or any(not address.is_global for address in addresses):
        raise AppError("ACCOUNT_MODEL_BASE_URL_FORBIDDEN", "该地址不在允许的公共 HTTPS 服务范围内", 422, False)
    return value.rstrip("/")


class AccountService:
    def __init__(
        self,
        repository: SqliteAccountRepository,
        *,
        session_ttl_days: int = 14,
        clock: Callable[[], datetime] | None = None,
        password_hash: PasswordHash | None = None,
        api_key_encryption_key: str | None = None,
    ) -> None:
        self.repository = repository
        self.session_ttl = timedelta(days=min(session_ttl_days, MAX_SESSION_TTL_DAYS))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._password_hash = password_hash or PasswordHash.recommended()
        self._cipher = Fernet(api_key_encryption_key.encode()) if api_key_encryption_key else None

    @staticmethod
    def _credentials_error() -> AppError:
        return AppError(
            "ACCOUNT_CREDENTIALS_INVALID",
            "邮箱或密码不正确",
            401,
            False,
        )

    @staticmethod
    def _session_error() -> AppError:
        return AppError(
            "ACCOUNT_SESSION_REQUIRED",
            "账户会话无效或已过期",
            401,
            False,
        )

    def _issue_session(self, user: CurrentUser) -> tuple[CurrentUser, str]:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        self.repository.create_session(
            token=token,
            user_id=user.user_id,
            expires_at=now + self.session_ttl,
        )
        return user, token

    def register(self, payload: RegisterRequest) -> tuple[CurrentUser, str]:
        password_hash = self._password_hash.hash(payload.password)
        try:
            stored = self.repository.create_user(
                email=normalized_email(payload.email),
                password_hash=password_hash,
                display_name=payload.display_name,
            )
        except AccountStoreError as error:
            if error.code == "ACCOUNT_EMAIL_TAKEN":
                raise AppError(
                    "ACCOUNT_EMAIL_TAKEN",
                    "该邮箱已注册",
                    409,
                    False,
                ) from error
            raise
        return self._issue_session(stored.current_user())

    def login(self, payload: LoginRequest) -> tuple[CurrentUser, str]:
        stored = self.repository.get_user_by_email(normalized_email(payload.email))
        if stored is None:
            raise self._credentials_error()
        try:
            valid = self._password_hash.verify(payload.password, stored.password_hash)
        except PwdlibError:
            valid = False
        if not valid:
            raise self._credentials_error()
        return self._issue_session(stored.current_user())

    def current_user(self, token: str | None) -> CurrentUser:
        if not token:
            raise self._session_error()
        stored = self.repository.get_user_by_session(token, now=self._clock())
        if stored is None:
            raise self._session_error()
        return stored.current_user()

    def update_profile(
        self,
        token: str | None,
        payload: ProfileUpdateRequest,
    ) -> CurrentUser:
        user = self.current_user(token)
        try:
            return self.repository.update_profile(user.user_id, payload).current_user()
        except AccountStoreError as error:
            if error.code == "ACCOUNT_USER_NOT_FOUND":
                raise self._session_error() from error
            raise

    def logout(self, token: str | None) -> None:
        if token:
            self.repository.revoke_session(token)

    def model_settings(self, token: str | None) -> ModelSettingsView:
        user = self.current_user(token)
        stored = self.repository.get_model_settings(user.user_id)
        return ModelSettingsView(
            configured=stored is not None,
            model=stored[0] if stored else None,
            base_url=stored[2] if stored else None,
        )

    def update_model_settings(self, token: str | None, payload: ModelSettingsUpdateRequest) -> ModelSettingsView:
        user = self.current_user(token)
        if self._cipher is None:
            raise AppError("ACCOUNT_KEY_STORAGE_UNAVAILABLE", "服务端未配置 API Key 加密密钥", 503, False)
        base_url = validate_public_model_base_url(payload.base_url)
        api_key = payload.api_key.get_secret_value()
        self.repository.save_model_settings(user.user_id, model=payload.model, encrypted_api_key=self._cipher.encrypt(api_key.encode()).decode(), base_url=base_url)
        return ModelSettingsView(
            configured=True,
            model=payload.model,
            base_url=base_url,
        )

    def delete_model_settings(self, token: str | None) -> None:
        self.repository.delete_model_settings(self.current_user(token).user_id)

    def user_model_credentials(self, token: str | None) -> tuple[str, str, str] | None:
        user = self.current_user(token)
        stored = self.repository.get_model_settings(user.user_id)
        return (stored[0], self._decrypt(stored[1]), stored[2]) if stored else None

    def _decrypt(self, value: str) -> str:
        if self._cipher is None:
            raise AppError("ACCOUNT_KEY_STORAGE_UNAVAILABLE", "服务端未配置 API Key 加密密钥", 503, False)
        try: return self._cipher.decrypt(value.encode()).decode()
        except (InvalidToken, UnicodeDecodeError) as error: raise AppError("ACCOUNT_KEY_STORAGE_UNAVAILABLE", "已保存的 API Key 无法读取", 503, False) from error
