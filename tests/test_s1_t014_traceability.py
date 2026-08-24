"""Machine-readable traceability for the S1-T014 snapshot contract."""

from __future__ import annotations

import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TRACE_JSON = REPOSITORY_ROOT / "docs/traceability/sprint1/chen_ziyuan_s1_t014.json"
TRACE_MARKDOWN = REPOSITORY_ROOT / "docs/traceability/sprint1/chen_ziyuan_s1_t014.md"


def test_s1_t014_traceability_contract_is_complete_and_points_to_real_evidence() -> None:
    """The published T014 record identifies scope, evidence, and deferred work."""
    assert TRACE_JSON.is_file(), "T014 machine-readable traceability record is missing"
    assert TRACE_MARKDOWN.is_file(), "T014 human-readable traceability record is missing"

    trace = json.loads(TRACE_JSON.read_text(encoding="utf-8"))

    assert {
        "schemaVersion": "1.0",
        "taskId": "S1-T014",
        "pbiId": "PBI-04-B",
        "acId": "AC-04-B",
        "owner": "陈梓元",
        "status": "IMPLEMENTED",
        "baseline": "512a9b2897a3c9f00c13722306412b2db7b7eb06",
    }.items() <= trace.items()
    assert trace["dependsOn"] == ["S1-T013"]
    assert trace["consumedBy"] == ["S1-T017"]
    assert set(trace["codeFiles"]) == {
        "backend/app/schemas/__init__.py",
        "backend/app/schemas/plan.py",
        "backend/app/schemas/trip.py",
        "backend/app/schemas/validation_error.py",
    }
    assert set(trace["contractFiles"]) == {
        ".agent/api_contracts.md",
        "docs/superpowers/specs/2026-08-24-s1-t014-plan-snapshot-contract-design.md",
        "docs/superpowers/plans/2026-08-24-s1-t014-plan-snapshot-contract.md",
    }
    assert set(trace["testFiles"]) == {
        "tests/test_plan_versions.py",
        "tests/test_plan_v2_diff.py",
        "tests/test_s1_t014_traceability.py",
    }

    cases = {case["id"]: case for case in trace["acceptanceCases"]}
    expected_v1_public_errors = {
        "v1_multiple_participants": {"path": "tripSnapshot.participants", "code": "too_long"},
        "v1_multiple_days": {"path": "tripSnapshot.days", "code": "too_long"},
        "v1_date_mismatch": {"path": "tripSnapshot.endDate", "code": "date_mismatch"},
        "v1_day_date_mismatch": {"path": "tripSnapshot.days[0].date", "code": "date_mismatch"},
        "v1_invalid_day_index": {"path": "tripSnapshot.days[0].dayIndex", "code": "invalid_day_index"},
        "v1_equal_time_window": {"path": "tripSnapshot.days[0].timeWindow.end", "code": "invalid_time_window"},
        "v1_reversed_time_window": {"path": "tripSnapshot.days[0].timeWindow.end", "code": "invalid_time_window"},
        "v1_daily_budget_exceeded": {"path": "tripSnapshot.days[0].dailyBudgetCents", "code": "budget_exceeded"},
        "v1_preference_hardness_mismatch": {"path": "tripSnapshot.participants[0].preferences[0].isHard", "code": "invalid_preference_hardness"},
        "v1_preference_conflict": {"path": "tripSnapshot.participants[0].preferences[1].value", "code": "preference_conflict"},
    }
    expected_v2_public_errors = {
        "v2_multiple_participants_preserves_current": {"path": "tripSnapshot.participants", "code": "too_long"},
        "v2_invalid_preference_hardness_preserves_current": {
            "path": "tripSnapshot.participants[0].preferences[0].isHard",
            "code": "invalid_preference_hardness",
        },
    }
    assert {case_id for case_id in cases if case_id.startswith("v1_")} == set(expected_v1_public_errors)
    assert {case_id for case_id in cases if case_id.startswith("v2_")} == set(expected_v2_public_errors)
    for case_id, expected_public_error in expected_v1_public_errors.items():
        assert cases[case_id]["publicError"] == expected_public_error
        assert cases[case_id]["noPersistence"] is True
    for case_id, expected_public_error in expected_v2_public_errors.items():
        assert cases[case_id]["publicError"] == expected_public_error
        assert cases[case_id]["preservesFullCurrent"] is True
    assert cases["enum_preservation"]["preservesEnums"] is True
    assert cases["valid_v1_v2_regression"]["regression"] is True
    assert trace["implementationCommit"] == "9f11d8a"

    non_goals = " ".join(trace["nonGoals"])
    for required_text in (
        "state-transition",
        "SQLite",
        "T011",
        "T015",
        "T016",
        "T017",
        "T018",
        "server-side recomputation",
        "HARD PASS",
    ):
        assert required_text in non_goals

    assert trace["externalEvidence"] == {
        "pullRequest": None,
        "ciBuild": None,
        "qaSignOff": None,
        "poAcceptance": None,
    }
    for relative_path in (
        *trace["codeFiles"],
        *trace["contractFiles"],
        *trace["testFiles"],
    ):
        assert (REPOSITORY_ROOT / relative_path).is_file(), relative_path

    markdown = TRACE_MARKDOWN.read_text(encoding="utf-8")
    for required_text in (
        "PBI-04-B",
        "AC-04-B",
        "S1-T014",
        "S1-T013",
        "S1-T017",
        "PLAN_REVIEW",
        "TRIP_SCHEMA_INVALID",
        "not available",
    ):
        assert required_text in markdown
