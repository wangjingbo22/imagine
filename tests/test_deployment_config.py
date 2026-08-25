from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app
from tests.test_plan_versions import UnusedLocationService


ROOT = Path(__file__).parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def nginx_location_block(nginx: str, location: str) -> str:
    marker = f"location {location} {{"
    start = nginx.index(marker)
    opening_brace = nginx.index("{", start)
    depth = 0
    for index in range(opening_brace, len(nginx)):
        if nginx[index] == "{":
            depth += 1
        elif nginx[index] == "}":
            depth -= 1
            if depth == 0:
                return nginx[start : index + 1]
    raise AssertionError(f"unclosed nginx location block: {location}")


def test_nginx_has_spa_fallback_and_api_proxy() -> None:
    nginx = read("frontend/nginx.conf")
    api = nginx_location_block(nginx, "/api/")
    health = nginx_location_block(nginx, "/health")
    assert "try_files $uri $uri/ /index.html;" in nginx
    for block, proxy_pass in (
        (api, "proxy_pass ${API_UPSTREAM};"),
        (health, "proxy_pass ${API_UPSTREAM}/health;"),
    ):
        assert proxy_pass in block
        assert "proxy_ssl_server_name on;" in block
        assert "proxy_ssl_name $proxy_host;" in block
        assert "proxy_set_header Host $proxy_host;" in block
        assert "proxy_set_header X-Forwarded-Proto $scheme;" in block


def test_render_blueprint_declares_https_services_and_health_checks() -> None:
    render = read("render.yaml")
    assert "name: xingzhi-travel-api" in render
    assert "name: xingzhi-travel-web" in render
    assert render.count("healthCheckPath: /health") == 2
    assert "value: https://imagine-1-31o2.onrender.com" in render
    assert "healthCheckPath: /\n" not in render
    assert "AMAP_WEB_SERVICE_KEY" in render
    assert "API_UPSTREAM" in render


def test_production_compose_persists_sqlite_and_routes_frontend_to_backend() -> None:
    compose = read("docker-compose.prod.yml")
    assert "PLAN_VERSION_DB_PATH: /app/data/plan_versions.sqlite3" in compose
    assert "xingzhi-data:/app/data" in compose
    assert "API_UPSTREAM: http://backend:8000" in compose
    assert '"${WEB_PORT:-8080}:80"' in compose


def test_ci_runs_backend_and_frontend_quality_gates() -> None:
    workflow = read(".github/workflows/ci.yml")
    assert 'pip install -e ".[dev]"' in workflow
    assert "- run: pytest" in workflow
    assert "run: npm run lint" in workflow
    assert "run: npm run build" in workflow


def test_dockerfiles_use_reproducible_install_and_production_servers() -> None:
    backend = read("Dockerfile")
    frontend = read("frontend/Dockerfile")
    assert "pip install --no-cache-dir ." in backend
    assert "uvicorn app.main:app" in backend
    assert "${PORT:-8000}" in backend
    assert "RUN npm ci" in frontend
    assert "FROM nginx:1.27-alpine" in frontend


@pytest.mark.asyncio
async def test_health_endpoints_expose_the_same_configured_build_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BUILD_SHA", "test-build-sha")
    settings = Settings(
        plan_version_db_path=tmp_path / "health.sqlite3",
        amap_cache_db_path=tmp_path / "cache.sqlite3",
    )
    app = create_app(settings=settings, service=UnusedLocationService())  # type: ignore[arg-type]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        direct = await client.get("/health")
        api = await client.get("/api/v1/health")

    assert direct.status_code == api.status_code == 200
    assert direct.json()["buildSha"] == api.json()["data"]["buildSha"] == "test-build-sha"


@pytest.mark.asyncio
async def test_health_reports_unavailable_without_a_build_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BUILD_SHA", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    settings = Settings(
        _env_file=None,
        plan_version_db_path=tmp_path / "health-unavailable.sqlite3",
        amap_cache_db_path=tmp_path / "cache.sqlite3",
    )
    app = create_app(settings=settings, service=UnusedLocationService())  # type: ignore[arg-type]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        direct = await client.get("/health")
        api = await client.get("/api/v1/health")

    assert direct.json()["buildSha"] == api.json()["data"]["buildSha"] == "unavailable"
