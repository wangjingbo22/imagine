from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).parents[2]
TRACE = ROOT / "docs" / "traceability" / "sprint2" / "lin_canhan_day1.json"
LATEST_MAIN_COMMIT = "012fa364894ffc7dd36a6dd91cdd21641550da06"
DELIVERY_BASE_COMMIT = "a43ad37a5c8b97d2b90507fa9966998bfee038b9"
IMPLEMENTATION_COMMIT = "f376574a5c8c5c577d6ed43efd200293023b3b32"
CONTRACT_HARDENING_COMMIT = "0856b745075156e3da5365e74852aaa192329325"
CLOSURE_COMMIT = "1a7fcf7169f3e3656507be878e896bf4db1dd9fd"


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
    assert trace["verifiedAgainstMainCommit"] == LATEST_MAIN_COMMIT
    assert trace["integratedWithMainCommit"] == trace["verifiedAgainstMainCommit"]
    assert trace["deliveryBaseCommit"] == DELIVERY_BASE_COMMIT
    assert trace["implementationCommit"] == IMPLEMENTATION_COMMIT
    assert trace["contractHardeningCommit"] == CONTRACT_HARDENING_COMMIT
    assert trace["compatibilityClosureCommit"] == CLOSURE_COMMIT
    assert re.fullmatch(r"[0-9a-f]{40}", trace["implementationCommit"])
    assert re.fullmatch(r"[0-9a-f]{40}", trace["contractHardeningCommit"])
    for commit in (
        LATEST_MAIN_COMMIT,
        DELIVERY_BASE_COMMIT,
        IMPLEMENTATION_COMMIT,
        CONTRACT_HARDENING_COMMIT,
        CLOSURE_COMMIT,
    ):
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    for ancestor in (DELIVERY_BASE_COMMIT, IMPLEMENTATION_COMMIT, CONTRACT_HARDENING_COMMIT):
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, LATEST_MAIN_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )


def test_pbi_ac_tasks_and_all_evidence_paths_are_machine_resolvable() -> None:
    trace = _trace()
    assert trace["pbi"] == {
        "pbiId": "PBI-11-B",
        "acceptanceCriteriaId": "AC-11-B",
        "day1Coverage": "S2-T019_AND_S2-T020_IMPLEMENTED",
        "outsideDay1TasksNowDelivered": ["S2-T021", "S2-T022"],
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
    assert verification["status"] == "LATEST_MAIN_FULL_REGRESSION_PASS"
    assert verification["latestMainCommit"] == LATEST_MAIN_COMMIT
    assert verification["latestMainTraceResult"] == "4 passed"
    assert verification["historicalBaselineCommit"] == DELIVERY_BASE_COMMIT
    assert verification["historicalFocusedResult"] == "24 passed"
    assert verification["historicalBackendResult"] == "528 passed"
    assert verification["historicalFrontendTest"] == "32 passed"
    assert verification["historicalFrontendBuild"] == "PASS"
    assert verification["historicalFrontendLint"] == (
        "PASS_WITH_2_EXISTING_WARNINGS"
    )
    assert verification["historicalDiffCheck"] == "PASS"
    assert verification["latestMainClosureCommit"] == CLOSURE_COMMIT
    assert verification["latestMainBackendResult"] == "633 passed in 78.57s"
    assert verification["latestMainFrontendTest"] == "52 passed"
    assert verification["latestMainFrontendBuild"] == "PASS"
    assert verification["latestMainFrontendLint"] == (
        "PASS_WITH_2_EXISTING_WARNINGS"
    )
    assert verification["latestMainDiffCheck"] == "PASS"
    assert verification["latestMainFunctionalRegression"] == "PASS"

    tasks = {task["taskId"]: task for task in trace["tasks"]}
    assert "backend/schemas/execution_event_draft.schema.json" in (
        tasks["S2-T019"]["contractFiles"]
    )
    assert "backend/tests/snapshots/s2_t020_visible_reasons.json" in (
        tasks["S2-T020"]["fixtureFiles"]
    )
    assert trace["productDecisionsStillNeeded"]
    external = trace["externalAcceptanceStillNeeded"]
    assert any("S2-T023" in item for item in external)
    assert any("BAILIAN_API_KEY" in item for item in external)
    assert any("public end-to-end" in item for item in external)
