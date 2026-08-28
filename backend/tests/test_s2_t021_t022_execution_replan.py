from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.application.collaboration_ports import ReadinessPermit
from app.application.plan_service import PlanVersionService
from app.application.workflow_service import WorkflowService
from app.core.config import Settings
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.infrastructure.trusted_planning_store import TrustedPlanningStoreError
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.main import create_app
from app.domain.collaboration import TripFlowKind
from app.schemas.plan import PlanVersion
from app.schemas.replan_explanation import ReplanDifferenceExplanation
from app.schemas.trip import CreateSingleDayTrip
from app.services.replanning import (
    DeterministicRetainedSuffixPlanner,
    SuffixPlanningInput,
)
from backend.tests.plan_support import UnusedLocationService


ROOT = Path(__file__).parent
PLANNING_FIXTURE = ROOT / "fixtures" / "planning" / "golden_candidate_plan.json"
CASES_FIXTURE = (
    ROOT / "fixtures" / "execution_replanning" / "s2_t021_t022_cases.json"
)
DIFF_SNAPSHOT = ROOT / "snapshots" / "s2_t022_adjustment_diff.json"


def _planning_request() -> dict[str, Any]:
    return json.loads(PLANNING_FIXTURE.read_text(encoding="utf-8"))["request"]


def _cases() -> dict[str, dict[str, Any]]:
    return json.loads(CASES_FIXTURE.read_text(encoding="utf-8"))["cases"]


def _confirmed_trip(request: dict[str, Any]) -> CreateSingleDayTrip:
    payload = deepcopy(request["trip"])
    payload["status"] = "DRAFT"
    return CreateSingleDayTrip.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )


class RestAwareSuffixPlanner:
    def plan_suffix(
        self,
        planning_input: SuffixPlanningInput,
    ):
        assert planning_input.event_constraints is not None
        return tuple(
            fact.model_copy(
                update={
                    "elapsed_since_rest_minutes": min(
                        fact.elapsed_since_rest_minutes,
                        30,
                    )
                }
            )
            for fact in planning_input.task_facts
        )


class PassThroughSuffixPlanner:
    def plan_suffix(
        self,
        planning_input: SuffixPlanningInput,
    ):
        assert planning_input.event_constraints is not None
        return planning_input.task_facts


class ReturnShiftSuffixPlanner:
    def plan_suffix(
        self,
        planning_input: SuffixPlanningInput,
    ):
        assert planning_input.event_constraints is not None
        output = []
        for fact in planning_input.task_facts:
            if fact.category != "RETURN":
                output.append(fact)
                continue
            start = datetime.combine(date(2026, 9, 5), fact.start_at) + timedelta(
                minutes=30
            )
            end = datetime.combine(date(2026, 9, 5), fact.end_at) + timedelta(
                minutes=30
            )
            output.append(
                fact.model_copy(
                    update={"start_at": start.time(), "end_at": end.time()}
                )
            )
        return tuple(output)


class BrokenRouteSuffixPlanner:
    def plan_suffix(
        self,
        planning_input: SuffixPlanningInput,
    ):
        facts = list(planning_input.task_facts)
        first = facts[0]
        facts[0] = first.model_copy(
            update={
                "route": first.route.model_copy(
                    update={"destination": first.route.origin}
                )
            }
        )
        return tuple(facts)


class StaticExplainer:
    async def explain(self, _diff):
        return ReplanDifferenceExplanation(
            summary="已保留锁定前缀，并调整剩余行程。",
            model="fixture-qwen",
        )


class FailingExplainer:
    async def explain(self, _diff):
        raise RuntimeError("provider failure must stay private")


class MutableReadinessGuard:
    def __init__(self) -> None:
        self.readiness_digest = "a" * 64
        self.current_revision = 1

    @contextmanager
    def operation(self, access):
        yield ReadinessPermit(
            trip_id=access.trip_id,
            readiness_digest=self.readiness_digest,
            operation_id=access.operation_id,
            operation=access.operation,
            flow_kind=TripFlowKind.COLLABORATION_V2,
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
            current_revision=self.current_revision,
        )


