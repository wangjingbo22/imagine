import copy
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.application.plan_service import PlanVersionService
from app.application.workflow_service import WorkflowService
from app.infrastructure.plan_store import PlanStoreError, SqlitePlanVersionRepository
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.main import create_app
from app.schemas.plan import (
    PlanDiffChangeType,
    PlanV2Decision,
    PlanVersionStatus,
)
from app.schemas.trip import CreateSingleDayTrip, TripStatus
from tests.test_plan_versions import (
    UnusedLocationService,
    parse_proposal,
    proposal_payload,
)


PLANNING_FIXTURE = (
    Path(__file__).parents[1]
    / "backend"
    / "tests"
    / "fixtures"
    / "planning"
    / "golden_candidate_plan.json"
)


def planning_request() -> dict[str, object]:
    return json.loads(PLANNING_FIXTURE.read_text(encoding="utf-8"))["request"]


def trusted_http_app(tmp_path: Path):
    database_path = tmp_path / "trusted_http.sqlite3"
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    confirmed_payload = copy.deepcopy(planning_request()["trip"])
    confirmed_payload["status"] = "DRAFT"  # type: ignore[index]
    workflow.confirm_trip(
        CreateSingleDayTrip.model_validate_json(
            json.dumps(confirmed_payload, ensure_ascii=False),
            strict=True,
        )
    )
    plans = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=workflow,
    )
    return create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plans,
        workflow_service=workflow,
    )


async def start_issued_v1(
    client: httpx.AsyncClient,
    request: dict[str, object],
) -> dict[str, object]:
    trip_id = request["trip"]["tripId"]  # type: ignore[index]
    profile = request["trip"]["participants"][0]["assistanceProfile"]  # type: ignore[index]
    saved = await client.put(
        f"/api/v1/trips/{trip_id}/constraints",
        json=profile,
    )
    confirmed_constraints = await client.post(
        f"/api/v1/trips/{trip_id}/constraints/confirm"
    )
    assert saved.status_code == 200, saved.text
    assert confirmed_constraints.status_code == 200, confirmed_constraints.text
    generated = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions/generate",
        json=request,
    )
    assert generated.status_code == 200, generated.text
    plan = generated.json()["data"]
    confirmed = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions/{plan['planId']}/confirm"
    )
    started = await client.post(f"/api/v1/trips/{trip_id}/execution/start")
    assert confirmed.status_code == started.status_code == 200
    return plan


def v2_payload() -> dict[str, object]:
    payload = copy.deepcopy(proposal_payload())
    payload["planId"] = "20000000-0000-4000-8000-000000000002"
    payload["version"] = 2
    payload["parentId"] = "20000000-0000-4000-8000-000000000001"
    payload["reason"] = "EXPENSE_CHANGE"
    payload["metrics"] = {
        "totalCostCents": 27_400,
        "bufferCents": 7_600,
        "totalWalkMeters": 1_980,
        "transferCount": 1,
        "validationStatus": "PASS",
    }
    tasks = payload["days"][0]["tasks"]  # type: ignore[index]
    payload["days"][0]["tasks"] = [  # type: ignore[index]
        tasks[0],
        {
            **tasks[1],
            "timeRange": "12:20 — 13:30",
            "costCents": 11_800,
        },
        {
            **tasks[3],
            "order": 3,
            "costCents": 14_000,
            "walkMeters": 800,
            "transport": "地铁直达 · 22 分钟",
        },
        {
            "taskId": "task-5",
            "order": 4,
            "title": "北京城市艺术馆",
            "category": "室内文化",
            "timeRange": "16:10 — 17:20",
            "durationMinutes": 70,
            "transport": "步行 300 米 · 5 分钟",
            "costCents": 1_000,
            "walkMeters": 300,
            "note": "根据实际消费减少费用和户外步行",
        },
    ]
    payload["constraintsSnapshot"].append(  # type: ignore[union-attr]
        {
            "ruleId": "rest-after-expense",
            "scope": "trip.days[0]",
            "hardness": "SOFT",
            "status": "WARNING",
            "description": "调整后增加一次室内休息",
            "details": {"reason": "EXPENSE_CHANGE"},
        }
    )
    payload["sourcesSnapshot"].append(  # type: ignore[union-attr]
        {
            "provider": "FRONTEND_MOCK",
            "sourceStatus": "ESTIMATED",
            "fetchedAt": "2026-08-24T11:00:00+08:00",
            "isStale": False,
            "referenceId": "workspace-recommendation-v2",
        }
    )
    return payload


