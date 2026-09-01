from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.application.amap_service import AmapLocationService
from app.infrastructure.cache import SqliteProviderCache


class CityProviderStub:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses

    async def resolve_city(self, city_name: str) -> dict[str, Any]:
        return {"status": "1", "geocodes": [self.responses[city_name]]}


def location_service(
    tmp_path: Path,
    responses: dict[str, dict[str, Any]],
) -> AmapLocationService:
    return AmapLocationService(
        client=CityProviderStub(responses),  # type: ignore[arg-type]
        cache=SqliteProviderCache(tmp_path / "provider.sqlite3"),
        place_ttl_seconds=86_400,
        route_ttl_seconds=1_800,
    )


@pytest.mark.asyncio
async def test_district_and_city_queries_share_one_planning_city_code(
    tmp_path: Path,
) -> None:
    service = location_service(
        tmp_path,
        {
            "杭州西湖": {
                "formatted_address": "浙江省杭州市西湖区",
                "province": "浙江省",
                "city": "杭州市",
                "district": "西湖区",
                "citycode": "0571",
                "adcode": "330106",
                "location": "120.130396,30.259242",
            },
            "杭州市": {
                "formatted_address": "浙江省杭州市",
                "province": "浙江省",
                "city": "杭州市",
                "district": [],
                "citycode": "0571",
                "adcode": "330100",
                "location": "120.209903,30.246566",
            },
        },
    )

    district = await service.resolve_city("杭州西湖")
    city = await service.resolve_city("杭州市")

    assert district.cityContext.city_code == city.cityContext.city_code == "330100"
    assert district.cityContext.city_name == city.cityContext.city_name == "杭州市"
    assert district.adCode == "330106"
    assert city.adCode == "330100"


@pytest.mark.asyncio
async def test_county_level_city_and_prefecture_share_one_planning_city_code(
    tmp_path: Path,
) -> None:
    service = location_service(
        tmp_path,
        {
            "瑞安市": {
                "formatted_address": "浙江省温州市瑞安市",
                "province": "浙江省",
                "city": "温州市",
                "district": "瑞安市",
                "citycode": "0577",
                "adcode": "330381",
                "location": "120.655148,27.778657",
            },
            "温州市": {
                "formatted_address": "浙江省温州市",
                "province": "浙江省",
                "city": "温州市",
                "district": [],
                "citycode": "0577",
                "adcode": "330300",
                "location": "120.699279,27.993849",
            },
        },
    )

    county_level_city = await service.resolve_city("瑞安市")
    prefecture = await service.resolve_city("温州市")

    assert (
        county_level_city.cityContext.city_code
        == prefecture.cityContext.city_code
        == "330300"
    )
    assert (
        county_level_city.cityContext.city_name
        == prefecture.cityContext.city_name
        == "温州市"
    )
    assert county_level_city.adCode == "330381"
    assert prefecture.adCode == "330300"


@pytest.mark.asyncio
async def test_municipality_district_promotes_to_municipality_code(
    tmp_path: Path,
) -> None:
    service = location_service(
        tmp_path,
        {
            "北京朝阳": {
                "formatted_address": "北京市朝阳区",
                "province": "北京市",
                "city": [],
                "district": "朝阳区",
                "citycode": "010",
                "adcode": "110105",
                "location": "116.443108,39.921470",
            },
        },
    )

    resolution = await service.resolve_city("北京朝阳")

    assert resolution.cityContext.city_code == "110000"
    assert resolution.cityContext.city_name == "北京市"
    assert resolution.adCode == "110105"
