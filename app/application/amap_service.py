import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app.core.errors import AppError
from app.domain.models import (
    AddressResolution,
    CityContext,
    CityResolution,
    FacilityEvidence,
    FacilityEvidenceStatus,
    FacilityType,
    Place,
    PlaceCollection,
    PriceFact,
    Provenance,
    Route,
    RouteCollection,
    RouteStep,
    SourceStatus,
    TravelMode,
)
from app.schemas.trip import GeoPoint, ProviderConfig
from app.infrastructure.amap import AmapClient
from app.infrastructure.cache import SqliteProviderCache


SHARED_BICYCLE_BLOCK_SECONDS = 15 * 60
SHARED_BICYCLE_BLOCK_CENTS = 150


@dataclass(frozen=True, slots=True)
class FetchResult:
    payload: dict[str, Any]
    provenance: Provenance


class AmapLocationService:
    def __init__(
        self,
        *,
        client: AmapClient,
        cache: SqliteProviderCache,
        place_ttl_seconds: int,
        route_ttl_seconds: int,
    ) -> None:
        self.client = client
        self.cache = cache
        self.place_ttl_seconds = place_ttl_seconds
        self.route_ttl_seconds = route_ttl_seconds

    async def _fetch(
        self,
        *,
        operation: str,
        city_code: str,
        parameters: dict[str, Any],
        ttl_seconds: int,
        online_call: Callable[[], Awaitable[dict[str, Any]]],
        allow_cache_fallback: bool = True,
    ) -> FetchResult:
        try:
            payload = await online_call()
            fetched_at = datetime.now(UTC)
            self.cache.put(
                provider="AMAP",
                operation=operation,
                city_code=city_code,
                parameters=parameters,
                payload=payload,
                ttl_seconds=ttl_seconds,
                fetched_at=fetched_at,
            )
            return FetchResult(
                payload,
                Provenance(
                    sourceStatus=SourceStatus.ONLINE,
                    fetchedAt=fetched_at,
                    isStale=False,
                ),
            )
        except AppError as online_error:
            if not allow_cache_fallback:
                raise online_error
            cached = self.cache.get(
                provider="AMAP",
                operation=operation,
                city_code=city_code,
                parameters=parameters,
            )
            if cached is None:
                raise online_error
            return FetchResult(
                cached.payload,
                Provenance(
                    sourceStatus=SourceStatus.VERIFIED_CACHE,
                    fetchedAt=cached.fetched_at,
                    isStale=cached.is_stale,
                ),
            )

    async def resolve_city(self, city_name: str) -> CityResolution:
        normalized_name = city_name.strip()
        parameters = {"cityName": normalized_name}
        result = await self._fetch(
            operation="resolve_city",
            city_code=f"CITY_NAME:{normalized_name}",
            parameters=parameters,
            ttl_seconds=self.place_ttl_seconds,
            online_call=lambda: self.client.resolve_city(normalized_name),
        )
        geocodes = _list(result.payload.get("geocodes"))
        if not geocodes:
            raise AppError("CITY_NOT_FOUND", "未找到目标城市", 404, False)
        item = geocodes[0]
        location = _coordinates(item.get("location"))
        ad_code = _text(item.get("adcode"))
        city_code, city_display_name = _planning_city_identity(
            item,
            fallback_name=normalized_name,
        )
        if not city_code:
            raise AppError("CITY_CONTEXT_INVALID", "高德未返回城市编码", 502, False)
        return CityResolution(
            cityContext=CityContext(
                country_code="CN",
                city_code=city_code,
                city_name=city_display_name,
                center=location,
                provider_config=ProviderConfig(
                    provider="AMAP",
                    coordinate_system="GCJ02",
                ),
            ),
            adCode=ad_code or None,
            formattedAddress=_optional_text(item.get("formatted_address")),
            provenance=result.provenance,
        )

    async def suggestions(
        self,
        city: CityContext,
        *,
        keywords: str,
        types: list[str],
        limit: int,
    ) -> PlaceCollection:
        parameters = {
            "cityCode": city.city_code,
            "keywords": keywords,
            "types": types,
        }
        result = await self._fetch(
            operation="suggestions",
            city_code=city.city_code,
            parameters=parameters,
            ttl_seconds=self.place_ttl_seconds,
            online_call=lambda: self.client.suggestions(
                city_code=city.city_code,
                keywords=keywords,
                types=types,
            ),
        )
        items = []
        for tip in _list(result.payload.get("tips"))[:limit]:
            if not (_text(tip.get("id")) and _text(tip.get("name")) and _text(tip.get("location"))):
                continue
            items.append(self._normalize_place(tip, city.city_code, result.provenance))
        return PlaceCollection(
            cityCode=city.city_code,
            total=len(items),
            places=items,
            provenance=result.provenance,
        )

    async def search_places(
        self,
        city: CityContext,
        *,
        keywords: str,
        types: list[str],
        page: int,
        page_size: int,
    ) -> PlaceCollection:
        parameters = {
            "cityCode": city.city_code,
            "keywords": keywords,
            "types": types,
            "page": page,
            "pageSize": page_size,
        }
        result = await self._fetch(
            operation="place_search",
            city_code=city.city_code,
            parameters=parameters,
            ttl_seconds=self.place_ttl_seconds,
            online_call=lambda: self.client.search_places(
                city_code=city.city_code,
                keywords=keywords,
                types=types,
                page=page,
                page_size=page_size,
            ),
        )
        places = [
            self._normalize_place(item, city.city_code, result.provenance)
            for item in _list(result.payload.get("pois"))
            if _text(item.get("id")) and _text(item.get("name")) and _text(item.get("location"))
        ]
        return PlaceCollection(
            cityCode=city.city_code,
            total=_integer(result.payload.get("count"), default=len(places)),
            places=places,
            provenance=result.provenance,
        )

    async def nearby_places(
        self,
        city: CityContext,
        *,
        center: GeoPoint,
        radius_meters: int,
        keywords: str | None,
        types: list[str],
        page: int,
        page_size: int,
    ) -> PlaceCollection:
        parameters = {
            "cityCode": city.city_code,
            "center": center.model_dump(),
            "radiusMeters": radius_meters,
            "keywords": keywords,
            "types": types,
            "page": page,
            "pageSize": page_size,
        }
        result = await self._fetch(
            operation="nearby_search",
            city_code=city.city_code,
            parameters=parameters,
            ttl_seconds=self.place_ttl_seconds,
            online_call=lambda: self.client.nearby_places(
                city_code=city.city_code,
                center=center,
                radius_meters=radius_meters,
                keywords=keywords,
                types=types,
                page=page,
                page_size=page_size,
            ),
        )
        places = [
            self._normalize_place(item, city.city_code, result.provenance)
            for item in _list(result.payload.get("pois"))
            if _text(item.get("id")) and _text(item.get("name")) and _text(item.get("location"))
        ]
        return PlaceCollection(
            cityCode=city.city_code,
            total=_integer(result.payload.get("count"), default=len(places)),
            places=places,
            provenance=result.provenance,
        )

    async def place_detail(self, city: CityContext, *, place_id: str) -> Place:
        parameters = {"cityCode": city.city_code, "placeId": place_id}
        result = await self._fetch(
            operation="place_detail",
            city_code=city.city_code,
            parameters=parameters,
            ttl_seconds=self.place_ttl_seconds,
            online_call=lambda: self.client.place_detail(city_code=city.city_code, place_id=place_id),
        )
        places = _list(result.payload.get("pois"))
        if not places:
            raise AppError("PLACE_NOT_FOUND", "未找到地点", 404, False)
        return self._normalize_place(places[0], city.city_code, result.provenance)

    async def forward_geocode(self, city: CityContext, *, address: str) -> AddressResolution:
        parameters = {"cityCode": city.city_code, "address": address}
        result = await self._fetch(
            operation="forward_geocode",
            city_code=city.city_code,
            parameters=parameters,
            ttl_seconds=self.place_ttl_seconds,
            online_call=lambda: self.client.forward_geocode(city_code=city.city_code, address=address),
        )
        geocodes = _list(result.payload.get("geocodes"))
        if not geocodes:
            raise AppError("PLACE_NOT_FOUND", "未找到该地址", 404, False)
        item = geocodes[0]
        provider_city_code = _optional_text(item.get("citycode"))
        returned_ad_code = _optional_text(item.get("adcode"))
        _assert_same_city(city.city_code, provider_city_code, returned_ad_code)
        return AddressResolution(
            formattedAddress=_text(item.get("formatted_address")) or address,
            cityCode=city.city_code,
            adCode=returned_ad_code,
            location=_coordinates(item.get("location")),
            provenance=result.provenance,
        )

    async def reverse_geocode(
        self,
        city: CityContext,
        *,
        location: GeoPoint,
    ) -> AddressResolution:
        parameters = {"cityCode": city.city_code, "location": location.model_dump()}
        result = await self._fetch(
            operation="reverse_geocode",
            city_code=city.city_code,
            parameters=parameters,
            ttl_seconds=self.place_ttl_seconds,
            online_call=lambda: self.client.reverse_geocode(
                city_code=city.city_code,
                location=location,
            ),
        )
        item = result.payload.get("regeocode") or {}
        component = item.get("addressComponent") or {}
        provider_city_code = _optional_text(component.get("citycode"))
        returned_ad_code = _optional_text(component.get("adcode"))
        _assert_same_city(city.city_code, provider_city_code, returned_ad_code)
        formatted_address = _text(item.get("formatted_address"))
        if not formatted_address:
            raise AppError("PLACE_NOT_FOUND", "该坐标没有可用地址", 404, False)
        return AddressResolution(
            formattedAddress=formatted_address,
            cityCode=city.city_code,
            adCode=returned_ad_code,
            location=location,
            provenance=result.provenance,
        )

    async def plan_route(
        self,
        city: CityContext,
        *,
        origin: GeoPoint,
        destination: GeoPoint,
        mode: TravelMode,
        strategy: int | None,
    ) -> RouteCollection:
        parameters = {
            "cityCode": city.city_code,
            "origin": origin.model_dump(),
            "destination": destination.model_dump(),
            "mode": mode.value,
            "strategy": strategy,
        }
        result = await self._fetch(
            operation=f"route_{mode.value.lower()}",
            city_code=city.city_code,
            parameters=parameters,
            ttl_seconds=self.route_ttl_seconds,
            allow_cache_fallback=False,
            online_call=lambda: self.client.plan_route(
                city_code=city.city_code,
                origin=origin,
                destination=destination,
                mode=mode,
                strategy=strategy,
            ),
        )
        routes = self._normalize_routes(result.payload, mode, origin, destination, result.provenance)
        if not routes:
            raise AppError("ROUTE_NOT_FOUND", "未找到可用路线", 404, False)
        return RouteCollection(cityCode=city.city_code, routes=routes, provenance=result.provenance)

    def _normalize_place(
        self,
        item: dict[str, Any],
        requested_city_code: str,
        provenance: Provenance,
    ) -> Place:
        provider_city_code = _optional_text(item.get("citycode"))
        returned_ad_code = _optional_text(item.get("adcode"))
        _assert_same_city(requested_city_code, provider_city_code, returned_ad_code)
        business = item.get("biz_ext") if isinstance(item.get("biz_ext"), dict) else {}
        price = _price_fact(business.get("cost"), "PER_CAPITA_REFERENCE", provenance)
        rating = _decimal_float(business.get("rating"))
        return Place(
            placeId=_text(item.get("id")),
            name=_text(item.get("name")),
            address=_optional_text(item.get("address")),
            cityCode=requested_city_code,
            adCode=returned_ad_code,
            location=_coordinates(item.get("location")),
            category=_optional_text(item.get("type")),
            telephone=_optional_text(item.get("tel")),
            rating=rating,
            priceReference=price,
            provenance=provenance,
        )

    def _normalize_routes(
        self,
        payload: dict[str, Any],
        mode: TravelMode,
        origin: GeoPoint,
        destination: GeoPoint,
        provenance: Provenance,
    ) -> list[Route]:
        if mode is TravelMode.TRANSIT:
            raw_routes = _list((payload.get("route") or {}).get("transits"))
        elif mode is TravelMode.BICYCLING:
            raw_routes = _list((payload.get("data") or {}).get("paths"))
        else:
            raw_routes = _list((payload.get("route") or {}).get("paths"))

        routes: list[Route] = []
        for index, item in enumerate(raw_routes):
            distance = _integer(item.get("distance"), default=0)
            duration = _integer(item.get("duration"), default=0)
            steps = _route_steps(item, mode)
            price = _route_price(payload, item, mode, provenance)
            route_seed = f"{mode}:{origin}:{destination}:{index}:{distance}:{duration}"
            route_id = hashlib.sha256(route_seed.encode("utf-8")).hexdigest()[:20]
            routes.append(
                Route(
                    routeId=route_id,
                    mode=mode,
                    origin=origin,
                    destination=destination,
                    distanceMeters=distance,
                    durationSeconds=duration,
                    walkingDistanceMeters=_optional_integer(item.get("walking_distance")),
                    transferCount=_transfers(item, mode),
                    steps=steps,
                    facilityEvidence=_unknown_facility_evidence(route_id, provenance),
                    priceReference=price,
                    provenance=provenance,
                )
            )
        return routes


