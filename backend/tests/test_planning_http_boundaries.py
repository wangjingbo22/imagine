from __future__ import annotations

from copy import deepcopy
import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.application.plan_service import PlanVersionService
from app.application.workflow_service import WorkflowService
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.main import create_app
from app.schemas.trip import CreateSingleDayTrip
from app.services.planning.models import CandidatePlanRequest
from app.services.planning.planner import generate_proposed_plan_version
from backend.tests.plan_support import UnusedLocationService, proposal_payload


PLANNING_FIXTURE = (
    Path(__file__).parent / "fixtures" / "planning" / "golden_candidate_plan.json"
)


def _candidate_request() -> dict[str, Any]:
    fixture = json.loads(PLANNING_FIXTURE.read_text(encoding="utf-8"))
    return fixture["request"]


def _confirmed_trip(request: dict[str, Any]) -> CreateSingleDayTrip:
    payload = deepcopy(request["trip"])
    payload["status"] = "DRAFT"
    return CreateSingleDayTrip.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )


def _app_and_database(tmp_path: Path, *, persist_confirmed_trip: bool = True):
    database_path = tmp_path / "planning_http.sqlite3"
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    if persist_confirmed_trip:
        workflow.confirm_trip(_confirmed_trip(_candidate_request()))
    plans = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=workflow,
    )
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plans,
        workflow_service=workflow,
    )
    return app, database_path


async def _save_and_confirm_constraints(
    client: httpx.AsyncClient,
    request: dict[str, Any],
) -> None:
    trip_id = request["trip"]["tripId"]
    profile = request["trip"]["participants"][0]["assistanceProfile"]
    saved = await client.put(
        f"/api/v1/trips/{trip_id}/constraints",
        json=profile,
    )
    confirmed = await client.post(
        f"/api/v1/trips/{trip_id}/constraints/confirm"
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["status"] == "DRAFT"
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "CONSTRAINT_CONFIRMED"


async def _generate_confirm_and_start(
    client: httpx.AsyncClient,
    request: dict[str, Any],
) -> dict[str, Any]:
    trip_id = request["trip"]["tripId"]
    await _save_and_confirm_constraints(client, request)
    generated = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions/generate",
        json=request,
    )
    assert generated.status_code == 200, generated.text
    plan = generated.json()["data"]
    assert plan["status"] == "PROPOSED"
    assert plan["version"] == 1

    confirmed = await client.post(
        f"/api/v1/trips/{trip_id}/plan-versions/{plan['planId']}/confirm"
    )
    started = await client.post(f"/api/v1/trips/{trip_id}/execution/start")
    assert confirmed.status_code == 200, confirmed.text
    assert started.status_code == 200, started.text
    return plan


