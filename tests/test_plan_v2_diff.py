import copy
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.application.plan_service import PlanVersionService
from app.infrastructure.plan_store import PlanStoreError, SqlitePlanVersionRepository
from app.main import create_app
from app.schemas.plan import (
    PlanDiffChangeType,
    PlanV2Decision,
    PlanVersionStatus,
)
from app.schemas.trip import TripStatus
from tests.test_plan_versions import (
    UnusedLocationService,
    parse_proposal,
    proposal_payload,
)


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
    repository = SqlitePlanVersionRepository(tmp_path / "plan_versions.sqlite3")
    v1 = setup_executing(repository)
    service = PlanVersionService(repository)
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=service,
    )
    transport = httpx.ASGITransport(app=app)
    payload = v2_payload()
    trip_id = str(v1.trip_snapshot.trip_id)
    plan_id = payload["planId"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        registered = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions",
            json=payload,
        )
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
    assert registered.json()["data"]["version"] == 2
    assert diff.status_code == 200
    assert diff.json()["data"]["metricsDelta"]["totalCostCents"] == -2_400
    assert accepted.status_code == 200
    assert accepted.json()["data"]["decision"] == "ACCEPTED"
    assert rejected_after_accept.status_code == 409
    assert rejected_after_accept.json()["code"] == "PLAN_STATE_TRANSITION_INVALID"


@pytest.mark.asyncio
async def test_v2_http_reject_is_idempotent_and_preserves_v1(tmp_path: Path) -> None:
    repository = SqlitePlanVersionRepository(tmp_path / "plan_versions.sqlite3")
    v1 = setup_executing(repository)
    service = PlanVersionService(repository)
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=service,
    )
    transport = httpx.ASGITransport(app=app)
    payload = v2_payload()
    trip_id = str(v1.trip_snapshot.trip_id)
    plan_id = payload["planId"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(f"/api/v1/trips/{trip_id}/plan-versions", json=payload)
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
    assert second.json()["data"]["currentPlanId"] == str(v1.plan_id)
    assert restored.json()["data"]["tripStatus"] == "EXECUTING"
    assert restored.json()["data"]["currentPlan"]["planId"] == str(v1.plan_id)
    assert accepted_after_reject.status_code == 409
    assert accepted_after_reject.json()["code"] == "PLAN_STATE_TRANSITION_INVALID"
