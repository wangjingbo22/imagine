from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest

from app.application.collaboration_ports import PlanningAccess, ReadinessPermit
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.collaboration import TripFlowKind
from app.main import create_app


TRIP_ID = UUID("44444444-4444-4444-8444-444444444444")
ORGANIZER_TOKEN = "organizer-test-token"
CITY_CONTEXT = {
    "countryCode": "CN",
    "cityCode": "110000",
    "cityName": "北京",
    "center": {"longitude": 116.407387, "latitude": 39.904179},
    "providerConfig": {"provider": "AMAP", "coordinateSystem": "GCJ02"},
}


class CountingLocationService:
    def __init__(self) -> None:
        self.calls = 0
        self.resolve_calls = 0

    async def resolve_city(self, city_name: str) -> dict[str, object]:
        self.resolve_calls += 1
        return {"cityName": city_name}

    async def _trip_call(self, *args, **kwargs) -> dict[str, object]:
        self.calls += 1
        return {}

    suggestions = _trip_call
    search_places = _trip_call
    nearby_places = _trip_call
    place_detail = _trip_call
    forward_geocode = _trip_call
    reverse_geocode = _trip_call
    plan_route = _trip_call


class RejectingReadinessGuard:
    @contextmanager
    def operation(self, access: PlanningAccess):
        raise AppError(
            "COLLABORATION_NOT_READY",
            "全部成员确认并解决冲突后才能继续",
            409,
            False,
        )
        yield ReadinessPermit(
            trip_id=access.trip_id,
            readiness_digest="a" * 64,
            operation_id=access.operation_id,
            operation=access.operation,
            flow_kind=TripFlowKind.COLLABORATION_V2,
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )


@pytest.fixture
def counting_location_service() -> CountingLocationService:
    return CountingLocationService()


@pytest.fixture
def not_ready_app(tmp_path, counting_location_service: CountingLocationService):
    app = create_app(
        settings=Settings(
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=tmp_path / "plan.sqlite3",
        ),
        service=counting_location_service,  # type: ignore[arg-type]
    )
    app.state.collaboration_readiness_guard = RejectingReadinessGuard()
    return app


def _scoped(**extra: object) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "tripId": str(TRIP_ID),
        "cityContext": CITY_CONTEXT,
        **extra,
    }


def suggestion_payload(_: UUID) -> dict[str, object]:
    return _scoped(keywords="博物馆")


def search_payload(_: UUID) -> dict[str, object]:
    return _scoped(keywords="博物馆")


def nearby_payload(_: UUID) -> dict[str, object]:
    return _scoped(
        center={"longitude": 116.407387, "latitude": 39.904179},
        keywords="博物馆",
    )


def detail_payload(_: UUID) -> dict[str, object]:
    return _scoped(placeId="B000A00001")


def forward_payload(_: UUID) -> dict[str, object]:
    return _scoped(address="天安门")


def reverse_payload(_: UUID) -> dict[str, object]:
    return _scoped(location={"longitude": 116.407387, "latitude": 39.904179})


def route_payload(_: UUID) -> dict[str, object]:
    return _scoped(
        origin={"longitude": 116.407387, "latitude": 39.904179},
        destination={"longitude": 116.417387, "latitude": 39.914179},
        mode="WALKING",
    )


PROVIDER_CASES = (
    ("/api/v1/places/suggestions", suggestion_payload),
    ("/api/v1/places/search", search_payload),
    ("/api/v1/places/nearby", nearby_payload),
    ("/api/v1/places/detail", detail_payload),
    ("/api/v1/geocoding/forward", forward_payload),
    ("/api/v1/geocoding/reverse", reverse_payload),
    ("/api/v1/routes/plan", route_payload),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "payload_factory"), PROVIDER_CASES)
async def test_not_ready_rejects_before_location_service(
    path: str,
    payload_factory,
    not_ready_app,
    counting_location_service: CountingLocationService,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=not_ready_app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            path,
            headers={"X-Organizer-Token": ORGANIZER_TOKEN},
            json=payload_factory(TRIP_ID),
        )

    assert (response.status_code, response.json()["code"]) == (
        409,
        "COLLABORATION_NOT_READY",
    )
    assert counting_location_service.calls == 0


@pytest.mark.asyncio
async def test_city_resolve_remains_non_trip_scoped(
    not_ready_app,
    counting_location_service: CountingLocationService,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=not_ready_app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/cities/resolve",
            json={"schemaVersion": "1.0", "cityName": "北京"},
        )

    assert response.status_code == 200
    assert counting_location_service.resolve_calls == 1