_DEFAULT_TEST_SUFFIX = object()


def _app_and_db(
    tmp_path: Path,
    *,
    suffix_planner: object | None = _DEFAULT_TEST_SUFFIX,
    explanation_gateway: object | None = None,
    readiness_guard: object | None = None,
):
    database_path = tmp_path / "s2_t021_t022.sqlite3"
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    request = _planning_request()
    workflow.confirm_trip(_confirmed_trip(request))
    plans = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=workflow,
    )
    settings = Settings(
        plan_version_db_path=database_path,
        amap_cache_db_path=tmp_path / "amap.sqlite3",
        bailian_api_key=None,
    )
    app = create_app(
        settings=settings,
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plans,
        workflow_service=workflow,
        suffix_planner=(
            PassThroughSuffixPlanner()
            if suffix_planner is _DEFAULT_TEST_SUFFIX
            else suffix_planner
        ),
        replan_explanation_gateway=explanation_gateway,  # type: ignore[arg-type]
        collaboration_readiness_guard=readiness_guard,  # type: ignore[arg-type]
    )
    return app, database_path


def _diff_snapshot(diff: dict[str, Any]) -> dict[str, Any]:
    return {
        "tripId": diff["tripId"],
        "basePlanId": diff["basePlanId"],
        "candidatePlanId": diff["candidatePlanId"],
        "baseVersion": diff["baseVersion"],
        "candidateVersion": diff["candidateVersion"],
        "items": [
            item
            for item in diff["items"]
            if item["key"] == "task:task-return:time_range"
        ],
        "metricsDelta": diff["metricsDelta"],
    }


async def _generate_current(
    client: httpx.AsyncClient,
    *,
    start_execution: bool = True,
) -> dict[str, Any]:
    request = _planning_request()
    trip_id = request["trip"]["tripId"]
    profile = request["trip"]["participants"][0]["assistanceProfile"]
    saved = await client.put(f"/api/v1/trips/{trip_id}/constraints", json=profile)
    confirmed = await client.post(f"/api/v1/trips/{trip_id}/constraints/confirm")
    generated = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions/generate",
        json=request,
    )
    assert saved.status_code == confirmed.status_code == generated.status_code == 200
    plan = generated.json()["data"]
    accepted = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions/{plan['planId']}/confirm"
    )
    assert accepted.status_code == 200
    if start_execution:
        started = await client.post(f"/api/v1/trips/{trip_id}/execution/start")
        assert started.status_code == 200
    return plan


async def _event(
    client: httpx.AsyncClient,
    *,
    trip_id: str,
    plan_id: str,
    task_id: str,
    event_type: str,
    key: str,
    amount_cents: int | None = None,
) -> None:
    response = await client.post(
        f"/api/v1/trips/{trip_id}/events",
        json={
            "schemaVersion": "1.0",
            "taskId": task_id,
            "planVersionId": plan_id,
            "eventType": event_type,
            "amountCents": amount_cents,
            "idempotencyKey": key,
            "occurredAt": "2026-09-05T11:35:00+08:00",
        },
    )
    assert response.status_code == 200, response.text


async def _preview(
    client: httpx.AsyncClient,
    trip_id: str,
    command: dict[str, Any],
) -> httpx.Response:
    state_response = await client.get(f"/api/v1/trips/{trip_id}")
    state = state_response.json()["data"]
    source_task_id = command["adjustment"]["taskId"]
    if not any(
        event["eventType"] == "START" and event["taskId"] == source_task_id
        for event in state["events"]
    ):
        await _event(
            client,
            trip_id=trip_id,
            plan_id=state["currentPlan"]["planId"],
            task_id=source_task_id,
            event_type="START",
            key=f"s2-adjustment-start-{source_task_id}",
        )
    return await client.post(
        f"/api/v1/trips/{trip_id}/replans/from-adjustment",
        json=command,
    )


