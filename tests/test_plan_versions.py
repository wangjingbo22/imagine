import copy
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.application.plan_service import PlanVersionService
from app.infrastructure.plan_store import PlanStoreError, SqlitePlanVersionRepository
from app.main import create_app
from app.schemas.plan import PlanVersionStatus, ProposedPlanVersion
from app.schemas.trip import TripStatus


class UnusedLocationService:
    pass


def proposal_payload() -> dict[str, object]:
    fixture_path = (
        Path(__file__).parents[1]
        / "backend"
        / "tests"
        / "fixtures"
        / "trips"
        / "beijing.json"
    )
    trip = json.loads(fixture_path.read_text(encoding="utf-8"))
    trip["status"] = "PLAN_REVIEW"
    return {
        "schemaVersion": "1.0",
        "planId": "20000000-0000-4000-8000-000000000001",
        "tripSnapshot": trip,
        "version": 1,
        "parentId": None,
        "reason": "INITIAL_PLAN",
        "metrics": {
            "totalCostCents": 29_800,
            "bufferCents": 5_200,
            "totalWalkMeters": 2_650,
            "transferCount": 2,
            "validationStatus": "PASS",
        },
        "days": [
            {
                "dayIndex": 0,
                "date": "2026-09-05",
                "tasks": [
                    {
                        "taskId": "task-1",
                        "order": 1,
                        "title": "中国国家博物馆",
                        "category": "历史文化",
                        "timeRange": "09:40 — 11:40",
                        "durationMinutes": 120,
                        "transport": "地铁 8 号线 · 38 分钟",
                        "costCents": 600,
                        "walkMeters": 420,
                        "note": "东门无障碍入口信息待现场确认",
                    },
                    {
                        "taskId": "task-2",
                        "order": 2,
                        "title": "四季民福 · 前门店",
                        "category": "特色餐饮",
                        "timeRange": "12:05 — 13:20",
                        "durationMinutes": 75,
                        "transport": "步行 460 米 · 8 分钟",
                        "costCents": 13_800,
                        "walkMeters": 460,
                        "note": "已预留午餐与休息时间",
                    },
                    {
                        "taskId": "task-3",
                        "order": 3,
                        "title": "景山公园",
                        "category": "城市风景",
                        "timeRange": "14:10 — 16:00",
                        "durationMinutes": 110,
                        "transport": "公交 5 路 · 31 分钟",
                        "costCents": 400,
                        "walkMeters": 780,
                        "note": "山顶路线包含坡道，建议量力而行",
                    },
                    {
                        "taskId": "task-4",
                        "order": 4,
                        "title": "什刹海落日漫步",
                        "category": "轻松收尾",
                        "timeRange": "16:35 — 18:20",
                        "durationMinutes": 105,
                        "transport": "出租车 · 18 分钟",
                        "costCents": 15_000,
                        "walkMeters": 990,
                        "note": "18:20 返程，满足最晚结束时间",
                    },
                ],
            }
        ],
        "constraintsSnapshot": [
            {
                "ruleId": "budget-limit",
                "scope": "trip",
                "hardness": "HARD",
                "status": "PASS",
                "description": "方案总金额不超过行程预算",
                "details": {"budgetCents": "35000"},
            }
        ],
        "sourcesSnapshot": [
            {
                "provider": "FRONTEND_MOCK",
                "sourceStatus": "ESTIMATED",
                "fetchedAt": "2026-08-24T10:00:00+08:00",
                "isStale": False,
                "referenceId": "workspace-recommendation-v1",
            }
        ],
    }


def parse_proposal(payload: dict[str, object] | None = None) -> ProposedPlanVersion:
    return ProposedPlanVersion.model_validate_json(
        json.dumps(payload or proposal_payload(), ensure_ascii=False),
        strict=True,
    )


def build_plan_service(tmp_path: Path) -> PlanVersionService:
    return PlanVersionService(
        SqlitePlanVersionRepository(tmp_path / "plan_versions.sqlite3")
    )


