from __future__ import annotations

from datetime import UTC, datetime
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.domain.models import (
    AddressResolution,
    CityResolution,
    Place,
    PlaceCollection,
    PriceFact,
    Provenance,
    SourceStatus,
)
from app.infrastructure.provider_fact_registry import SqliteProviderFactRegistry
from app.main import create_app
from backend.tests.test_s2_t003_collaboration_service import _ready_harness


FETCHED_AT = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)
CITY_CONTEXT = {
    "countryCode": "CN",
    "cityCode": "310000",
    "cityName": "上海市",
    "center": {"longitude": 121.473701, "latitude": 31.230416},
    "providerConfig": {"provider": "AMAP", "coordinateSystem": "GCJ02"},
}


def _provenance(
    status: SourceStatus,
    *,
    stale: bool = False,
) -> Provenance:
    return Provenance(
        provider="AMAP",
        sourceStatus=status,
        fetchedAt=FETCHED_AT,
        isStale=stale,
    )


def _place(
    place_id: str,
    name: str,
    *,
    category: str = "景点",
    city_code: str = "310000",
    status: SourceStatus = SourceStatus.ONLINE,
    price_cents: int | None = 2_000,
    stale: bool = False,
) -> Place:
    price_status = status if price_cents is not None else SourceStatus.UNKNOWN
    return Place(
        placeId=place_id,
        name=name,
        address=f"上海市 {name}",
        cityCode=city_code,
        adCode="310101",
        location={"longitude": 121.47, "latitude": 31.23},
        category=category,
        telephone=None,
        rating=4.5,
        priceReference=PriceFact(
            amountCents=price_cents,
            currency="CNY",
            kind="门票参考",
            provenance=_provenance(price_status, stale=stale),
        ),
        provenance=_provenance(status, stale=stale),
    )


def _provider_pool() -> list[Place]:
    return [
        _place("poi-bund", "The Bund", category="architecture"),
        _place("poi-architecture", "Shanghai Architecture Museum", category="architecture"),
        _place("poi-food", "Shanghai Food Market", category="food"),
        _place("poi-garden", "Yu Garden"),
        _place("poi-temple", "City God Temple"),
        _place(
            "poi-art",
            "Shanghai Art Center",
            status=SourceStatus.VERIFIED_CACHE,
            stale=True,
        ),
        _place("poi-science", "Shanghai Science Center"),
        _place("poi-park", "People's Park"),
        _place("poi-avoid", "crowded malls"),
        _place("poi-over-budget", "Luxury Theme Park", price_cents=35_000),
        _place("poi-cross-city", "Hangzhou Museum", city_code="330100"),
        _place(
            "poi-estimated",
            "Estimated Place",
            status=SourceStatus.ESTIMATED,
        ),
    ]


class StubLocationService:
    def __init__(self, places: list[Place]) -> None:
        self.places = places
        self.resolve_calls = 0
        self.geocode_calls = 0
        self.search_calls = 0

    async def resolve_city(self, city_name: str) -> CityResolution:
        self.resolve_calls += 1
        return CityResolution(
            cityContext=CITY_CONTEXT,
            adCode="310000",
            formattedAddress=city_name,
            provenance=_provenance(SourceStatus.ONLINE),
        )

    async def forward_geocode(self, city, *, address: str) -> AddressResolution:
        self.geocode_calls += 1
        return AddressResolution(
            formattedAddress=address,
            cityCode="310000",
            adCode="310000",
            location={"longitude": 121.47, "latitude": 31.23},
            provenance=_provenance(
                SourceStatus.ONLINE
                if self.geocode_calls == 1
                else SourceStatus.VERIFIED_CACHE
            ),
        )

    async def search_places(
        self,
        city,
        *,
        keywords: str,
        types: list[str],
        page: int,
        page_size: int,
    ) -> PlaceCollection:
        self.search_calls += 1
        return PlaceCollection(
            cityCode="310000",
            total=len(self.places),
            places=self.places,
            provenance=_provenance(SourceStatus.ONLINE),
        )


