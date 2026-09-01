from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.recommendation_routes import (
    PROVIDER_SEARCH_RADIUS_METERS,
    _provider_places_for_term,
)
from app.schemas.trip import GeoPoint


@pytest.mark.asyncio
async def test_provider_places_use_confirmed_start_instead_of_prefecture_center() -> None:
    confirmed_start = GeoPoint(longitude=120.641527, latitude=27.783699)
    prefecture_center = GeoPoint(longitude=120.699279, latitude=27.993849)
    calls: list[dict[str, object]] = []

    class ProviderStub:
        async def nearby_places(self, city_context: object, **kwargs: object):
            calls.append({"city_context": city_context, **kwargs})
            return SimpleNamespace(places=[])

        async def search_places(self, *_args: object, **_kwargs: object):
            raise AssertionError("city-wide search must not replace nearby search")

    city_context = SimpleNamespace(
        city_code="330300",
        center=prefecture_center,
    )
    resolution = SimpleNamespace(cityContext=city_context)

    places = await _provider_places_for_term(
        ProviderStub(),
        city_resolution=resolution,
        center=confirmed_start,
        keywords="景点",
    )

    assert places == []
    assert calls == [{
        "city_context": city_context,
        "center": confirmed_start,
        "radius_meters": PROVIDER_SEARCH_RADIUS_METERS,
        "keywords": "景点",
        "types": [],
        "page": 1,
        "page_size": 25,
    }]


@pytest.mark.asyncio
async def test_hard_must_visit_uses_citywide_search_instead_of_nearby_radius() -> None:
    """硬性必去地点不能因为离出发地较远而从候选白名单中消失。"""

    citywide_calls: list[dict[str, object]] = []

    class ProviderStub:
        async def nearby_places(self, *_args: object, **_kwargs: object):
            raise AssertionError("hard must-visit must not use radius-limited nearby search")

        async def search_places(self, city_context: object, **kwargs: object):
            citywide_calls.append({"city_context": city_context, **kwargs})
            return SimpleNamespace(places=["天坛公园"])

    city_context = SimpleNamespace(city_code="110000")
    resolution = SimpleNamespace(cityContext=city_context)
    center = GeoPoint(longitude=116.40, latitude=39.90)

    places = await _provider_places_for_term(
        ProviderStub(),
        city_resolution=resolution,
        center=center,
        keywords="天坛",
        citywide=True,
    )

    assert places == ["天坛公园"]
    assert citywide_calls == [{
        "city_context": city_context,
        "keywords": "天坛",
        "types": [],
        "page": 1,
        "page_size": 25,
    }]
