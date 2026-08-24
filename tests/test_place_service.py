from typing import Any

import pytest

from app.core.errors import AppError
from app.domain.models import CityContext, SourceStatus
from tests.conftest import build_service


def place_payload(
    *,
    provider_city_code: str,
    ad_code: str,
    cost: str | list[Any] = "",
) -> dict[str, Any]:
    return {
        "status": "1",
        "count": "1",
        "pois": [
            {
                "id": f"poi-{ad_code}",
                "name": "测试景点",
                "address": "测试路1号",
                "location": "116.397499,39.908722",
                "citycode": provider_city_code,
                "adcode": ad_code,
                "type": "风景名胜",
                "tel": [],
                "biz_ext": {"rating": "4.8", "cost": cost},
            }
        ],
    }


class SearchClient:
    def __init__(self, payload: dict[str, Any] | None = None, error: AppError | None = None) -> None:
        self.payload = payload
        self.error = error
        self.city_codes: list[str] = []

    async def search_places(self, **kwargs: Any) -> dict[str, Any]:
        self.city_codes.append(kwargs["city_code"])
        if self.error:
            raise self.error
        assert self.payload is not None
        return self.payload


@pytest.mark.asyncio
async def test_city_code_enters_provider_request_and_unknown_price_is_not_zero(
    tmp_path,
    beijing: CityContext,
) -> None:
    client = SearchClient(place_payload(provider_city_code="010", ad_code="110101"))
    service = build_service(tmp_path, client)

    result = await service.search_places(
        beijing,
        keywords="公园",
        types=[],
        page=1,
        page_size=20,
    )

    assert client.city_codes == ["110000"]
    assert result.cityCode == "110000"
    assert result.provenance.sourceStatus is SourceStatus.ONLINE
    assert result.places[0].priceReference.amountCents is None
    assert result.places[0].priceReference.provenance.sourceStatus is SourceStatus.UNKNOWN
    assert result.places[0].provenance.fetchedAt is not None


@pytest.mark.asyncio
async def test_price_reference_is_normalized_to_integer_cents(
    tmp_path,
    beijing: CityContext,
) -> None:
    service = build_service(
        tmp_path,
        SearchClient(place_payload(provider_city_code="010", ad_code="110101", cost="12.30")),
    )

    result = await service.search_places(
        beijing,
        keywords="博物馆",
        types=[],
        page=1,
        page_size=20,
    )

    assert result.places[0].priceReference.amountCents == 1230
    assert result.places[0].priceReference.provenance.sourceStatus is SourceStatus.ONLINE


@pytest.mark.asyncio
async def test_online_failure_reads_only_matching_city_cache(
    tmp_path,
    beijing: CityContext,
    shanghai: CityContext,
) -> None:
    online_service = build_service(
        tmp_path,
        SearchClient(place_payload(provider_city_code="010", ad_code="110101", cost="20")),
    )
    await online_service.search_places(
        beijing,
        keywords="公园",
        types=[],
        page=1,
        page_size=20,
    )

    failure = AppError("PROVIDER_TIMEOUT", "timeout", 503, True)
    offline_service = build_service(tmp_path, SearchClient(error=failure))
    cached = await offline_service.search_places(
        beijing,
        keywords="公园",
        types=[],
        page=1,
        page_size=20,
    )
    assert cached.provenance.sourceStatus is SourceStatus.VERIFIED_CACHE
    assert cached.places[0].cityCode == "110000"

    with pytest.raises(AppError) as captured:
        await offline_service.search_places(
            shanghai,
            keywords="公园",
            types=[],
            page=1,
            page_size=20,
        )
    assert captured.value.code == "PROVIDER_TIMEOUT"


@pytest.mark.asyncio
async def test_cross_city_provider_result_is_rejected(
    tmp_path,
    beijing: CityContext,
) -> None:
    service = build_service(
        tmp_path,
        SearchClient(place_payload(provider_city_code="021", ad_code="310101")),
    )

    with pytest.raises(AppError) as captured:
        await service.search_places(
            beijing,
            keywords="外滩",
            types=[],
            page=1,
            page_size=20,
        )

    assert captured.value.code == "CITY_CONTEXT_MISMATCH"
