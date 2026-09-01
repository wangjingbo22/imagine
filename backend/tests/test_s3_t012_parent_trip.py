from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import httpx

from app.application.parent_trip_service import ParentTripService
from app.core.errors import AppError
from app.domain.parent_trip import ParentTripCreateRequest
from app.infrastructure.parent_trip_store import ParentTripStoreError, SqliteParentTripRepository
from app.core.config import Settings
from app.main import create_app


class Revisions:
    def __init__(self): self.items = {}
    def get_current(self, trip_id): return self.items[trip_id]


class Collaboration:
    def __init__(self): self.tokens = {}
    def organizer_state(self, trip_id, token):
        if self.tokens.get(trip_id) != token: raise AppError("ORGANIZER_PERMISSION_REQUIRED", "x", 403, False)
        return object()


class Plans:
    def __init__(self): self.items = {}
    def get_trip_state(self, trip_id):
        if trip_id not in self.items:
            raise AppError("TRIP_NOT_FOUND", "x", 404, False)
        return self.items[trip_id]


def request(days=3):
    return ParentTripCreateRequest(schemaVersion="1.0", parentTripId=uuid4(), title="北京三日",
        cityName="北京", startDate=date(2026, 9, 6), dayBudgetCents=[50_000] * days)


def service(tmp_path: Path):
    revisions, collaboration = Revisions(), Collaboration()
    return ParentTripService(SqliteParentTripRepository(tmp_path / "t.sqlite3"), revisions,
        collaboration, Plans(), today=lambda: date(2026, 9, 1)), revisions, collaboration


def plan_task(
    place_id: str,
    title: str,
    category: str = "景点",
):
    return SimpleNamespace(task_id=place_id, title=title, category=category)


def plan(*tasks, version=1, status="PROPOSED"):
    return SimpleNamespace(
        plan_id=uuid4(),
        version=version,
        status=status,
        created_at=datetime.now(UTC),
        days=[SimpleNamespace(tasks=list(tasks))],
        metrics=SimpleNamespace(total_cost_cents=0),
    )


def test_two_and_three_day_parent_are_consecutive_and_budgeted(tmp_path: Path):
    current, _, _ = service(tmp_path)
    for count in (2, 3):
        value = current.create(request(count), f"token-{count}" * 8)
        assert len(value.days) == count
        assert [item.day_index for item in value.days] == list(range(count))
        assert value.end_date == date(2026, 9, 5 + count)
        assert value.total_budget_cents == 50_000 * count
        assert value.planned_cost_cents is None
        assert all(day.cost_status == "NOT_AVAILABLE" for day in value.days)


def test_parent_trip_rejects_a_start_date_before_today(tmp_path: Path):
    current, _, _ = service(tmp_path)
    payload = request(2).model_copy(update={"start_date": date(2026, 8, 31)})

    with pytest.raises(AppError) as caught:
        current.create(payload, "past-date-token" * 4)

    assert caught.value.code == "PARENT_TRIP_DATE_IN_PAST"
    assert caught.value.http_status == 422


def test_child_must_match_city_date_and_budget_and_cannot_be_overwritten(tmp_path: Path):
    current, revisions, collaboration = service(tmp_path)
    parent_request = request(2)
    parent = current.create(parent_request, "parent-token" * 4)
    child = uuid4(); collaboration.tokens[child] = "child-token"
    revisions.items[child] = SimpleNamespace(understanding=SimpleNamespace(trip=SimpleNamespace(
        city_name="北京", travel_date=date(2026, 9, 6), budget_cents=49_000)))
    linked = current.link_day(parent.parent_trip_id, 0, child, "parent-token" * 4, "child-token")
    assert linked.days[0].child_trip_id == child
    other = uuid4(); collaboration.tokens[other] = "other-token"
    revisions.items[other] = SimpleNamespace(understanding=SimpleNamespace(trip=SimpleNamespace(
        city_name="北京", travel_date=date(2026, 9, 6), budget_cents=40_000)))
    with pytest.raises(AppError, match="不能覆盖"):
        current.link_day(parent.parent_trip_id, 0, other, "parent-token" * 4, "other-token")


@pytest.mark.parametrize("city,travel_date,budget", [
    ("上海", date(2026, 9, 6), 20_000), ("北京", date(2026, 9, 7), 20_000),
    ("北京", date(2026, 9, 6), 50_001),
])
def test_cross_city_wrong_date_and_over_budget_fail_closed(tmp_path: Path, city, travel_date, budget):
    current, revisions, collaboration = service(tmp_path)
    parent = current.create(request(2), "parent-token" * 4)
    child = uuid4(); collaboration.tokens[child] = "child-token"
    revisions.items[child] = SimpleNamespace(understanding=SimpleNamespace(trip=SimpleNamespace(
        city_name=city, travel_date=travel_date, budget_cents=budget)))
    with pytest.raises(AppError) as caught:
        current.link_day(parent.parent_trip_id, 0, child, "parent-token" * 4, "child-token")
    assert caught.value.code in {"PARENT_CHILD_SCOPE_MISMATCH", "PARENT_CHILD_BUDGET_EXCEEDED"}


