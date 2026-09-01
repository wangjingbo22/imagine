from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.domain.collaboration import QUESTION_IDS
from app.main import create_app
from app.application.account_service import AccountService


PASSWORD = "correct-horse-battery-staple"


def test_production_requires_secure_account_cookie():
    with pytest.raises(ValueError, match="AUTH_COOKIE_SECURE"):
        Settings(_env_file=None, app_environment="production")

    with pytest.raises(ValueError, match="ACCOUNT_API_KEY_ENCRYPTION_KEY"):
        Settings(
            _env_file=None,
            app_environment="production",
            auth_cookie_secure=True,
        )

    production = Settings(
        _env_file=None,
        app_environment="production",
        auth_cookie_secure=True,
        account_api_key_encryption_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    assert production.auth_cookie_secure is True


def test_account_service_never_issues_sessions_longer_than_fourteen_days():
    service = AccountService(object(), session_ttl_days=30)  # type: ignore[arg-type]

    assert service.session_ttl == timedelta(days=14)


def test_render_persists_account_database_on_the_api_data_disk():
    render = (Path(__file__).parents[2] / "render.yaml").read_text(encoding="utf-8")
    api_service = re.search(
        r"(?ms)^  - type: web\n(?=    name: xingzhi-travel-api)(.*?)(?=^  - type: web|\Z)",
        render,
    )

    assert api_service is not None
    api_config = api_service.group(1)
    assert re.search(
        r"(?ms)^    disk:\s*\n"
        r"^      name:\s+\S+\s*\n"
        r"^      mountPath:\s+/app/data\s*\n"
        r"^      sizeGB:\s+\d+\s*$",
        api_config,
    )
    assert re.search(
        r"(?ms)^      - key: ACCOUNT_SESSION_DB_PATH\s*\n"
        r"^        value: /app/data/account\.sqlite3\s*$",
        api_config,
    )


def _app(tmp_path: Path, *, secure_cookie: bool = False):
    return create_app(
        settings=Settings(
            _env_file=None,
            plan_version_db_path=tmp_path / "planning.sqlite3",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            account_session_db_path=tmp_path / "accounts.sqlite3",
            account_api_key_encryption_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
            auth_cookie_secure=secure_cookie,
        ),
        service=object(),  # type: ignore[arg-type]
    )


async def _client(tmp_path: Path, *, secure_cookie: bool = False):
    app = _app(tmp_path, secure_cookie=secure_cookie)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )
    return app, client


@pytest.mark.asyncio
async def test_register_creates_current_user_and_opaque_account_cookie(tmp_path: Path):
    _, client = await _client(tmp_path)
    async with client:
        response = await client.post(
            "/api/v1/account/register",
            json={
                "email": " Alice@example.com ",
                "password": PASSWORD,
                "displayName": "Alice",
            },
        )
        assert response.status_code == 200

    assert response.status_code == 200
    assert response.json()["data"] == {
        "userId": response.json()["data"]["userId"],
        "email": "alice@example.com",
        "displayName": "Alice",
        "homeCity": None,
        "interests": [],
    }
    set_cookie = response.headers["set-cookie"]
    assert "account_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/api" in set_cookie
    assert "Max-Age=1209600" in set_cookie
    assert "Cache-Control" in response.headers

    with sqlite3.connect(tmp_path / "accounts.sqlite3") as connection:
        users = connection.execute(
            "SELECT email, password_hash, display_name FROM users"
        ).fetchall()
        sessions = connection.execute(
            "SELECT token_hash, user_id, revoked_at FROM account_sessions"
        ).fetchall()
    assert users[0][0] == "alice@example.com"
    assert users[0][1] != PASSWORD
    assert users[0][1].startswith("$argon2id$")
    assert sessions[0][0] != response.cookies.get("account_session")
    assert len(sessions[0][0]) == 64
    assert sessions[0][2] is None


@pytest.mark.asyncio
async def test_secure_account_cookie_is_marked_secure(tmp_path: Path):
    _, client = await _client(tmp_path, secure_cookie=True)
    async with client:
        response = await client.post(
            "/api/v1/account/register",
            json={
                "email": "secure@example.com",
                "password": PASSWORD,
                "displayName": "Secure",
            },
        )

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_unconfigured_account_cannot_generate_trip_drafts(tmp_path: Path):
    _, client = await _client(tmp_path)
    async with client:
        registered = await client.post(
            "/api/v1/account/register",
            json={
                "email": "unconfigured@example.com",
                "password": PASSWORD,
                "displayName": "Unconfigured",
            },
        )
        response = await client.post(
            "/api/v1/trips/drafts/parse",
            json={"schemaVersion": "1.0", "rawText": "北京一日游"},
        )

    assert registered.status_code == 200
    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_MODEL_CONFIGURATION_REQUIRED"