def _unknown_facility_evidence(
    route_id: str,
    route_provenance: Provenance,
) -> list[FacilityEvidence]:
    """Expose missing facility facts without turning missing evidence into PASS."""

    unknown = route_provenance.model_copy(
        update={"sourceStatus": SourceStatus.UNKNOWN}
    )
    labels = (
        (FacilityType.ELEVATOR, "电梯"),
        (FacilityType.RAMP, "坡道"),
        (FacilityType.NURSING_ROOM, "母婴室"),
        (FacilityType.ACCESSIBLE_ENTRANCE, "无障碍入口"),
    )
    return [
        FacilityEvidence(
            facilityType=facility_type,
            label=label,
            status=FacilityEvidenceStatus.NEEDS_CONFIRMATION,
            message=f"高德路线快照未提供{label}事实，需现场或人工来源确认",
            referenceId=route_id,
            provenance=unknown,
        )
        for facility_type, label in labels
    ]


def _assert_same_city(
    requested: str,
    provider_city_code: str | None,
    returned_ad_code: str | None,
) -> None:
    if requested in {provider_city_code, returned_ad_code}:
        return

    if requested.isdigit() and len(requested) == 6 and returned_ad_code:
        if requested.endswith("0000") and returned_ad_code.startswith(requested[:2]):
            return
        if requested.endswith("00") and returned_ad_code.startswith(requested[:4]):
            return

    returned = returned_ad_code or provider_city_code or "<missing>"
    raise AppError(
        "CITY_CONTEXT_MISMATCH",
        f"返回数据城市编码 {returned} 与请求城市编码 {requested} 不一致",
        409,
        False,
    )


