from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from typing import Any

import httpx
import pytest

from app.application.amap_service import AmapLocationService
from app.core.config import Settings
from app.infrastructure.cache import SqliteProviderCache
from app.main import create_app


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "s1_t024"
    / "beijing_low_stamina_single.json"
)


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class BeijingProviderStub:
    """Deterministic external seam used through the production Amap service."""

    def __init__(self, fixture: dict[str, Any]) -> None:
        self._places = {
            item["keyword"]: item for item in fixture["providerPlaces"]
        }
        self.city_requests: list[str] = []
        self.place_requests: list[dict[str, Any]] = []
        self.route_requests: list[dict[str, Any]] = []

    async def resolve_city(self, city_name: str) -> dict[str, Any]:
        self.city_requests.append(city_name)
        return {
            "status": "1",
            "geocodes": [
                {
                    "formatted_address": "北京市",
                    "city": "北京市",
                    "citycode": "010",
                    "adcode": "110000",
                    "location": "116.407387,39.904179",
                }
            ],
        }

    async def search_places(self, **kwargs: Any) -> dict[str, Any]:
        self.place_requests.append(kwargs)
        item = self._places[kwargs["keywords"]]
        return {
            "status": "1",
            "count": "1",
            "pois": [
                {
                    "id": item["placeId"],
                    "name": item["name"],
                    "address": "北京市测试地址",
                    "location": item["location"],
                    "citycode": "010",
                    "adcode": "110101",
                    "type": "风景名胜",
                    "tel": [],
                    "biz_ext": {"rating": "4.8", "cost": item["cost"]},
                }
            ],
        }

    async def plan_route(self, **kwargs: Any) -> dict[str, Any]:
        self.route_requests.append(kwargs)
        origin = kwargs["origin"]
        destination = kwargs["destination"]
        polyline = (
            f"{origin.longitude},{origin.latitude};"
            f"{destination.longitude},{destination.latitude}"
        )
        return {
            "status": "1",
            "route": {
                "paths": [
                    {
                        "distance": "300",
                        "duration": "600",
                        "steps": [
                            {
                                "instruction": "低强度步行前往下一地点",
                                "distance": "300",
                                "duration": "600",
                                "polyline": polyline,
                            }
                        ],
                    }
                ]
            },
        }


def _app_and_database(tmp_path: Path, fixture: dict[str, Any]):
    database_path = tmp_path / "s1_t024.sqlite3"
    provider = BeijingProviderStub(fixture)
    location_service = AmapLocationService(
        client=provider,  # type: ignore[arg-type]
        cache=SqliteProviderCache(tmp_path / "provider.sqlite3"),
        place_ttl_seconds=86_400,
        route_ttl_seconds=1_800,
    )
    settings = Settings(
        _env_file=None,
        plan_version_db_path=database_path,
        amap_cache_db_path=tmp_path / "provider.sqlite3",
    )
    app = create_app(settings=settings, service=location_service)
    return app, database_path, provider


def _assert_low_stamina_single(trip: dict[str, Any]) -> None:
    assert trip["mode"] == "SINGLE"
    assert len(trip["participants"]) == 1
    participant = trip["participants"][0]
    assert participant["nickname"] == "单人旅客"
    assert participant["assistanceProfile"] == {
        "type": "LOW_STAMINA",
        "childAge": None,
        "walkLimits": {
            "maxContinuousMeters": 800,
            "maxDailyMeters": None,
        },
        "maxTransfers": 1,
        "restInterval": 60,
        "napWindow": None,
        "avoidStairs": False,
    }


