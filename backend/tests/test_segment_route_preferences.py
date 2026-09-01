from __future__ import annotations

from copy import deepcopy
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.api.model_access import require_account_model_credentials
from app.application.plan_service import PlanVersionService
from app.application.workflow_service import WorkflowService
from app.application.amap_service import AmapLocationService
from app.core.errors import AppError
from app.domain.models import CityContext, TravelMode
from app.infrastructure.cache import SqliteProviderCache
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.main import create_app
from app.schemas.trip import CreateSingleDayTrip
from app.schemas.trip import GeoPoint, ProviderConfig
from backend.tests.plan_support import UnusedLocationService


PLANNING_FIXTURE = (
    Path(__file__).parent / "fixtures" / "planning" / "golden_candidate_plan.json"
)


def _candidate_request() -> dict[str, Any]:
    fixture = json.loads(PLANNING_FIXTURE.read_text(encoding="utf-8"))
    return fixture["request"]


def _confirmed_trip(request: dict[str, Any]) -> CreateSingleDayTrip:
    payload = deepcopy(request["trip"])
    payload["status"] = "DRAFT"
    return CreateSingleDayTrip.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )


def _app_and_database(tmp_path: Path):
    database_path = tmp_path / "segment_route_preferences.sqlite3"
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    request = _candidate_request()
    workflow.confirm_trip(_confirmed_trip(request))
    plans = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=workflow,
    )
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plans,
        workflow_service=workflow,
    )
    app.dependency_overrides[require_account_model_credentials] = (
        lambda: ("test-model", "test-key", "https://example.test/v1")
    )
    return app, database_path


async def _save_and_confirm_constraints(
    client: httpx.AsyncClient,
    request: dict[str, Any],
) -> None:
    trip_id = request["trip"]["tripId"]
    profile = request["trip"]["participants"][0]["assistanceProfile"]
    saved = await client.put(
        f"/api/v1/trips/{trip_id}/constraints",
        json=profile,
    )
    confirmed = await client.post(f"/api/v1/trips/{trip_id}/constraints/confirm")
    assert saved.status_code == 200, saved.text
    assert confirmed.status_code == 200, confirmed.text


def _assert_preview_left_no_planning_state(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM plan_versions").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM trusted_plan_issuances"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM candidate_plan_reviews"
        ).fetchone() == (0,)


class _FailingRouteClient:
    async def plan_route(self, **_: Any) -> dict[str, Any]:
        raise AppError("PROVIDER_TIMEOUT", "provider timed out", 503, True)


@pytest.mark.asyncio
async def test_route_error_does_not_fall_back_to_matching_verified_cache(tmp_path: Path) -> None:
    cache = SqliteProviderCache(tmp_path / "route_cache.sqlite3")
    city = CityContext(
        country_code="CN",
        city_code="310000",
        city_name="Shanghai",
        center=GeoPoint(longitude=121.4737, latitude=31.2304),
        provider_config=ProviderConfig(provider="AMAP", coordinate_system="GCJ02"),
    )
    origin = GeoPoint(longitude=121.4737, latitude=31.2304)
    destination = GeoPoint(longitude=121.4900, latitude=31.2350)
    parameters = {
        "cityCode": city.city_code,
        "origin": origin.model_dump(),
        "destination": destination.model_dump(),
        "mode": TravelMode.DRIVING.value,
        "strategy": None,
    }
    cache.put(
        provider="AMAP",
        operation="route_driving",
        city_code=city.city_code,
        parameters=parameters,
        payload={"route": {"paths": [{"distance": "1000", "duration": "600"}]}},
        ttl_seconds=1_800,
        fetched_at=datetime.now(UTC),
    )
    service = AmapLocationService(
        client=_FailingRouteClient(),  # type: ignore[arg-type]
        cache=cache,
        place_ttl_seconds=86_400,
        route_ttl_seconds=1_800,
    )

    with pytest.raises(AppError) as captured:
        await service.plan_route(
            city,
            origin=origin,
            destination=destination,
            mode=TravelMode.DRIVING,
            strategy=None,
        )

    assert captured.value.code == "PROVIDER_TIMEOUT"


@pytest.mark.asyncio
async def test_preview_returns_hard_constraint_failure_without_persistence(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]
    request["taskFacts"][0]["route"]["walkingDistanceMeters"] = 50_000

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _save_and_confirm_constraints(client, _candidate_request())
        response = await client.post(
            f"/api/v1/trips/{trip_id}/plan-previews/validate",
            json=request,
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["validationStatus"] == "FAIL"
    assert any(
        item["hardness"] == "HARD" and item["status"] == "FAIL"
        for item in data["constraintResults"]
    )
    _assert_preview_left_no_planning_state(database_path)


@pytest.mark.asyncio
async def test_preview_returns_pass_without_persistence(tmp_path: Path) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _save_and_confirm_constraints(client, request)
        response = await client.post(
            f"/api/v1/trips/{trip_id}/plan-previews/validate",
            json=request,
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["validationStatus"] == "PASS"
    assert data["metrics"]["validationStatus"] == "PASS"
    assert data["warnings"] == []
    _assert_preview_left_no_planning_state(database_path)


@pytest.mark.asyncio
async def test_preview_returns_needs_confirmation_without_persistence(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]
    price = request["taskFacts"][0]["place"]["priceReference"]
    price["amountCents"] = None
    price["provenance"]["sourceStatus"] = "UNKNOWN"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _save_and_confirm_constraints(client, _candidate_request())
        response = await client.post(
            f"/api/v1/trips/{trip_id}/plan-previews/validate",
            json=request,
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["validationStatus"] == "NEEDS_CONFIRMATION"
    assert data["metrics"]["validationStatus"] == "NEEDS_CONFIRMATION"
    assert data["warnings"]
    _assert_preview_left_no_planning_state(database_path)
