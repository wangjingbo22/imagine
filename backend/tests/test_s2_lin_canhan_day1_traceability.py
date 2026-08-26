from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).parents[2]
TRACE = ROOT / "docs" / "traceability" / "sprint2" / "lin_canhan_day1.json"


def _trace() -> dict[str, object]:
    return json.loads(TRACE.read_text(encoding="utf-8"))


def _all_paths(task: dict[str, object]) -> set[str]:
    paths: set[str] = set()
    for key in (
        "moduleFiles",
        "integrationFiles",
        "contractFiles",
        "ruleFiles",
        "fixtureFiles",
        "testFiles",
    ):
        paths.update(task.get(key, []))
    return paths


def test_trace_identifies_latest_main_delivery_base_and_real_implementation() -> None:
    trace = _trace()
    assert trace["owner"] == "林粲涵"
    assert trace["sprint"] == "Sprint2"
    assert trace["deliveryDay"] == "Day1"
    assert trace["verifiedAgainstMainCommit"] == (
        "3e60435fcfde0705149dbc5f340d60e1aa63103c"
    )
    assert trace["deliveryBaseCommit"] == (
        "299341928f7d3c0474328219083e821bcb026498"
    )
    assert trace["implementationCommit"] == (
        "f095e6973dced01d0f2498386e7b62779073053a"
    )
    assert re.fullmatch(r"[0-9a-f]{40}", trace["implementationCommit"])


def test_pbi_ac_tasks_and_all_evidence_paths_are_machine_resolvable() -> None:
    trace = _trace()
    assert trace["pbi"] == {
        "pbiId": "PBI-11-B",
        "acceptanceCriteriaId": "AC-11-B",
        "day1Coverage": "S2-T019_AND_S2-T020_IMPLEMENTED",
        "remainingTasks": ["S2-T021", "S2-T022"],
    }
    tasks = {task["taskId"]: task for task in trace["tasks"]}
    assert set(tasks) == {"S2-T019", "S2-T020"}
    for task in tasks.values():
        assert task["pbiId"] == "PBI-11-B"
        assert task["acceptanceCriteriaId"] == "AC-11-B"
        assert task["status"] == "IMPLEMENTED"
        for path in _all_paths(task):
            assert (ROOT / path).is_file(), path


def test_runtime_linkages_are_explicit_and_honest_about_day2_boundary() -> None:
    trace = _trace()
    links = {(item["from"], item["to"]): item for item in trace["crossTaskLinkages"]}
    assert links[("S2-T019", "S2-T020")]["status"] == (
        "EXECUTABLE_AND_TESTED"
    )
    assert links[("S2-T020", "S2-T021")]["status"] == (
        "DOWNSTREAM_PORT_ONLY_NOT_IMPLEMENTED_BY_DAY1"
    )
    assert links[("S2-T019", "S2-T023")]["status"] == (
        "FIXTURE_AND_HTTP_CONTRACT_READY_UI_NOT_IMPLEMENTED_HERE"
    )
    assert links[("S2-T020", "S1-T007")]["status"] == (
        "ISOLATED_MUST_NOT_APPEND_TO_CONFIRMED_CONSTRAINTS"
    )
    assert "no frontend component is implemented by this delivery" in (
        trace["integrationBoundaries"]
    )


def test_verification_and_required_acceptance_artifacts_are_locked() -> None:
    trace = _trace()
    verification = trace["localVerification"]
    assert verification["focusedResult"] == "19 passed"
    assert verification["backendResult"] == "193 passed"
    assert verification["frontendTest"] == "32 passed"
    assert verification["frontendBuild"] == "PASS"
    assert verification["frontendLint"] == "PASS"
    assert verification["diffCheck"] == "PASS"

    tasks = {task["taskId"]: task for task in trace["tasks"]}
    assert "backend/schemas/execution_event_draft.schema.json" in (
        tasks["S2-T019"]["contractFiles"]
    )
    assert "backend/tests/snapshots/s2_t020_visible_reasons.json" in (
        tasks["S2-T020"]["fixtureFiles"]
    )
    assert trace["productDecisionsStillNeeded"]