async def post_proposal_and_restore_state(
    client: httpx.AsyncClient,
    payload: dict[str, object],
) -> tuple[httpx.Response, httpx.Response]:
    trip_id = payload["tripSnapshot"]["tripId"]  # type: ignore[index]
    registered = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions",
        json=payload,
    )
    restored = await client.get(f"/api/v1/trips/{trip_id}")
    return registered, restored


def test_plan_contract_rejects_bad_totals_order_and_hard_constraint() -> None:
    bad_total = proposal_payload()
    bad_total["metrics"]["totalCostCents"] = 1  # type: ignore[index]
    with pytest.raises(ValidationError, match="task cost sum"):
        parse_proposal(bad_total)

    bad_order = proposal_payload()
    bad_order["days"][0]["tasks"][1]["order"] = 3  # type: ignore[index]
    with pytest.raises(ValidationError, match="contiguous order"):
        parse_proposal(bad_order)

    failed_hard_rule = proposal_payload()
    failed_hard_rule["constraintsSnapshot"][0]["status"] = "FAIL"  # type: ignore[index]
    with pytest.raises(ValidationError, match="hard constraints"):
        parse_proposal(failed_hard_rule)


def test_plan_confirmation_guard_and_refresh_restore(tmp_path: Path) -> None:
    repository = SqlitePlanVersionRepository(tmp_path / "plan_versions.sqlite3")
    proposal = parse_proposal()

    registered = repository.register_proposed(proposal)
    assert registered.status is PlanVersionStatus.PROPOSED
    with pytest.raises(PlanStoreError, match="不可开始执行") as blocked:
        repository.start_execution(proposal.trip_snapshot.trip_id)
    assert blocked.value.code == "PLAN_NOT_CONFIRMED"

    confirmed = repository.confirm(
        proposal.trip_snapshot.trip_id,
        proposal.plan_id,
    )
    assert confirmed.trip_status is TripStatus.CONFIRMED
    assert confirmed.plan_status is PlanVersionStatus.CURRENT
    execution = repository.start_execution(proposal.trip_snapshot.trip_id)
    assert execution.trip_status == "EXECUTING"

    reopened = SqlitePlanVersionRepository(tmp_path / "plan_versions.sqlite3")
    restored = reopened.get_trip_state(proposal.trip_snapshot.trip_id)
    assert restored.trip_status is TripStatus.EXECUTING
    assert restored.current_plan is not None
    assert restored.current_plan.trip_snapshot.city_context.city_code == "110000"
    assert restored.current_plan.trip_snapshot.days[0].day_index == 0
    assert restored.current_plan.metrics.total_cost_cents == 29_800
    assert [task.task_id for task in restored.current_plan.days[0].tasks] == [
        "task-1",
        "task-2",
        "task-3",
        "task-4",
    ]


def test_plan_snapshot_is_immutable_and_confirm_is_idempotent(tmp_path: Path) -> None:
    repository = SqlitePlanVersionRepository(tmp_path / "plan_versions.sqlite3")
    proposal = parse_proposal()
    repository.register_proposed(proposal)
    first = repository.confirm(proposal.trip_snapshot.trip_id, proposal.plan_id)
    second = repository.confirm(proposal.trip_snapshot.trip_id, proposal.plan_id)
    assert first.plan_status is second.plan_status is PlanVersionStatus.CURRENT

    changed = copy.deepcopy(proposal_payload())
    changed["days"][0]["tasks"][0]["title"] = "被原地修改"  # type: ignore[index]
    with pytest.raises(PlanStoreError) as immutable:
        repository.register_proposed(parse_proposal(changed))
    assert immutable.value.code == "PLAN_VERSION_IMMUTABLE"


def test_rejected_plan_cannot_transition_to_current(tmp_path: Path) -> None:
    database_path = tmp_path / "plan_versions.sqlite3"
    repository = SqlitePlanVersionRepository(database_path)
    proposal = parse_proposal()
    repository.register_proposed(proposal)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE plan_versions SET status = 'REJECTED' WHERE plan_id = ?",
            (str(proposal.plan_id),),
        )

    with pytest.raises(PlanStoreError) as invalid_transition:
        repository.confirm(proposal.trip_snapshot.trip_id, proposal.plan_id)
    assert invalid_transition.value.code == "PLAN_STATE_TRANSITION_INVALID"


