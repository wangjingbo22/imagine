from __future__ import annotations

import httpx
import pytest

from app.application.llm_gateway import (
    StrictTripUnderstandingGateway,
    TripUnderstandingGateway,
    UnavailableTripUnderstandingGateway,
)
from app.core.config import Settings
from app.main import create_app


class UnusedLocationService:
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_key", "expected_mode", "expected_explainer"),
    [
        (None, "DETERMINISTIC_RULES", "NOT_CONFIGURED"),
        ("test-bailian-key", "BAILIAN_CONFIGURED", "BAILIAN_CONFIGURED"),
    ],
)
async def test_health_exposes_the_actual_natural_language_parser(
    tmp_path,
    api_key: str | None,
    expected_mode: str,
    expected_explainer: str,
) -> None:
    settings = Settings(
        amap_web_service_key="test-amap-key",
        bailian_api_key=api_key,
        amap_cache_db_path=tmp_path / "amap.sqlite3",
        plan_version_db_path=tmp_path / "plans.sqlite3",
        build_sha="test-sha",
    )
    app = create_app(
        settings=settings,
        service=UnusedLocationService(),  # type: ignore[arg-type]
    )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            root_health = await client.get("/health")
            api_health = await client.get("/api/v1/health")

    assert root_health.status_code == 200
    assert root_health.json()["naturalLanguageParser"] == expected_mode
    assert root_health.json()["replanDifferenceExplainer"] == expected_explainer
    assert api_health.status_code == 200
    assert api_health.json()["data"]["naturalLanguageParser"] == expected_mode
    assert (
        api_health.json()["data"]["replanDifferenceExplainer"]
        == expected_explainer
    )
    assert "test-bailian-key" not in root_health.text
    assert "test-bailian-key" not in api_health.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_key", "expected_gateway"),
    [
        (None, UnavailableTripUnderstandingGateway),
        ("test-bailian-key", StrictTripUnderstandingGateway),
    ],
)
async def test_runtime_exposes_trip_understanding_gateway(
    tmp_path,
    api_key: str | None,
    expected_gateway: type[TripUnderstandingGateway],
) -> None:
    settings = Settings(
        amap_web_service_key="test-amap-key",
        bailian_api_key=api_key,
        amap_cache_db_path=tmp_path / f"amap-{api_key or 'none'}.sqlite3",
        plan_version_db_path=tmp_path / f"plans-{api_key or 'none'}.sqlite3",
    )
    app = create_app(
        settings=settings,
        service=UnusedLocationService(),  # type: ignore[arg-type]
    )

    assert isinstance(app.state.trip_understanding_gateway, expected_gateway)
    if isinstance(app.state.trip_understanding_gateway, StrictTripUnderstandingGateway):
        assert (
            app.state.trip_understanding_gateway._client
            is app.state.trip_draft_service._llm_extractor
        )

    injected = object()
    injected_app = create_app(
        settings=Settings(
            _env_file=None,
            amap_cache_db_path=tmp_path / "injected-amap.sqlite3",
            plan_version_db_path=tmp_path / "injected-plans.sqlite3",
        ),
        service=UnusedLocationService(),  # type: ignore[arg-type]
        trip_understanding_gateway=injected,  # type: ignore[arg-type]
    )
    assert injected_app.state.trip_understanding_gateway is injected