@pytest.mark.asyncio
async def test_raw_client_plan_registration_is_forbidden_without_persistence(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    raw = proposal_payload()
    tasks = raw["days"][0]["tasks"]
    tasks[0]["walkMeters"] = 50_000
    raw["metrics"]["totalWalkMeters"] = sum(task["walkMeters"] for task in tasks)
    raw["metrics"]["validationStatus"] = "PASS"
    raw["constraintsSnapshot"][0]["status"] = "PASS"
    raw["sourcesSnapshot"][0]["sourceStatus"] = "UNKNOWN"
    trip_id = raw["tripSnapshot"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        registered = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions",
            json=raw,
        )
        restored = await client.get(f"/api/v1/trips/{trip_id}")

    assert registered.status_code == 403, registered.text
    assert registered.json()["code"] == "PLAN_VERSION_DIRECT_REGISTRATION_FORBIDDEN"
    assert restored.status_code == 404
    assert restored.json()["code"] == "TRIP_NOT_FOUND"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM trips"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM trusted_plan_issuances"
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_v1_generation_requires_an_authoritative_confirmed_trip(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(
        tmp_path,
        persist_confirmed_trip=False,
    )
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _save_and_confirm_constraints(client, request)
        response = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=request,
        )

    assert response.status_code == 409
    assert response.json()["code"] == "TRIP_NOT_CONFIRMED"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM trusted_plan_issuances"
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(
            lambda request: request["trip"].__setitem__(
                "totalBudgetCents", 36_000
            ),
            id="budget",
        ),
        pytest.param(
            lambda request: request["trip"]["days"][0]["timeWindow"].__setitem__(
                "start", "08:30:00"
            ),
            id="time",
        ),
        pytest.param(
            lambda request: request["trip"]["days"][0].__setitem__(
                "endLocationText", "北京站"
            ),
            id="end-location",
        ),
        pytest.param(
            lambda request: request["trip"]["participants"][0].__setitem__(
                "participantId", "33333333-3333-4333-8333-333333333333"
            ),
            id="participant",
        ),
        pytest.param(
            lambda request: request["trip"]["participants"][0][
                "preferences"
            ].append(
                {
                    "type": "INTEREST",
                    "value": "临时篡改偏好",
                    "weight": 1,
                    "isHard": False,
                }
            ),
            id="preferences",
        ),
    ],
)
@pytest.mark.asyncio
async def test_v1_generation_rejects_any_material_confirmed_trip_tamper(
    tmp_path: Path,
    tamper,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    confirmed = _candidate_request()
    request = deepcopy(confirmed)
    tamper(request)
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _save_and_confirm_constraints(client, confirmed)
        response = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=request,
        )

    assert response.status_code == 409
    assert response.json()["code"] == "CONFIRMED_TRIP_MISMATCH"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM trusted_plan_issuances"
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_v1_generation_recomputes_unknown_price_and_hard_walk_failure(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    valid = _candidate_request()
    trip_id = valid["trip"]["tripId"]

    unknown = deepcopy(valid)
    unknown_price = unknown["taskFacts"][0]["place"]["priceReference"]
    unknown_price["amountCents"] = None
    unknown_price["provenance"]["sourceStatus"] = "UNKNOWN"

    unknown_facility = deepcopy(valid)
    facility = unknown_facility["taskFacts"][0]["route"]["facilityEvidence"][0]
    facility["status"] = "NEEDS_CONFIRMATION"
    facility["provenance"]["sourceStatus"] = "UNKNOWN"

    excessive_walk = deepcopy(valid)
    excessive_walk["taskFacts"][0]["route"]["walkingDistanceMeters"] = 50_000

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _save_and_confirm_constraints(client, valid)
        unknown_response = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=unknown,
        )
        facility_response = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=unknown_facility,
        )
        excessive_response = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=excessive_walk,
        )

    assert unknown_response.status_code == 422, unknown_response.text
    assert unknown_response.json()["code"] == "CANDIDATE_CONFIRMATION_REQUIRED"
    assert facility_response.status_code == 422, facility_response.text
    assert facility_response.json()["code"] == "CANDIDATE_CONFIRMATION_REQUIRED"
    assert facility_response.json()["errors"][0]["field"] == (
        "candidate.metrics.validationStatus"
    )
    assert excessive_response.status_code == 422, excessive_response.text
    assert excessive_response.json()["code"] == "CANDIDATE_PLAN_REJECTED"
    assert excessive_response.json()["errors"]
    with sqlite3.connect(database_path) as connection:
        plan_count = connection.execute("SELECT COUNT(*) FROM plan_versions").fetchone()
    assert plan_count == (0,)