def test_parent_token_is_required_and_child_is_unique_across_days(tmp_path: Path):
    current, revisions, collaboration = service(tmp_path)
    parent = current.create(request(2), "parent-token" * 4)
    with pytest.raises(AppError) as caught: current.get(parent.parent_trip_id, "wrong" * 8)
    assert caught.value.code == "PARENT_TRIP_PERMISSION_REQUIRED"
    child = uuid4(); collaboration.tokens[child] = "child-token"
    revisions.items[child] = SimpleNamespace(understanding=SimpleNamespace(trip=SimpleNamespace(
        city_name="北京", travel_date=date(2026, 9, 6), budget_cents=20_000)))
    current.link_day(parent.parent_trip_id, 0, child, "parent-token" * 4, "child-token")
    # A child cannot be silently reused for another day, even if a caller tampers with its date.
    revisions.items[child].understanding.trip.travel_date = date(2026, 9, 7)
    with pytest.raises(AppError) as duplicate:
        current.link_day(parent.parent_trip_id, 1, child, "parent-token" * 4, "child-token")
    assert duplicate.value.code == "CHILD_TRIP_ALREADY_LINKED"


def test_sibling_plan_places_are_automatic_hard_exclusions(tmp_path: Path):
    current, revisions, collaboration = service(tmp_path)
    parent = current.create(request(2), "parent-token" * 4)
    first, second = uuid4(), uuid4()
    collaboration.tokens.update({first: "first-token", second: "second-token"})
    revisions.items[first] = SimpleNamespace(understanding=SimpleNamespace(trip=SimpleNamespace(
        city_name="北京", travel_date=date(2026, 9, 6), budget_cents=20_000)))
    revisions.items[second] = SimpleNamespace(understanding=SimpleNamespace(trip=SimpleNamespace(
        city_name="北京", travel_date=date(2026, 9, 7), budget_cents=20_000)))
    current.link_day(parent.parent_trip_id, 0, first, "parent-token" * 4, "first-token")
    current.link_day(parent.parent_trip_id, 1, second, "parent-token" * 4, "second-token")
    first_plan = plan(
        plan_task("B000A83M61", "故宫博物院"),
        plan_task("B000A83M62", "天坛公园"),
        plan_task("B000A83M63", "故宫博物院"),
        plan_task("return-110000-home", "返回住处", "RETURN"),
        status="CURRENT",
    )
    current.plans.items[first] = SimpleNamespace(
        current_plan=first_plan,
        proposed_plans=[],
        trip_status=SimpleNamespace(value="PLAN_REVIEW"),
        actual_budget=None,
    )

    assert current.used_place_names_for_child(second) == ("故宫博物院", "天坛公园")
    assert current.used_place_names_for_child(uuid4()) == ()
    memory = current.place_memory_for_child(second)
    assert [(item.place_id, item.plan_status) for item in memory] == [
        ("B000A83M61", "CURRENT"),
        ("B000A83M62", "CURRENT"),
    ]
    aggregate = current.get(parent.parent_trip_id, "parent-token" * 4)
    assert aggregate.place_memory == list(memory)


def test_latest_proposed_v1_is_remembered_and_return_is_reusable(tmp_path: Path):
    current, revisions, collaboration = service(tmp_path)
    parent = current.create(request(2), "parent-token" * 4)
    first, second = uuid4(), uuid4()
    collaboration.tokens.update({first: "first-token", second: "second-token"})
    revisions.items[first] = SimpleNamespace(understanding=SimpleNamespace(trip=SimpleNamespace(
        city_name="北京", travel_date=date(2026, 9, 6), budget_cents=20_000)))
    revisions.items[second] = SimpleNamespace(understanding=SimpleNamespace(trip=SimpleNamespace(
        city_name="北京", travel_date=date(2026, 9, 7), budget_cents=20_000)))
    current.link_day(parent.parent_trip_id, 0, first, "parent-token" * 4, "first-token")
    current.link_day(parent.parent_trip_id, 1, second, "parent-token" * 4, "second-token")
    old_v1 = plan(plan_task("old-place", "旧地点"))
    latest_v1 = plan(
        plan_task("new-place", "新地点"),
        plan_task("return-110000-home", "返回住处", "RETURN"),
    )
    proposed_v2 = plan(plan_task("v2-place", "重规划地点"), version=2)
    current.plans.items[first] = SimpleNamespace(
        current_plan=None,
        proposed_plans=[old_v1, latest_v1, proposed_v2],
    )

    memory = current.place_memory_for_child(second)

    assert [(item.place_id, item.place_name) for item in memory] == [
        ("new-place", "新地点")
    ]
    assert memory[0].plan_id == latest_v1.plan_id
    assert memory[0].plan_status == "PROPOSED"


