from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.trip import CreateSingleDayTrip, validate_trip_json
from app.schemas.validation_error import TripSchemaError, ValidationIssue


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trips"
SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "create_single_day_trip.schema.json"
EXPECTED_CITY_CODES = {
    "beijing": "110000",
    "shanghai": "310000",
    "chengdu": "510100",
}


def fixture_path(name: str) -> Path:
    return FIXTURE_DIR / f"{name}.json"


@pytest.mark.parametrize("fixture_name", ["beijing", "shanghai", "chengdu"])
def test_three_city_fixtures_validate_and_round_trip(fixture_name: str):
    raw = fixture_path(fixture_name).read_text(encoding="utf-8")

    trip = validate_trip_json(raw)
    recovered = validate_trip_json(trip.model_dump_json(by_alias=True))

    assert isinstance(trip, CreateSingleDayTrip)
    assert recovered == trip
    assert recovered.city_context.city_code == EXPECTED_CITY_CODES[fixture_name]
    assert len(recovered.participants) == 1
    assert len(recovered.days) == 1
    assert recovered.participants[0].participant_id == trip.participants[0].participant_id
    assert recovered.days[0].date == trip.days[0].date


def test_missing_nested_field_reports_alias_path():
    payload = json.loads(fixture_path("beijing").read_text(encoding="utf-8"))
    del payload["days"][0]["timeWindow"]["end"]

    with pytest.raises(TripSchemaError) as exc_info:
        validate_trip_json(json.dumps(payload, ensure_ascii=False))

    error = exc_info.value.as_dict()
    assert error["errors"][0]["path"] == "days[0].timeWindow.end"
    assert error["errors"][0]["code"] == "missing"


def test_unknown_field_is_rejected():
    payload = json.loads(fixture_path("beijing").read_text(encoding="utf-8"))
    payload["cityContext"]["beijingFallback"] = True

    with pytest.raises(TripSchemaError) as exc_info:
        validate_trip_json(json.dumps(payload, ensure_ascii=False))

    error = exc_info.value.as_dict()
    assert error["errors"][0]["path"] == "cityContext.beijingFallback"
    assert error["errors"][0]["code"] == "extra_forbidden"


def load_fixture_payload(name: str = "beijing") -> dict[str, object]:
    return json.loads(fixture_path(name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mutation", "expected_path", "expected_code"),
    [
        (
            lambda payload: payload.update({"endDate": "2026-09-06"}),
            "endDate",
            "date_mismatch",
        ),
        (
            lambda payload: payload["days"][0].update({"date": "2026-09-06"}),
            "days[0].date",
            "date_mismatch",
        ),
        (
            lambda payload: payload["days"][0].update({"dayIndex": 1}),
            "days[0].dayIndex",
            "invalid_day_index",
        ),
        (
            lambda payload: payload["days"][0]["timeWindow"].update(
                {"end": "08:00:00"}
            ),
            "days[0].timeWindow.end",
            "invalid_time_window",
        ),
        (
            lambda payload: payload["days"][0].update({"dailyBudgetCents": 36000}),
            "days[0].dailyBudgetCents",
            "budget_exceeded",
        ),
        (
            lambda payload: payload["participants"][0]["preferences"][0].update(
                {"isHard": True}
            ),
            "participants[0].preferences[0].isHard",
            "invalid_preference_hardness",
        ),
    ],
    ids=[
        "trip-end-date",
        "day-date",
        "day-index",
        "time-window",
        "budget",
        "preference-hardness",
    ],
)
def test_single_day_policy_reports_field_level_issue(
    mutation, expected_path: str, expected_code: str
):
    payload = load_fixture_payload()
    mutation(payload)

    with pytest.raises(TripSchemaError) as exc_info:
        validate_trip_json(json.dumps(payload, ensure_ascii=False))

    error = exc_info.value.as_dict()
    assert error["errors"][0]["path"] == expected_path
    assert error["errors"][0]["code"] == expected_code


def test_must_visit_and_avoid_place_conflict_after_normalization():
    payload = load_fixture_payload()
    payload["participants"][0]["preferences"].extend(
        [
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
    )

    with pytest.raises(TripSchemaError) as exc_info:
        validate_trip_json(json.dumps(payload, ensure_ascii=False))

    error = exc_info.value.as_dict()
    assert error["errors"][0]["path"] == "participants[0].preferences[3].value"
    assert error["errors"][0]["code"] == "preference_conflict"


def test_create_single_day_trip_schema_matches_snapshot():
    expected = json.dumps(
        CreateSingleDayTrip.model_json_schema(by_alias=True, mode="validation"),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"

    assert SNAPSHOT_PATH.exists()
    assert SNAPSHOT_PATH.read_text(encoding="utf-8") == expected

    schema = json.loads(expected)
    assert {
        "schemaVersion",
        "cityContext",
        "participants",
        "days",
    }.issubset(schema["properties"])


@pytest.mark.parametrize(
    ("mutation", "expected_path", "expected_code"),
    [
        (
            lambda payload: payload.update({"participants": []}),
            "participants",
            "too_short",
        ),
        (
            lambda payload: payload.update({"days": []}),
            "days",
            "too_short",
        ),
        (
            lambda payload: payload["participants"].append(
                dict(payload["participants"][0])
            ),
            "participants",
            "too_long",
        ),
        (
            lambda payload: payload.update({"mode": "GROUP"}),
            "mode",
            "literal_error",
        ),
        (
            lambda payload: payload.update({"status": "PLANNING"}),
            "status",
            "literal_error",
        ),
    ],
    ids=["empty-participants", "empty-days", "two-participants", "bad-mode", "bad-status"],
)
def test_single_day_structural_constraints_report_field_level_issue(
    mutation, expected_path: str, expected_code: str
):
    payload = load_fixture_payload()
    mutation(payload)

    with pytest.raises(TripSchemaError) as exc_info:
        validate_trip_json(json.dumps(payload, ensure_ascii=False))

    error = exc_info.value.as_dict()
    assert error["errors"][0]["path"] == expected_path
    assert error["errors"][0]["code"] == expected_code


def test_confirmation_error_envelope_preserves_reference_date_and_candidates():
    error = TripSchemaError(
        [
            ValidationIssue(
                path="days[0].date",
                code="ambiguous_value",
                message="需要确认具体日期",
                context={"referenceDate": "2026-08-24"},
                candidates=["2026-08-29", "2026-09-05"],
            )
        ],
        code="TRIP_CONFIRMATION_REQUIRED",
    ).as_dict()

    assert error == {
        "code": "TRIP_CONFIRMATION_REQUIRED",
        "schemaVersion": "1.0",
        "errors": [
            {
                "path": "days[0].date",
                "code": "ambiguous_value",
                "message": "需要确认具体日期",
                "context": {"referenceDate": "2026-08-24"},
                "candidates": ["2026-08-29", "2026-09-05"],
            }
        ],
    }
