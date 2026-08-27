from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
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
SCENARIO_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "s2_t017"
    / "memory_timeline_scenarios.json"
)


def _scenarios() -> list[dict[str, Any]]:
    return json.loads(SCENARIO_FIXTURE.read_text(encoding="utf-8"))["scenarios"]


def _planning_request(
    task_ids: tuple[str, str, str, str],
    costs: tuple[int, int, int, int],
) -> dict[str, Any]:
    request = json.loads(PLANNING_FIXTURE.read_text(encoding="utf-8"))["request"]
    for fact, task_id, cost in zip(
        request["taskFacts"],
        task_ids,
        costs,
        strict=True,
    ):
        fact["taskId"] = task_id
        fact["place"]["priceReference"]["amountCents"] = cost
        fact["route"]["priceReference"]["amountCents"] = 0
    return request


def _confirmed_trip(request: dict[str, Any]) -> CreateSingleDayTrip:
    payload = deepcopy(request["trip"])
    payload["status"] = "DRAFT"
    return CreateSingleDayTrip.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )


async def _post_event(
    client: httpx.AsyncClient,
    *,
    trip_id: str,
    plan_id: str,
    task_id: str,
    event_type: str,
    occurred_at: str,
    key: str,
    amount_cents: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "schemaVersion": "1.0",
        "taskId": task_id,
        "planVersionId": plan_id,
        "eventType": event_type,
        "idempotencyKey": key,
        "occurredAt": occurred_at,
    }
    if amount_cents is not None:
        payload["amountCents"] = amount_cents
    response = await client.post(
        f"/api/v1/trips/{trip_id}/events",
        json=payload,
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda item: item["id"])
async def test_four_memory_scenarios_are_complete_sorted_and_traceable(
    scenario: dict[str, Any],
    tmp_path: Path,
) -> None:
    fixture = json.loads(SCENARIO_FIXTURE.read_text(encoding="utf-8"))
    database_path = tmp_path / f"{scenario['id']}.sqlite3"
    v1_request = _planning_request(
        ("task-1", "task-2", "task-3", "task-4"),
        (600, 13_800, 400, 15_000),
    )
    v2_request = _planning_request(
        ("task-1", "task-2", "task-4", "task-5"),
        (600, 11_800, 14_000, 1_000),
    )
    trip_id = v1_request["trip"]["tripId"]
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    workflow.confirm_trip(_confirmed_trip(v1_request))
    plans = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=workflow,
    )
    app = create_app(
        settings=Settings(
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / f"{scenario['id']}-amap.sqlite3",
            plan_version_db_path=database_path,
        ),
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plans,
        workflow_service=workflow,
    )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            profile = v1_request["trip"]["participants"][0]["assistanceProfile"]
            assert (
                await client.put(
                    f"/api/v1/trips/{trip_id}/constraints",
                    json=profile,
                )
            ).status_code == 200
            assert (
                await client.post(
                    f"/api/v1/trips/{trip_id}/constraints/confirm"
                )
            ).status_code == 200
            generated_v1 = await client.post(
                f"/api/v1/trips/{trip_id}/plan-versions/generate",
                json=v1_request,
            )
            assert generated_v1.status_code == 200, generated_v1.text
            current_plan = generated_v1.json()["data"]
            assert (
                await client.post(
                    f"/api/v1/trips/{trip_id}/plan-versions/"
                    f"{current_plan['planId']}/confirm"
                )
            ).status_code == 200
            assert (
                await client.post(f"/api/v1/trips/{trip_id}/execution/start")
            ).status_code == 200

            if scenario["withV2"]:
                generated_v2 = await client.post(
                    f"/api/v1/trips/{trip_id}/replans",
                    json={
                        "schemaVersion": "1.0",
                        "reason": "USER_FEEDBACK",
                        "lockedTaskIds": [],
                        "candidates": [
                            {"request": v2_request, "satisfactionLoss": 0}
                        ],
                    },
                )
                assert generated_v2.status_code == 200, generated_v2.text
                current_plan = generated_v2.json()["data"]["plan"]
                accepted = await client.post(
                    f"/api/v1/trips/{trip_id}/plan-versions/"
                    f"{current_plan['planId']}/accept"
                )
                assert accepted.status_code == 200, accepted.text

            task_ids = [task["taskId"] for task in current_plan["days"][0]["tasks"]]
            # Deliberately submit out of chronological order.
            await _post_event(
                client,
                trip_id=trip_id,
                plan_id=current_plan["planId"],
                task_id=task_ids[1],
                event_type="EXPENSE",
                amount_cents=700,
                occurred_at="2030-01-01T12:00:00+08:00",
                key=f"{scenario['id']}:expense-late",
            )
            await _post_event(
                client,
                trip_id=trip_id,
                plan_id=current_plan["planId"],
                task_id=task_ids[0],
                event_type="COMPLETE",
                occurred_at="2030-01-01T11:00:00+08:00",
                key=f"{scenario['id']}:complete",
            )
            await _post_event(
                client,
                trip_id=trip_id,
                plan_id=current_plan["planId"],
                task_id=task_ids[0],
                event_type="EXPENSE",
                amount_cents=300,
                occurred_at="2030-01-01T10:00:00+08:00",
                key=f"{scenario['id']}:expense-early",
            )

            deleted_task = task_ids[1]
            deleted_upload = await client.post(
                f"/api/v2/trips/{trip_id}/tasks/{deleted_task}/media",
                json={
                    "data_url": fixture["deletedPhotoDataUrl"],
                    "mime_type": "image/jpeg",
                    "byte_size": 20,
                },
            )
            assert deleted_upload.status_code == 200, deleted_upload.text
            assert (
                await client.delete(
                    f"/api/v2/trips/{trip_id}/tasks/{deleted_task}/media"
                )
            ).status_code == 200

            if scenario["withPhoto"]:
                active_upload = await client.post(
                    f"/api/v2/trips/{trip_id}/tasks/{task_ids[0]}/media",
                    json={
                        "data_url": fixture["activePhotoDataUrl"],
                        "mime_type": "image/jpeg",
                        "byte_size": 19,
                    },
                )
                assert active_upload.status_code == 200, active_upload.text

            first = await client.get(
                f"/api/v1/trips/{trip_id}/memory-timeline"
            )
            second = await client.get(
                f"/api/v1/trips/{trip_id}/memory-timeline"
            )

    assert first.status_code == 200, first.text
    assert second.json() == first.json()
    timeline = first.json()["data"]
    summary = timeline["summary"]
    assert summary["completedTaskCount"] == 1
    assert summary["totalTaskCount"] == 4
    assert summary["completionRatePercent"] == 25.0
    assert summary["actualCostCents"] == 1_000
    assert summary["costDifferenceCents"] == (
        summary["actualCostCents"] - summary["plannedCostCents"]
    )
    assert summary["currentPlanVersion"] == (2 if scenario["withV2"] else 1)
    assert summary["planChangeCount"] == (1 if scenario["withV2"] else 0)
    assert summary["photoCount"] == (1 if scenario["withPhoto"] else 0)
    assert summary["assistanceProfile"] == profile

    items = timeline["items"]
    occurred = [datetime.fromisoformat(item["occurredAt"]) for item in items]
    assert occurred == sorted(occurred)
    plan_items = [item for item in items if item["kind"] == "PLAN_VERSION"]
    assert len(plan_items) == (2 if scenario["withV2"] else 1)
    current_plan_item = next(
        item for item in plan_items if item["planStatus"] == "CURRENT"
    )
    assert current_plan_item["amountCents"] == summary["plannedCostCents"]
    expenses = [item for item in items if item["kind"] == "EXPENSE"]
    assert sum(item["amountCents"] for item in expenses) == summary["actualCostCents"]
    assert all(item["eventId"] and item["planVersionId"] for item in expenses)
    assert any(item["kind"] == "CARE_CONFIRMED" for item in items)
    photos = [item for item in items if item["kind"] == "PHOTO"]
    assert len(photos) == (1 if scenario["withPhoto"] else 0)
    serialized = json.dumps(timeline, ensure_ascii=False)
    assert fixture["deletedPhotoDataUrl"] not in serialized
    assert (fixture["activePhotoDataUrl"] in serialized) is scenario["withPhoto"]
