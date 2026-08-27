from __future__ import annotations

from copy import deepcopy
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.application.plan_service import PlanVersionService
from app.application.workflow_service import WorkflowService
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.main import create_app
from app.schemas.trip import CreateSingleDayTrip
from app.services.replanning import SuffixPlanningInput
from backend.tests.plan_support import UnusedLocationService


PLANNING_FIXTURE = (
    Path(__file__).parent / "fixtures" / "planning" / "golden_candidate_plan.json"
)


def _candidate_request() -> dict[str, Any]:
    return json.loads(PLANNING_FIXTURE.read_text(encoding="utf-8"))["request"]


def _confirmed_trip(request: dict[str, Any]) -> CreateSingleDayTrip:
    payload = deepcopy(request["trip"])
    payload["status"] = "DRAFT"
    return CreateSingleDayTrip.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )


def _app_and_database(tmp_path: Path, *, suffix_planner: object | None = None):
    database_path = tmp_path / "s1_t017.sqlite3"
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    workflow.confirm_trip(_confirmed_trip(_candidate_request()))
    plans = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=workflow,
    )
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plans,
        workflow_service=workflow,
        suffix_planner=suffix_planner,
    )
    return app, database_path


async def _generate_confirm_and_start(
    client: httpx.AsyncClient,
    request: dict[str, Any],
) -> dict[str, Any]:
    trip_id = request["trip"]["tripId"]
    profile = request["trip"]["participants"][0]["assistanceProfile"]
    saved = await client.put(f"/api/v1/trips/{trip_id}/constraints", json=profile)
    confirmed_constraints = await client.post(
        f"/api/v1/trips/{trip_id}/constraints/confirm"
    )
    generated = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions/generate",
        json=request,
    )
    assert saved.status_code == 200, saved.text
    assert confirmed_constraints.status_code == 200, confirmed_constraints.text
    assert generated.status_code == 200, generated.text
    plan = generated.json()["data"]
    confirmed = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions/{plan['planId']}/confirm"
    )
    started = await client.post(f"/api/v1/trips/{trip_id}/execution/start")
    assert confirmed.status_code == 200, confirmed.text
    assert started.status_code == 200, started.text
    return plan


async def _write_event(
    client: httpx.AsyncClient,
    *,
    trip_id: str,
    plan_id: str,
    task_id: str,
    event_type: str,
    key: str,
    amount_cents: int | None = None,
) -> httpx.Response:
    return await client.post(
        f"/api/v1/trips/{trip_id}/events",
        json={
            "schemaVersion": "1.0",
            "taskId": task_id,
            "planVersionId": plan_id,
            "eventType": event_type,
            "amountCents": amount_cents,
            "idempotencyKey": key,
            "occurredAt": "2026-09-05T10:30:00+08:00",
        },
    )


async def _record_completed_task(
    client: httpx.AsyncClient,
    *,
    trip_id: str,
    plan_id: str,
    task_id: str,
    actual_cents: int,
) -> None:
    expense = await _write_event(
        client,
        trip_id=trip_id,
        plan_id=plan_id,
        task_id=task_id,
        event_type="EXPENSE",
        key=f"{task_id}:expense:{actual_cents}",
        amount_cents=actual_cents,
    )
    complete = await _write_event(
        client,
        trip_id=trip_id,
        plan_id=plan_id,
        task_id=task_id,
        event_type="COMPLETE",
        key=f"{task_id}:complete",
    )
    assert expense.status_code == 200, expense.text
    assert complete.status_code == 200, complete.text


async def _request_event_replan(
    client: httpx.AsyncClient,
    trip_id: str,
) -> httpx.Response:
    return await client.post(
        f"/api/v1/trips/{trip_id}/replans/from-events",
        json={
            "schemaVersion": "1.0",
            "reason": "EXPENSE_CHANGE",
        },
    )


