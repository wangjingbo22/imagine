from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.application.plan_service import PlanVersionService
from app.application.workflow_service import WorkflowService
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.main import create_app
from app.schemas.plan import PlanVersion, TripPlanState
from app.schemas.trip import CreateSingleDayTrip
from app.schemas.workflow import TripExecutionSummary
from app.services.summary_trace import SummaryTraceError, trace_summary_numbers
from tests.test_plan_versions import UnusedLocationService


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "summary_paths"
PLANNING_FIXTURE = (
    Path(__file__).parent / "fixtures" / "planning" / "golden_candidate_plan.json"
)
PATH_FIXTURES = ("no_v2", "accepted_v2", "rejected_v2")


def _load_path_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _planning_request(
    task_ids: tuple[str, str, str, str],
    task_costs: tuple[int, int, int, int],
) -> dict[str, Any]:
    request = json.loads(PLANNING_FIXTURE.read_text(encoding="utf-8"))["request"]
    for task, task_id, cost_cents in zip(
        request["taskFacts"],
        task_ids,
        task_costs,
        strict=True,
    ):
        task["taskId"] = task_id
        task["place"]["priceReference"]["amountCents"] = cost_cents
        task["route"]["priceReference"]["amountCents"] = 0
    return request


def _contains_photo_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            "photo" in str(key).casefold() or _contains_photo_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_photo_key(item) for item in value)
    return False


def _services(tmp_path: Path) -> tuple[PlanVersionService, WorkflowService]:
    database_path = tmp_path / "s1_t022.sqlite3"
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    plan = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=workflow,
    )
    return plan, workflow


async def _post_events(
    client: httpx.AsyncClient,
    trip_id: str,
    events: list[dict[str, Any]],
    plan_ids: dict[str, str],
) -> None:
    for configured in events:
        payload = {
            "schemaVersion": configured["schemaVersion"],
            "taskId": configured["taskId"],
            "planVersionId": plan_ids[configured["plan"]],
            "eventType": configured["eventType"],
            "idempotencyKey": configured["idempotencyKey"],
            "occurredAt": configured["occurredAt"],
        }
        if "amountCents" in configured:
            payload["amountCents"] = configured["amountCents"]
        response = await client.post(f"/api/v1/trips/{trip_id}/events", json=payload)
        assert response.status_code == 200, response.text


