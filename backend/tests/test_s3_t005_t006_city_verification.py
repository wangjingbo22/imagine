from __future__ import annotations

import os
import sqlite3
from math import ceil
from pathlib import Path
from typing import Any

import pytest

from app.application.amap_service import (
    AmapLocationService,
    _price_fact,
    _route_price,
)
from app.application.route_risk_adapter import route_snapshot_to_risk_input
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.models import Provenance, SourceStatus, TravelMode
from app.infrastructure.amap import AmapClient
from app.infrastructure.cache import SqliteProviderCache
from app.schemas.constraint import Constraint
from app.schemas.trip import CityContext, GeoPoint, ProviderConfig
from app.services.route_risk import (
    FIELD_AVOID_STAIRS,
    FIELD_MAX_TRANSFERS,
    FIELD_WALK_SEGMENT,
    ValidationStatus,
    evaluate_route_risk,
)


CITY_CASES = (
    ("北京", "北京市", "110000", 116.407387, 39.904179),
    ("上海", "上海市", "310000", 121.473701, 31.230416),
    ("成都", "成都市", "510100", 104.066541, 30.572269),
)

LIVE_CITY_CASES = (
    pytest.param("西安", "610100", id="xian"),
    pytest.param("杭州", "330100", id="hangzhou"),
)


def _city_context(
    city_name: str,
    city_code: str,
    longitude: float,
    latitude: float,
) -> CityContext:
    return CityContext(
        country_code="CN",
        city_code=city_code,
        city_name=city_name,
        center=GeoPoint(longitude=longitude, latitude=latitude),
        provider_config=ProviderConfig(
            provider="AMAP",
            coordinate_system="GCJ02",
        ),
    )


class _ThreeCityPlaceClient:
    def __init__(self) -> None:
        self.fail_online = False
        self.calls: list[str] = []

    async def search_places(self, **kwargs: Any) -> dict[str, Any]:
        city_code = str(kwargs["city_code"])
        self.calls.append(city_code)
        if self.fail_online:
            raise AppError("PROVIDER_UNAVAILABLE", "offline", 503, True)
        index = len(self.calls)
        return {
            "count": "1",
            "pois": [
                {
                    "id": f"{city_code}-museum",
                    "name": f"museum-{city_code}",
                    "citycode": city_code,
                    "adcode": city_code,
                    "location": f"{100 + index / 100:.6f},{30 + index / 100:.6f}",
                    "biz_ext": {"cost": []},
                }
            ],
        }


@pytest.mark.asyncio
async def test_s3_t005_three_city_cache_keys_are_isolated(tmp_path: Path) -> None:
    cache_path = tmp_path / "s3-t005-three-city-cache.sqlite3"
    client = _ThreeCityPlaceClient()
    service = AmapLocationService(
        client=client,  # type: ignore[arg-type]
        cache=SqliteProviderCache(cache_path),
        place_ttl_seconds=86_400,
        route_ttl_seconds=1_800,
    )

    contexts = [
        _city_context(city_name, city_code, longitude, latitude)
        for _, city_name, city_code, longitude, latitude in CITY_CASES
    ]
    online = [
        await service.search_places(
            city,
            keywords="博物馆",
            types=[],
            page=1,
            page_size=10,
        )
        for city in contexts
    ]
    assert [item.cityCode for item in online] == [
        "110000",
        "310000",
        "510100",
    ]
    assert all(item.provenance.sourceStatus is SourceStatus.ONLINE for item in online)

    client.fail_online = True
    cached = [
        await service.search_places(
            city,
            keywords="博物馆",
            types=[],
            page=1,
            page_size=10,
        )
        for city in contexts
    ]
    assert [item.cityCode for item in cached] == [
        "110000",
        "310000",
        "510100",
    ]
    assert all(
        item.provenance.sourceStatus is SourceStatus.VERIFIED_CACHE
        for item in cached
    )
    assert [item.places[0].placeId for item in cached] == [
        "110000-museum",
        "310000-museum",
        "510100-museum",
    ]

    with sqlite3.connect(cache_path) as connection:
        rows = connection.execute(
            "SELECT city_code, operation, request_hash FROM provider_cache "
            "ORDER BY city_code"
        ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        ("110000", "place_search"),
        ("310000", "place_search"),
        ("510100", "place_search"),
    ]
    assert len({row[2] for row in rows}) == 3


