from pathlib import Path

import pytest

from app.application.amap_service import AmapLocationService
from app.schemas.trip import CityContext, GeoPoint, ProviderConfig
from app.infrastructure.cache import SqliteProviderCache


@pytest.fixture
def beijing() -> CityContext:
    return CityContext(
        country_code="CN",
        city_code="110000",
        city_name="北京市",
        center=GeoPoint(longitude=116.397499, latitude=39.908722),
        provider_config=ProviderConfig(provider="AMAP", coordinate_system="GCJ02"),
    )


@pytest.fixture
def shanghai() -> CityContext:
    return CityContext(
        country_code="CN",
        city_code="310000",
        city_name="上海市",
        center=GeoPoint(longitude=121.473701, latitude=31.230416),
        provider_config=ProviderConfig(provider="AMAP", coordinate_system="GCJ02"),
    )


def build_service(tmp_path: Path, client: object) -> AmapLocationService:
    return AmapLocationService(
        client=client,  # type: ignore[arg-type]
        cache=SqliteProviderCache(tmp_path / "cache.sqlite3"),
        place_ttl_seconds=86_400,
        route_ttl_seconds=1_800,
    )
