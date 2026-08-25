from pathlib import Path


ROOT = Path(__file__).parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_nginx_has_spa_fallback_and_api_proxy() -> None:
    nginx = read("frontend/nginx.conf")
    assert "try_files $uri $uri/ /index.html;" in nginx
    assert "location /api/" in nginx
    assert "proxy_pass ${API_UPSTREAM};" in nginx
    assert "X-Forwarded-Proto" in nginx


def test_render_blueprint_declares_https_services_and_health_checks() -> None:
    render = read("render.yaml")
    assert "name: xingzhi-travel-api" in render
    assert "name: xingzhi-travel-web" in render
    assert "healthCheckPath: /health" in render
    assert "healthCheckPath: /" in render
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
    assert 'CMD ["uvicorn"' in backend
    assert "RUN npm ci" in frontend
    assert "FROM nginx:1.27-alpine" in frontend
