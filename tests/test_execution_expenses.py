import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.application.plan_service import PlanVersionService
from app.application.workflow_service import WorkflowService
from app.infrastructure.plan_store import PlanStoreError, SqlitePlanVersionRepository
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.main import create_app
from app.schemas.execution import CreateExecutionEvent, ExecutionEventType
from tests.test_plan_v2_diff import setup_executing, v2_payload
from tests.test_plan_versions import UnusedLocationService, parse_proposal


def expense_input(
    *,
    plan_id,
    task_id: str,
    amount_cents: int,
    key: str,
    offset_minutes: int = 0,
) -> CreateExecutionEvent:
    return CreateExecutionEvent(
        schema_version="1.0",
        task_id=task_id,
        plan_version_id=plan_id,
        event_type=ExecutionEventType.EXPENSE,
        amount_cents=amount_cents,
        idempotency_key=key,
        occurred_at=datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
        + timedelta(minutes=offset_minutes),
    )


def setup_services(tmp_path: Path):
    database_path = tmp_path / "events.sqlite3"
    plans = SqlitePlanVersionRepository(database_path)
    current = setup_executing(plans)
    workflow = SqliteWorkflowRepository(database_path)
    workflow_service = WorkflowService(workflow)
    plan_service = PlanVersionService(plans, workflow_service=workflow_service)
    return database_path, plans, workflow, workflow_service, plan_service, current


def test_legacy_execution_events_schema_adds_created_at_without_data_loss(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy_events.sqlite3"
    event_id = "10000000-0000-4000-8000-000000000001"
    trip_id = "10000000-0000-4000-8000-000000000002"
    plan_id = "10000000-0000-4000-8000-000000000003"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE execution_events (
                event_id TEXT PRIMARY KEY,
                trip_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                plan_version_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                amount_cents INTEGER,
                idempotency_key TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                UNIQUE (trip_id, idempotency_key)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO execution_events (
                event_id, trip_id, task_id, plan_version_id, event_type,
                amount_cents, idempotency_key, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                trip_id,
                "legacy-task",
                plan_id,
                "EXPENSE",
                1_234,
                "legacy-expense",
                "2026-08-24T02:00:00+00:00",
            ),
        )

    repository = SqliteWorkflowRepository(database_path)
    reopened = SqliteWorkflowRepository(database_path)

    with sqlite3.connect(database_path) as connection:
        columns = connection.execute(
            "PRAGMA table_info(execution_events)"
        ).fetchall()
        stored = connection.execute(
            "SELECT event_id, created_at FROM execution_events"
        ).fetchone()
    assert [column[1] for column in columns].count("created_at") == 1
    assert stored == (event_id, None)

    restored = reopened.list_events(UUID(trip_id))
    assert len(restored) == 1
    assert restored[0].event_id == UUID(event_id)
    assert restored[0].plan_version_id == UUID(plan_id)
    assert restored[0].amount_cents == 1_234
    assert repository.list_events(UUID(trip_id)) == restored


def test_expenses_use_integer_cents_and_refresh_recomputes_from_event_stream(
    tmp_path: Path,
) -> None:
    database_path, _, workflow, _, _, v1 = setup_services(tmp_path)
    lunch = expense_input(
        plan_id=v1.plan_id,
        task_id="task-2",
        amount_cents=13_800,
        key="expense-task-2-v1",
    )
    park = expense_input(
        plan_id=v1.plan_id,
        task_id="task-3",
        amount_cents=5_000,
        key="expense-task-3-v1",
        offset_minutes=90,
    )

    first = workflow.create_event(v1.trip_snapshot.trip_id, lunch)
    replay = workflow.create_event(v1.trip_snapshot.trip_id, lunch)
    workflow.create_event(v1.trip_snapshot.trip_id, park)

    assert replay.event_id == first.event_id
    budget = workflow.get_budget_summary(v1.trip_snapshot.trip_id)
    assert budget.planned_budget_cents == 35_000
    assert budget.actual_spent_cents == 18_800
    assert budget.remaining_budget_cents == 16_200
    assert budget.expense_event_count == 2

    reopened_workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    reopened_plan = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=reopened_workflow,
    )
    restored = reopened_plan.get_trip_state(v1.trip_snapshot.trip_id)
    assert len(restored.events) == 2
    assert restored.actual_budget == budget
    assert [event.amount_cents for event in restored.events] == [13_800, 5_000]
    assert all(event.plan_version_id == v1.plan_id for event in restored.events)


