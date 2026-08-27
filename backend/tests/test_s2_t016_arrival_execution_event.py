from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from typing import Any

import httpx
import pytest

from app.application.plan_service import PlanVersionService
from app.application.workflow_service import WorkflowService
from app.core.config import Settings
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.main import create_app
from app.schemas.trip import CreateSingleDayTrip
from backend.tests.plan_support import UnusedLocationService


PLANNING_FIXTURE = (
    Path(__file__).parent / "fixtures" / "planning" / "golden_candidate_plan.json"
)
T016_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "s2_t016"
    / "arrival_execution_event.json"
)


def _planning_request() -> dict[str, Any]:
    return json.loads(PLANNING_FIXTURE.read_text(encoding="utf-8"))["request"]


def _t016_fixture() -> dict[str, Any]:
    return json.loads(T016_FIXTURE.read_text(encoding="utf-8"))


def _confirmed_trip(request: dict[str, Any]) -> CreateSingleDayTrip:
    payload = deepcopy(request["trip"])
    payload["status"] = "DRAFT"
    return CreateSingleDayTrip.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )


def _app_for_database(database_path: Path, cache_path: Path):
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    plans = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=workflow,
    )
    settings = Settings(
        amap_web_service_key="test-amap",
        amap_cache_db_path=cache_path,
        plan_version_db_path=database_path,
    )
    return create_app(
        settings=settings,
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plans,
        workflow_service=workflow,
    )


async def _start_execution(
    client: httpx.AsyncClient,
    request: dict[str, Any],
) -> dict[str, Any]:
    trip_id = request["trip"]["tripId"]
    profile = request["trip"]["participants"][0]["assistanceProfile"]
    assert (
        await client.put(
            f"/api/v1/trips/{trip_id}/constraints",
            json=profile,
        )
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/trips/{trip_id}/constraints/confirm")
    ).status_code == 200
    generated = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions/generate",
        json=request,
    )
    assert generated.status_code == 200, generated.text
    plan = generated.json()["data"]
    assert (
        await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{plan['planId']}/confirm"
        )
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/trips/{trip_id}/execution/start")
    ).status_code == 200
    return plan


def _fill_payloads(
    *,
    task_id: str,
    plan_id: str,
    evidence_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = _t016_fixture()
    location = deepcopy(fixture["locationEvidence"])
    location["taskId"] = task_id
    event = deepcopy(fixture["arrivalEvent"])
    event["taskId"] = task_id
    event["planVersionId"] = plan_id
    event["arrivalEvidenceId"] = evidence_id or "__EVIDENCE_ID__"
    return location, event


@pytest.mark.asyncio
async def test_arrival_event_is_idempotent_and_restores_after_refresh(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "s2-t016.sqlite3"
    request = _planning_request()
    trip_id = request["trip"]["tripId"]
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    workflow.confirm_trip(_confirmed_trip(request))
    first_app = _app_for_database(database_path, tmp_path / "amap-1.sqlite3")

    async with first_app.router.lifespan_context(first_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=first_app),
            base_url="http://testserver",
        ) as client:
            plan = await _start_execution(client, request)
            task_id = plan["days"][0]["tasks"][0]["taskId"]
            location, _ = _fill_payloads(
                task_id=task_id,
                plan_id=plan["planId"],
            )
            saved = await client.post(
                f"/api/v1/trips/{trip_id}/arrival-evidence",
                json=location,
            )
            assert saved.status_code == 200, saved.text
            evidence_id = saved.json()["data"]["evidenceId"]
            _, event_payload = _fill_payloads(
                task_id=task_id,
                plan_id=plan["planId"],
                evidence_id=evidence_id,
            )
            first = await client.post(
                f"/api/v1/trips/{trip_id}/arrival-events",
                json=event_payload,
            )
            retry = await client.post(
                f"/api/v1/trips/{trip_id}/arrival-events",
                json=event_payload,
            )

    assert first.status_code == 200, first.text
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    event = first.json()["data"]
    assert event["eventType"] == "COMPLETE"
    assert event["tripId"] == trip_id
    assert event["taskId"] == task_id
    assert event["arrivalEvidence"] == {
        "evidenceId": evidence_id,
        **_t016_fixture()["expectedArrivalEvidence"],
    }

    refreshed_app = _app_for_database(
        database_path,
        tmp_path / "amap-2.sqlite3",
    )
    async with refreshed_app.router.lifespan_context(refreshed_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=refreshed_app),
            base_url="http://testserver",
        ) as client:
            restored = await client.get(
                f"/api/v1/trips/{trip_id}/arrival-events"
            )
            all_events = await client.get(f"/api/v1/trips/{trip_id}/events")
            summary = await client.get(f"/api/v1/trips/{trip_id}/summary")

    assert restored.status_code == 200
    assert restored.json()["data"] == [event]
    assert all_events.json()["data"] == [event]
    assert task_id in summary.json()["data"]["completedTaskIds"]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM execution_events"
        ).fetchone()[0] == 1
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(execution_events)"
            ).fetchall()
        }
    assert "arrival_evidence_json" in columns


