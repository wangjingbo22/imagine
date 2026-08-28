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
        "a43ad37a5c8b97d2b90507fa9966998bfee038b9"
    )
    assert trace["integratedWithMainCommit"] == trace["verifiedAgainstMainCommit"]
    assert trace["deliveryBaseCommit"] == (
        "a43ad37a5c8b97d2b90507fa9966998bfee038b9"
    )
    assert trace["implementationCommit"] == (
        "f376574a5c8c5c577d6ed43efd200293023b3b32"
    )
    assert trace["contractHardeningCommit"] == (
        "0856b745075156e3da5365e74852aaa192329325"
    )
    assert re.fullmatch(r"[0-9a-f]{40}", trace["implementationCommit"])
    assert re.fullmatch(r"[0-9a-f]{40}", trace["contractHardeningCommit"])


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
    assert tasks["S2-T020"]["productThresholdStatus"] == "PENDING"

    requirements_file = (
        "doc/行知旅伴_V2.3_Sprint2待办列表_含负责人_新增需求修订版.xlsx"
    )
    assert trace["requirementsSource"] == [
        {
            "file": requirements_file,
            "sheet": "SprintBacklog模板",
            "range": "A23:V24",
        },
        {
            "file": requirements_file,
            "sheet": "PBI追溯",
            "range": "A11:J11",
        },
        {
            "file": requirements_file,
            "sheet": "LLM接入设计",
            "range": "A5:K5",
        },
    ]
    assert (ROOT / requirements_file).is_file()


def test_runtime_linkages_are_explicit_and_honest_about_day2_boundary() -> None:
    trace = _trace()
    links = {(item["from"], item["to"]): item for item in trace["crossTaskLinkages"]}
    assert links[("S2-T019", "S2-T020")]["status"] == (
        "EXECUTABLE_AND_TESTED"
    )
    assert links[("S2-T020", "S2-T021")]["status"] == (
        "EXECUTABLE_AND_TESTED"
    )
    assert links[("S2-T019", "S2-T021")] == {
        "from": "S2-T019",
        "to": "S2-T021",
        "artifact": (
            "ConfirmedExecutionAdjustmentEvent.eventId plus Trip-scoped lookup"
        ),
        "status": "EXECUTABLE_AND_TESTED",
    }
    assert (
        "S2-T021 resolves eventId within the Trip and matches it to CURRENT "
        "and the inline confirmed adjustment"
    ) in trace["integrationBoundaries"]
    assert (
        "same idempotencyKey requires identical payload and UTC-normalized "
        "occurredAt"
    ) in trace["integrationBoundaries"]
    assert (
        "app/application/workflow_service.py"
        in {task["taskId"]: task for task in trace["tasks"]}["S2-T019"][
            "moduleFiles"
        ]
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
    assert verification["focusedResult"] == "24 passed"
    assert verification["backendResult"] == "528 passed"
    assert verification["frontendTest"] == "32 passed"
    assert verification["frontendBuild"] == "PASS"
    assert verification["frontendLint"] == "PASS_WITH_2_EXISTING_WARNINGS"
    assert verification["diffCheck"] == "PASS"

    tasks = {task["taskId"]: task for task in trace["tasks"]}
    assert "backend/schemas/execution_event_draft.schema.json" in (
        tasks["S2-T019"]["contractFiles"]
    )
    assert "backend/tests/snapshots/s2_t020_visible_reasons.json" in (
        tasks["S2-T020"]["fixtureFiles"]
    )
    assert trace["productDecisionsStillNeeded"]