def _planning_city_identity(
    item: dict[str, Any],
    *,
    fallback_name: str,
) -> tuple[str, str]:
    """Promote district geocodes to the city scope used by planning."""

    ad_code = _text(item.get("adcode"))
    provider_city_code = _text(item.get("citycode"))
    province_name = _text(item.get("province"))
    city_name = _text(item.get("city"))

    if ad_code.isdigit() and len(ad_code) == 6:
        is_municipality = province_name.endswith("市") and (
            not city_name or city_name == province_name
        )
        if is_municipality:
            return f"{ad_code[:2]}0000", province_name
        if city_name and not ad_code.endswith("00"):
            return f"{ad_code[:4]}00", city_name

    return ad_code or provider_city_code, city_name or fallback_name


def _coordinates(value: Any) -> GeoPoint:
    text = _text(value)
    try:
        longitude, latitude = text.split(",", maxsplit=1)
        return GeoPoint(longitude=float(longitude), latitude=float(latitude))
    except (TypeError, ValueError) as exc:
        raise AppError("PROVIDER_DATA_INVALID", "高德坐标字段格式无效", 502, False) from exc


def _polyline(value: Any) -> list[GeoPoint]:
    """Normalize an Amap semicolon-delimited GCJ-02 route polyline."""

    points: list[GeoPoint] = []
    for item in _text(value).split(";"):
        if not item:
            continue
        try:
            points.append(_coordinates(item))
        except AppError:
            # A malformed optional shape point must not discard an otherwise
            # usable route. The route still exposes its trusted endpoints.
            continue
    return points


