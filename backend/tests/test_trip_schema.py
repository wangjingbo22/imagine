from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.schemas.trip as trip_schema
from app.schemas.trip import (
    CreateDayTrip,
    CreateSingleDayTrip,
    validate_create_day_trip_json,
    validate_trip_json,
)
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


@pytest.mark.parametrize(
    ("field_path", "mutate"),
    [
        (
            "tripId",
            lambda payload: payload.update(
                {"tripId": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"}
            ),
        ),
        (
            "participants[0].participantId",
            lambda payload: payload["participants"][0].update(
                {"participantId": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"}
            ),
        ),
    ],
    ids=["trip-id", "participant-id"],
)
def test_uuid_fields_require_uuid4(field_path: str, mutate):
    payload = load_fixture_payload()
    mutate(payload)

    with pytest.raises(TripSchemaError) as exc_info:
        validate_trip_json(json.dumps(payload, ensure_ascii=False))

    errors = exc_info.value.as_dict()["errors"]
    assert {error["path"] for error in errors} == {field_path}
    assert errors[0]["code"] == "uuid_version"


@pytest.mark.parametrize(
    ("start", "end", "expected_paths"),
    [
        (
            "09:00:00.500000",
            "10:00:00.500000",
            {"days[0].timeWindow.start", "days[0].timeWindow.end"},
        ),
        (
            "09:00:00+08:00",
            "10:00:00+08:00",
            {"days[0].timeWindow.start", "days[0].timeWindow.end"},
        ),
        ("09:00:00", "10:00:00+08:00", {"days[0].timeWindow.end"}),
    ],
    ids=["fractional", "offset", "mixed"],
)
def test_time_window_requires_naive_second_precision(
    start: str, end: str, expected_paths: set[str]
):
    payload = load_fixture_payload()
    payload["days"][0]["timeWindow"] = {"start": start, "end": end}

    with pytest.raises(TripSchemaError) as exc_info:
        validate_trip_json(json.dumps(payload, ensure_ascii=False))

    errors = exc_info.value.as_dict()["errors"]
    assert {error["path"] for error in errors} == expected_paths
    assert {error["code"] for error in errors} == {"time_format"}


def test_reverse_preference_conflict_points_to_second_item():
    payload = load_fixture_payload()
    payload["participants"][0]["preferences"] = [
        {"type": "AVOID_PLACE", "value": "abc", "weight": 1, "isHard": True},
        {"type": "MUST_VISIT", "value": "ＡＢＣ", "weight": 1, "isHard": True},
    ]

    with pytest.raises(TripSchemaError) as exc_info:
        validate_trip_json(json.dumps(payload, ensure_ascii=False))

    error = exc_info.value.as_dict()
    assert error["errors"][0]["path"] == "participants[0].preferences[1].value"
    assert error["errors"][0]["code"] == "preference_conflict"


def test_published_schema_matches_test_snapshot():
    published_path = Path(__file__).parents[1] / "schemas" / "trip.schema.json"
    assert published_path.exists()
    assert json.loads(published_path.read_text(encoding="utf-8")) == json.loads(
        SNAPSHOT_PATH.read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("fixture_name", ["group_two_participants", "group_three_participants"])
def test_group_fixtures_validate_as_distinct_create_day_trips(fixture_name: str):
    raw = fixture_path(fixture_name).read_text(encoding="utf-8")

    trip = validate_create_day_trip_json(raw)
    recovered = validate_create_day_trip_json(trip.model_dump_json(by_alias=True))

    assert isinstance(trip, CreateDayTrip)
    assert recovered == trip
    assert trip.mode.value == "GROUP"
    assert len(trip.participants) in {2, 3}
    assert len({participant.participant_id for participant in trip.participants}) == len(
        trip.participants
    )
    assert len({participant.nickname for participant in trip.participants}) == len(
        trip.participants
    )


def test_create_day_trip_schema_matches_snapshot_and_published_schema():
    snapshot_path = Path(__file__).parent / "snapshots" / "create_day_trip.schema.json"
    published_path = Path(__file__).parents[1] / "schemas" / "create-day-trip.schema.json"
    expected = json.dumps(
        CreateDayTrip.model_json_schema(by_alias=True, mode="validation"),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"

    assert snapshot_path.read_text(encoding="utf-8") == expected
    assert json.loads(published_path.read_text(encoding="utf-8")) == json.loads(expected)
    schema = json.loads(expected)
    assert schema["properties"]["status"]["const"] == "DRAFT"
    assert schema["properties"]["participants"]["maxItems"] == 3
    assert schema["properties"]["days"]["maxItems"] == 1


def test_legacy_validator_rejects_the_group_fixture():
    raw = fixture_path("group_two_participants").read_text(encoding="utf-8")

    with pytest.raises(TripSchemaError) as exc_info:
        validate_trip_json(raw)

    assert exc_info.value.as_dict()["errors"][0]["path"] == "mode"
    assert exc_info.value.as_dict()["errors"][0]["code"] == "literal_error"


@pytest.mark.parametrize(
    ("mode", "participant_count", "expected_code"),
    [
        ("SINGLE", 0, "too_short"),
        ("SINGLE", 2, "mode_participant_mismatch"),
        ("SINGLE", 3, "mode_participant_mismatch"),
        ("GROUP", 0, "too_short"),
        ("GROUP", 1, "mode_participant_mismatch"),
        ("GROUP", 4, "too_long"),
    ],
)
def test_create_day_trip_enforces_mode_and_participant_matrix(
    mode: str, participant_count: int, expected_code: str
):
    payload = json.loads(
        fixture_path("group_two_participants").read_text(encoding="utf-8")
    )
    payload["mode"] = mode
    participants = list(payload["participants"])
    while len(participants) < participant_count:
        clone = json.loads(json.dumps(participants[-1] if participants else payload["participants"][0]))
        clone["participantId"] = f"10000000-0000-4000-8000-{len(participants) + 100:012d}"
        clone["nickname"] = f"Member {len(participants) + 1}"
        participants.append(clone)
    payload["participants"] = participants[:participant_count]

    with pytest.raises(TripSchemaError) as exc_info:
        validate_create_day_trip_json(json.dumps(payload, ensure_ascii=False))

    errors = exc_info.value.as_dict()["errors"]
    assert errors[0]["path"] == "participants"
    assert errors[0]["code"] == expected_code


def test_unified_day_trip_accepts_a_valid_two_member_group():
    payload = load_fixture_payload()
    payload["mode"] = "GROUP"
    second_participant = json.loads(json.dumps(payload["participants"][0]))
    second_participant["participantId"] = "10000000-0000-4000-8000-000000000002"
    second_participant["nickname"] = "同行成员"
    second_participant["budgetCapCents"] = 15000
    second_participant["preferences"] = [
        {
            "type": "MUST_VISIT",
            "value": "故宫",
            "weight": 5,
            "isHard": True,
        }
    ]
    payload["participants"].append(second_participant)

    assert "GROUP" in {mode.value for mode in trip_schema.TripMode}
    validator = getattr(trip_schema, "validate_create_day_trip_json", None)
    assert validator is not None

    trip = validator(json.dumps(payload, ensure_ascii=False))

    assert trip.mode.value == "GROUP"
    assert len(trip.participants) == 2


def test_unified_day_trip_rejects_single_mode_with_two_members():
    payload = load_fixture_payload()
    second_participant = json.loads(json.dumps(payload["participants"][0]))
    second_participant["participantId"] = "10000000-0000-4000-8000-000000000002"
    payload["participants"].append(second_participant)

    validator = getattr(trip_schema, "validate_create_day_trip_json", None)
    assert validator is not None

    with pytest.raises(Exception):
        validator(json.dumps(payload, ensure_ascii=False))