@pytest.mark.asyncio
async def test_plan_http_flow_and_unconfirmed_guard(tmp_path: Path) -> None:
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=build_plan_service(tmp_path),
    )
    transport = httpx.ASGITransport(app=app)
    payload = proposal_payload()
    trip_id = payload["tripSnapshot"]["tripId"]  # type: ignore[index]
    plan_id = payload["planId"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        registered = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions",
            json=payload,
        )
        blocked = await client.post(f"/api/v1/trips/{trip_id}/execution/start")
        confirmed = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{plan_id}/confirm"
        )
        started = await client.post(f"/api/v1/trips/{trip_id}/execution/start")
        restored = await client.get(f"/api/v1/trips/{trip_id}")

    assert registered.status_code == 200
    assert registered.json()["data"]["status"] == "PROPOSED"
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "PLAN_NOT_CONFIRMED"
    assert confirmed.json()["data"] == {
        "tripId": trip_id,
        "planId": plan_id,
        "tripStatus": "CONFIRMED",
        "planStatus": "CURRENT",
    }
    assert started.json()["data"]["tripStatus"] == "EXECUTING"
    state = restored.json()["data"]
    assert state["currentPlan"]["days"][0]["tasks"][1]["costCents"] == 13_800
    assert state["currentPlan"]["tripSnapshot"]["cityContext"]["cityCode"] == "110000"