async def _candidate_request_from_provider(
    client: httpx.AsyncClient,
    *,
    trip: dict[str, Any],
    city_resolution: dict[str, Any],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    trip_id = trip["tripId"]
    city_context = trip["cityContext"]
    origin = city_context["center"]
    task_facts: list[dict[str, Any]] = []

    for spec in fixture["taskSpecs"]:
        places_response = await client.post(
            "/api/v1/places/search",
            json={
                "schemaVersion": "1.0",
                "tripId": trip_id,
                "cityContext": city_context,
                "keywords": spec["keywords"],
                "types": [],
                "page": 1,
                "pageSize": 1,
            },
        )
        assert places_response.status_code == 200, places_response.text
        place = places_response.json()["data"]["places"][0]

        route_response = await client.post(
            "/api/v1/routes/plan",
            json={
                "schemaVersion": "1.0",
                "tripId": trip_id,
                "cityContext": city_context,
                "origin": origin,
                "destination": place["location"],
                "mode": spec["routeMode"],
                "strategy": None,
            },
        )
        assert route_response.status_code == 200, route_response.text
        route = route_response.json()["data"]["routes"][0]
        task_facts.append(
            {
                "taskId": spec["taskId"],
                "order": spec["order"],
                "title": spec["title"],
                "category": spec["category"],
                "startAt": spec["startAt"],
                "endAt": spec["endAt"],
                "endLocationText": place["name"],
                "cityCode": place["cityCode"],
                "place": place,
                "route": route,
                "elapsedSinceRestMinutes": spec["elapsedSinceRestMinutes"],
                "note": spec["note"],
            }
        )
        origin = place["location"]

    planning_trip = deepcopy(trip)
    planning_trip["status"] = "PLANNING"
    endpoint_provenance = city_resolution["provenance"]
    return {
        "schemaVersion": "1.0",
        "trip": planning_trip,
        "startLocation": {
            "locationText": trip["days"][0]["startLocationText"],
            "cityCode": city_context["cityCode"],
            "location": city_context["center"],
            "provenance": endpoint_provenance,
        },
        "endLocation": {
            "locationText": trip["days"][0]["endLocationText"],
            "cityCode": city_context["cityCode"],
            "location": city_context["center"],
            "provenance": endpoint_provenance,
        },
        "taskFacts": task_facts,
        "confirmedConstraints": fixture["confirmedConstraints"],
    }


def _review_confirmations(
    review: dict[str, Any],
    fixture: dict[str, Any],
) -> list[dict[str, Any]]:
    confirmed_price = next(
        item["confirmedPriceCents"]
        for item in fixture["providerPlaces"]
        if "confirmedPriceCents" in item
    )
    confirmations = []
    for item in review["items"]:
        confirmations.append(
            {
                "itemId": item["itemId"],
                "amountCents": (
                    confirmed_price if item["valueType"] == "PRICE_CENTS" else None
                ),
                "facilityStatus": (
                    "PASS" if item["valueType"] == "FACILITY_STATUS" else None
                ),
                "sourceConfirmed": (
                    True if item["valueType"] == "SOURCE_CONFIRMATION" else None
                ),
                "note": "S1-T024 固定案例人工确认",
            }
        )
    return confirmations


async def _event(
    client: httpx.AsyncClient,
    *,
    trip_id: str,
    plan_id: str,
    task_id: str,
    event_type: str,
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
            "idempotencyKey": f"{plan_id}:{task_id}:{event_type}",
            "occurredAt": "2026-08-26T10:30:00+08:00",
        },
    )


