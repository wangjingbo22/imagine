"""Run the approved PBI-02-A live acceptance checks without printing secrets."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.application.amap_service import AmapLocationService
from app.core.config import get_settings
from app.core.errors import AppError
from app.domain.models import SourceStatus
from app.infrastructure.amap import AmapClient
from app.infrastructure.cache import SqliteProviderCache
from app.schemas.trip import CityContext, GeoPoint, ProviderConfig


BASE_URL = "http://127.0.0.1:8000"
TRIP_ID = "550e8400-e29b-41d4-a716-446655440000"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def post(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    if response.is_error:
        raise AssertionError(
            f"{path} HTTP {response.status_code}: {response.text}"
        )
    body = response.json()
    require(body.get("code") == 200, f"{path} 未返回业务成功码")
    return body


def trip_request(city_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "tripId": TRIP_ID,
        "cityContext": city_context,
    }


async def verify_cache(city_context: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    offline_client = AmapClient(
        api_key=None,
        base_url=settings.amap_base_url,
        timeout_seconds=settings.amap_request_timeout_seconds,
    )
    service = AmapLocationService(
        client=offline_client,
        cache=SqliteProviderCache(settings.amap_cache_db_path),
        place_ttl_seconds=settings.amap_place_cache_ttl_seconds,
        route_ttl_seconds=settings.amap_route_cache_ttl_seconds,
    )
    beijing = CityContext.model_validate(city_context)
    shanghai = CityContext(
        country_code="CN",
        city_code="310000",
        city_name="上海市",
        center=GeoPoint(longitude=121.473701, latitude=31.230416),
        provider_config=ProviderConfig(provider="AMAP", coordinate_system="GCJ02"),
    )
    try:
        cached = await service.search_places(
            beijing,
            keywords="故宫博物院",
            types=[],
            page=1,
            page_size=10,
        )
        require(
            cached.provenance.sourceStatus is SourceStatus.VERIFIED_CACHE,
            "断网后没有读取已核验缓存",
        )
        require(
            all(place.cityCode == "110000" for place in cached.places),
            "北京缓存中出现了其他城市数据",
        )

        cross_city_code = "NO_ERROR"
        try:
            await service.search_places(
                shanghai,
                keywords="故宫博物院",
                types=[],
                page=1,
                page_size=10,
            )
        except AppError as error:
            cross_city_code = error.code
        require(
            cross_city_code == "AMAP_KEY_MISSING",
            "上海请求错误读取了北京缓存",
        )
        return {
            "beijingFallback": cached.provenance.sourceStatus.value,
            "beijingResultCount": len(cached.places),
            "shanghaiFallback": "DENIED",
            "shanghaiError": cross_city_code,
        }
    finally:
        await offline_client.close()


def main() -> None:
    settings = get_settings()
    require(bool(settings.amap_web_service_key), "AMAP_WEB_SERVICE_KEY 未配置")
    results: dict[str, Any] = {
        "1_配置与服务": {"keyConfigured": True},
    }

    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        health_response = client.get("/api/v1/health")
        health_response.raise_for_status()
        health = health_response.json()
        require(health == {"code": 200, "message": "success", "data": {"status": "UP"}}, "健康响应不正确")
        results["2_健康检查"] = health["data"]

        city = post(
            client,
            "/api/v1/cities/resolve",
            {"schemaVersion": "1.0", "cityName": "北京市"},
        )["data"]
        city_context = city["cityContext"]
        require(city_context["cityCode"] == "110000", "北京市 cityCode 应为 110000")
        require(city_context["providerConfig"]["provider"] == "AMAP", "Provider 应为 AMAP")
        require(city["provenance"]["sourceStatus"] in {"ONLINE", "VERIFIED_CACHE"}, "城市来源状态无效")
        results["3_城市解析"] = {
            "cityCode": city_context["cityCode"],
            "cityName": city_context["cityName"],
            "sourceStatus": city["provenance"]["sourceStatus"],
            "hasFetchedAt": bool(city["provenance"]["fetchedAt"]),
        }

        place_payload = {
            **trip_request(city_context),
            "keywords": "故宫博物院",
            "types": [],
            "page": 1,
            "pageSize": 10,
        }
        places = post(client, "/api/v1/places/search", place_payload)["data"]
        require(places["total"] > 0 and places["places"], "没有找到故宫博物院")
        require(all(item["cityCode"] == "110000" for item in places["places"]), "地点结果发生跨城")
        require(all(item["provenance"]["fetchedAt"] for item in places["places"]), "地点缺少 fetchedAt")
        require(
            all(
                item["priceReference"]["amountCents"] is not None
                or item["priceReference"]["provenance"]["sourceStatus"] == "UNKNOWN"
                for item in places["places"]
            ),
            "未知价格没有标记 UNKNOWN",
        )
        unknown_prices = [
            item for item in places["places"]
            if item["priceReference"]["provenance"]["sourceStatus"] == "UNKNOWN"
        ]
        require(
            all(item["priceReference"]["amountCents"] is None for item in unknown_prices),
            "未知价格被错误当成 0 元",
        )
        results["4_地点搜索"] = {
            "total": places["total"],
            "returned": len(places["places"]),
            "allCityCode110000": True,
            "unknownPriceUsesNull": True,
            "sourceStatus": places["provenance"]["sourceStatus"],
        }

        origin = {"longitude": 116.378922, "latitude": 39.865246}
        destination = {"longitude": 116.403414, "latitude": 39.924091}
        route_results: dict[str, Any] = {}
        for mode in ["WALKING", "TRANSIT", "DRIVING", "BICYCLING"]:
            route_request = {
                **trip_request(city_context),
                "origin": origin,
                "destination": destination,
                "mode": mode,
                "strategy": None,
            }
            routes = post(client, "/api/v1/routes/plan", route_request)["data"]
            require(routes["routes"], f"{mode} 没有返回路线")
            first_route = routes["routes"][0]
            require(first_route["mode"] == mode, f"{mode} 返回方式不一致")
            require(first_route["distanceMeters"] > 0, f"{mode} 距离无效")
            require(first_route["durationSeconds"] > 0, f"{mode} 时长无效")
            require(first_route["provenance"]["fetchedAt"], f"{mode} 缺少 fetchedAt")
            route_results[mode] = {
                "distanceMeters": first_route["distanceMeters"],
                "durationSeconds": first_route["durationSeconds"],
                "sourceStatus": first_route["provenance"]["sourceStatus"],
                "priceStatus": first_route["priceReference"]["provenance"]["sourceStatus"],
            }
        results["5_四种路线"] = route_results

        invalid_payload = {
            **place_payload,
            "cityContext": {
                **city_context,
                "center": {"longitude": city_context["center"]["longitude"]},
            },
        }
        invalid_response = client.post("/api/v1/places/search", json=invalid_payload)
        require(invalid_response.status_code == 422, "错误输入应返回 HTTP 422")
        invalid = invalid_response.json()
        require(invalid["code"] == "TRIP_SCHEMA_INVALID", "Schema 错误码不正确")
        error_paths = {error["path"] for error in invalid["errors"]}
        require("cityContext.center.latitude" in error_paths, "错误路径不准确")
        results["6_Schema错误"] = {
            "httpStatus": 422,
            "code": invalid["code"],
            "pathDetected": "cityContext.center.latitude",
        }

    results["7_缓存隔离"] = asyncio.run(verify_cache(city_context))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