def test_reused_idempotency_key_with_different_expense_is_rejected(
    tmp_path: Path,
) -> None:
    _, _, workflow, _, _, v1 = setup_services(tmp_path)
    original = expense_input(
        plan_id=v1.plan_id,
        task_id="task-2",
        amount_cents=13_800,
        key="same-expense-key",
    )
    workflow.create_event(v1.trip_snapshot.trip_id, original)

    changed = original.model_copy(update={"amount_cents": 13_801})
    with pytest.raises(PlanStoreError) as conflict:
        workflow.create_event(v1.trip_snapshot.trip_id, changed)

    assert conflict.value.code == "EVENT_IDEMPOTENCY_CONFLICT"
    budget = workflow.get_budget_summary(v1.trip_snapshot.trip_id)
    assert budget.actual_spent_cents == 13_800
    assert budget.expense_event_count == 1


def test_expense_replay_remains_idempotent_after_current_switches_to_v2(
    tmp_path: Path,
) -> None:
    _, plans, workflow, _, _, v1 = setup_services(tmp_path)
    expense = expense_input(
        plan_id=v1.plan_id,
        task_id="task-2",
        amount_cents=13_800,
        key="expense-before-v2-switch",
    )
    first = workflow.create_event(v1.trip_snapshot.trip_id, expense)
    v2 = parse_proposal(v2_payload())
    plans.register_proposed(v2)
    plans.accept_v2(v1.trip_snapshot.trip_id, v2.plan_id)

    replay = workflow.create_event(v1.trip_snapshot.trip_id, expense)
    budget = workflow.get_budget_summary(v1.trip_snapshot.trip_id)

    assert replay.event_id == first.event_id
    assert budget.plan_version_id == v2.plan_id
    assert budget.actual_spent_cents == 13_800
    assert budget.expense_event_count == 1


def test_event_must_bind_current_plan_and_existing_task(tmp_path: Path) -> None:
    _, _, workflow, _, _, v1 = setup_services(tmp_path)
    event = expense_input(
        plan_id=v1.plan_id,
        task_id="missing-task",
        amount_cents=1_000,
        key="missing-task-key",
    )

    with pytest.raises(PlanStoreError) as missing:
        workflow.create_event(v1.trip_snapshot.trip_id, event)
    assert missing.value.code == "EVENT_TASK_NOT_FOUND"


@pytest.mark.asyncio
async def test_expense_http_is_idempotent_and_rejects_fractional_cents(
    tmp_path: Path,
) -> None:
    _, _, _, workflow_service, plan_service, v1 = setup_services(tmp_path)
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plan_service,
        workflow_service=workflow_service,
    )
    payload = {
        "schemaVersion": "1.0",
        "taskId": "task-2",
        "planVersionId": str(v1.plan_id),
        "eventType": "EXPENSE",
        "amountCents": 13_800,
        "idempotencyKey": "http-expense-task-2",
        "occurredAt": "2026-08-25T10:00:00+08:00",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            f"/api/v1/trips/{v1.trip_snapshot.trip_id}/events", json=payload
        )
        replay = await client.post(
            f"/api/v1/trips/{v1.trip_snapshot.trip_id}/events", json=payload
        )
        restored = await client.get(f"/api/v1/trips/{v1.trip_snapshot.trip_id}")
        fractional = await client.post(
            f"/api/v1/trips/{v1.trip_snapshot.trip_id}/events",
            json={**payload, "idempotencyKey": "fractional-expense", "amountCents": 50.5},
        )

    assert first.status_code == replay.status_code == restored.status_code == 200
    assert replay.json()["data"]["eventId"] == first.json()["data"]["eventId"]
    assert restored.json()["data"]["actualBudget"]["actualSpentCents"] == 13_800
    assert len(restored.json()["data"]["events"]) == 1
    assert fractional.status_code == 422


def test_t016_budget_recalculation_evidence() -> None:
    evidence = json.loads(
        Path("docs/testing/evidence/s1_t016_expense_event_stream.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["taskId"] == "S1-T016"
    assert evidence["amountUnit"] == "integer_cents"
    assert sum(item["amountCents"] for item in evidence["expenseEvents"]) == 18_800
    assert evidence["budget"] == {
        "plannedBudgetCents": 35_000,
        "actualSpentCents": 18_800,
        "remainingBudgetCents": 16_200,
        "expenseEventCount": 2,
    }
    assert evidence["idempotency"]["duplicateDebitCount"] == 0


def test_execution_page_calls_real_expense_api_and_restores_server_budget() -> None:
    page = Path("frontend/src/pages/WorkspacePage.tsx").read_text(encoding="utf-8")
    api = Path("frontend/src/api/tripApi.ts").read_text(encoding="utf-8")

    assert "'EXPENSE',\n        actualExpenseCents" in page
    assert "state.actualBudget?.actualSpentCents" in page
    assert "request<ExecutionEvent>" in api
    create_event_block = api.split("createExecutionEvent", maxsplit=1)[1].split(
        "updatePlan", maxsplit=1
    )[0]
    assert "mockResponse" not in create_event_block
    assert Path(
        "docs/testing/evidence/s1_t016_expense_refresh_desktop.png"
    ).stat().st_size > 10_000