class NeverRouteBuilder:
    def __init__(self) -> None:
        self.calls = 0

    async def build(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("invalid digest must not build routes")


def _count(database_path: Path, table: str) -> int:
    with sqlite3.connect(database_path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _app(tmp_path: Path, places: list[Place]):
    harness = _ready_harness(tmp_path)
    database_path = harness.repository._path
    registry = SqliteProviderFactRegistry(database_path)
    location = StubLocationService(places)
    route_builder = NeverRouteBuilder()
    app = create_app(
        settings=Settings(
            _env_file=None,
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=database_path,
        ),
        service=location,  # type: ignore[arg-type]
        route_candidate_builder=route_builder,
        provider_fact_registry=registry,
        collaboration_repository=harness.repository,
        trip_draft_revision_port=harness.revisions,
    )
    return app, harness, registry, location, route_builder, database_path


@pytest.mark.asyncio
async def test_ready_group_signs_six_to_eight_filtered_provider_fact_refs(
    tmp_path: Path,
) -> None:
    app, harness, registry, location, route_builder, database_path = _app(
        tmp_path,
        _provider_pool(),
    )
    headers = {
        "X-Organizer-Token": harness.organizer_token,
        "Idempotency-Key": "s2-t030-issue-candidates",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v2/trips/{harness.revision.trip_id}/recommendations",
            headers=headers,
        )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert 6 <= len(payload["candidates"]) <= 8
    assert len(payload["factSetId"]) > 0
    assert len(payload["providerFactDigest"]) == 64
    assert len(payload["provenance"]) == len(payload["candidates"])
    assert all(
        item["factRefId"].startswith("AMAP:")
        for item in payload["candidates"]
    )
    assert {item["sourceStatus"] for item in payload["provenance"]} == {
        "ONLINE",
        "VERIFIED_CACHE",
    }
    selected_ids = {item["placeId"] for item in payload["candidates"]}
    assert "poi-bund" in selected_ids
    assert selected_ids.isdisjoint(
        {
            "poi-avoid",
            "poi-over-budget",
            "poi-cross-city",
            "poi-estimated",
        }
    )
    restored = registry.restore(
        harness.revision.trip_id,
        payload["factSetId"],
    )
    assert restored.provider_fact_digest == payload["providerFactDigest"]
    assert len(restored.candidate_facts) == len(payload["candidates"])
    assert restored.trip.mode.value == "GROUP"
    assert len(restored.trip.participants) == 2
    assert location.resolve_calls == 1
    assert location.geocode_calls == 2
    assert location.search_calls >= 1

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        rejected = await client.post(
            f"/api/v1/trips/{harness.revision.trip_id}/recommendations",
            headers={
                **headers,
                "Idempotency-Key": "s2-t030-invalid-digest",
            },
            json={
                "factSetId": payload["factSetId"],
                "providerFactDigest": "f" * 64,
            },
        )

    assert (rejected.status_code, rejected.json()["code"]) == (
        409,
        "PROVIDER_FACT_DIGEST_MISMATCH",
    )
    assert route_builder.calls == 0
    assert _count(database_path, "plan_versions") == 0


@pytest.mark.asyncio
async def test_fewer_than_six_after_hard_filter_issues_no_fact_set(
    tmp_path: Path,
) -> None:
    sparse = _provider_pool()[:5] + _provider_pool()[8:]
    app, harness, _registry, _location, _builder, database_path = _app(
        tmp_path,
        sparse,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v2/trips/{harness.revision.trip_id}/recommendations",
            headers={
                "X-Organizer-Token": harness.organizer_token,
                "Idempotency-Key": "s2-t030-insufficient",
            },
        )

    assert (response.status_code, response.json()["code"]) == (
        422,
        "INSUFFICIENT_TRUSTED_PROVIDER_CANDIDATES",
    )
    assert _count(database_path, "provider_fact_sets") == 0
    assert _count(database_path, "plan_versions") == 0