def _list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _optional_text(value: Any) -> str | None:
    return _text(value) or None


def _integer(value: Any, *, default: int) -> int:
    try:
        return max(0, int(Decimal(str(value))))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _optional_integer(value: Any) -> int | None:
    text = _text(value)
    return _integer(text, default=0) if text else None


def _decimal_float(value: Any) -> float | None:
    text = _text(value)
    try:
        return float(Decimal(text)) if text else None
    except InvalidOperation:
        return None


def _yuan_to_cents(value: Any) -> int | None:
    text = _text(value)
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    try:
        return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except DecimalException:
        return None


def _price_fact(value: Any, kind: str, provenance: Provenance) -> PriceFact:
    amount = _yuan_to_cents(value)
    if amount is None:
        unknown = provenance.model_copy(update={"sourceStatus": SourceStatus.UNKNOWN})
        return PriceFact(amountCents=None, kind=kind, provenance=unknown)
    return PriceFact(amountCents=amount, kind=kind, provenance=provenance)


def _route_price(
    payload: dict[str, Any],
    item: dict[str, Any],
    mode: TravelMode,
    provenance: Provenance,
) -> PriceFact:
    if mode is TravelMode.WALKING:
        return PriceFact(amountCents=0, kind="FREE", provenance=provenance)
    if mode is TravelMode.BICYCLING:
        duration_seconds = _optional_integer(item.get("duration"))
        estimated = Provenance(
            provider="APP_ESTIMATE",
            sourceStatus=SourceStatus.ESTIMATED,
            fetchedAt=provenance.fetchedAt,
            isStale=provenance.isStale,
        )
        if duration_seconds is None or duration_seconds <= 0:
            return PriceFact(
                amountCents=None,
                kind="SHARED_BICYCLE_ESTIMATE",
                provenance=estimated.model_copy(
                    update={"sourceStatus": SourceStatus.UNKNOWN}
                ),
            )
        billing_blocks = (
            (duration_seconds + SHARED_BICYCLE_BLOCK_SECONDS - 1)
            // SHARED_BICYCLE_BLOCK_SECONDS
        )
        return PriceFact(
            amountCents=billing_blocks * SHARED_BICYCLE_BLOCK_CENTS,
            kind="SHARED_BICYCLE_ESTIMATE",
            provenance=estimated,
        )
    if mode is TravelMode.TRANSIT:
        return _price_fact(item.get("cost"), "TRANSIT_FARE", provenance)
    route = payload.get("route") or {}
    if mode is TravelMode.TAXI:
        estimated = provenance.model_copy(
            update={"sourceStatus": SourceStatus.ESTIMATED}
        )
        return _price_fact(route.get("taxi_cost"), "TAXI_ESTIMATE", estimated)
    return _price_fact(item.get("tolls"), "ROAD_TOLLS", provenance)