@pytest.mark.asyncio
async def test_pending_price_review_is_persisted_confirmed_and_idempotent(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]
    price = request["taskFacts"][0]["place"]["priceReference"]
    price["amountCents"] = None
    price["provenance"]["sourceStatus"] = "UNKNOWN"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _save_and_confirm_constraints(client, request)
        generated = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=request,
        )
        assert generated.status_code == 422, generated.text
        review = generated.json()["errors"][0]["review"]
        review_id = review["reviewId"]
        assert review["status"] == "PENDING"
        assert [item["valueType"] for item in review["items"]] == [
            "PRICE_CENTS"
        ]

        restored = await client.get(
            f"/api/v1/trips/{trip_id}/plan-reviews/{review_id}"
        )
        payload = {
            "schemaVersion": "1.0",
            "confirmations": [
                {
                    "itemId": review["items"][0]["itemId"],
                    "amountCents": 0,
                    "facilityStatus": None,
                    "sourceConfirmed": None,
                    "note": "用户确认为免费",
                }
            ],
        }
        confirmed = await client.post(
            f"/api/v1/trips/{trip_id}/plan-reviews/{review_id}/confirm",
            json=payload,
        )
        retried = await client.post(
            f"/api/v1/trips/{trip_id}/plan-reviews/{review_id}/confirm",
            json=payload,
        )
        changed = deepcopy(payload)
        changed["confirmations"][0]["amountCents"] = 100
        conflict = await client.post(
            f"/api/v1/trips/{trip_id}/plan-reviews/{review_id}/confirm",
            json=changed,
        )

    assert restored.status_code == 200, restored.text
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["metrics"]["validationStatus"] == "PASS"
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["planId"] == confirmed.json()["data"]["planId"]
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "PLANNING_REVIEW_ALREADY_CONFIRMED"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT review_state, issued_plan_id FROM candidate_plan_reviews"
        ).fetchone()
    assert row == ("CONFIRMED", confirmed.json()["data"]["planId"])


@pytest.mark.asyncio
async def test_facility_review_preserves_user_confirmed_absence_as_soft_fact(
    tmp_path: Path,
) -> None:
    app, _ = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]
    request["taskFacts"][0]["taskId"] = "task.with.coordinate.116.3"
    facility = request["taskFacts"][0]["route"]["facilityEvidence"][2]
    assert facility["facilityType"] == "NURSING_ROOM"
    facility["status"] = "NEEDS_CONFIRMATION"
    facility["provenance"]["sourceStatus"] = "UNKNOWN"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _save_and_confirm_constraints(client, request)
        pending = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=request,
        )
        review = pending.json()["errors"][0]["review"]
        confirmed = await client.post(
            f"/api/v1/trips/{trip_id}/plan-reviews/{review['reviewId']}/confirm",
            json={
                "schemaVersion": "1.0",
                "confirmations": [
                    {
                        "itemId": review["items"][0]["itemId"],
                        "amountCents": None,
                        "facilityStatus": "FAIL",
                        "sourceConfirmed": None,
                        "note": "现场确认没有母婴室",
                    }
                ],
            },
        )

    assert pending.status_code == 422, pending.text
    assert review["items"][0]["valueType"] == "FACILITY_STATUS"
    assert review["items"][0]["label"].startswith("参观城市博物馆")
    assert confirmed.status_code == 200, confirmed.text
    data = confirmed.json()["data"]
    assert data["metrics"]["validationStatus"] == "PASS"
    facility_snapshot = next(
        item
        for item in data["constraintsSnapshot"]
        if item["ruleId"].endswith("NURSING_ROOM")
    )
    assert facility_snapshot["hardness"] == "SOFT"
    assert facility_snapshot["status"] == "FAIL"
    source = next(
        item
        for item in data["sourcesSnapshot"]
        if item["referenceId"].endswith("routeFacility.NURSING_ROOM")
    )
    assert source["sourceStatus"] == "USER_CONFIRMED"


@pytest.mark.asyncio
async def test_issued_v1_can_confirm_start_and_restore_from_sqlite(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        plan = await _generate_confirm_and_start(client, request)
        restored = await client.get(f"/api/v1/trips/{trip_id}")

    assert restored.status_code == 200, restored.text
    state = restored.json()["data"]
    assert state["tripStatus"] == "EXECUTING"
    assert state["currentPlan"]["planId"] == plan["planId"]
    assert state["currentPlan"]["status"] == "CURRENT"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT version, status FROM plan_versions WHERE plan_id = ?",
            (plan["planId"],),
        ).fetchone()
    assert row == (1, "CURRENT")