def _numeric_values(summary: TripExecutionSummary) -> dict[str, int]:
    values = {
        "plannedCostCents": summary.planned_cost_cents,
        "actualCostCents": summary.actual_cost_cents,
        "differenceCents": summary.difference_cents,
        "totalTasks": summary.total_tasks,
        "currentPlanVersion": summary.current_plan_version,
    }
    values.update(
        {
            f"planHistory[{index}].version": item.version
            for index, item in enumerate(summary.plan_history)
        }
    )
    values.update(
        {
            f"events[{index}].amountCents": event.amount_cents
            for index, event in enumerate(summary.events)
            if event.amount_cents is not None
        }
    )
    return values


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture_name", PATH_FIXTURES)
async def test_s1_t022_real_summary_path_is_complete_and_traceable(
    fixture_name: str,
    tmp_path: Path,
) -> None:
    """No-V2, accepted-V2 and rejected-V2 must all retain numeric lineage."""

    scenario = _load_path_fixture(fixture_name)
    v1_request = _planning_request(
        ("task-1", "task-2", "task-3", "task-4"),
        (600, 13_800, 400, 15_000),
    )
    v2_request = _planning_request(
        ("task-1", "task-2", "task-4", "task-5"),
        (600, 11_800, 14_000, 1_000),
    )
    trip_id = str(v1_request["trip"]["tripId"])
    plan_ids: dict[str, str] = {}
    plan_payloads: dict[str, dict[str, Any]] = {}
    plan_service, workflow_service = _services(tmp_path)
    confirmed_payload = deepcopy(v1_request["trip"])
    confirmed_payload["status"] = "DRAFT"
    workflow_service.confirm_trip(
        CreateSingleDayTrip.model_validate_json(
            json.dumps(confirmed_payload, ensure_ascii=False),
            strict=True,
        )
    )
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plan_service,
        workflow_service=workflow_service,
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        saved_constraints = await client.put(
            f"/api/v1/trips/{trip_id}/constraints",
            json=v1_request["trip"]["participants"][0]["assistanceProfile"],
        )
        confirmed_constraints = await client.post(
            f"/api/v1/trips/{trip_id}/constraints/confirm"
        )
        assert saved_constraints.status_code == 200, saved_constraints.text
        assert confirmed_constraints.status_code == 200, confirmed_constraints.text
        generated_v1 = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=v1_request,
        )
        assert generated_v1.status_code == 200, generated_v1.text
        plan_payloads["V1"] = generated_v1.json()["data"]
        plan_ids["V1"] = plan_payloads["V1"]["planId"]
        confirmed_v1 = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{plan_ids['V1']}/confirm"
        )
        started = await client.post(f"/api/v1/trips/{trip_id}/execution/start")
        assert confirmed_v1.status_code == 200, confirmed_v1.text
        assert started.status_code == 200

        await _post_events(
            client,
            trip_id,
            scenario["beforeDecisionEvents"],
            plan_ids,
        )

        if scenario["decision"] != "NONE":
            generated_v2 = await client.post(
                f"/api/v1/trips/{trip_id}/replans",
                json={
                    "schemaVersion": "1.0",
                    "reason": "USER_FEEDBACK",
                    "lockedTaskIds": [],
                    "candidates": [
                        {"request": v2_request, "satisfactionLoss": 0},
                    ],
                },
            )
            assert generated_v2.status_code == 200, generated_v2.text
            plan_payloads["V2"] = generated_v2.json()["data"]["plan"]
            plan_ids["V2"] = plan_payloads["V2"]["planId"]
            action = "accept" if scenario["decision"] == "ACCEPT" else "reject"
            decision = await client.post(
                f"/api/v1/trips/{trip_id}/plan-versions/{plan_ids['V2']}/{action}"
            )
            assert decision.status_code == 200, decision.text

        await _post_events(
            client,
            trip_id,
            scenario["afterDecisionEvents"],
            plan_ids,
        )
        summary_response = await client.get(f"/api/v1/trips/{trip_id}/summary")
        state_response = await client.get(f"/api/v1/trips/{trip_id}")

    assert summary_response.status_code == state_response.status_code == 200
    summary_payload = summary_response.json()["data"]
    state_payload = state_response.json()["data"]
    summary = TripExecutionSummary.model_validate_json(
        json.dumps(summary_payload, ensure_ascii=False),
        strict=True,
    )
    state = TripPlanState.model_validate_json(
        json.dumps(state_payload, ensure_ascii=False),
        strict=True,
    )
    assert state.current_plan is not None

    expected = scenario["expected"]
    assert summary.trip_status.value == expected["tripStatus"]
    assert summary.planned_cost_cents == expected["plannedCostCents"]
    assert summary.actual_cost_cents == expected["actualCostCents"]
    assert summary.difference_cents == expected["differenceCents"]
    assert summary.total_tasks == expected["totalTasks"]
    assert summary.current_plan_version == expected["currentPlanVersion"]
    assert summary.completed_task_ids == expected["completedTaskIds"]
    assert summary.skipped_task_ids == expected["skippedTaskIds"]
    assert len(summary.events) == expected["eventCount"]
    assert str(state.current_plan.plan_id) == plan_ids[expected["currentPlan"]]

    configured_events = [
        *scenario["beforeDecisionEvents"],
        *scenario["afterDecisionEvents"],
    ]
    configured_times = [
        datetime.fromisoformat(item["occurredAt"]).astimezone(UTC)
        for item in configured_events
    ]
    assert all(item["schemaVersion"] == "1.0" for item in configured_events)
    assert all(item["occurredAt"].endswith("+08:00") for item in configured_events)
    assert configured_times == sorted(configured_times)
    assert [event.idempotency_key for event in summary.events] == [
        item["idempotencyKey"] for item in configured_events
    ]
    assert [event.occurred_at for event in summary.events] == configured_times

    labels_by_id = {UUID(value): label for label, value in plan_ids.items()}
    actual_statuses = {
        labels_by_id[item.plan_id]: item.status.value for item in summary.plan_history
    }
    assert actual_statuses == expected["planStatuses"]

    plan_versions = tuple(
        PlanVersion.model_validate_json(
            json.dumps(plan_payloads[label], ensure_ascii=False),
            strict=True,
        )
        for label in expected["planStatuses"]
    )
    traces = trace_summary_numbers(summary, state.current_plan, plan_versions)
    traces_by_path = {trace.path: trace for trace in traces}
    numeric_values = _numeric_values(summary)
    assert {path: trace.value for path, trace in traces_by_path.items()} == (
        numeric_values
    )

    task_ids_by_plan = {
        plan.plan_id: {task.task_id for task in plan.days[0].tasks}
        for plan in plan_versions
    }
    known_event_ids = {event.event_id for event in summary.events}
    known_plan_ids = {item.plan_id for item in summary.plan_history}
    for trace in traces:
        assert set(trace.task_ids) <= set().union(*task_ids_by_plan.values())
        assert set(trace.event_ids) <= known_event_ids
        assert set(trace.plan_version_ids) <= known_plan_ids
        assert trace.plan_version_ids
    for event in summary.events:
        assert event.task_id in task_ids_by_plan[event.plan_version_id]

    expense_events = [
        event for event in summary.events if event.amount_cents is not None
    ]
    actual_trace = traces_by_path["actualCostCents"]
    assert set(actual_trace.event_ids) == {event.event_id for event in expense_events}
    assert set(actual_trace.task_ids) == {event.task_id for event in expense_events}
    expected_expense_plans = {event.plan_version_id for event in expense_events}
    expected_expense_plans.add(state.current_plan.plan_id)
    assert set(actual_trace.plan_version_ids) == expected_expense_plans

    for index, event in enumerate(summary.events):
        if event.amount_cents is None:
            continue
        event_trace = traces_by_path[f"events[{index}].amountCents"]
        assert event_trace.task_ids == (event.task_id,)
        assert event_trace.event_ids == (event.event_id,)
        assert event_trace.plan_version_ids == (event.plan_version_id,)

    tampered = summary.model_copy(
        update={"actual_cost_cents": summary.actual_cost_cents + 1}
    )
    with pytest.raises(SummaryTraceError, match="actualCostCents"):
        trace_summary_numbers(tampered, state.current_plan, plan_versions)

    forged_events = list(summary.events)
    forged_events[0] = forged_events[0].model_copy(
        update={"task_id": "forged-task-id"}
    )
    forged_task_summary = summary.model_copy(update={"events": forged_events})
    with pytest.raises(SummaryTraceError, match="taskId does not belong"):
        trace_summary_numbers(
            forged_task_summary,
            state.current_plan,
            plan_versions,
        )

    if fixture_name == "accepted_v2":
        wrong_version_events = list(summary.events)
        unique_v2_index = next(
            index
            for index, event in enumerate(wrong_version_events)
            if event.task_id == "task-5"
        )
        wrong_version_events[unique_v2_index] = wrong_version_events[
            unique_v2_index
        ].model_copy(update={"plan_version_id": UUID(plan_ids["V1"])})
        wrong_version_summary = summary.model_copy(
            update={"events": wrong_version_events}
        )
        with pytest.raises(SummaryTraceError, match="taskId does not belong"):
            trace_summary_numbers(
                wrong_version_summary,
                state.current_plan,
                plan_versions,
            )

    assert not _contains_photo_key(scenario)
    assert not _contains_photo_key(summary_payload)
    assert not _contains_photo_key(state_payload)
