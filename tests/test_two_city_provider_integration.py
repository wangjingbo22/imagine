from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.domain.models import CityContext, SourceStatus, TravelMode
from app.schemas.trip import GeoPoint
from tests.conftest import build_service
from tests.test_route_service import route_payload


CITY_PROVIDER_CODES = {
    "110000": ("010", "110101", "116.397499,39.908722"),
    "310000": ("021", "310101", "121.473701,31.230416"),
}
EVIDENCE_PATH = (
    Path(__file__).parent.parent
    / "docs"
    / "testing"
    / "evidence"
    / "s1_t005_provider_beijing_shanghai.json"
)


class TwoCityProviderStub:
    def __init__(self) -> None:
        self.place_requests: list[dict[str, Any]] = []
        self.route_requests: list[dict[str, Any]] = []

    async def search_places(self, **kwargs: Any) -> dict[str, Any]:
        self.place_requests.append(kwargs)
        provider_code, ad_code, location = CITY_PROVIDER_CODES[kwargs["city_code"]]
        return {
            "status": "1",
            "count": "1",
            "pois": [
                {
                    "id": f"poi-{ad_code}",
                    "name": "同城测试博物馆",
                    "address": "测试路1号",
                    "location": location,
                    "citycode": provider_code,
                    "adcode": ad_code,
                    "type": "科教文化服务;博物馆",
                    "tel": [],
                    "biz_ext": {"rating": "4.8", "cost": ""},
                }
            ],
        }

    async def plan_route(self, **kwargs: Any) -> dict[str, Any]:
        self.route_requests.append(kwargs)
        return route_payload(kwargs["mode"])


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture_name", ["beijing", "shanghai"])
async def test_beijing_and_shanghai_provider_requests_and_results_are_city_scoped(
    request: pytest.FixtureRequest,
    fixture_name: str,
    tmp_path,
) -> None:
    city: CityContext = request.getfixturevalue(fixture_name)
    client = TwoCityProviderStub()
    service = build_service(tmp_path, client)

    places = await service.search_places(
        city,
        keywords="博物馆",
        types=[],
        page=1,
        page_size=10,
    )
    routes = await service.plan_route(
        city,
        origin=city.center,
        destination=GeoPoint(
            longitude=city.center.longitude + 0.01,
            latitude=city.center.latitude + 0.01,
        ),
        mode=TravelMode.WALKING,
        strategy=None,
    )

    assert client.place_requests[0]["city_code"] == city.city_code
    assert client.route_requests[0]["city_code"] == city.city_code
    assert places.cityCode == city.city_code
    assert places.places and all(item.cityCode == city.city_code for item in places.places)
    assert places.provenance.sourceStatus is SourceStatus.ONLINE
    assert places.provenance.fetchedAt is not None
    assert places.places[0].priceReference.amountCents is None
    assert places.places[0].priceReference.provenance.sourceStatus is SourceStatus.UNKNOWN
    assert routes.cityCode == city.city_code
    assert routes.routes and routes.routes[0].provenance.fetchedAt is not None
    assert routes.routes[0].priceReference.amountCents == 0


def test_live_two_city_evidence_is_complete_and_does_not_contain_secret() -> None:
    raw = EVIDENCE_PATH.read_text(encoding="utf-8")
    evidence = json.loads(raw)

    assert evidence["taskId"] == "S1-T005"
    assert [item["cityResolve"]["response"]["cityCode"] for item in evidence["cities"]] == [
        "110000",
        "310000",
    ]
    assert all(
        item["poiSearch"]["request"]["cityCode"]
        == item["poiSearch"]["response"]["resultCityCode"]
        for item in evidence["cities"]
    )
    assert all(
        item["walkingRoute"]["request"]["cityCode"]
        == item["walkingRoute"]["response"]["resultCityCode"]
        for item in evidence["cities"]
    )
    secret = os.getenv("AMAP_WEB_SERVICE_KEY")
    if secret:
        assert secret not in raw