def _route_steps(item: dict[str, Any], mode: TravelMode) -> list[RouteStep]:
    if mode is TravelMode.TRANSIT:
        steps: list[RouteStep] = []
        for segment in _list(item.get("segments")):
            walking = segment.get("walking") if isinstance(segment.get("walking"), dict) else {}
            for step in _list(walking.get("steps")):
                steps.append(_step(step, "WALKING"))
            bus = segment.get("bus") if isinstance(segment.get("bus"), dict) else {}
            for line in _list(bus.get("buslines")):
                steps.append(
                    RouteStep(
                        instruction=_optional_text(line.get("name")),
                        distanceMeters=_optional_integer(line.get("distance")),
                        durationSeconds=_optional_integer(line.get("duration")),
                        transport="TRANSIT",
                        polyline=_polyline(line.get("polyline")),
                    )
                )
        return steps
    return [_step(step, mode.value) for step in _list(item.get("steps"))]


def _step(item: dict[str, Any], transport: str) -> RouteStep:
    return RouteStep(
        instruction=_optional_text(item.get("instruction")),
        road=_optional_text(item.get("road")),
        distanceMeters=_optional_integer(item.get("distance")),
        durationSeconds=_optional_integer(item.get("duration")),
        transport=transport,
        polyline=_polyline(item.get("polyline")),
    )


def _transfers(item: dict[str, Any], mode: TravelMode) -> int | None:
    if mode is not TravelMode.TRANSIT:
        return None
    bus_line_count = 0
    for segment in _list(item.get("segments")):
        bus = segment.get("bus") if isinstance(segment.get("bus"), dict) else {}
        bus_line_count += len(_list(bus.get("buslines")))
    return max(0, bus_line_count - 1)
