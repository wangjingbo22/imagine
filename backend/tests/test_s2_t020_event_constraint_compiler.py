from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.execution_adjustment import ExecutionConstraintCompileRequest
from app.services.execution_adjustments import (
    ExecutionConstraintCompileError,
    compile_execution_constraints,
)
from app.schemas.trip import AssistanceProfile


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "execution_adjustments"
    / "s2_t020_boundary_cases.json"
)
REASON_SNAPSHOT = (
    Path(__file__).parent / "snapshots" / "s2_t020_visible_reasons.json"
)


def _request(case: dict[str, object]) -> ExecutionConstraintCompileRequest:
    return ExecutionConstraintCompileRequest.model_validate_json(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "event": case["event"],
                "currentConstraints": case["currentConstraints"],
            }
        ),
        strict=True,
    )


def test_boundary_fixture_outputs_only_relevant_tightening_constraints() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for case in cases:
        result = compile_execution_constraints(_request(case))
        values = {item.field: item.value for item in result.constraints}
        assert values == case["expected"], case["name"]
        assert all(item.scope == "REMAINING_ITINERARY" for item in result.constraints)
        assert all(item.hardness == "HARD" for item in result.constraints)
        if case["event"]["eventType"] == "LATE":
            assert set(values) == {"remaining.timeBudgetMinutes"}
        else:
            assert "remaining.timeBudgetMinutes" not in values


def test_same_input_has_same_output_and_visible_reason_snapshot() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snapshots = json.loads(REASON_SNAPSHOT.read_text(encoding="utf-8"))
    selected = {
        "late_twenty": "late",
        "fatigue_mild": "fatigueMild",
        "fatigue_moderate": "fatigueModerate",
    }
    for case in cases:
        request = _request(case)
        first = compile_execution_constraints(request)
        second = compile_execution_constraints(request)
        assert first == second
        assert first.input_digest == second.input_digest
        snapshot_key = selected.get(case["name"])
        if snapshot_key:
            assert first.reasons[0].message == snapshots[snapshot_key]

    severe_case = next(case for case in cases if case["name"] == "fatigue_moderate")
    severe_case = json.loads(json.dumps(severe_case))
    severe_case["event"]["fatigueLevel"] = "SEVERE"
    severe_case["currentConstraints"] = {
        "remainingWalkBudgetMeters": 5000,
        "maxSegmentWalkMeters": 1200,
        "restIntervalMinutes": 90,
    }
    severe = compile_execution_constraints(_request(severe_case))
    assert severe.reasons[0].message == snapshots["fatigueSevere"]


def test_compile_never_mutates_long_term_profile_or_plan_state() -> None:
    profile = AssistanceProfile.model_validate_json(
        json.dumps({
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
        }),
        strict=True,
    )
    before = profile.model_dump_json(by_alias=True)
    case = json.loads(FIXTURE.read_text(encoding="utf-8"))[3]
    result = compile_execution_constraints(_request(case))

    assert profile.model_dump_json(by_alias=True) == before
    serialized = result.model_dump_json(by_alias=True)
    assert "assistanceProfile" not in serialized
    assert "planVersion" not in serialized
    assert "CURRENT" not in serialized


def test_irrelevant_context_and_unconfirmed_event_are_rejected() -> None:
    with pytest.raises(ValueError, match="LATE cannot carry walking"):
        ExecutionConstraintCompileRequest.model_validate_json(
            json.dumps({
                "event": {
                    "confirmationStatus": "CONFIRMED",
                    "eventType": "LATE",
                    "taskId": "task-2",
                    "lateMinutes": 20,
                    "fatigueLevel": None,
                },
                "currentConstraints": {
                    "remainingTimeMinutes": 100,
                    "remainingWalkBudgetMeters": 1000,
                },
            }),
            strict=True,
        )

    with pytest.raises(ValueError):
        ExecutionConstraintCompileRequest.model_validate_json(
            json.dumps({
                "event": {
                    "confirmationStatus": "DRAFT",
                    "eventType": "LATE",
                    "taskId": "task-2",
                    "lateMinutes": 20,
                    "fatigueLevel": None,
                },
                "currentConstraints": {"remainingTimeMinutes": 100},
            }),
            strict=True,
        )


def test_mutated_validated_model_is_revalidated_at_compiler_boundary() -> None:
    case = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
    request = _request(case)
    request.event.late_minutes = -1

    with pytest.raises(ExecutionConstraintCompileError):
        compile_execution_constraints(request)
