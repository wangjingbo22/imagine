from functools import lru_cache
from pathlib import Path

from pydantic import Field
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