@pytest.mark.asyncio
async def test_replan_rejects_a_legacy_current_v1_without_issuance(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-unissued.sqlite3"
    request = _candidate_request()
    candidate = CandidatePlanRequest.model_validate_json(
        json.dumps(request, ensure_ascii=False),
        strict=True,
    )
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    workflow.confirm_trip(_confirmed_trip(request))
    profile = candidate.trip.participants[0].assistance_profile
    assert profile is not None
    workflow.save_constraint_draft(candidate.trip.trip_id, profile)
    workflow.confirm_constraints(candidate.trip.trip_id)
    plans = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=workflow,
    )
    legacy = generate_proposed_plan_version(candidate)
    plans.register_proposed(legacy)
    plans.confirm(candidate.trip.trip_id, legacy.plan_id)
    plans.start_execution(candidate.trip.trip_id)
    app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plans,
        workflow_service=workflow,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/trips/{candidate.trip.trip_id}/replans",
            json={
                "schemaVersion": "1.0",
                "reason": "USER_FEEDBACK",
                "lockedTaskIds": [],
                "candidates": [{"request": request, "satisfactionLoss": 0}],
            },
        )

    assert response.status_code == 409
    assert response.json()["code"] == "PLANNING_PLAN_NOT_ISSUED"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version, status FROM plan_versions ORDER BY version"
        ).fetchall() == [(1, "CURRENT")]
        assert connection.execute(
            "SELECT COUNT(*) FROM trusted_plan_issuances"
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_replan_uses_actual_expense_and_registers_no_over_budget_v2(
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
        expense = await client.post(
            f"/api/v1/trips/{trip_id}/events",
            json={
                "schemaVersion": "1.0",
                "taskId": current["days"][0]["tasks"][0]["taskId"],
                "planVersionId": current["planId"],
                "eventType": "EXPENSE",
                "amountCents": 50_000,
                "idempotencyKey": "planning-boundary-over-budget",
                "occurredAt": "2026-09-05T10:00:00+08:00",
            },
        )
        replanned = await client.post(
            f"/api/v1/trips/{trip_id}/replans",
            json={
                "schemaVersion": "1.0",
                "reason": "EXPENSE_CHANGE",
                "lockedTaskIds": [],
                "candidates": [
                    {"request": request, "satisfactionLoss": 0},
                ],
            },
        )

    assert expense.status_code == 200, expense.text
    assert replanned.status_code == 422, replanned.text
    assert replanned.json()["code"] == "REPLAN_NO_FEASIBLE_CANDIDATE"
    with sqlite3.connect(database_path) as connection:
        versions = connection.execute(
            "SELECT version, status FROM plan_versions ORDER BY version"
        ).fetchall()
        actual = connection.execute(
            "SELECT amount_cents FROM execution_events WHERE event_type = 'EXPENSE'"
        ).fetchall()
        trusted_v2_count = connection.execute(
            "SELECT COUNT(*) FROM trusted_plan_issuances WHERE plan_version = 2"
        ).fetchone()
    assert versions == [(1, "CURRENT")]
    assert actual == [(50_000,)]
    assert trusted_v2_count == (0,)


@pytest.mark.asyncio
async def test_two_candidate_replan_is_selected_issued_diffed_and_accepted(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]
    higher_loss = deepcopy(request)
    higher_loss["taskFacts"][2]["note"] = "候选 A：保留更多原偏好"
    preferred = deepcopy(request)
    preferred["taskFacts"][3]["note"] = "候选 B：用户更偏好"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_confirm_and_start(client, request)
        replanned = await client.post(
            f"/api/v1/trips/{trip_id}/replans",
            json={
                "schemaVersion": "1.0",
                "reason": "USER_FEEDBACK",
                "lockedTaskIds": [],
                "candidates": [
                    {"request": higher_loss, "satisfactionLoss": 10},
                    {"request": preferred, "satisfactionLoss": 0},
                ],
            },
        )
        assert replanned.status_code == 200, replanned.text
        selected = replanned.json()["data"]
        selected_plan = selected["plan"]
        diff = await client.get(
            f"/api/v1/trips/{trip_id}/plan-versions/{selected_plan['planId']}/diff"
        )
        accepted = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{selected_plan['planId']}/accept"
        )
        restored = await client.get(f"/api/v1/trips/{trip_id}")

    assert selected["outcome"] == "SELECTED"
    assert selected["disruptionScore"] == 1
    assert selected["satisfactionLoss"] == 0
    assert len(selected["assessments"]) == 2
    assert selected_plan["status"] == "PROPOSED"
    assert selected_plan["version"] == 2
    assert selected_plan["parentId"] == current["planId"]
    assert selected_plan["days"][0]["tasks"][3]["note"] == "候选 B：用户更偏好"
    assert diff.status_code == 200, diff.text
    assert diff.json()["data"]["basePlanId"] == current["planId"]
    assert diff.json()["data"]["candidatePlanId"] == selected_plan["planId"]
    assert accepted.status_code == 200, accepted.text
    state = restored.json()["data"]
    assert state["tripStatus"] == "EXECUTING"
    assert state["currentPlan"]["planId"] == selected_plan["planId"]
    assert state["currentPlan"]["status"] == "CURRENT"

    with sqlite3.connect(database_path) as connection:
        plans = connection.execute(
            "SELECT plan_id, version, status FROM plan_versions ORDER BY version"
        ).fetchall()
        issuances = connection.execute(
            """
            SELECT plan_id, plan_version, boundary_kind, issuance_state
            FROM trusted_plan_issuances
            ORDER BY plan_version, plan_id
            """
        ).fetchall()
    assert plans == [
        (current["planId"], 1, "SUPERSEDED"),
        (selected_plan["planId"], 2, "CURRENT"),
    ]
    issued_v2 = [
        row for row in issuances if row[1:] == (2, "V2", "ISSUED")
    ]
    validated_v2 = [
        row for row in issuances if row[1:] == (2, "V2", "VALIDATED")
    ]
    assert issued_v2 == [(selected_plan["planId"], 2, "V2", "ISSUED")]
    assert validated_v2 == []


@pytest.mark.asyncio
async def test_raw_v2_registration_is_forbidden_and_current_is_unchanged(
    tmp_path: Path,
) -> None:
    app, _ = _app_and_database(tmp_path)
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        current = await _generate_confirm_and_start(client, request)
        raw_v2 = {
            "schemaVersion": "1.0",
            "planId": str(uuid4()),
            "tripSnapshot": current["tripSnapshot"],
            "version": 2,
            "parentId": current["planId"],
            "reason": "USER_FEEDBACK",
            "metrics": current["metrics"],
            "days": current["days"],
            "constraintsSnapshot": current["constraintsSnapshot"],
            "sourcesSnapshot": current["sourcesSnapshot"],
        }
        registered = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions",
            json=raw_v2,
        )
        accepted = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{raw_v2['planId']}/accept"
        )
        restored = await client.get(f"/api/v1/trips/{trip_id}")

    assert registered.status_code == 403, registered.text
    assert registered.json()["code"] == "PLAN_VERSION_DIRECT_REGISTRATION_FORBIDDEN"
    assert accepted.status_code == 404
    assert accepted.json()["code"] == "PLAN_VERSION_NOT_FOUND"
    state = restored.json()["data"]
    assert state["currentPlan"]["planId"] == current["planId"]
    assert state["tripStatus"] == "EXECUTING"
    assert state["proposedPlans"] == []


