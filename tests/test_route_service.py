from typing import Any

import pytest

from app.domain.models import CityContext, SourceStatus, TravelMode
from app.schemas.trip import GeoPoint
from tests.conftest import build_service


def route_payload(mode: TravelMode) -> dict[str, Any]:
    if mode is TravelMode.TRANSIT:
        return {
            "status": "1",
            "route": {
                "transits": [
                    {
                        "distance": "8000",
                        "duration": "2400",
                        "walking_distance": "600",
                        "cost": "5",
                        "segments": [
                            {
                                "walking": {"steps": [{"instruction": "步行到车站", "distance": "300"}]},
                                "bus": {"buslines": [{"name": "地铁1号线", "distance": "7000", "duration": "1800"}]},
                            }
                        ],
                    }
                ]
            },
        }
    if mode is TravelMode.BICYCLING:
        return {
            "errcode": 0,
            "data": {
                "paths": [
                    {
                        "distance": "5000",
                        "duration": "1200",
                        "steps": [{"instruction": "沿道路骑行", "distance": "5000"}],
                    }
                ]
            },
        }
    return {
        "status": "1",
        "route": {
            "taxi_cost": "18" if mode is TravelMode.DRIVING else "",
            "paths": [
                {
                    "distance": "3000",
                    "duration": "900",
                    "tolls": "0",
                    "steps": [{"instruction": "向东出发", "distance": "3000"}],
                }
            ],
        },
    }


class RouteClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def plan_route(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return route_payload(kwargs["mode"])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", list(TravelMode))
async def test_all_approved_route_modes_are_normalized(
    tmp_path,
    beijing: CityContext,
    mode: TravelMode,
) -> None:
    client = RouteClient()
    service = build_service(tmp_path, client)
    origin = GeoPoint(longitude=116.397499, latitude=39.908722)
    destination = GeoPoint(longitude=116.481028, latitude=39.989643)

    result = await service.plan_route(
        beijing,
        origin=origin,
        destination=destination,
        mode=mode,
        strategy=None,
    )

    assert client.calls[0]["city_code"] == "110000"
    assert result.cityCode == "110000"
    assert result.routes[0].mode is mode
    assert result.routes[0].distanceMeters > 0
    assert result.routes[0].provenance.sourceStatus is SourceStatus.ONLINE
    if mode in {TravelMode.WALKING, TravelMode.BICYCLING}:
        assert result.routes[0].priceReference.amountCents == 0
