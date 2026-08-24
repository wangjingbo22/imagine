from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.assistance import PROFILE_FACTORIES, create_assistance_profile
from app.schemas.trip import AssistanceProfile, AssistanceType, CreateSingleDayTrip
from app.schemas.trip import validate_trip_json
from app.schemas.validation_error import TripSchemaError


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "assistance_profiles"
PROFILE_CASES = (
    ("ordinary", AssistanceType.ORDINARY),
    ("parent_child", AssistanceType.PARENT_CHILD),
    ("low_stamina", AssistanceType.LOW_STAMINA),
    ("mobility_assistance_beta", AssistanceType.MOBILITY_ASSISTANCE_BETA),
)
SERIALIZED_PROFILE_FIELDS = {
    "type",
    "childAge",
    "walkLimits",
    "maxTransfers",
    "restInterval",
    "napWindow",
    "avoidStairs",
}
EXPECTED_PROFILE_PAYLOADS = {
    AssistanceType.ORDINARY: {
        "type": "ORDINARY",
        "childAge": None,
        "walkLimits": {
            "maxContinuousMeters": None,
            "maxDailyMeters": None,
        },
        "maxTransfers": None,
        "restInterval": None,
        "napWindow": None,
        "avoidStairs": False,
    },
    AssistanceType.PARENT_CHILD: {
        "type": "PARENT_CHILD",
        "childAge": None,
        "walkLimits": {
            "maxContinuousMeters": None,
            "maxDailyMeters": None,
        },
        "maxTransfers": None,
        "restInterval": None,
        "napWindow": {"start": "13:00:00", "end": "14:00:00"},
        "avoidStairs": False,
    },
    AssistanceType.LOW_STAMINA: {
        "type": "LOW_STAMINA",
        "childAge": None,
        "walkLimits": {
            "maxContinuousMeters": 500,
            "maxDailyMeters": None,
        },
        "maxTransfers": 2,
        "restInterval": 90,
        "napWindow": None,
        "avoidStairs": False,
    },
    AssistanceType.MOBILITY_ASSISTANCE_BETA: {
        "type": "MOBILITY_ASSISTANCE_BETA",
        "childAge": None,
        "walkLimits": {
            "maxContinuousMeters": None,
            "maxDailyMeters": None,
        },
        "maxTransfers": None,
        "restInterval": None,
        "napWindow": None,
        "avoidStairs": True,
    },
}


def fixture_path(name: str) -> Path:
    return FIXTURE_DIR / f"{name}.json"


@pytest.mark.parametrize(("fixture_name", "profile_type"), PROFILE_CASES)
def test_four_complete_profile_fixtures_validate_and_round_trip(
    fixture_name: str,
    profile_type: AssistanceType,
):
    trip = validate_trip_json(fixture_path(fixture_name).read_text(encoding="utf-8"))
    recovered = validate_trip_json(trip.model_dump_json(by_alias=True))

    assert isinstance(trip, CreateSingleDayTrip)
    assert recovered == trip
    assert recovered.status == "DRAFT"
    assert len(recovered.participants) == 1

    profile = recovered.participants[0].assistance_profile
    assert isinstance(profile, AssistanceProfile)
    assert profile.type is profile_type
    assert profile == create_assistance_profile(profile_type)

    serialized_trip = json.loads(recovered.model_dump_json(by_alias=True))
    serialized_profile = serialized_trip["participants"][0]["assistanceProfile"]
    assert set(serialized_profile) == SERIALIZED_PROFILE_FIELDS
    assert serialized_profile == EXPECTED_PROFILE_PAYLOADS[profile_type]
    assert "childAge" in serialized_profile
    assert "napWindow" in serialized_profile


def test_all_four_presets_are_registered_as_fresh_factories():
    assert set(PROFILE_FACTORIES) == set(AssistanceType)

    for profile_type in AssistanceType:
        first = create_assistance_profile(profile_type)
        second = create_assistance_profile(profile_type)

        assert first == second
        assert first is not second
        assert first.type is profile_type
        assert set(first.model_dump(mode="json", by_alias=True)) == (
            SERIALIZED_PROFILE_FIELDS
        )


def test_assistance_profile_schema_uses_public_aliases_and_draft_trip_guard():
    schema = CreateSingleDayTrip.model_json_schema(
        by_alias=True,
        mode="validation",
    )
    profile_schema = schema["$defs"]["AssistanceProfile"]

    assert set(profile_schema["properties"]) == SERIALIZED_PROFILE_FIELDS
    assert set(profile_schema["required"]) == SERIALIZED_PROFILE_FIELDS
    assert schema["properties"]["status"]["const"] == "DRAFT"
    assert schema["properties"]["participants"]["minItems"] == 1
    assert schema["properties"]["participants"]["maxItems"] == 1


@pytest.mark.parametrize(
    ("mutation", "expected_path", "expected_code"),
    [
        (
            lambda profile: profile.pop("walkLimits"),
            "participants[0].assistanceProfile.walkLimits",
            "missing",
        ),
        (
            lambda profile: profile.pop("avoidStairs"),
            "participants[0].assistanceProfile.avoidStairs",
            "missing",
        ),
        (
            lambda profile: profile.update({"maxTransfers": "2"}),
            "participants[0].assistanceProfile.maxTransfers",
            "int_type",
        ),
        (
            lambda profile: profile.update({"unregisteredCareFlag": True}),
            "participants[0].assistanceProfile.unregisteredCareFlag",
            "extra_forbidden",
        ),
        (
            lambda profile: profile["napWindow"].update({"end": "13:00:00"}),
            "participants[0].assistanceProfile.napWindow.end",
            "invalid_nap_window",
        ),
        (
            lambda profile: profile["napWindow"].update(
                {"start": "13:00:00.500000"}
            ),
            "participants[0].assistanceProfile.napWindow.start",
            "time_format",
        ),
    ],
    ids=[
        "missing-walk-limits",
        "missing-avoid-stairs",
        "strict-integer",
        "unknown-field",
        "invalid-nap-window",
        "nap-window-second-precision",
    ],
)
def test_invalid_profile_field_stops_trip_validation(
    mutation,
    expected_path: str,
    expected_code: str,
):
    payload = json.loads(fixture_path("parent_child").read_text(encoding="utf-8"))
    mutation(payload["participants"][0]["assistanceProfile"])

    with pytest.raises(TripSchemaError) as exc_info:
        validate_trip_json(json.dumps(payload, ensure_ascii=False))

    issue = exc_info.value.as_dict()["errors"][0]
    assert issue["path"] == expected_path
    assert issue["code"] == expected_code