@pytest.mark.asyncio
async def test_default_app_replans_from_events_and_freezes_completed_prefix(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_confirm_and_start(client, request)
        first_task = current["days"][0]["tasks"][0]
        await _record_completed_task(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            task_id=first_task["taskId"],
            actual_cents=first_task["costCents"] + 5_000,
        )
        replanned = await _request_event_replan(client, trip_id)
        assert replanned.status_code == 200, replanned.text
        result = replanned.json()["data"]
        candidate = result["plan"]
        diff = await client.get(
            f"/api/v1/trips/{trip_id}/plan-versions/{candidate['planId']}/diff"
        )
        restored = await client.get(f"/api/v1/trips/{trip_id}")

    assert result["outcome"] == "SELECTED"
    assert result["frozenTaskIds"] == [first_task["taskId"]]
    assert result["disruptionScore"] == 0
    assert candidate["version"] == 2
    assert candidate["parentId"] == current["planId"]
    assert candidate["status"] == "PROPOSED"
    assert candidate["days"][0]["tasks"][0] == first_task
    budget_check = next(
        item
        for item in result["validationReport"]["checks"]
        if item["ruleId"] == "REPLAN.BUDGET.ACTUAL_PLUS_REMAINING"
    )
    assert budget_check["status"] == "PASS"
    assert diff.status_code == 200, diff.text
    state = restored.json()["data"]
    assert state["currentPlan"]["planId"] == current["planId"]
    assert [item["planId"] for item in state["proposedPlans"]] == [
        candidate["planId"]
    ]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version, status FROM plan_versions ORDER BY version"
        ).fetchall() == [(1, "CURRENT"), (2, "PROPOSED")]


@pytest.mark.asyncio
async def test_planner_receives_only_unfinished_suffix(
    tmp_path: Path,
) -> None:
    class CapturingPlanner:
        def __init__(self) -> None:
            self.inputs: list[SuffixPlanningInput] = []

        def plan_suffix(self, planning_input: SuffixPlanningInput):
            self.inputs.append(planning_input)
            return planning_input.task_facts

    planner = CapturingPlanner()
    app, _ = _app_and_database(tmp_path, suffix_planner=planner)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_confirm_and_start(client, request)
        first = current["days"][0]["tasks"][0]
        await _record_completed_task(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            task_id=first["taskId"],
            actual_cents=first["costCents"] + 5_000,
        )
        response = await _request_event_replan(client, trip_id)

    assert response.status_code == 200, response.text
    assert len(planner.inputs) == 1
    planning_input = planner.inputs[0]
    assert planning_input.frozen_task_ids == (first["taskId"],)
    assert [item.task_id for item in planning_input.task_facts] == [
        item["taskId"] for item in current["days"][0]["tasks"][1:]
    ]
    assert planning_input.actual_spent_cents == first["costCents"] + 5_000


