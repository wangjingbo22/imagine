from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.domain.collaboration import QUESTION_IDS
from app.main import create_app


_SENSITIVE_VALUES = (
    "Bearer p1-authorization-sentinel",
    "p1-organizer-token-sentinel",
    "p1-participant-session-sentinel",
    "p1-idempotency-key-sentinel",
    "p1-server-secret-sentinel",
)


class CountingGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def understand(self, request) -> None:
        self.calls += 1
        raise AssertionError("schema validation must happen before the gateway")


def _app(tmp_path: Path, gateway: CountingGateway):
    return create_app(
        settings=Settings(
            _env_file=None,
            amap_web_service_key=_SENSITIVE_VALUES[4],
            plan_version_db_path=tmp_path / "planning.sqlite3",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
        ),
        service=object(),  # type: ignore[arg-type]
        trip_understanding_gateway=gateway,  # type: ignore[arg-type]
    )


def _sensitive_headers() -> dict[str, str]:
    return {
        "Authorization": _SENSITIVE_VALUES[0],
        "X-Organizer-Token": _SENSITIVE_VALUES[1],
        "X-Participant-Session": _SENSITIVE_VALUES[2],
        "Idempotency-Key": _SENSITIVE_VALUES[3],
    }


def _assert_validation_response(response: httpx.Response) -> None:
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["code"] == "TRIP_SCHEMA_INVALID"
    assert body["schemaVersion"] == "1.0"
    assert isinstance(body["errors"], list)
    assert body["errors"]
    for sensitive_value in _SENSITIVE_VALUES:
        assert sensitive_value not in response.text


def _organizer_invalid_payload() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "referenceDate": "2026-08-27",
        "naturalLanguageRequest": "two people need an accessible day trip",
        "answers": [
            {"questionId": question_id, "answer": "test answer"}
            for question_id in QUESTION_IDS[:-1]
        ],
    }


def _member_invalid_payload() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "baseRevision": 1,
        "expectedVersion": 1,
        "naturalLanguageRequest": "member correction",
        "answers": [
            {"questionId": question_id, "answer": "test answer"}
            for question_id in QUESTION_IDS[:-1]
        ],
    }


@pytest.mark.asyncio
async def test_organizer_invalid_conversation_is_no_store_and_skips_gateway(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway()
    app = _app(tmp_path, gateway)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v2/trips/conversations",
            headers=_sensitive_headers(),
            json=_organizer_invalid_payload(),
        )

    _assert_validation_response(response)
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_member_invalid_conversation_is_no_store_and_skips_gateway(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway()
    app = _app(tmp_path, gateway)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.put(
            "/api/v2/member-session/conversation",
            headers=_sensitive_headers(),
            json=_member_invalid_payload(),
        )

    _assert_validation_response(response)
    assert gateway.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v2/trips/30000000-0000-4000-8000-000000000001/participants/"
        "10000000-0000-4000-8000-000000000001/invitations",
        "/api/v2/trips/30000000-0000-4000-8000-000000000001/participants/"
        "10000000-0000-4000-8000-000000000001/confirm",
    ],
)
async def test_sensitive_v2_validation_errors_are_no_store_and_skip_gateway(
    tmp_path: Path,
    path: str,
) -> None:
    gateway = CountingGateway()
    app = _app(tmp_path, gateway)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            path,
            headers=_sensitive_headers(),
            json={"schemaVersion": "2.0"},
        )

    _assert_validation_response(response)
    assert gateway.calls == 0