@pytest.mark.asyncio
async def test_plan_http_rejects_path_payload_trip_mismatch(tmp_path: Path) -> None:
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=build_plan_service(tmp_path),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/trips/30000000-0000-4000-8000-000000000001/plan-versions",
            json=proposal_payload(),
        )

    assert response.status_code == 422
    assert response.json()["errors"][0]["path"] == "tripSnapshot.tripId"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invalid_case", "expected_path", "expected_code"),
    [
        ("multiple_participants", "tripSnapshot.participants", "too_long"),
        ("multiple_trip_days", "tripSnapshot.days", "too_long"),
        ("end_date_mismatch", "tripSnapshot.endDate", "date_mismatch"),
        ("trip_day_date_mismatch", "tripSnapshot.days[0].date", "date_mismatch"),
        ("nonzero_day_index", "tripSnapshot.days[0].dayIndex", "invalid_day_index"),
        (
            "equal_time_window",
            "tripSnapshot.days[0].timeWindow.end",
            "invalid_time_window",
        ),
        (
            "reversed_time_window",
            "tripSnapshot.days[0].timeWindow.end",
            "invalid_time_window",
        ),
        (
            "daily_budget_exceeds_total",
            "tripSnapshot.days[0].dailyBudgetCents",
            "budget_exceeded",
        ),
        (
            "invalid_preference_hardness",
            "tripSnapshot.participants[0].preferences[0].isHard",
            "invalid_preference_hardness",
        ),
        (
            "normalized_preference_conflict",
            "tripSnapshot.participants[0].preferences[1].value",
            "preference_conflict",
        ),
    ],
)
async def test_single_day_snapshot_rejects_invalid_v1_without_persistence(
    tmp_path: Path,
    invalid_case: str,
    expected_path: str,
    expected_code: str,
) -> None:
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=build_plan_service(tmp_path),
    )
    payload = proposal_payload()
    snapshot = payload["tripSnapshot"]  # type: ignore[index]
    snapshot_day = snapshot["days"][0]  # type: ignore[index]
    plan_day = payload["days"][0]  # type: ignore[index]

    if invalid_case == "multiple_participants":
        snapshot["participants"].append(copy.deepcopy(snapshot["participants"][0]))  # type: ignore[index]
    elif invalid_case == "multiple_trip_days":
        snapshot["days"].append(copy.deepcopy(snapshot_day))  # type: ignore[index]
    elif invalid_case == "end_date_mismatch":
        snapshot["endDate"] = "2026-09-06"  # type: ignore[index]
    elif invalid_case == "trip_day_date_mismatch":
        snapshot_day["date"] = "2026-09-06"  # type: ignore[index]
        plan_day["date"] = "2026-09-06"  # type: ignore[index]
    elif invalid_case == "nonzero_day_index":
        snapshot_day["dayIndex"] = 1  # type: ignore[index]
        plan_day["dayIndex"] = 1  # type: ignore[index]
    elif invalid_case == "equal_time_window":
        snapshot_day["timeWindow"]["end"] = "09:00:00"  # type: ignore[index]
    elif invalid_case == "reversed_time_window":
        snapshot_day["timeWindow"]["end"] = "08:59:59"  # type: ignore[index]
    elif invalid_case == "daily_budget_exceeds_total":
        snapshot_day["dailyBudgetCents"] = 35_001  # type: ignore[index]
    elif invalid_case == "invalid_preference_hardness":
        snapshot["participants"][0]["preferences"][0]["isHard"] = True  # type: ignore[index]
    elif invalid_case == "normalized_preference_conflict":
        snapshot["participants"][0]["preferences"] = [  # type: ignore[index]
            {
                "type": "MUST_VISIT",
                "value": " 故宫 ",
                "weight": 5,
                "isHard": True,
            },
            {
                "type": "AVOID_PLACE",
                "value": "故宫",
                "weight": 5,
                "isHard": True,
            },
        ]
    else:
        raise AssertionError(f"Unhandled invalid snapshot case: {invalid_case}")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        registered, restored = await post_proposal_and_restore_state(client, payload)

    assert registered.status_code == 422
    body = registered.json()
    assert body["code"] == "TRIP_SCHEMA_INVALID"
    assert body["errors"][0]["path"] == expected_path
    assert body["errors"][0]["code"] == expected_code
    assert restored.status_code == 404
    assert restored.json()["code"] == "TRIP_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invalid_case", "expected_path", "expected_code"),
    [
        ("multiple_participants", "tripSnapshot.participants", "too_long"),
        (
            "invalid_preference_hardness",
            "tripSnapshot.participants[0].preferences[0].isHard",
            "invalid_preference_hardness",
        ),
    ],
)
async def test_invalid_v2_snapshot_preserves_current_v1_execution_state(
    tmp_path: Path,
    invalid_case: str,
    expected_path: str,
    expected_code: str,
) -> None:
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=build_plan_service(tmp_path),
    )
    v1 = proposal_payload()
    trip_id = v1["tripSnapshot"]["tripId"]  # type: ignore[index]
    v2 = copy.deepcopy(v1)
    v2["planId"] = "20000000-0000-4000-8000-000000000002"
    v2["version"] = 2
    v2["parentId"] = v1["planId"]
    v2["reason"] = "DELAY"
    if invalid_case == "multiple_participants":
        v2["tripSnapshot"]["participants"].append(  # type: ignore[index]
            copy.deepcopy(v2["tripSnapshot"]["participants"][0])  # type: ignore[index]
        )
    elif invalid_case == "invalid_preference_hardness":
        v2["tripSnapshot"]["participants"][0]["preferences"][0][  # type: ignore[index]
            "isHard"
        ] = True
    else:
        raise AssertionError(f"Unhandled invalid V2 snapshot case: {invalid_case}")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        registered_v1 = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions",
            json=v1,
        )
        confirmed_v1 = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{v1['planId']}/confirm"
        )
        started_v1 = await client.post(f"/api/v1/trips/{trip_id}/execution/start")
        state_before = await client.get(f"/api/v1/trips/{trip_id}")
        rejected_v2, state_after = await post_proposal_and_restore_state(client, v2)

    assert registered_v1.status_code == confirmed_v1.status_code == started_v1.status_code == 200
    assert state_before.status_code == 200
    before = state_before.json()["data"]
    assert before["tripStatus"] == "EXECUTING"
    assert before["currentPlan"]["planId"] == v1["planId"]
    assert before["proposedPlans"] == []
    assert rejected_v2.status_code == 422
    body = rejected_v2.json()
    assert body["code"] == "TRIP_SCHEMA_INVALID"
    assert body["errors"][0]["path"] == expected_path
    assert body["errors"][0]["code"] == expected_code
    assert state_after.status_code == 200
    after = state_after.json()["data"]
    assert after["tripStatus"] == "EXECUTING"
    assert after["currentPlan"] == before["currentPlan"]
    assert after["proposedPlans"] == []