def test_s3_t006_unknown_and_estimated_prices_are_not_live_zero() -> None:
    online = Provenance(
        sourceStatus=SourceStatus.ONLINE,
        fetchedAt="2026-08-31T00:00:00Z",
        isStale=False,
    )

    unknown = _price_fact([], "PER_CAPITA_REFERENCE", online)
    assert unknown.amountCents is None
    assert unknown.provenance.sourceStatus is SourceStatus.UNKNOWN

    driving = _route_price(
        {"route": {"taxi_cost": "23.50"}},
        {"tolls": "4.75"},
        TravelMode.DRIVING,
        online,
    )
    assert driving.amountCents == 475
    assert driving.kind == "ROAD_TOLLS"
    assert driving.provenance.sourceStatus is SourceStatus.ONLINE

    taxi = _route_price(
        {"route": {"taxi_cost": "23.50"}},
        {"tolls": "4.75"},
        TravelMode.TAXI,
        online,
    )
    assert taxi.amountCents == 2_350
    assert taxi.kind == "TAXI_ESTIMATE"
    assert taxi.provenance.sourceStatus is SourceStatus.ESTIMATED

    bicycle = _route_price(
        {},
        {"duration": str(31 * 60)},
        TravelMode.BICYCLING,
        online,
    )
    assert bicycle.amountCents == 450
    assert bicycle.kind == "SHARED_BICYCLE_ESTIMATE"
    assert bicycle.provenance.provider == "APP_ESTIMATE"
    assert bicycle.provenance.sourceStatus is SourceStatus.ESTIMATED

    unknown_driving = _route_price({}, {}, TravelMode.DRIVING, online)
    assert unknown_driving.amountCents is None
    assert unknown_driving.kind == "ROAD_TOLLS"
    assert unknown_driving.provenance.sourceStatus is SourceStatus.UNKNOWN

    unknown_taxi = _route_price({}, {}, TravelMode.TAXI, online)
    assert unknown_taxi.amountCents is None
    assert unknown_taxi.kind == "TAXI_ESTIMATE"
    assert unknown_taxi.provenance.sourceStatus is SourceStatus.UNKNOWN

    unknown_bicycle = _route_price({}, {}, TravelMode.BICYCLING, online)
    assert unknown_bicycle.amountCents is None
    assert unknown_bicycle.kind == "SHARED_BICYCLE_ESTIMATE"
    assert unknown_bicycle.provenance.provider == "APP_ESTIMATE"
    assert unknown_bicycle.provenance.sourceStatus is SourceStatus.UNKNOWN