@pytest.mark.asyncio
async def test_non_arrived_evidence_does_not_complete_or_write_event(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "s2-t016-too-far.sqlite3"
    request = _planning_request()
    trip_id = request["trip"]["tripId"]
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    workflow.confirm_trip(_confirmed_trip(request))
    app = _app_for_database(database_path, tmp_path / "amap.sqlite3")

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            plan = await _start_execution(client, request)
            task_id = plan["days"][0]["tasks"][0]["taskId"]
            location, _ = _fill_payloads(
                task_id=task_id,
                plan_id=plan["planId"],
            )
            location["locationEvidence"]["longitude"] += 0.02
            saved = await client.post(
                f"/api/v1/trips/{trip_id}/arrival-evidence",
                json=location,
            )
            evidence_id = saved.json()["data"]["evidenceId"]
            _, event_payload = _fill_payloads(
                task_id=task_id,
                plan_id=plan["planId"],
                evidence_id=evidence_id,
            )
            rejected = await client.post(
                f"/api/v1/trips/{trip_id}/arrival-events",
                json=event_payload,
            )
            restored = await client.get(f"/api/v1/trips/{trip_id}/events")

    assert rejected.status_code == 409
    assert rejected.json()["code"] == "ARRIVAL_CONFIRMATION_REQUIRED"
    assert rejected.json()["errors"][0]["code"] == "TOO_FAR"
    assert restored.json()["data"] == []


@pytest.mark.asyncio
async def test_same_event_key_with_different_evidence_conflicts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "s2-t016-conflict.sqlite3"
    request = _planning_request()
    trip_id = request["trip"]["tripId"]
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    workflow.confirm_trip(_confirmed_trip(request))
    app = _app_for_database(database_path, tmp_path / "amap.sqlite3")

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            plan = await _start_execution(client, request)
            task_id = plan["days"][0]["tasks"][0]["taskId"]
            location, _ = _fill_payloads(
                task_id=task_id,
                plan_id=plan["planId"],
            )
            first_evidence = await client.post(
                f"/api/v1/trips/{trip_id}/arrival-evidence",
                json=location,
            )
            location["idempotencyKey"] = "s2-t016:location:002"
            location["locationEvidence"]["capturedAt"] = (
                "2026-09-05T10:31:00+08:00"
            )
            second_evidence = await client.post(
                f"/api/v1/trips/{trip_id}/arrival-evidence",
                json=location,
            )
            _, first_payload = _fill_payloads(
                task_id=task_id,
                plan_id=plan["planId"],
                evidence_id=first_evidence.json()["data"]["evidenceId"],
            )
            _, second_payload = _fill_payloads(
                task_id=task_id,
                plan_id=plan["planId"],
                evidence_id=second_evidence.json()["data"]["evidenceId"],
            )
            first = await client.post(
                f"/api/v1/trips/{trip_id}/arrival-events",
                json=first_payload,
            )
            conflict = await client.post(
                f"/api/v1/trips/{trip_id}/arrival-events",
                json=second_payload,
            )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "EVENT_IDEMPOTENCY_CONFLICT"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM execution_events"
        ).fetchone()[0] == 1
