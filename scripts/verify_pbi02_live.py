"""Run T005 live Beijing/Shanghai checks and print a key-free JSON evidence log."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import time
from typing import Any

import httpx

from app.core.config import get_settings


BASE_URL = "http://127.0.0.1:8000"
TRIP_ID = "550e8400-e29b-41d4-a716-446655440000"
CITY_CASES = (
    {
        "name": "北京",
        "expectedCityCode": "110000",
        "keyword": "故宫博物院",
        "origin": {"longitude": 116.397499, "latitude": 39.908722},
        "destination": {"longitude": 116.403414, "latitude": 39.924091},
    },
    {
        "name": "上海",
        "expectedCityCode": "310000",
        "keyword": "上海博物馆",
        "origin": {"longitude": 121.473701, "latitude": 31.230416},
        "destination": {"longitude": 121.490317, "latitude": 31.241701},
    },
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def post(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(2):
        response = client.post(path, json=payload)
        body = response.json()
        if not response.is_error:
            require(body.get("code") == 200, f"{path} 未返回业务成功码")
            return body["data"]
        if attempt == 0 and body.get("retryable") is True:
            time.sleep(0.5)
            continue
        raise AssertionError(f"{path} HTTP {response.status_code}: {response.text}")
    raise AssertionError(f"{path} 未返回结果")


def city_log(client: httpx.Client, case: dict[str, Any]) -> dict[str, Any]:
    city = post(
        client,
        "/api/v1/cities/resolve",
        {"schemaVersion": "1.0", "cityName": case["name"]},
    )
    context = city["cityContext"]
    city_code = context["cityCode"]
    require(city_code == case["expectedCityCode"], f"{case['name']} cityCode 不正确")

    place_request = {
        "schemaVersion": "1.0",
        "tripId": TRIP_ID,
        "cityContext": context,
        "keywords": case["keyword"],
        "types": [],
        "page": 1,
        "pageSize": 10,
    }
    places = post(client, "/api/v1/places/search", place_request)
    require(places["places"], f"{case['name']} POI 搜索无结果")
    require(
        all(item["cityCode"] == city_code for item in places["places"]),
        f"{case['name']} POI 结果发生跨城",
    )
    require(places["provenance"]["fetchedAt"], f"{case['name']} POI 缺少 fetchedAt")
    for item in places["places"]:
        price = item["priceReference"]
        require(
            price["amountCents"] is not None
            or price["provenance"]["sourceStatus"] == "UNKNOWN",
            f"{case['name']} 未知价格事实状态错误",
        )

    route_request = {
        "schemaVersion": "1.0",
        "tripId": TRIP_ID,
        "cityContext": context,
        "origin": case["origin"],
        "destination": case["destination"],
        "mode": "WALKING",
        "strategy": None,
    }
    routes = post(client, "/api/v1/routes/plan", route_request)
    require(routes["routes"], f"{case['name']} 步行路线无结果")
    require(routes["cityCode"] == city_code, f"{case['name']} 路线结果发生跨城")
    first_route = routes["routes"][0]
    require(first_route["provenance"]["fetchedAt"], f"{case['name']} 路线缺少 fetchedAt")

    first_place = places["places"][0]
    return {
        "city": case["name"],
        "cityResolve": {
            "request": {"cityName": case["name"]},
            "response": {
                "cityCode": city_code,
                "cityName": context["cityName"],
                "sourceStatus": city["provenance"]["sourceStatus"],
                "fetchedAt": city["provenance"]["fetchedAt"],
            },
        },
        "poiSearch": {
            "request": {"cityCode": city_code, "keywords": case["keyword"]},
            "response": {
                "resultCityCode": places["cityCode"],
                "returned": len(places["places"]),
                "firstPlace": first_place["name"],
                "firstPlaceCityCode": first_place["cityCode"],
                "sourceStatus": places["provenance"]["sourceStatus"],
                "fetchedAt": places["provenance"]["fetchedAt"],
                "priceFactStatus": first_place["priceReference"]["provenance"]["sourceStatus"],
                "priceAmountCents": first_place["priceReference"]["amountCents"],
            },
        },
        "walkingRoute": {
            "request": {"cityCode": city_code, "mode": "WALKING"},
            "response": {
                "resultCityCode": routes["cityCode"],
                "distanceMeters": first_route["distanceMeters"],
                "durationSeconds": first_route["durationSeconds"],
                "sourceStatus": first_route["provenance"]["sourceStatus"],
                "fetchedAt": first_route["provenance"]["fetchedAt"],
                "priceFactStatus": first_route["priceReference"]["provenance"]["sourceStatus"],
                "priceAmountCents": first_route["priceReference"]["amountCents"],
            },
        },
    }


def main() -> None:
    settings = get_settings()
    require(bool(settings.amap_web_service_key), "AMAP_WEB_SERVICE_KEY 未配置")
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        health = client.get("/api/v1/health")
        health.raise_for_status()
        logs = [city_log(client, case) for case in CITY_CASES]

    evidence = {
        "taskId": "S1-T005",
        "generatedAt": datetime.now(UTC).isoformat(),
        "provider": "AMAP",
        "secretRedaction": "PASS - 请求/响应证据不记录 key",
        "cities": logs,
    }
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    require(settings.amap_web_service_key not in serialized, "脱敏日志意外包含高德 Key")
    print(serialized)


if __name__ == "__main__":
    main()