@pytest.mark.asyncio
async def test_beijing_single_accept_path_uses_real_sqlite_asgi_and_server_summary(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    assert "PARENT_CHILD" not in json.dumps(fixture, ensure_ascii=False)
    assert "childAge" not in fixture["draftRequest"]
    app, database_path, provider = _app_and_database(tmp_path, fixture)
    sent_replan_bodies: list[dict[str, Any]] = []

    async def capture_request(request: httpx.Request) -> None:
        if request.url.path.endswith("/replans/from-events"):
            sent_replan_bodies.append(json.loads(request.content.decode("utf-8")))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        event_hooks={"request": [capture_request]},
    ) as client:
        city_response = await client.post(
            "/api/v1/cities/resolve",
            json={"schemaVersion": "1.0", "cityName": "北京"},
        )
        confirmed_trip_response = await client.post(
            "/api/v1/trips/drafts/confirm",
            json=fixture["draftRequest"],
        )
        assert city_response.status_code == 200, city_response.text
        assert confirmed_trip_response.status_code == 200, confirmed_trip_response.text
        city_resolution = city_response.json()["data"]
        confirmed_trip = confirmed_trip_response.json()["data"]
        trip_id = confirmed_trip["tripId"]
        _assert_low_stamina_single(confirmed_trip)
        assert city_resolution["cityContext"]["cityCode"] == "110000"

        profile = confirmed_trip["participants"][0]["assistanceProfile"]
        saved_constraints = await client.put(
            f"/api/v1/trips/{trip_id}/constraints",
            json=profile,
        )
        confirmed_constraints = await client.post(
            f"/api/v1/trips/{trip_id}/constraints/confirm"
        )
        restored_constraints = await client.get(
            f"/api/v1/trips/{trip_id}/constraints"
        )
        assert saved_constraints.status_code == 200, saved_constraints.text
        assert confirmed_constraints.status_code == 200, confirmed_constraints.text
        assert restored_constraints.status_code == 200, restored_constraints.text
        assert confirmed_constraints.json()["data"]["status"] == "CONSTRAINT_CONFIRMED"
        assert confirmed_constraints.json()["data"]["assistanceProfile"] == profile
        assert restored_constraints.json()["data"]["assistanceProfile"] == profile

        request = await _candidate_request_from_provider(
            client,
            trip=confirmed_trip,
            city_resolution=city_resolution,
            fixture=fixture,
        )
        _assert_low_stamina_single(request["trip"])
        generated_v1 = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/generate",
            json=request,
        )
        assert generated_v1.status_code == 422, generated_v1.text
        assert generated_v1.json()["code"] == "CANDIDATE_CONFIRMATION_REQUIRED"
        review = generated_v1.json()["errors"][0]["review"]
        assert {item["valueType"] for item in review["items"]} == {
            "PRICE_CENTS",
            "FACILITY_STATUS",
        }
        confirmed_v1 = await client.post(
            f"/api/v1/trips/{trip_id}/plan-reviews/{review['reviewId']}/confirm",
            json={
                "schemaVersion": "1.0",
                "confirmations": _review_confirmations(review, fixture),
            },
        )
        assert confirmed_v1.status_code == 200, confirmed_v1.text
        v1 = confirmed_v1.json()["data"]
        v1_id = v1["planId"]
        assert v1["version"] == 1
        assert v1["status"] == "PROPOSED"
        _assert_low_stamina_single(v1["tripSnapshot"])

        planning_facts = await client.get(
            f"/api/v1/trips/{trip_id}/planning-facts"
        )
        assert planning_facts.status_code == 200, planning_facts.text
        _assert_low_stamina_single(planning_facts.json()["data"]["trip"])

        confirmed_plan = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{v1_id}/confirm"
        )
        started = await client.post(f"/api/v1/trips/{trip_id}/execution/start")
        assert confirmed_plan.status_code == 200, confirmed_plan.text
        assert started.status_code == 200, started.text

        first_task = v1["days"][0]["tasks"][0]
        start = await _event(
            client,
            trip_id=trip_id,
            plan_id=v1_id,
            task_id=first_task["taskId"],
            event_type="START",
        )
        actual_cents = first_task["costCents"] + 5_000
        expense = await _event(
            client,
            trip_id=trip_id,
            plan_id=v1_id,
            task_id=first_task["taskId"],
            event_type="EXPENSE",
            amount_cents=actual_cents,
        )
        expense_replay = await _event(
            client,
            trip_id=trip_id,
            plan_id=v1_id,
            task_id=first_task["taskId"],
            event_type="EXPENSE",
            amount_cents=actual_cents,
        )
        expense_conflict = await _event(
            client,
            trip_id=trip_id,
            plan_id=v1_id,
            task_id=first_task["taskId"],
            event_type="EXPENSE",
            amount_cents=actual_cents + 1,
        )
        complete = await _event(
            client,
            trip_id=trip_id,
            plan_id=v1_id,
            task_id=first_task["taskId"],
            event_type="COMPLETE",
        )
        assert start.status_code == expense.status_code == complete.status_code == 200
        assert expense_replay.status_code == 200, expense_replay.text
        assert expense_replay.json()["data"]["eventId"] == expense.json()["data"]["eventId"]
        assert expense_conflict.status_code == 409, expense_conflict.text
        assert expense_conflict.json()["code"] == "EVENT_IDEMPOTENCY_CONFLICT"

        replan_body = {"schemaVersion": "1.0", "reason": "EXPENSE_CHANGE"}
        invalid_extras = (
            {"candidates": []},
            {"lockedTaskIds": []},
            {"validationReport": {"status": "PASS"}},
        )
        for extra in invalid_extras:
            rejected = await client.post(
                f"/api/v1/trips/{trip_id}/replans/from-events",
                json={**replan_body, **extra},
            )
            assert rejected.status_code == 422, rejected.text
            assert rejected.json()["code"] == "TRIP_SCHEMA_INVALID"

        from_events = await client.post(
            f"/api/v1/trips/{trip_id}/replans/from-events",
            json=replan_body,
        )
        assert sent_replan_bodies[-1] == replan_body
        assert from_events.status_code == 200, from_events.text
        from_events_payload = from_events.json()["data"]
        v2 = from_events_payload["plan"]
        v2_id = v2["planId"]
        assert from_events_payload["outcome"] == "SELECTED"
        assert from_events_payload["frozenTaskIds"] == [first_task["taskId"]]
        assert v2["version"] == 2
        assert v2["status"] == "PROPOSED"
        assert v2["parentId"] == v1_id

        diff_response = await client.get(
            f"/api/v1/trips/{trip_id}/plan-versions/{v2_id}/diff"
        )
        assert diff_response.status_code == 200, diff_response.text
        diff = diff_response.json()["data"]
        assert diff["basePlanId"] == v1_id
        assert diff["candidatePlanId"] == v2_id
        assert diff["items"]
        assert all(item["changeType"] == "RETAINED" for item in diff["items"])
        assert all(item["before"] == item["after"] for item in diff["items"])
        assert diff["metricsDelta"] == {
            "totalCostCents": 0,
            "totalWalkMeters": 0,
            "transferCount": 0,
        }
        frozen_diff = [
            item
            for item in diff["items"]
            if item["key"].startswith(f"task:{first_task['taskId']}:")
        ]
        assert len(frozen_diff) == 4
        assert all(item["changeType"] == "RETAINED" for item in frozen_diff)

        accepted = await client.post(
            f"/api/v1/trips/{trip_id}/plan-versions/{v2_id}/accept"
        )
        assert accepted.status_code == 200, accepted.text
        decision = accepted.json()["data"]
        assert decision["previousCurrentStatus"] == "SUPERSEDED"
        assert decision["candidateStatus"] == "CURRENT"

        state_after_accept_response = await client.get(f"/api/v1/trips/{trip_id}")
        assert state_after_accept_response.status_code == 200
        state_after_accept = state_after_accept_response.json()["data"]
        current_v2 = state_after_accept["currentPlan"]
        assert current_v2["planId"] == v2_id
        assert current_v2["status"] == "CURRENT"

        terminal_task_ids = {
            event["taskId"]
            for event in state_after_accept["events"]
            if event["eventType"] in {"COMPLETE", "SKIP"}
        }
        unfinished_tasks = [
            task
            for task in current_v2["days"][0]["tasks"]
            if task["taskId"] not in terminal_task_ids
        ]
        assert unfinished_tasks
        first_unfinished_task_id = unfinished_tasks[0]["taskId"]

        for task in unfinished_tasks:
            started_task = await _event(
                client,
                trip_id=trip_id,
                plan_id=v2_id,
                task_id=task["taskId"],
                event_type="START",
            )
            expense_task = await _event(
                client,
                trip_id=trip_id,
                plan_id=v2_id,
                task_id=task["taskId"],
                event_type="EXPENSE",
                amount_cents=task["costCents"],
            )
            completed_task = await _event(
                client,
                trip_id=trip_id,
                plan_id=v2_id,
                task_id=task["taskId"],
                event_type="COMPLETE",
            )
            assert started_task.status_code == 200, started_task.text
            assert expense_task.status_code == 200, expense_task.text
            assert completed_task.status_code == 200, completed_task.text

        final_state_response = await client.get(f"/api/v1/trips/{trip_id}")
        summary_response = await client.get(f"/api/v1/trips/{trip_id}/summary")
        assert final_state_response.status_code == 200, final_state_response.text
        assert summary_response.status_code == 200, summary_response.text
        final_state = final_state_response.json()["data"]
        summary = summary_response.json()["data"]

    assert database_path.exists()
    with sqlite3.connect(database_path) as connection:
        persisted_trip_row = connection.execute(
            "SELECT trip_json FROM confirmed_trip_inputs WHERE trip_id = ?",
            (trip_id,),
        ).fetchone()
        plan_rows = connection.execute(
            "SELECT version, status, snapshot_json FROM plan_versions ORDER BY version"
        ).fetchall()

    assert persisted_trip_row is not None
    persisted_trip = json.loads(persisted_trip_row[0])
    _assert_low_stamina_single(persisted_trip)
    assert persisted_trip == confirmed_trip
    assert [(row[0], row[1]) for row in plan_rows] == [
        (1, "SUPERSEDED"),
        (2, "CURRENT"),
    ]
    persisted_v1 = json.loads(plan_rows[0][2])
    persisted_v2 = json.loads(plan_rows[1][2])
    assert persisted_v2["parentId"] == persisted_v1["planId"] == v1_id
    assert persisted_v2["planId"] == v2_id

    assert provider.city_requests
    assert set(provider.city_requests) == {"北京"}
    assert [call["keywords"] for call in provider.place_requests] == [
        item["keywords"] for item in fixture["taskSpecs"]
    ]
    assert len(provider.route_requests) == len(fixture["taskSpecs"])
    assert all(call["city_code"] == "110000" for call in provider.place_requests)
    assert all(call["city_code"] == "110000" for call in provider.route_requests)

    assert final_state["tripStatus"] == "COMPLETED"
    assert final_state["currentPlan"]["planId"] == v2_id
    assert summary["tripStatus"] == "COMPLETED"
    assert summary["differenceCents"] == 5_000
    assert summary["totalTasks"] == len(v2["days"][0]["tasks"])
    assert set(summary["completedTaskIds"]) == {
        task["taskId"] for task in v2["days"][0]["tasks"]
    }
    assert {item["status"] for item in summary["planHistory"]} == {
        "CURRENT",
        "SUPERSEDED",
    }

    task_ids_by_plan = {
        v1_id: {task["taskId"] for task in v1["days"][0]["tasks"]},
        v2_id: {task["taskId"] for task in v2["days"][0]["tasks"]},
    }
    assert len({event["eventId"] for event in summary["events"]}) == len(summary["events"])
    for event in summary["events"]:
        assert event["tripId"] == trip_id
        assert event["planVersionId"] in task_ids_by_plan
        assert event["taskId"] in task_ids_by_plan[event["planVersionId"]]

    first_unfinished_starts = [
        event
        for event in summary["events"]
        if event["eventType"] == "START"
        and event["planVersionId"] == v2_id
        and event["taskId"] == first_unfinished_task_id
    ]
    assert len(first_unfinished_starts) == 1
