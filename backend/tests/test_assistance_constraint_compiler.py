from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

import pytest

from app.schemas.assistance import (
    create_assistance_profile,
    low_stamina_profile,
    ordinary_profile,
    parent_child_profile,
)
from app.schemas.trip import AssistanceProfile, AssistanceType
from app.services.assistance_constraints import (
    AssistanceConstraintCompileError,
    DeterministicAssistanceConstraintCompiler,
)


EXPECTED = {
    AssistanceType.ORDINARY: [],
    AssistanceType.PARENT_CHILD: [
        {
            "field": "napWindow",
            "operator": "BLOCK",
            "value": {"start": "13:00:00", "end": "14:00:00"},
            "scope": "DAY",
            "hardness": "HARD",
        },
        {
            "field": "return",
            "operator": "ARRIVE_BY",
            "value": {
                "endLocationPath": "days[0].endLocationText",
                "deadlinePath": "days[0].timeWindow.end",
            },
            "scope": "DAY",
            "hardness": "HARD",
        },
    ],
    AssistanceType.LOW_STAMINA: [
        {
            "field": "walkLimits.maxContinuousMeters",
            "operator": "LTE",
            "value": 500,
            "scope": "ROUTE_SEGMENT",
            "hardness": "HARD",
        },
        {
            "field": "maxTransfers",
            "operator": "LTE",
            "value": 2,
            "scope": "ROUTE",
            "hardness": "HARD",
        },
        {
            "field": "restInterval",
            "operator": "LTE",
            "value": 90,
            "scope": "ROUTE",
            "hardness": "HARD",
        },
    ],
    AssistanceType.MOBILITY_ASSISTANCE_BETA: [
        {
            "field": "avoidStairs",
            "operator": "EQ",
            "value": True,
            "scope": "ROUTE_SEGMENT",
            "hardness": "HARD",
        }
    ],
}

SNAPSHOT_PATH = (
    Path(__file__).parent / "snapshots" / "assistance_constraints.json"
)


def dumped(compiler, profile: AssistanceProfile) -> list[dict[str, Any]]:
    return [
        item.model_dump(mode="json", by_alias=True)
        for item in compiler.compile(profile)
    ]


@pytest.mark.parametrize("profile_type", list(AssistanceType))
def test_four_profiles_compile_to_exact_repeatable_constraints(profile_type):
    compiler = DeterministicAssistanceConstraintCompiler()
    profile = create_assistance_profile(profile_type)

    first = compiler.compile(profile)
    second = compiler.compile(profile)

    assert dumped(compiler, profile) == EXPECTED[profile_type]
    assert first == second
    assert json.dumps(
        [item.model_dump(mode="json", by_alias=True) for item in first],
        ensure_ascii=False,
        separators=(",", ":"),
    ) == json.dumps(
        [item.model_dump(mode="json", by_alias=True) for item in second],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert all(left is not right for left, right in zip(first, second))


def test_all_optional_rules_follow_one_canonical_order():
    compiler = DeterministicAssistanceConstraintCompiler()
    profile = parent_child_profile()
    profile.walk_limits.max_continuous_meters = 500
    profile.walk_limits.max_daily_meters = 2_000
    profile.max_transfers = 2
    profile.rest_interval = 90
    profile.avoid_stairs = True

    assert [item.field for item in compiler.compile(profile)] == [
        "walkLimits.maxContinuousMeters",
        "walkLimits.maxDailyMeters",
        "maxTransfers",
        "restInterval",
        "napWindow",
        "return",
        "avoidStairs",
    ]


def test_null_and_false_sources_emit_no_constraint_or_null_value():
    compiler = DeterministicAssistanceConstraintCompiler()

    assert compiler.compile(ordinary_profile()) == ()
    for profile_type in AssistanceType:
        payload = json.dumps(
            dumped(compiler, create_assistance_profile(profile_type)),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        assert "null" not in payload


@pytest.mark.parametrize(
    ("mutation", "expected_path", "expected_code"),
    [
        (
            lambda profile: setattr(profile, "max_transfers", "2"),
            "maxTransfers",
            "int_type",
        ),
        (
            lambda profile: setattr(
                profile.walk_limits,
                "max_continuous_meters",
                0,
            ),
            "walkLimits.maxContinuousMeters",
            "greater_than_equal",
        ),
    ],
    ids=["wrong-type", "out-of-range"],
)
def test_mutated_profile_fails_closed_with_field_issue(
    mutation: Callable[[AssistanceProfile], None],
    expected_path: str,
    expected_code: str,
):
    compiler = DeterministicAssistanceConstraintCompiler()
    profile = low_stamina_profile()
    mutation(profile)

    with pytest.raises(AssistanceConstraintCompileError) as exc_info:
        compiler.compile(profile)

    error = exc_info.value.as_dict()
    assert error["code"] == "ASSISTANCE_PROFILE_INVALID"
    assert error["errors"][0]["path"] == expected_path
    assert error["errors"][0]["code"] == expected_code


@pytest.mark.parametrize("profile_type", list(AssistanceType))
def test_profile_output_matches_reviewed_snapshot(profile_type):
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    compiler = DeterministicAssistanceConstraintCompiler()

    assert dumped(
        compiler,
        create_assistance_profile(profile_type),
    ) == expected[profile_type.value]
