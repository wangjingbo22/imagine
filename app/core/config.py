from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    amap_web_service_key: str | None = None
    amap_base_url: str = "https://restapi.amap.com"
    amap_request_timeout_seconds: float = Field(default=8.0, gt=0, le=30)
    amap_cache_db_path: Path = Path("data/amap_cache.sqlite3")
    amap_place_cache_ttl_seconds: int = Field(default=86_400, ge=60)
    amap_route_cache_ttl_seconds: int = Field(default=1_800, ge=60)
    bailian_api_key: SecretStr | None = None
    account_api_key_encryption_key: SecretStr | None = None
    bailian_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_model: str = "qwen-plus"
    bailian_organizer_model: str = "qwen-turbo"
    bailian_request_timeout_seconds: float = Field(
        default=45.0,
        ge=8,
        le=45,
    )
    bailian_candidate_timeout_seconds: float = Field(
        default=10.0,
        ge=8,
        le=12,
    )
    bailian_execution_event_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=10,
    )
    bailian_replan_explanation_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=10,
    )
    plan_version_db_path: Path = Path("data/plan_versions.sqlite3")
    account_session_db_path: Path = Path("data/account.sqlite3")
    account_session_ttl_days: int = Field(default=14, ge=1, le=14)
    app_environment: Literal["development", "test", "production"] = "development"
    auth_cookie_secure: bool = False
    build_sha: str | None = Field(
        default=None,
        validation_alias=AliasChoices("BUILD_SHA", "RENDER_GIT_COMMIT"),
    )
    cors_allowed_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174"
    )

    @model_validator(mode="after")
    def validate_production_cookie_security(self) -> "Settings":
        if self.app_environment == "production" and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SECURE must be true in production")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