@pytest.mark.asyncio
async def test_planning_facts_survive_app_rebuild_and_raw_plan_cannot_read_them(
    tmp_path: Path,
) -> None:
    issued_app, database_path = _app_and_database(tmp_path / "issued")
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]
    normalized_request = CandidatePlanRequest.model_validate_json(
        json.dumps(request),
        strict=True,
    ).model_dump(mode="json", by_alias=True)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=issued_app),
        base_url="http://test",
    ) as client:
        await _save_and_confirm_constraints(client, request)
        generated = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=request,
        )
        assert generated.status_code == 200, generated.text
        proposed_facts = await client.get(
            f"/api/v1/trips/{trip_id}/planning-facts"
        )
        assert proposed_facts.status_code == 200, proposed_facts.text
        assert proposed_facts.json()["data"] == normalized_request
        confirmed = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/"
            f"{generated.json()['data']['planId']}/confirm"
        )
        assert confirmed.status_code == 200, confirmed.text

    rebuilt_workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    rebuilt_plans = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=rebuilt_workflow,
    )
    rebuilt_app = create_app(
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=rebuilt_plans,
        workflow_service=rebuilt_workflow,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=rebuilt_app),
        base_url="http://test",
    ) as client:
        restored = await client.get(
            f"/api/v1/trips/{trip_id}/planning-facts"
        )
    assert restored.status_code == 200, restored.text
    assert restored.json()["data"] == normalized_request

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT snapshot_json FROM plan_versions WHERE version = 1"
        ).fetchone()
        assert row is not None
        tampered_snapshot = json.loads(row[0])
        tampered_snapshot["days"][0]["tasks"][0]["title"] = "tampered-title"
        connection.execute(
            "UPDATE plan_versions SET snapshot_json = ? WHERE version = 1",
            (json.dumps(tampered_snapshot, ensure_ascii=False),),
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=rebuilt_app),
        base_url="http://test",
    ) as client:
        tampered = await client.get(
            f"/api/v1/trips/{trip_id}/planning-facts"
        )
    assert tampered.status_code == 409
    assert tampered.json()["code"] == "PLANNING_PROPOSAL_DIGEST_MISMATCH"

    raw_app, _ = _app_and_database(tmp_path / "raw")
    raw = proposal_payload()
    raw_trip_id = raw["tripSnapshot"]["tripId"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=raw_app),
        base_url="http://test",
    ) as client:
        registered = await client.post(
            f"/api/v1/trips/{raw_trip_id}/plan-versions",
            json=raw,
        )
        blocked = await client.get(
            f"/api/v1/trips/{raw_trip_id}/planning-facts"
        )
    assert registered.status_code == 403, registered.text
    assert registered.json()["code"] == "PLAN_VERSION_DIRECT_REGISTRATION_FORBIDDEN"
    assert blocked.status_code == 404
    assert blocked.json()["code"] == "TRIP_NOT_FOUND"


