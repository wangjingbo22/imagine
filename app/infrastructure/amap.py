from typing import Any

import httpx

from app.core.errors import AppError, error_from_amap
from app.domain.models import TravelMode
from app.schemas.trip import GeoPoint


class AmapClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise AppError(
                "AMAP_KEY_MISSING",
                "未配置高德 Web 服务 Key",
                503,
                False,
            )
        request_parameters = {
            **parameters,
            "key": self.api_key,
            "output": "JSON",
        }
        try:
            response = await self._client.get(path, params=request_parameters)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise AppError("PROVIDER_TIMEOUT", "高德接口请求超时", 503, True) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError("PROVIDER_UNAVAILABLE", "高德接口暂时不可用", 503, True) from exc

        if "errcode" in payload and str(payload.get("errcode")) not in {"0", "10000"}:
            raise error_from_amap(str(payload.get("errcode", "")), str(payload.get("errmsg", "")))
        if str(payload.get("status", "1")) != "1":
            raise error_from_amap(str(payload.get("infocode", "")), str(payload.get("info", "")))
        return payload

    async def resolve_city(self, city_name: str) -> dict[str, Any]:
        return await self._get("/v3/geocode/geo", {"address": city_name, "city": city_name})

    async def suggestions(
        self,
        *,
        city_code: str,
        keywords: str,
        types: list[str],
    ) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "city": city_code,
            "citylimit": "true",
            "keywords": keywords,
            "datatype": "poi",
        }
        if types:
            parameters["type"] = "|".join(types)
        return await self._get("/v3/assistant/inputtips", parameters)

    async def search_places(
        self,
        *,
        city_code: str,
        keywords: str,
        types: list[str],
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "city": city_code,
            "citylimit": "true",
            "keywords": keywords,
            "page": page,
            "offset": page_size,
            "extensions": "all",
        }
        if types:
            parameters["types"] = "|".join(types)
        return await self._get("/v3/place/text", parameters)

    async def nearby_places(
        self,
        *,
        city_code: str,
        center: GeoPoint,
        radius_meters: int,
        keywords: str | None,
        types: list[str],
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "city": city_code,
            "citylimit": "true",
            "location": _location(center),
            "radius": radius_meters,
            "page": page,
            "offset": page_size,
            "extensions": "all",
        }
        if keywords:
            parameters["keywords"] = keywords
        if types:
            parameters["types"] = "|".join(types)
        return await self._get("/v3/place/around", parameters)

    async def place_detail(self, *, city_code: str, place_id: str) -> dict[str, Any]:
        # city_code remains part of the provider operation context and cache key.
        return await self._get(
            "/v3/place/detail",
            {"id": place_id, "extensions": "all", "city": city_code},
        )

    async def forward_geocode(self, *, city_code: str, address: str) -> dict[str, Any]:
        return await self._get("/v3/geocode/geo", {"city": city_code, "address": address})

    async def reverse_geocode(
        self,
        *,
        city_code: str,
        location: GeoPoint,
    ) -> dict[str, Any]:
        # city_code is deliberately carried for auditability and provider scoping.
        return await self._get(
            "/v3/geocode/regeo",
            {"location": _location(location), "extensions": "all", "city": city_code},
        )

    async def plan_route(
        self,
        *,
        city_code: str,
        origin: GeoPoint,
        destination: GeoPoint,
        mode: TravelMode,
        strategy: int | None,
    ) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "origin": _location(origin),
            "destination": _location(destination),
        }
        if strategy is not None:
            parameters["strategy"] = strategy

        if mode is TravelMode.TRANSIT:
            parameters["city"] = city_code
            return await self._get("/v3/direction/transit/integrated", parameters)
        if mode is TravelMode.WALKING:
            return await self._get("/v3/direction/walking", parameters)
        if mode is TravelMode.DRIVING:
            return await self._get("/v3/direction/driving", parameters)
        if mode is TravelMode.BICYCLING:
            return await self._get("/v4/direction/bicycling", parameters)
        raise AppError("INVALID_ROUTE_MODE", "不支持的路线方式", 422, False)


def _location(coordinates: GeoPoint) -> str:
    return f"{coordinates.longitude:.6f},{coordinates.latitude:.6f}"