def setup_executing(repository: SqlitePlanVersionRepository):
    v1 = parse_proposal()
    repository.register_proposed(v1)
    repository.confirm(v1.trip_snapshot.trip_id, v1.plan_id)
    repository.start_execution(v1.trip_snapshot.trip_id)
    return v1


def test_v2_registration_and_diff_cover_all_required_change_types(tmp_path: Path) -> None:
    repository = SqlitePlanVersionRepository(tmp_path / "plan_versions.sqlite3")
    v1 = setup_executing(repository)
    v2 = parse_proposal(v2_payload())

    registered = repository.register_proposed(v2)
    assert registered.status is PlanVersionStatus.PROPOSED
    restored = repository.get_trip_state(v1.trip_snapshot.trip_id)
    assert restored.trip_status is TripStatus.REPLAN_REVIEW
    assert restored.current_plan is not None
    assert restored.current_plan.plan_id == v1.plan_id
    assert [plan.plan_id for plan in restored.proposed_plans] == [v2.plan_id]

    diff = repository.get_diff(v1.trip_snapshot.trip_id, v2.plan_id)
    changes = {item.key: item.change_type for item in diff.items}
    assert changes["task:task-1:title"] is PlanDiffChangeType.RETAINED
    assert changes["task:task-2:cost_cents"] is PlanDiffChangeType.CHANGED
    assert changes["task:task-3:title"] is PlanDiffChangeType.REMOVED
    assert changes["task:task-5:title"] is PlanDiffChangeType.ADDED
    assert changes["constraint:rest-after-expense"] is PlanDiffChangeType.ADDED
    assert diff.metrics_delta.total_cost_cents == -2_400
    assert diff.metrics_delta.total_walk_meters == -670
    assert diff.metrics_delta.transfer_count == -1


def test_accept_v2_atomically_switches_unique_current_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "plan_versions.sqlite3"
    repository = SqlitePlanVersionRepository(database_path)
    v1 = setup_executing(repository)
    v2 = parse_proposal(v2_payload())
    repository.register_proposed(v2)

    first = repository.accept_v2(v1.trip_snapshot.trip_id, v2.plan_id)
    second = repository.accept_v2(v1.trip_snapshot.trip_id, v2.plan_id)
    assert first.decision is second.decision is PlanV2Decision.ACCEPTED
    assert first.current_plan_id == v2.plan_id
    restored = repository.get_trip_state(v1.trip_snapshot.trip_id)
    assert restored.trip_status is TripStatus.EXECUTING
    assert restored.current_plan is not None
    assert restored.current_plan.plan_id == v2.plan_id
    assert restored.current_plan.version == 2

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT plan_id, status FROM plan_versions ORDER BY version"
        ).fetchall()
        current_count = connection.execute(
            "SELECT COUNT(*) FROM plan_versions WHERE status = 'CURRENT'"
        ).fetchone()[0]
    assert rows == [
        (str(v1.plan_id), "SUPERSEDED"),
        (str(v2.plan_id), "CURRENT"),
    ]
    assert current_count == 1

    with pytest.raises(PlanStoreError) as opposite:
        repository.reject_v2(v1.trip_snapshot.trip_id, v2.plan_id)
    assert opposite.value.code == "PLAN_STATE_TRANSITION_INVALID"


def test_reject_v2_preserves_current_and_execution_state(tmp_path: Path) -> None:
    database_path = tmp_path / "plan_versions.sqlite3"
    repository = SqlitePlanVersionRepository(database_path)
    v1 = setup_executing(repository)
    v2 = parse_proposal(v2_payload())
    repository.register_proposed(v2)

    first = repository.reject_v2(v1.trip_snapshot.trip_id, v2.plan_id)
    second = repository.reject_v2(v1.trip_snapshot.trip_id, v2.plan_id)
    assert first.decision is second.decision is PlanV2Decision.REJECTED
    assert first.current_plan_id == v1.plan_id
    restored = repository.get_trip_state(v1.trip_snapshot.trip_id)
    assert restored.trip_status is TripStatus.EXECUTING
    assert restored.current_plan is not None
    assert restored.current_plan.plan_id == v1.plan_id

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT plan_id, status FROM plan_versions ORDER BY version"
        ).fetchall()
    assert rows == [
        (str(v1.plan_id), "CURRENT"),
        (str(v2.plan_id), "REJECTED"),
    ]

    with pytest.raises(PlanStoreError) as opposite:
        repository.accept_v2(v1.trip_snapshot.trip_id, v2.plan_id)
    assert opposite.value.code == "PLAN_STATE_TRANSITION_INVALID"


