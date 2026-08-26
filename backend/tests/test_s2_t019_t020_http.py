from __future__ import annotations

import sqlite3

import httpx
import pytest

from app.application.execution_event_draft_service import ExecutionEventDraftService
from app.core.config import Settings
from app.main import create_app
from backend.tests.plan_support import UnusedLocationService


def _row_counts(database_path) -> dict[str, int]:
    with sqlite3.connect(database_path) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        return {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in tables
        }


@pytest.mark.asyncio
async def test_http_parse_and_compile_are_zero_write_and_exact(tmp_path) -> None:
    database_path = tmp_path / "s2.sqlite3"
    settings = Settings(
        amap_web_service_key="test-amap",
        amap_cache_db_path=tmp_path / "amap.sqlite3",
        plan_version_db_path=database_path,
    )
    app = create_app(
        settings=settings,
        service=UnusedLocationService(),  # type: ignore[arg-type]
        execution_event_draft_service=ExecutionEventDraftService(),
    )
    before = _row_counts(database_path)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            parsed = await client.post(
                "/api/v1/execution-adjustments/parse",
                json={
                    "schemaVersion": "1.0",
                    "rawText": "晚了二十分钟",
                    "taskId": "task-2",
                    "currentTask": {
                        "taskId": "task-2",
                        "title": "参观博物馆",
                    },
                },
            )
            compiled = await client.post(
                "/api/v1/execution-adjustments/compile",
                json={
                    "schemaVersion": "1.0",
                    "event": {
                        "schemaVersion": "1.0",
                        "confirmationStatus": "CONFIRMED",
                        "eventType": "LATE",
                        "taskId": "task-2",
                        "lateMinutes": 20,
                        "fatigueLevel": None,
                    },
                    "currentConstraints": {"remainingTimeMinutes": 180},
                },
            )

    assert parsed.status_code == 200, parsed.text
    assert set(parsed.json()) == {
        "schemaVersion",
        "eventType",
        "taskId",
        "lateMinutes",
        "fatigueLevel",
        "clarificationQuestions",
    }
    assert parsed.json()["lateMinutes"] == 20
    assert parsed.headers["X-Recognition-Source"] == "DETERMINISTIC_FORM"

    assert compiled.status_code == 200, compiled.text
    body = compiled.json()
    assert body["constraints"] == [
        {
            "field": "remaining.timeBudgetMinutes",
            "operator": "LTE",
            "value": 160,
            "scope": "REMAINING_ITINERARY",
            "hardness": "HARD",
        }
    ]
    assert body["sourceEvent"]["confirmationStatus"] == "CONFIRMED"
    assert _row_counts(database_path) == before


def test_t019_timeout_default_is_hard_capped_at_ten_seconds() -> None:
    settings = Settings()
    assert settings.bailian_execution_event_timeout_seconds == 10

    with pytest.raises(ValueError):
        Settings(bailian_execution_event_timeout_seconds=10.1)