async def _persist_adjustment(
    client: httpx.AsyncClient,
    *,
    trip_id: str,
    plan_id: str,
    command: dict[str, Any],
    key: str,
) -> str:
    adjustment = command["adjustment"]
    response = await client.post(
        f"/api/v1/execution-adjustments/trips/{trip_id}/events",
        json={
            **adjustment,
            "planVersionId": plan_id,
            "idempotencyKey": key,
            "occurredAt": "2026-09-05T11:36:00+08:00",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["eventId"]


@pytest.mark.asyncio
async def test_late_preview_freezes_complete_current_and_locked_tasks(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_db(
        tmp_path,
        suffix_planner=ReturnShiftSuffixPlanner(),
        explanation_gateway=StaticExplainer(),
    )
    request = _planning_request()
    trip_id = request["trip"]["tripId"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_current(client)
        await _event(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            task_id="task-museum",
            event_type="EXPENSE",
            key="museum-expense",
            amount_cents=current["days"][0]["tasks"][0]["costCents"],
        )
        await _event(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            task_id="task-museum",
            event_type="COMPLETE",
            key="museum-complete",
        )
        await _event(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            task_id="task-lunch",
            event_type="START",
            key="lunch-start",
        )
        response = await _preview(client, trip_id, _cases()["lateFeasible"])
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        restored = (await client.get(f"/api/v1/trips/{trip_id}")).json()["data"]

    assert data["currentPlanId"] == current["planId"]
    assert data["currentPlanChanged"] is False
    assert data["candidatePlan"]["status"] == "PROPOSED"
    assert data["candidatePlan"]["reason"] == "DELAY"
    assert data["frozenTaskIds"] == ["task-museum", "task-lunch", "task-park"]
    assert data["candidatePlan"]["days"][0]["tasks"][:3] == (
        current["days"][0]["tasks"][:3]
    )
    assert restored["currentPlan"]["planId"] == current["planId"]
    assert data["explanation"] == {
        "status": "GENERATED",
        "summary": "已保留锁定前缀，并调整剩余行程。",
        "model": "fixture-qwen",
        "degradedReason": None,
    }
    domains = {
        item["domain"]
        for item in data["validationReport"]["checks"]
        if item["hardness"] == "HARD"
    }
    assert domains == {"BUDGET", "TIME", "ROUTE", "CARE"}
    transient = next(
        item
        for item in data["validationReport"]["checks"]
        if item["ruleId"] == "S2-T020.remaining.timeBudgetMinutes"
    )
    assert transient["status"] == "PASS"
    assert all(
        item["ruleId"] != "S2-T020.remaining.timeBudgetMinutes"
        for item in data["candidatePlan"]["constraintsSnapshot"]
    )
    assert _diff_snapshot(data["diff"]) == json.loads(
        DIFF_SNAPSHOT.read_text(encoding="utf-8")
    )
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version,status FROM plan_versions ORDER BY version"
        ).fetchall() == [(1, "CURRENT"), (2, "PROPOSED")]


@pytest.mark.asyncio
async def test_fatigue_replans_suffix_with_transient_walk_and_rest_checks(
    tmp_path: Path,
) -> None:
    planner = RestAwareSuffixPlanner()
    app, _ = _app_and_db(tmp_path, suffix_planner=planner)
    trip_id = _planning_request()["trip"]["tripId"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_current(client)
        response = await _preview(client, trip_id, _cases()["fatigueFeasible"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["candidatePlan"]["reason"] == "FATIGUE"
    assert data["frozenTaskIds"] == ["task-museum"]
    assert data["candidatePlan"]["days"][0]["tasks"][0] == (
        current["days"][0]["tasks"][0]
    )
    event_rules = [
        item
        for item in data["validationReport"]["checks"]
        if item["ruleId"].startswith("S2-T020.")
    ]
    assert len(event_rules) == 3
    assert {item["status"] for item in event_rules} == {"PASS"}
    assert data["explanation"]["status"] == "NOT_REQUESTED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_name", "rule_id"),
    [
        ("lateNoFeasible", "S2-T020.remaining.timeBudgetMinutes"),
        ("fatigueNoFeasible", "S2-T020.remaining.restIntervalMinutes"),
    ],
)
async def test_transient_hard_failure_returns_conflict_and_zero_writes(
    tmp_path: Path,
    case_name: str,
    rule_id: str,
) -> None:
    app, database_path = _app_and_db(tmp_path)
    trip_id = _planning_request()["trip"]["tripId"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_current(client)
        before = (await client.get(f"/api/v1/trips/{trip_id}")).json()["data"]
        response = await _preview(client, trip_id, _cases()[case_name])
        after = (await client.get(f"/api/v1/trips/{trip_id}")).json()["data"]

    assert response.status_code == 422
    assert response.json()["code"] == "REPLAN_NO_FEASIBLE_CANDIDATE"
    flattened = json.dumps(response.json()["errors"], ensure_ascii=False)
    assert rule_id in flattened
    assert "relaxations" in flattened
    assert before["currentPlan"]["planId"] == current["planId"]
    assert after["currentPlan"]["planId"] == current["planId"]
    assert after["proposedPlans"] == []
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE version=2"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM trusted_plan_issuances WHERE boundary_kind='V2'"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_actual_expense_budget_failure_is_revalidated_with_zero_v2_write(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_db(tmp_path)
    trip_id = _planning_request()["trip"]["tripId"]
    command = deepcopy(_cases()["lateFeasible"])
    command["lockedTaskIds"] = []
    command["adjustment"]["taskId"] = "task-museum"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_current(client)
        await _event(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            task_id="task-museum",
            event_type="EXPENSE",
            key="over-budget-expense",
            amount_cents=40_000,
        )
        response = await _preview(client, trip_id, command)
    assert response.status_code == 422
    assert "REPLAN.BUDGET.ACTUAL_PLUS_REMAINING" in json.dumps(
        response.json()["errors"]
    )
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE version=2"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_route_fact_break_is_rejected_before_any_v2_write(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_db(
        tmp_path,
        suffix_planner=BrokenRouteSuffixPlanner(),
    )
    trip_id = _planning_request()["trip"]["tripId"]
    command = deepcopy(_cases()["lateFeasible"])
    command["lockedTaskIds"] = []
    command["adjustment"]["taskId"] = "task-museum"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _generate_current(client)
        response = await _preview(client, trip_id, command)
    assert response.status_code == 422
    assert response.json()["code"] == "REPLAN_NO_FEASIBLE_CANDIDATE"
    assert "FACT_LINK_MISMATCH" in json.dumps(response.json()["errors"]).upper()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE version=2"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_explanation_failure_keeps_candidate_and_diff_complete(
    tmp_path: Path,
) -> None:
    app, _ = _app_and_db(tmp_path, explanation_gateway=FailingExplainer())
    trip_id = _planning_request()["trip"]["tripId"]
    command = deepcopy(_cases()["lateFeasible"])
    command["lockedTaskIds"] = []
    command["adjustment"]["taskId"] = "task-museum"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _generate_current(client)
        response = await _preview(client, trip_id, command)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["candidatePlan"]["version"] == 2
    assert data["diff"]["candidatePlanId"] == data["candidatePlan"]["planId"]
    assert data["explanation"] == {
        "status": "UNAVAILABLE",
        "summary": None,
        "model": None,
        "degradedReason": "EXPLAINER_FAILED",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["ACCEPT", "REJECT"])
async def test_decision_reuses_atomic_plan_version_state_machine(
    tmp_path: Path,
    decision: str,
) -> None:
    app, database_path = _app_and_db(tmp_path)
    trip_id = _planning_request()["trip"]["tripId"]
    command = deepcopy(_cases()["lateFeasible"])
    command["lockedTaskIds"] = []
    command["adjustment"]["taskId"] = "task-museum"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_current(client)
        preview = await _preview(client, trip_id, command)
        assert preview.status_code == 200, preview.text
        candidate = preview.json()["data"]["candidatePlan"]
        result = await client.post(
            f"/api/v1/trips/{trip_id}/replans/{candidate['planId']}/decision",
            json={"schemaVersion": "1.0", "decision": decision},
        )
        state = (await client.get(f"/api/v1/trips/{trip_id}")).json()["data"]
    assert result.status_code == 200, result.text
    payload = result.json()["data"]["result"]
    assert payload["decision"] == ("ACCEPTED" if decision == "ACCEPT" else "REJECTED")
    expected_current = candidate["planId"] if decision == "ACCEPT" else current["planId"]
    assert state["currentPlan"]["planId"] == expected_current
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE status='CURRENT'"
        ).fetchone()[0] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["accept", "reject"])
async def test_adjustment_v2_cannot_bypass_dedicated_decision_endpoint(
    tmp_path: Path,
    action: str,
) -> None:
    app, _ = _app_and_db(tmp_path)
    trip_id = _planning_request()["trip"]["tripId"]
    command = deepcopy(_cases()["lateFeasible"])
    command["lockedTaskIds"] = []
    command["adjustment"]["taskId"] = "task-museum"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_current(client)
        preview = await _preview(client, trip_id, command)
        assert preview.status_code == 200, preview.text
        candidate = preview.json()["data"]["candidatePlan"]
        response = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{candidate['planId']}/{action}"
        )
        state = (await client.get(f"/api/v1/trips/{trip_id}")).json()["data"]

    assert response.status_code == 409
    assert response.json()["code"] == "S2_T022_DEDICATED_DECISION_REQUIRED"
    assert state["currentPlan"]["planId"] == current["planId"]
    assert [item["planId"] for item in state["proposedPlans"]] == [
        candidate["planId"]
    ]


@pytest.mark.asyncio
async def test_readiness_change_after_preview_rejects_decision_without_state_change(
    tmp_path: Path,
) -> None:
    readiness = MutableReadinessGuard()
    app, database_path = _app_and_db(tmp_path, readiness_guard=readiness)
    trip_id = _planning_request()["trip"]["tripId"]
    command = deepcopy(_cases()["lateFeasible"])
    command["lockedTaskIds"] = []
    command["adjustment"]["taskId"] = "task-museum"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_current(client)
        preview = await _preview(client, trip_id, command)
        assert preview.status_code == 200, preview.text
        candidate = preview.json()["data"]["candidatePlan"]
        readiness.readiness_digest = "b" * 64
        readiness.current_revision = 2
        decision = await client.post(
            f"/api/v1/trips/{trip_id}/replans/{candidate['planId']}/decision",
            json={"schemaVersion": "1.0", "decision": "ACCEPT"},
        )
        state = (await client.get(f"/api/v1/trips/{trip_id}")).json()["data"]

    assert decision.status_code == 409
    assert decision.json()["code"] == "S2_T022_READINESS_CHANGED"
    assert state["currentPlan"]["planId"] == current["planId"]
    assert state["proposedPlans"][0]["planId"] == candidate["planId"]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT status FROM plan_versions WHERE plan_id=?",
            (candidate["planId"],),
        ).fetchone()[0] == "PROPOSED"