def test_v2_requires_current_parent_and_matching_snapshot(tmp_path: Path) -> None:
    repository = SqlitePlanVersionRepository(tmp_path / "plan_versions.sqlite3")
    v1 = setup_executing(repository)

    bad_parent = v2_payload()
    bad_parent["parentId"] = "30000000-0000-4000-8000-000000000001"
    with pytest.raises(PlanStoreError) as missing_parent:
        repository.register_proposed(parse_proposal(bad_parent))
    assert missing_parent.value.code == "PLAN_PARENT_NOT_FOUND"

    changed_snapshot = v2_payload()
    changed_snapshot["tripSnapshot"]["cityContext"]["cityCode"] = "310000"  # type: ignore[index]
    with pytest.raises(PlanStoreError) as immutable:
        repository.register_proposed(parse_proposal(changed_snapshot))
    assert immutable.value.code == "TRIP_SNAPSHOT_IMMUTABLE"
    restored = repository.get_trip_state(v1.trip_snapshot.trip_id)
    assert restored.trip_status is TripStatus.EXECUTING


@pytest.mark.asyncio
async def test_v2_http_diff_accept_and_opposite_decision_guard(tmp_path: Path) -> None:
    app = trusted_http_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    v1_request = planning_request()
    v2_request = copy.deepcopy(v1_request)
    v2_request["taskFacts"][1]["place"]["priceReference"][  # type: ignore[index]
        "amountCents"
    ] -= 2_400
    trip_id = v1_request["trip"]["tripId"]  # type: ignore[index]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        v1 = await start_issued_v1(client, v1_request)
        registered = await client.post(
            f"/api/v1/trips/{trip_id}/replans",
            json={
                "schemaVersion": "1.0",
                "reason": "EXPENSE_CHANGE",
                "lockedTaskIds": [],
                "candidates": [
                    {"request": v2_request, "satisfactionLoss": 0},
                ],
            },
        )
        assert registered.status_code == 200, registered.text
        plan_id = registered.json()["data"]["plan"]["planId"]
        diff = await client.get(
            f"/api/v1/trips/{trip_id}/plan-versions/{plan_id}/diff"
        )
        accepted = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{plan_id}/accept"
        )
        rejected_after_accept = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{plan_id}/reject"
        )

    assert registered.status_code == 200
    assert registered.json()["data"]["plan"]["version"] == 2
    assert registered.json()["data"]["plan"]["parentId"] == v1["planId"]
    assert diff.status_code == 200
    assert diff.json()["data"]["metricsDelta"]["totalCostCents"] == -2_400
    assert accepted.status_code == 200
    assert accepted.json()["data"]["decision"] == "ACCEPTED"
    assert rejected_after_accept.status_code == 409
    assert rejected_after_accept.json()["code"] == "PLAN_STATE_TRANSITION_INVALID"


@pytest.mark.asyncio
async def test_v2_http_reject_is_idempotent_and_preserves_v1(tmp_path: Path) -> None:
    app = trusted_http_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    v1_request = planning_request()
    v2_request = copy.deepcopy(v1_request)
    v2_request["taskFacts"][3]["note"] = "服务端签发后测试拒绝幂等"  # type: ignore[index]
    trip_id = v1_request["trip"]["tripId"]  # type: ignore[index]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        v1 = await start_issued_v1(client, v1_request)
        generated = await client.post(
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
        assert generated.status_code == 200, generated.text
        plan_id = generated.json()["data"]["plan"]["planId"]
        first = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{plan_id}/reject"
        )
        second = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{plan_id}/reject"
        )
        restored = await client.get(f"/api/v1/trips/{trip_id}")
        accepted_after_reject = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{plan_id}/accept"
        )

    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["decision"] == "REJECTED"
    assert second.json()["data"]["currentPlanId"] == v1["planId"]
    assert restored.json()["data"]["tripStatus"] == "EXECUTING"
    assert restored.json()["data"]["currentPlan"]["planId"] == v1["planId"]
    assert accepted_after_reject.status_code == 409
    assert accepted_after_reject.json()["code"] == "PLAN_STATE_TRANSITION_INVALID"