class _StubRouteClient(AmapClient):
    def __init__(self) -> None:
        self.request_log: list[tuple[str, dict[str, Any]]] = []

    async def _get(
        self,
        path: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        self.request_log.append((path, dict(parameters)))
        return {"status": "1"}


@pytest.mark.asyncio
async def test_s3_t006_taxi_reuses_amap_driving_route_endpoint() -> None:
    client = _StubRouteClient()
    point = GeoPoint(longitude=116.4, latitude=39.9)

    await client.plan_route(
        city_code="110000",
        origin=point,
        destination=GeoPoint(longitude=116.5, latitude=39.95),
        mode=TravelMode.TAXI,
        strategy=None,
    )

    assert client.request_log == [
        (
            "/v3/direction/driving",
            {
                "origin": "116.400000,39.900000",
                "destination": "116.500000,39.950000",
            },
        )
    ]


class _RecordingAmapClient(AmapClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.request_log: list[tuple[str, dict[str, Any]]] = []

    async def _get(
        self,
        path: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        self.request_log.append((path, dict(parameters)))
        return await super()._get(path, parameters)


def _hard_constraint(
    field: str,
    operator: str,
    value: int | bool,
    *,
    scope: str,
) -> Constraint:
    return Constraint(
        field=field,
        operator=operator,
        value=value,
        scope=scope,
        hardness="HARD",
    )


@pytest.mark.skipif(
    os.getenv("RUN_AMAP_LIVE_SMOKE") != "1",
    reason="set RUN_AMAP_LIVE_SMOKE=1 to call the real AMap Web API",
)
@pytest.mark.parametrize(("city_input", "expected_city_code"), LIVE_CITY_CASES)
@pytest.mark.asyncio
async def test_s3_t006_xian_hangzhou_live_place_route_and_care_smoke(
    tmp_path: Path,
    city_input: str,
    expected_city_code: str,
) -> None:
    settings = Settings()
    assert settings.amap_web_service_key, "AMAP_WEB_SERVICE_KEY is required"
    cache_path = tmp_path / f"s3-t006-{expected_city_code}.sqlite3"
    client = _RecordingAmapClient(
        api_key=settings.amap_web_service_key,
        base_url=settings.amap_base_url,
        timeout_seconds=settings.amap_request_timeout_seconds,
        retry_attempts=2,
        retry_backoff_seconds=0.1,
    )
    service = AmapLocationService(
        client=client,
        cache=SqliteProviderCache(cache_path),
        place_ttl_seconds=settings.amap_place_cache_ttl_seconds,
        route_ttl_seconds=settings.amap_route_cache_ttl_seconds,
    )

    try:
        resolution = await service.resolve_city(city_input)
        city = resolution.cityContext
        assert city.city_code == expected_city_code
        assert resolution.provenance.sourceStatus is SourceStatus.ONLINE
        assert resolution.provenance.isStale is False

        places = await service.search_places(
            city,
            keywords="博物馆",
            types=[],
            page=1,
            page_size=10,
        )
        assert places.places
        assert places.cityCode == expected_city_code
        assert places.provenance.sourceStatus is SourceStatus.ONLINE
        assert {place.cityCode for place in places.places} == {expected_city_code}
        destination = next(
            place.location
            for place in places.places
            if place.location != city.center
        )

        route_collections = []
        for mode in (TravelMode.WALKING, TravelMode.TRANSIT):
            collection = await service.plan_route(
                city,
                origin=city.center,
                destination=destination,
                mode=mode,
                strategy=None,
            )
            assert collection.cityCode == expected_city_code
            assert collection.routes
            assert collection.provenance.sourceStatus is SourceStatus.ONLINE
            route_collections.append(collection)

        constraints = (
            _hard_constraint(
                FIELD_WALK_SEGMENT,
                "LTE",
                800,
                scope="ROUTE_SEGMENT",
            ),
            _hard_constraint(
                FIELD_MAX_TRANSFERS,
                "LTE",
                2,
                scope="ROUTE",
            ),
            _hard_constraint(
                FIELD_AVOID_STAIRS,
                "EQ",
                True,
                scope="ROUTE_SEGMENT",
            ),
        )
        for collection in route_collections:
            route = collection.routes[0]
            risk_input = route_snapshot_to_risk_input(
                route,
                elapsed_since_rest_minutes=max(
                    60,
                    ceil(route.durationSeconds / 60),
                ),
            )
            report = evaluate_route_risk(risk_input, constraints)
            assert report.status in {
                ValidationStatus.PASS,
                ValidationStatus.FAIL,
                ValidationStatus.NEEDS_CONFIRMATION,
            }
            stair_result = next(
                item
                for item in report.results
                if item.rule_id == "CARE.ROUTE.STAIRS_FORBIDDEN"
            )
            assert stair_result.status is ValidationStatus.NEEDS_CONFIRMATION

        price_facts = [
            *(place.priceReference for place in places.places),
            *(
                route.priceReference
                for collection in route_collections
                for route in collection.routes
            ),
        ]
        assert all(
            fact.amountCents is not None
            or fact.provenance.sourceStatus is SourceStatus.UNKNOWN
            for fact in price_facts
        )
        assert all(
            fact.kind != "TAXI_ESTIMATE"
            or fact.provenance.sourceStatus is SourceStatus.ESTIMATED
            for fact in price_facts
        )
    finally:
        await client.close()

    place_requests = [
        parameters
        for path, parameters in client.request_log
        if path == "/v3/place/text"
    ]
    transit_requests = [
        parameters
        for path, parameters in client.request_log
        if path == "/v3/direction/transit/integrated"
    ]
    assert place_requests and place_requests[-1]["city"] == expected_city_code
    assert transit_requests and transit_requests[-1]["city"] == expected_city_code

    with sqlite3.connect(cache_path) as connection:
        cached = connection.execute(
            "SELECT operation, city_code FROM provider_cache "
            "WHERE city_code=? ORDER BY operation",
            (expected_city_code,),
        ).fetchall()
    assert cached == [
        ("place_search", expected_city_code),
        ("route_transit", expected_city_code),
        ("route_walking", expected_city_code),
    ]
