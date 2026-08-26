from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app


class UnusedLocationService:
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_key", "expected_mode"),
    [
        (None, "DETERMINISTIC_RULES"),
        ("test-bailian-key", "BAILIAN_CONFIGURED"),
    ],
)
async def test_health_exposes_the_actual_natural_language_parser(
    tmp_path,
    api_key: str | None,
    expected_mode: str,
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
    assert api_health.status_code == 200
    assert api_health.json()["data"]["naturalLanguageParser"] == expected_mode
    assert "test-bailian-key" not in root_health.text
    assert "test-bailian-key" not in api_health.text
