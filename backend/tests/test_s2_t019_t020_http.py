from __future__ import annotations

import sqlite3
from uuid import UUID, uuid4

import httpx
import pytest

from app.application.execution_event_draft_service import ExecutionEventDraftService
from app.application.plan_service import PlanVersionService
from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.main import create_app
from backend.tests.plan_support import UnusedLocationService, parse_proposal


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


def _executing_app(tmp_path):
    database_path = tmp_path / "s2-adjustment-events.sqlite3"
    plan_service = PlanVersionService(SqlitePlanVersionRepository(database_path))
    app = create_app(
        settings=Settings(
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "amap-adjustment.sqlite3",
            plan_version_db_path=database_path,
        ),
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plan_service,
        execution_event_draft_service=ExecutionEventDraftService(),
    )
    plan = plan_service.register_proposed(parse_proposal())
    trip_id = plan.trip_snapshot.trip_id
    plan_service.confirm(trip_id, plan.plan_id)
    plan_service.start_execution(trip_id)
    return app, database_path, trip_id, plan.plan_id


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


@pytest.mark.asyncio
async def test_confirmed_adjustment_event_is_persisted_and_idempotent(
    tmp_path,
) -> None:
    app, database_path, trip_id, plan_id = _executing_app(tmp_path)
    endpoint = f"/api/v1/execution-adjustments/trips/{trip_id}/events"
    payload = {
        "schemaVersion": "1.0",
        "confirmationStatus": "CONFIRMED",
        "eventType": "LATE",
        "taskId": "task-2",
        "lateMinutes": 20,
        "fatigueLevel": None,
        "planVersionId": str(plan_id),
        "idempotencyKey": "s2-t019-late-confirm-001",
        "occurredAt": "2026-09-05T12:10:00+08:00",
    }

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            first = await client.post(endpoint, json=payload)
            replay = await client.post(
                endpoint,
                json={
                    **payload,
                    # Same instant as +08:00 above; idempotency compares UTC.
                    "occurredAt": "2026-09-05T04:10:00+00:00",
                },
            )
            conflict = await client.post(
                endpoint,
                json={**payload, "lateMinutes": 35},
            )
            occurred_at_conflict = await client.post(
                endpoint,
                json={
                    **payload,
                    "occurredAt": "2026-09-05T12:11:00+08:00",
                },
            )
            fatigue = await client.post(
                endpoint,
                json={
                    **payload,
                    "eventType": "FATIGUE",
                    "lateMinutes": None,
                    "fatigueLevel": "MODERATE",
                    "idempotencyKey": "s2-t019-fatigue-confirm-001",
                    "occurredAt": "2026-09-05T12:20:00+08:00",
                },
            )
            listed = await client.get(endpoint)

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert first.json()["data"] == replay.json()["data"]
    assert first.json()["data"]["eventType"] == "LATE"
    assert first.json()["data"]["planVersionId"] == str(plan_id)
    assert first.json()["data"]["idempotencyKey"] == payload["idempotencyKey"]
    event_id = UUID(first.json()["data"]["eventId"])
    fetched = app.state.workflow_service.get_adjustment_event(trip_id, event_id)
    assert fetched.event_id == event_id
    with pytest.raises(AppError) as cross_trip:
        app.state.workflow_service.get_adjustment_event(uuid4(), event_id)
    assert cross_trip.value.code == "ADJUSTMENT_EVENT_NOT_FOUND"
    assert cross_trip.value.http_status == 404

    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "EVENT_IDEMPOTENCY_CONFLICT"
    assert occurred_at_conflict.status_code == 409, occurred_at_conflict.text
    assert occurred_at_conflict.json()["code"] == "EVENT_IDEMPOTENCY_CONFLICT"

    assert fatigue.status_code == 200, fatigue.text
    assert fatigue.json()["data"]["eventType"] == "FATIGUE"
    assert fatigue.json()["data"]["fatigueLevel"] == "MODERATE"
    assert listed.status_code == 200, listed.text
    assert [item["eventType"] for item in listed.json()["data"]] == [
        "LATE",
        "FATIGUE",
    ]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM execution_adjustment_events"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM execution_events"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_confirmed_adjustment_event_requires_current_plan_and_timezone(
    tmp_path,
) -> None:
    app, database_path, trip_id, plan_id = _executing_app(tmp_path)
    endpoint = f"/api/v1/execution-adjustments/trips/{trip_id}/events"
    payload = {
        "schemaVersion": "1.0",
        "confirmationStatus": "CONFIRMED",
        "eventType": "FATIGUE",
        "taskId": "task-2",
        "lateMinutes": None,
        "fatigueLevel": "MILD",
        "planVersionId": str(plan_id),
        "idempotencyKey": "s2-t019-fatigue-invalid-001",
        "occurredAt": "2026-09-05T12:10:00",
    }

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            naive = await client.post(endpoint, json=payload)
            wrong_plan = await client.post(
                endpoint,
                json={
                    **payload,
                    "planVersionId": "30000000-0000-4000-8000-000000000001",
                    "idempotencyKey": "s2-t019-fatigue-invalid-002",
                    "occurredAt": "2026-09-05T12:10:00+08:00",
                },
            )

    assert naive.status_code == 422, naive.text
    assert wrong_plan.status_code == 409, wrong_plan.text
    assert wrong_plan.json()["code"] == "EVENT_PLAN_NOT_CURRENT"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM execution_adjustment_events"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_adjustment_event_table_does_not_change_legacy_event_semantics(
    tmp_path,
) -> None:
    app, database_path, trip_id, plan_id = _executing_app(tmp_path)
    endpoint = f"/api/v1/trips/{trip_id}/events"
    common = {
        "schemaVersion": "1.0",
        "planVersionId": str(plan_id),
    }
    legacy_payloads = [
        {
            **common,
            "taskId": "task-1",
            "eventType": "START",
            "amountCents": None,
            "idempotencyKey": "legacy-start-001",
            "occurredAt": "2026-09-05T09:40:00+08:00",
        },
        {
            **common,
            "taskId": "task-1",
            "eventType": "EXPENSE",
            "amountCents": 600,
            "idempotencyKey": "legacy-expense-001",
            "occurredAt": "2026-09-05T09:41:00+08:00",
        },
        {
            **common,
            "taskId": "task-1",
            "eventType": "COMPLETE",
            "amountCents": None,
            "idempotencyKey": "legacy-complete-001",
            "occurredAt": "2026-09-05T09:42:00+08:00",
        },
        {
            **common,
            "taskId": "task-2",
            "eventType": "SKIP",
            "amountCents": None,
            "idempotencyKey": "legacy-skip-001",
            "occurredAt": "2026-09-05T09:43:00+08:00",
        },
    ]

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            created = [
                await client.post(endpoint, json=payload)
                for payload in legacy_payloads
            ]
            listed = await client.get(endpoint)

    assert all(response.status_code == 200 for response in created), [
        response.text for response in created
    ]
    assert listed.status_code == 200, listed.text
    assert [event["eventType"] for event in listed.json()["data"]] == [
        "START",
        "EXPENSE",
        "COMPLETE",
        "SKIP",
    ]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM execution_events"
        ).fetchone()[0] == 4
        assert connection.execute(
            "SELECT COUNT(*) FROM execution_adjustment_events"
        ).fetchone()[0] == 0


def test_t019_timeout_default_is_hard_capped_at_ten_seconds() -> None:
    settings = Settings()
    assert settings.bailian_execution_event_timeout_seconds == 10

    with pytest.raises(ValueError):
        Settings(bailian_execution_event_timeout_seconds=10.1)