@pytest.mark.parametrize(
    ("candidate", "expected_place_id"),
    [
        (plan_task("B000A83M61", "不同展示名"), "B000A83M61"),
        (plan_task("different-provider-id", "  故宫博物院  "), "different-provider-id"),
    ],
)
def test_candidate_reusing_sibling_provider_id_or_normalized_name_is_rejected(
    tmp_path: Path,
    candidate,
    expected_place_id: str,
):
    current, revisions, collaboration = service(tmp_path)
    parent = current.create(request(2), "parent-token" * 4)
    first, second = uuid4(), uuid4()
    collaboration.tokens.update({first: "first-token", second: "second-token"})
    revisions.items[first] = SimpleNamespace(understanding=SimpleNamespace(trip=SimpleNamespace(
        city_name="北京", travel_date=date(2026, 9, 6), budget_cents=20_000)))
    revisions.items[second] = SimpleNamespace(understanding=SimpleNamespace(trip=SimpleNamespace(
        city_name="北京", travel_date=date(2026, 9, 7), budget_cents=20_000)))
    current.link_day(parent.parent_trip_id, 0, first, "parent-token" * 4, "first-token")
    current.link_day(parent.parent_trip_id, 1, second, "parent-token" * 4, "second-token")
    current.plans.items[first] = SimpleNamespace(
        current_plan=plan(
            plan_task("B000A83M61", "故宫博物院"),
            status="CURRENT",
        ),
        proposed_plans=[],
    )

    with pytest.raises(AppError) as caught:
        current.require_unique_candidate_places(second, [candidate])

    assert caught.value.code == "PARENT_TRIP_PLACE_REUSED"
    assert caught.value.errors[0]["placeId"] == expected_place_id
    assert caught.value.errors[0]["conflictingDayIndex"] == 0
    assert caught.value.errors[0]["conflictingPlaceId"] == "B000A83M61"


def test_return_task_does_not_conflict_with_sibling_day(tmp_path: Path):
    current, revisions, collaboration = service(tmp_path)
    parent = current.create(request(2), "parent-token" * 4)
    first, second = uuid4(), uuid4()
    collaboration.tokens.update({first: "first-token", second: "second-token"})
    revisions.items[first] = SimpleNamespace(understanding=SimpleNamespace(trip=SimpleNamespace(
        city_name="北京", travel_date=date(2026, 9, 6), budget_cents=20_000)))
    revisions.items[second] = SimpleNamespace(understanding=SimpleNamespace(trip=SimpleNamespace(
        city_name="北京", travel_date=date(2026, 9, 7), budget_cents=20_000)))
    current.link_day(parent.parent_trip_id, 0, first, "parent-token" * 4, "first-token")
    current.link_day(parent.parent_trip_id, 1, second, "parent-token" * 4, "second-token")
    current.plans.items[first] = SimpleNamespace(
        current_plan=plan(plan_task("shared-home", "返回住处"), status="CURRENT"),
        proposed_plans=[],
    )

    current.require_unique_candidate_places(
        second,
        [plan_task("shared-home", "返回住处", "RETURN")],
    )


@pytest.mark.asyncio
async def test_parent_trip_http_contract_round_trips_without_revealing_token(tmp_path: Path):
    app = create_app(settings=Settings(_env_file=None,
        plan_version_db_path=tmp_path / "http.sqlite3",
        amap_cache_db_path=tmp_path / "amap.sqlite3"))
    parent_id, token = uuid4(), "parent-http-token-0123456789abcdef"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v3/parent-trips", headers={"X-Parent-Trip-Token": token}, json={
            "schemaVersion": "1.0", "parentTripId": str(parent_id), "title": "成都两日",
            "cityName": "成都", "startDate": (date.today() + timedelta(days=9)).isoformat(), "dayBudgetCents": [30_000, 40_000],
        })
        assert created.status_code == 200, created.text
        body = created.json()["data"]
        assert body["totalBudgetCents"] == 70_000
        assert body["plannedCostCents"] is None
        assert body["placeMemory"] == []
        assert "token" not in created.text.lower()
        forbidden = await client.get(f"/api/v3/parent-trips/{parent_id}",
            headers={"X-Parent-Trip-Token": "wrong-token-0123456789abcdef000"})
        assert forbidden.status_code == 403