@pytest.mark.asyncio
async def test_unconfigured_account_cannot_start_model_backed_conversation(tmp_path: Path):
    _, client = await _client(tmp_path)
    raw_text = "北京 2026-12-01 09:00 到 18:00 北京站往返 500元"
    async with client:
        registered = await client.post(
            "/api/v1/account/register",
            json={
                "email": "conversation-without-model@example.com",
                "password": PASSWORD,
                "displayName": "Unconfigured conversation",
            },
        )
        response = await client.post(
            "/api/v2/trips/conversations",
            headers={"Idempotency-Key": "conversation-without-model-0001"},
            json={
                "schemaVersion": "1.0",
                "referenceDate": "2026-09-02",
                "naturalLanguageRequest": raw_text,
                "answers": [
                    {"questionId": question_id, "answer": raw_text}
                    for question_id in QUESTION_IDS
                ],
            },
        )

    assert registered.status_code == 200
    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_MODEL_CONFIGURATION_REQUIRED"


@pytest.mark.asyncio
async def test_account_accepts_custom_model_name_and_https_api_url(tmp_path: Path):
    _, client = await _client(tmp_path)
    async with client:
        registered = await client.post(
            "/api/v1/account/register",
            json={
                "email": "custom-model@example.com",
                "password": PASSWORD,
                "displayName": "Custom model",
            },
        )
        saved = await client.put(
            "/api/v1/account/me/model-settings",
            json={
                "model": "gpt-4.1-mini",
                "apiKey": "custom-api-key-value",
                "baseUrl": "https://models.example.com/v1",
            },
        )
        restored = await client.get("/api/v1/account/me/model-settings")

    assert registered.status_code == 200
    assert saved.status_code == 200
    assert restored.status_code == 200
    assert restored.json()["data"] == {
        "configured": True,
        "model": "gpt-4.1-mini",
        "baseUrl": "https://models.example.com/v1",
    }


@pytest.mark.asyncio
async def test_account_model_settings_reject_unsafe_key_and_url_inputs(tmp_path: Path):
    _, client = await _client(tmp_path)
    async with client:
        await client.post(
            "/api/v1/account/register",
            json={
                "email": "settings-validation@example.com",
                "password": PASSWORD,
                "displayName": "Settings validation",
            },
        )
        control_key = await client.put(
            "/api/v1/account/me/model-settings",
            json={
                "model": "gpt-4.1-mini",
                "apiKey": "valid-key\nnot-allowed",
                "baseUrl": "https://models.example.com/v1",
            },
        )
        query_url = await client.put(
            "/api/v1/account/me/model-settings",
            json={
                "model": "gpt-4.1-mini",
                "apiKey": "valid-api-key-value",
                "baseUrl": "https://models.example.com/v1?token=not-allowed",
            },
        )
        ip_url = await client.put(
            "/api/v1/account/me/model-settings",
            json={
                "model": "gpt-4.1-mini",
                "apiKey": "valid-api-key-value",
                "baseUrl": "https://127.0.0.1/v1",
            },
        )

    assert control_key.status_code == 422
    assert query_url.status_code == 422
    assert query_url.json()["code"] == "ACCOUNT_MODEL_BASE_URL_FORBIDDEN"
    assert ip_url.status_code == 422
    assert ip_url.json()["code"] == "ACCOUNT_MODEL_BASE_URL_FORBIDDEN"


@pytest.mark.asyncio
async def test_email_is_normalized_and_unique(tmp_path: Path):
    _, client = await _client(tmp_path)
    async with client:
        first = await client.post(
            "/api/v1/account/register",
            json={"email": "Person@Example.COM", "password": PASSWORD, "displayName": "One"},
        )
        duplicate = await client.post(
            "/api/v1/account/register",
            json={"email": " person@example.com ", "password": PASSWORD, "displayName": "Two"},
        )

    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "ACCOUNT_EMAIL_TAKEN"


@pytest.mark.asyncio
async def test_login_wrong_password_and_me_session(tmp_path: Path):
    _, client = await _client(tmp_path)
    async with client:
        await client.post(
            "/api/v1/account/register",
            json={"email": "person@example.com", "password": PASSWORD, "displayName": "Person"},
        )
        client.cookies.clear()
        wrong = await client.post(
            "/api/v1/account/login",
            json={"email": "PERSON@example.com", "password": "wrong-password-123"},
        )
        logged_in = await client.post(
            "/api/v1/account/login",
            json={"email": "PERSON@example.com", "password": PASSWORD},
        )
        me = await client.get("/api/v1/account/me")

    assert wrong.status_code == 401
    assert wrong.json()["code"] == "ACCOUNT_CREDENTIALS_INVALID"
    assert logged_in.status_code == 200
    assert logged_in.json()["data"]["displayName"] == "Person"
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "person@example.com"