@pytest.mark.asyncio
async def test_over_budget_event_has_no_v2_side_effect(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_confirm_and_start(client, request)
        first = current["days"][0]["tasks"][0]
        await _record_completed_task(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            task_id=first["taskId"],
            actual_cents=50_000,
        )
        response = await _request_event_replan(client, trip_id)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "REPLAN_NO_FEASIBLE_CANDIDATE"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version, status FROM plan_versions ORDER BY version"
        ).fetchall() == [(1, "CURRENT")]
        assert connection.execute(
            """
            SELECT COUNT(*) FROM trusted_plan_issuances
            WHERE plan_version = 2
            """
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_completed_task_without_expense_fails_closed_without_v2(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_confirm_and_start(client, request)
        first = current["days"][0]["tasks"][0]
        complete = await _write_event(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            task_id=first["taskId"],
            event_type="COMPLETE",
            key="complete-without-expense",
        )
        response = await _request_event_replan(client, trip_id)

    assert complete.status_code == 200, complete.text
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "REPLAN_EXPENSE_INCOMPLETE"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version, status FROM plan_versions ORDER BY version"
        ).fetchall() == [(1, "CURRENT")]
        assert connection.execute(
            """
            SELECT COUNT(*) FROM trusted_plan_issuances
            WHERE plan_version = 2
            """
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_event_replan_without_events_fails_closed_without_v2(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _generate_confirm_and_start(client, request)
        response = await _request_event_replan(client, trip_id)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "REPLAN_EVENTS_REQUIRED"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version, status FROM plan_versions ORDER BY version"
        ).fetchall() == [(1, "CURRENT")]
        assert connection.execute(
            """
            SELECT COUNT(*) FROM trusted_plan_issuances
            WHERE plan_version = 2
            """
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_event_replan_without_unfinished_suffix_fails_closed_without_v2(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_confirm_and_start(client, request)
        for task in current["days"][0]["tasks"]:
            await _record_completed_task(
                client,
                trip_id=trip_id,
                plan_id=current["planId"],
                task_id=task["taskId"],
                actual_cents=task["costCents"],
            )
        response = await _request_event_replan(client, trip_id)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "REPLAN_SUFFIX_EMPTY"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version, status FROM plan_versions ORDER BY version"
        ).fetchall() == [(1, "CURRENT")]
        assert connection.execute(
            """
            SELECT COUNT(*) FROM trusted_plan_issuances
            WHERE plan_version = 2
            """
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_same_event_replan_is_idempotent(tmp_path: Path) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_confirm_and_start(client, request)
        first = current["days"][0]["tasks"][0]
        await _record_completed_task(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            task_id=first["taskId"],
            actual_cents=first["costCents"] + 5_000,
        )
        first_response = await _request_event_replan(client, trip_id)
        second_response = await _request_event_replan(client, trip_id)

    assert first_response.status_code == second_response.status_code == 200
    assert (
        first_response.json()["data"]["plan"]["planId"]
        == second_response.json()["data"]["plan"]["planId"]
    )
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE version = 2"
        ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_rejected_v2_cannot_be_replayed_as_selected(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_confirm_and_start(client, request)
        first = current["days"][0]["tasks"][0]
        await _record_completed_task(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            task_id=first["taskId"],
            actual_cents=first["costCents"] + 5_000,
        )
        generated = await _request_event_replan(client, trip_id)
        assert generated.status_code == 200, generated.text
        candidate_id = generated.json()["data"]["plan"]["planId"]
        rejected = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{candidate_id}/reject"
        )
        assert rejected.status_code == 200, rejected.text

        tables = (
            "trips",
            "plan_versions",
            "execution_events",
            "trusted_plan_issuances",
        )
        with sqlite3.connect(database_path) as connection:
            before = {
                table: connection.execute(
                    f"SELECT * FROM {table} ORDER BY rowid"
                ).fetchall()
                for table in tables
            }

        replay = await _request_event_replan(client, trip_id)

    assert replay.status_code == 409, replay.text
    assert replay.json()["code"] == "REPLAN_S1_VERSION_LIMIT"
    with sqlite3.connect(database_path) as connection:
        after = {
            table: connection.execute(
                f"SELECT * FROM {table} ORDER BY rowid"
            ).fetchall()
            for table in tables
        }
    assert after == before


@pytest.mark.asyncio
async def test_event_replan_rejects_free_text_feedback_contract_without_v2(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_confirm_and_start(client, request)
        first = current["days"][0]["tasks"][0]
        await _record_completed_task(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            task_id=first["taskId"],
            actual_cents=first["costCents"] + 5_000,
        )
        feedback_response = await client.post(
            f"/api/v1/trips/{trip_id}/replans/from-events",
            json={
                "schemaVersion": "1.0",
                "reason": "EXPENSE_CHANGE",
                "feedback": "自由文本反馈不属于 S1-T017",
            },
        )
        user_feedback_response = await client.post(
            f"/api/v1/trips/{trip_id}/replans/from-events",
            json={
                "schemaVersion": "1.0",
                "reason": "USER_FEEDBACK",
            },
        )

    assert feedback_response.status_code == 422, feedback_response.text
    assert feedback_response.json()["code"] == "TRIP_SCHEMA_INVALID"
    assert user_feedback_response.status_code == 422, user_feedback_response.text
    assert user_feedback_response.json()["code"] == "TRIP_SCHEMA_INVALID"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version, status FROM plan_versions ORDER BY version"
        ).fetchall() == [(1, "CURRENT")]
        assert connection.execute(
            """
            SELECT COUNT(*) FROM trusted_plan_issuances
            WHERE plan_version = 2
            """
        ).fetchone() == (0,)