@pytest.mark.asyncio
async def test_v1_generation_requires_a_saved_and_confirmed_profile(
    tmp_path: Path,
) -> None:
    request = _candidate_request()
    trip_id = request["trip"]["tripId"]

    missing_app, missing_database = _app_and_database(tmp_path / "missing")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=missing_app),
        base_url="http://test",
    ) as client:
        missing = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=request,
        )
    assert missing.status_code == 409
    assert missing.json()["code"] == "CONSTRAINTS_NOT_CONFIRMED"

    draft_app, draft_database = _app_and_database(tmp_path / "draft")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=draft_app),
        base_url="http://test",
    ) as client:
        saved = await client.put(
            f"/api/v1/trips/{trip_id}/constraints",
            json=request["trip"]["participants"][0]["assistanceProfile"],
        )
        draft = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=request,
        )
    assert saved.status_code == 200, saved.text
    assert draft.status_code == 409
    assert draft.json()["code"] == "CONSTRAINTS_NOT_CONFIRMED"

    for database_path in (missing_database, draft_database):
        with sqlite3.connect(database_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM plan_versions"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT COUNT(*) FROM trusted_plan_issuances"
            ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_v1_generation_rejects_a_profile_different_from_confirmation(
    tmp_path: Path,
) -> None:
    app, database_path = _app_and_database(tmp_path)
    confirmed_request = _candidate_request()
    trip_id = confirmed_request["trip"]["tripId"]
    mismatched_request = deepcopy(confirmed_request)
    mismatched_request["trip"]["participants"][0]["assistanceProfile"][
        "maxTransfers"
    ] = 1

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await _save_and_confirm_constraints(client, confirmed_request)
        mismatched = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=mismatched_request,
        )

    assert mismatched.status_code == 409
    assert mismatched.json()["code"] == "CONSTRAINT_PROFILE_MISMATCH"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM plan_versions"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM trusted_plan_issuances"
        ).fetchone() == (0,)