@pytest.mark.asyncio
async def test_secure_cookie_and_account_errors_are_not_cached(tmp_path: Path):
    _, client = await _client(tmp_path, secure_cookie=True)
    async with client:
        registered = await client.post(
            "/api/v1/account/register",
            json={"email": "person@example.com", "password": PASSWORD, "displayName": "Person"},
        )
        client.cookies.clear()
        invalid_login = await client.post(
            "/api/v1/account/login",
            json={"email": "person@example.com", "password": "wrong-password-123"},
        )

    assert "Secure" in registered.headers["set-cookie"]
    assert registered.headers["Cache-Control"] == "no-store"
    assert invalid_login.status_code == 401
    assert invalid_login.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_account_cors_allows_browser_credentials(tmp_path: Path):
    _, client = await _client(tmp_path)
    async with client:
        preflight = await client.options(
            "/api/v1/account/me",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert preflight.headers["access-control-allow-credentials"] == "true"


@pytest.mark.asyncio
async def test_logout_revokes_session_and_clears_cookie(tmp_path: Path):
    _, client = await _client(tmp_path)
    async with client:
        await client.post(
            "/api/v1/account/register",
            json={"email": "person@example.com", "password": PASSWORD, "displayName": "Person"},
        )
        session = client.cookies.get("account_session")
        logged_out = await client.post("/api/v1/account/logout")
        client.cookies.set("account_session", session or "")
        me = await client.get("/api/v1/account/me")

    assert logged_out.status_code == 200
    assert logged_out.json()["data"] == {"loggedOut": True}
    assert "Max-Age=0" in logged_out.headers["set-cookie"]
    assert me.status_code == 401
    assert me.json()["code"] == "ACCOUNT_SESSION_REQUIRED"


@pytest.mark.asyncio
async def test_expired_session_is_rejected(tmp_path: Path):
    _, client = await _client(tmp_path)
    async with client:
        await client.post(
            "/api/v1/account/register",
            json={"email": "person@example.com", "password": PASSWORD, "displayName": "Person"},
        )
        with sqlite3.connect(tmp_path / "accounts.sqlite3") as connection:
            connection.execute(
                "UPDATE account_sessions SET expires_at = ?",
                ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(),),
            )
        me = await client.get("/api/v1/account/me")

    assert me.status_code == 401
    assert me.json()["code"] == "ACCOUNT_SESSION_REQUIRED"


@pytest.mark.asyncio
async def test_profile_update_accepts_eight_interests_and_rejects_nine(tmp_path: Path):
    _, client = await _client(tmp_path)
    interests = [f"interest-{index}" for index in range(8)]
    async with client:
        await client.post(
            "/api/v1/account/register",
            json={"email": "person@example.com", "password": PASSWORD, "displayName": "Person"},
        )
        updated = await client.put(
            "/api/v1/account/me/profile",
            json={"displayName": "Updated", "homeCity": "Beijing", "interests": interests},
        )
        invalid = await client.put(
            "/api/v1/account/me/profile",
            json={"displayName": "Updated", "interests": [*interests, "too-many"]},
        )

    assert updated.status_code == 200
    assert updated.json()["data"]["homeCity"] == "Beijing"
    assert updated.json()["data"]["interests"] == interests
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_account_session_does_not_grant_collaboration_access(tmp_path: Path):
    app, client = await _client(tmp_path)
    trip_id = uuid4()
    async with client:
        account = await client.post(
            "/api/v1/account/register",
            json={"email": "person@example.com", "password": PASSWORD, "displayName": "Person"},
        )
        assert account.status_code == 200
        collaboration = await client.get(f"/api/v2/trips/{trip_id}/collaboration")

    assert collaboration.status_code == 403
    assert collaboration.json()["code"] == "ORGANIZER_PERMISSION_REQUIRED"
    assert app.state.collaboration_service is not app.state.account_service


@pytest.mark.asyncio
async def test_account_requests_reject_sensitive_profile_fields(tmp_path: Path):
    _, client = await _client(tmp_path)
    async with client:
        response = await client.post(
            "/api/v1/account/register",
            json={
                "email": "person@example.com",
                "password": PASSWORD,
                "displayName": "Person",
                "phone": "13800000000",
            },
        )

    assert response.status_code == 422
    assert "phone" in json.dumps(response.json())
