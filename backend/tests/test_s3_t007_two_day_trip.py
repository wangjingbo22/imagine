from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest
from pydantic import ValidationError

from app.infrastructure.plan_store import PlanStoreError
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.schemas.trip import (
    CreateDayTrip,
    CreateTwoDayTrip,
    PlanReviewTripSnapshot,
    validate_create_day_trip_json,
    validate_two_day_trip_json,
)
from app.schemas.validation_error import TripSchemaError
from app.services.planning.models import CandidatePlanRequest


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "trips" / "two_day.json"
SCHEMA_SNAPSHOT_PATH = (
    Path(__file__).parent / "snapshots" / "create_two_day_trip.schema.json"
)
PUBLISHED_SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "create-two-day-trip.schema.json"
)
PLANNING_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "planning" / "golden_candidate_plan.json"
)


def fixture_payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def fixture_json(payload: dict[str, object] | None = None) -> str:
    return json.dumps(payload if payload is not None else fixture_payload())


def test_valid_two_day_fixture_round_trips_without_cross_day_loss() -> None:
    trip = validate_two_day_trip_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    recovered = validate_two_day_trip_json(trip.model_dump_json(by_alias=True))

    assert isinstance(trip, CreateTwoDayTrip)
    assert recovered == trip
    assert [day.day_index for day in recovered.days] == [0, 1]
    assert [day.date.isoformat() for day in recovered.days] == [
        "2026-09-05",
        "2026-09-06",
    ]
    assert [day.start_location_text for day in recovered.days] == [
        "Beijing Railway Station",
        "Forbidden City",
    ]
    assert recovered.participants[1].assistance_profile is not None
    assert recovered.participants[0].preferences[1].value == "Forbidden City"