@pytest.mark.asyncio
async def test_strict_command_rejects_client_candidates_before_v2_write(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_db(tmp_path)
    trip_id = _planning_request()["trip"]["tripId"]
    command = deepcopy(_cases()["lateFeasible"])
    command["candidates"] = [{"forged": True}]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _generate_current(client)
        response = await _preview(client, trip_id, command)
    assert response.status_code == 422
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE version=2"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper_mode", ["MISSING", "INVALID_JSON"])
async def test_missing_or_tampered_server_facts_fail_closed_without_v2_write(
    tmp_path: Path,
    tamper_mode: str,
) -> None:
    app, database_path = _app_and_db(tmp_path)
    trip_id = _planning_request()["trip"]["tripId"]
    command = deepcopy(_cases()["lateFeasible"])
    command["lockedTaskIds"] = []
    command["adjustment"]["taskId"] = "task-museum"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_current(client)
        with sqlite3.connect(database_path) as connection:
            if tamper_mode == "MISSING":
                connection.execute(
                    "DELETE FROM trusted_plan_issuances WHERE plan_id = ?",
                    (current["planId"],),
                )
            else:
                connection.execute(
                    """
                    UPDATE trusted_plan_issuances
                    SET candidate_facts_json = '{"forged":true}'
                    WHERE plan_id = ?
                    """,
                    (current["planId"],),
                )
            connection.commit()
        response = await _preview(client, trip_id, command)

    assert response.status_code == 409
    assert response.json()["code"] in {
        "PLANNING_PLAN_NOT_ISSUED",
        "PLANNING_FACTS_INVALID",
    }
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE version=2"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM trusted_plan_issuances WHERE boundary_kind='V2'"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_replanning_before_execution_has_no_plan_or_trust_side_effect(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_db(tmp_path)
    trip_id = _planning_request()["trip"]["tripId"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _generate_current(client, start_execution=False)
        response = await client.post(
            f"/api/v1/trips/{trip_id}/replans/from-adjustment",
            json=_cases()["fatigueFeasible"],
        )
    assert response.status_code == 409
    assert response.json()["code"] == "REPLAN_EXECUTION_REQUIRED"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE version=2"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM trusted_plan_issuances WHERE boundary_kind='V2'"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_adjustment_task_requires_an_official_start_event(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_db(tmp_path)
    trip_id = _planning_request()["trip"]["tripId"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _generate_current(client)
        response = await client.post(
            f"/api/v1/trips/{trip_id}/replans/from-adjustment",
            json=_cases()["fatigueFeasible"],
        )
    assert response.status_code == 409
    assert response.json()["code"] == "S2_T021_EVENT_TASK_NOT_STARTED"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE version=2"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_production_default_event_planner_reuses_trusted_provider_facts(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_db(tmp_path, suffix_planner=None)
    trip_id = _planning_request()["trip"]["tripId"]
    command = deepcopy(_cases()["fatigueFeasible"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_current(client)
        adjustment_event_id = await _persist_adjustment(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            command=command,
            key="default-planner-fatigue-001",
        )
        command["adjustmentEventId"] = adjustment_event_id
        response = await _preview(client, trip_id, command)
    assert response.status_code == 200, response.text
    candidate = response.json()["data"]["candidatePlan"]
    assert candidate["status"] == "PROPOSED"
    assert candidate["reason"] == "FATIGUE"
    with sqlite3.connect(database_path) as connection:
        trusted = {
            plan_id: json.loads(payload)
            for plan_id, payload in connection.execute(
                "SELECT plan_id,candidate_facts_json FROM trusted_plan_issuances "
                "WHERE plan_id IN (?,?)",
                (current["planId"], candidate["planId"]),
            ).fetchall()
        }
        evidence = json.loads(
            connection.execute(
                "SELECT validation_json FROM trusted_plan_issuances "
                "WHERE plan_id=? AND boundary_kind='V2'",
                (candidate["planId"],),
            ).fetchone()[0]
        )
    before_facts = trusted[current["planId"]]
    after_facts = trusted[candidate["planId"]]
    assert after_facts["startLocation"] == before_facts["startLocation"]
    assert after_facts["endLocation"] == before_facts["endLocation"]
    assert [item["place"] for item in after_facts["taskFacts"]] == [
        item["place"] for item in before_facts["taskFacts"]
    ]
    assert [item["route"] for item in after_facts["taskFacts"]] == [
        item["route"] for item in before_facts["taskFacts"]
    ]
    assert evidence["collaborationReadiness"] == {
        "readinessDigest": "legacy",
        "currentRevision": None,
        "flowKind": "LEGACY_SINGLE",
    }
    assert evidence["confirmedAdjustmentEventId"] == adjustment_event_id


@pytest.mark.asyncio
async def test_explicit_retained_suffix_fallback_fails_closed_without_v2_write(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_db(
        tmp_path,
        suffix_planner=DeterministicRetainedSuffixPlanner(),
    )
    trip_id = _planning_request()["trip"]["tripId"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _generate_current(client)
        response = await _preview(client, trip_id, _cases()["fatigueFeasible"])
    assert response.status_code == 503
    assert response.json()["code"] == "S2_T021_CANDIDATE_SOURCE_UNAVAILABLE"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE version=2"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM trusted_plan_issuances WHERE boundary_kind='V2'"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_persisted_adjustment_event_rejects_tampered_inline_payload(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_db(tmp_path, suffix_planner=None)
    trip_id = _planning_request()["trip"]["tripId"]
    command = deepcopy(_cases()["fatigueFeasible"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_current(client)
        command["adjustmentEventId"] = await _persist_adjustment(
            client,
            trip_id=trip_id,
            plan_id=current["planId"],
            command=command,
            key="tamper-fatigue-001",
        )
        command["adjustment"]["fatigueLevel"] = "SEVERE"
        response = await _preview(client, trip_id, command)

    assert response.status_code == 409
    assert response.json()["code"] == "S2_T021_ADJUSTMENT_EVENT_PAYLOAD_MISMATCH"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE version=2"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_event_digest_changes_v2_identity_and_issued_evidence_is_immutable(
    tmp_path: Path,
) -> None:
    async def generate(base: Path, late_minutes: int):
        base.mkdir()
        app, database_path = _app_and_db(
            base,
            suffix_planner=ReturnShiftSuffixPlanner(),
        )
        command = deepcopy(_cases()["lateFeasible"])
        command["adjustment"]["lateMinutes"] = late_minutes
        trip_id = _planning_request()["trip"]["tripId"]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await _generate_current(client)
            response = await _preview(client, trip_id, command)
        assert response.status_code == 200, response.text
        return app, database_path, response.json()["data"]

    first_app, first_database, first = await generate(tmp_path / "late-15", 15)
    _, _, second = await generate(tmp_path / "late-30", 30)
    assert first["candidatePlan"]["planId"] != second["candidatePlan"]["planId"]
    assert (
        first["eventConstraints"]["inputDigest"]
        != second["eventConstraints"]["inputDigest"]
    )

    repository = first_app.state.planning_boundary_service.trust_repository
    plan = PlanVersion.model_validate_json(
        json.dumps(first["candidatePlan"], ensure_ascii=False),
        strict=True,
    )
    with pytest.raises(TrustedPlanningStoreError) as conflict:
        repository.mark_issued(plan, validation={"forged": True})
    assert conflict.value.code == "PLANNING_VALIDATION_EVIDENCE_CONFLICT"
    with sqlite3.connect(first_database) as connection:
        evidence = json.loads(
            connection.execute(
                "SELECT validation_json FROM trusted_plan_issuances WHERE plan_id=?",
                (first["candidatePlan"]["planId"],),
            ).fetchone()[0]
        )
    assert evidence["transientEventConstraints"]["inputDigest"] == (
        first["eventConstraints"]["inputDigest"]
    )


@pytest.mark.asyncio
async def test_t022_decision_rejects_v2_not_issued_by_t021(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_db(tmp_path)
    request = _planning_request()
    trip_id = request["trip"]["tripId"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_current(client)
        generated = await client.post(
            f"/api/v1/trips/{trip_id}/replans",
            json={
                "schemaVersion": "1.0",
                "reason": "USER_FEEDBACK",
                "lockedTaskIds": [],
                "candidates": [{"request": request, "satisfactionLoss": 0}],
            },
        )
        assert generated.status_code == 200, generated.text
        candidate = generated.json()["data"]["plan"]
        decision = await client.post(
            f"/api/v1/trips/{trip_id}/replans/{candidate['planId']}/decision",
            json={"schemaVersion": "1.0", "decision": "ACCEPT"},
        )
        state = (await client.get(f"/api/v1/trips/{trip_id}")).json()["data"]
    assert decision.status_code == 409
    assert decision.json()["code"] == "S2_T022_ADJUSTMENT_V2_REQUIRED"
    assert state["currentPlan"]["planId"] == current["planId"]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT status FROM plan_versions WHERE plan_id=?",
            (candidate["planId"],),
        ).fetchone()[0] == "PROPOSED"