def test_two_day_schema_matches_snapshot_and_published_schema() -> None:
    expected = json.dumps(
        CreateTwoDayTrip.model_json_schema(by_alias=True, mode="validation"),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"

    assert SCHEMA_SNAPSHOT_PATH.read_text(encoding="utf-8") == expected
    assert json.loads(PUBLISHED_SCHEMA_PATH.read_text(encoding="utf-8")) == json.loads(
        expected
    )
    schema = json.loads(expected)
    assert schema["properties"]["status"]["const"] == "DRAFT"
    assert schema["properties"]["days"]["minItems"] == 2
    assert schema["properties"]["days"]["maxItems"] == 2


@pytest.mark.parametrize(
    ("mutation", "expected_path", "expected_code"),
    [
        (lambda payload: payload.update({"days": []}), "days", "too_short"),
        (
            lambda payload: payload["days"].append(deepcopy(payload["days"][1])),
            "days",
            "too_long",
        ),
        (
            lambda payload: payload.update({"endDate": "2026-09-07"}),
            "endDate",
            "non_consecutive_dates",
        ),
        (
            lambda payload: payload["days"][0].update({"dayIndex": 1}),
            "days[0].dayIndex",
            "invalid_day_index",
        ),
        (
            lambda payload: payload["days"][1].update({"dayIndex": 2}),
            "days[1].dayIndex",
            "invalid_day_index",
        ),
        (
            lambda payload: payload["days"][0].update({"date": "2026-09-06"}),
            "days[0].date",
            "date_mismatch",
        ),
        (
            lambda payload: payload["days"][1].update({"date": "2026-09-08"}),
            "days[1].date",
            "date_mismatch",
        ),
        (
            lambda payload: payload["days"][1]["timeWindow"].update(
                {"end": "09:00:00"}
            ),
            "days[1].timeWindow.end",
            "invalid_time_window",
        ),
        (
            lambda payload: payload["days"][1].update({"dailyBudgetCents": 70001}),
            "days[1].dailyBudgetCents",
            "budget_exceeded",
        ),
        (
            lambda payload: payload["cityContext"].update({"unexpected": True}),
            "cityContext.unexpected",
            "extra_forbidden",
        ),
        (
            lambda payload: payload.update({"status": "PLANNING"}),
            "status",
            "literal_error",
        ),
    ],
    ids=[
        "too-few-days",
        "too-many-days",
        "non-consecutive-trip-dates",
        "day-zero-index-wrong",
        "day-one-index-wrong",
        "day-zero-date-misaligned",
        "day-one-date-misaligned",
        "day-one-window-invalid",
        "day-one-budget-exceeded",
        "extra-field-forbidden",
        "draft-only",
    ],
)
def test_two_day_policy_rejects_invalid_payloads(
    mutation, expected_path: str, expected_code: str
) -> None:
    payload = fixture_payload()
    mutation(payload)

    with pytest.raises(TripSchemaError) as exc_info:
        validate_two_day_trip_json(fixture_json(payload))

    errors = exc_info.value.as_dict()["errors"]
    assert errors[0]["path"] == expected_path
    assert errors[0]["code"] == expected_code


def test_two_day_policy_rejects_duplicate_day_indexes() -> None:
    payload = fixture_payload()
    payload["days"][1]["dayIndex"] = 0

    with pytest.raises(TripSchemaError) as exc_info:
        validate_two_day_trip_json(fixture_json(payload))

    errors = exc_info.value.as_dict()["errors"]
    assert {error["path"] for error in errors} == {
        "days[0].dayIndex",
        "days[1].dayIndex",
    }
    assert {error["code"] for error in errors} == {"invalid_day_index"}


def test_two_day_snapshot_store_isolated_and_survives_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "two-day.sqlite3"
    trip = validate_two_day_trip_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    repository = SqliteWorkflowRepository(database_path)

    saved = repository.save_two_day_trip_snapshot(trip)
    assert saved == trip

    with sqlite3.connect(database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        row = connection.execute(
            "SELECT trip_id, trip_json, semantic_json, saved_at "
            "FROM two_day_trip_snapshots WHERE trip_id = ?",
            (str(trip.trip_id),),
        ).fetchone()
        confirmed_count = connection.execute(
            "SELECT COUNT(*) FROM confirmed_trip_inputs"
        ).fetchone()[0]
        flow_count = connection.execute(
            "SELECT COUNT(*) FROM trip_flow_registry WHERE trip_id = ?",
            (str(trip.trip_id),),
        ).fetchone()[0]

    assert "two_day_trip_snapshots" in table_names
    assert row is not None
    assert row[0] == str(trip.trip_id)
    assert json.loads(row[1]) == json.loads(trip.model_dump_json(by_alias=True))
    assert json.loads(row[2]) == json.loads(row[1])
    assert row[3]
    assert confirmed_count == 0
    assert flow_count == 0

    reopened = SqliteWorkflowRepository(database_path)
    assert reopened.read_two_day_trip_snapshot(trip.trip_id) == trip


def test_two_day_snapshot_save_is_idempotent_and_conflicts_on_changed_content(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "two-day-idempotency.sqlite3"
    trip = validate_two_day_trip_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    repository = SqliteWorkflowRepository(database_path)

    first = repository.save_two_day_trip_snapshot(trip)
    second = repository.save_two_day_trip_snapshot(trip)
    assert second == first

    changed_payload = fixture_payload()
    changed_payload["days"][1]["endLocationText"] = "Summer Palace"
    changed = validate_two_day_trip_json(fixture_json(changed_payload))

    with pytest.raises(PlanStoreError, match="不同的两日 Trip 内容") as exc_info:
        repository.save_two_day_trip_snapshot(changed)
    assert exc_info.value.code == "TWO_DAY_TRIP_CONFLICT"

    with sqlite3.connect(database_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM two_day_trip_snapshots WHERE trip_id = ?",
            (str(trip.trip_id),),
        ).fetchone()[0]
    assert count == 1


def test_two_day_trip_stays_out_of_single_day_confirmation_and_planner_contracts() -> None:
    raw = FIXTURE_PATH.read_text(encoding="utf-8")

    with pytest.raises(TripSchemaError):
        validate_create_day_trip_json(raw)

    payload = fixture_payload()
    payload["status"] = "PLAN_REVIEW"
    with pytest.raises(ValidationError):
        PlanReviewTripSnapshot.model_validate_json(fixture_json(payload), strict=True)

    planning_request = json.loads(PLANNING_FIXTURE_PATH.read_text(encoding="utf-8"))[
        "request"
    ]
    planning_request["trip"] = fixture_payload()
    planning_request["trip"]["status"] = "PLANNING"
    with pytest.raises(ValidationError, match="one day"):
        CandidatePlanRequest.model_validate_json(
            json.dumps(planning_request),
            strict=True,
        )


def test_two_day_contract_is_a_trip_subtype_without_relaxing_single_day_shape() -> None:
    trip = validate_two_day_trip_json(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert isinstance(trip, CreateTwoDayTrip)
    assert isinstance(trip, CreateDayTrip) is False
