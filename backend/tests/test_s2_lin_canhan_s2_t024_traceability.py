from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[2]
TRACE = (
    ROOT
    / "docs"
    / "traceability"
    / "sprint2"
    / "lin_canhan_s2_t024_day3.json"
)


def _trace() -> dict[str, object]:
    return json.loads(TRACE.read_text(encoding="utf-8"))


def test_t024_trace_locks_owner_pbi_ac_uat_and_requirement_ranges() -> None:
    trace = _trace()
    assert trace["schemaVersion"] == "1.0"
    assert trace["sprint"] == "Sprint2"
    assert trace["deliveryDay"] == "Day3"
    assert trace["owner"] == "林粲涵"
    assert trace["pbi"]["pbiId"] == "PBI-13-A"
    assert trace["pbi"]["acceptanceCriteriaId"] == "AC-13-A"
    assert trace["task"]["taskId"] == "S2-T024"
    assert trace["uat"]["uatId"] == "UAT-S2-012"
    assert trace["uat"]["evidenceId"] == "RESP-S2-001"

    source = "doc/行知旅伴_V2.3_Sprint2待办列表_含负责人_新增需求修订版.xlsx"
    assert (ROOT / source).is_file()
    assert {
        (item["sheet"], item["range"], item["file"])
        for item in trace["requirementsSource"]
    } == {
        ("SprintBacklog模板", "A28:V28", source),
        ("PBI追溯", "A13:J13", source),
        ("用户功能验收清单", "A15:J15", source),
        ("版权说明", "A10:B14", source),
        ("LLM接入设计", "A10:K10", source),
    }


def test_t024_is_explicitly_separate_from_t032() -> None:
    boundary = _trace()["scopeBoundary"]
    assert boundary["includedTask"] == "S2-T024"
    assert boundary["includedPbi"] == "PBI-13-A"
    assert boundary["excludedTask"] == "S2-T032"
    assert boundary["excludedPbi"] == "PBI-17-A"
    assert boundary["excludedUat"] == "UAT-S2-E2E-001"
    assert _trace()["knownGaps"]["t032"] == "EXCLUDED_SEPARATE_TASK_NOT_CLAIMED"


def test_t024_committed_trace_documents_and_dependency_evidence_resolve() -> None:
    task = _trace()["task"]
    assert task["owner"] == "林粲涵"
    assert task["deliveryDay"] == "Day3"
    assert task["priority"] == "Must"
    assert task["storyPoints"] == 3
    assert task["remainingHours"] == 2
    assert task["dependsOn"] == "S2-T001~S2-T023"
    for key in (
        "documentationFiles",
        "testFiles",
        "moduleFiles",
        "integrationFiles",
        "dependencyEvidenceFiles",
    ):
        for path in task[key]:
            assert (ROOT / path).is_file(), path


def test_t024_planned_files_are_frozen_and_implemented_for_local_acceptance() -> None:
    planned = {item["path"]: item for item in _trace()["plannedFiles"]}
    assert set(planned) == {
        "frontend/playwright.config.ts",
        "frontend/e2e/s2-t024-responsive.spec.ts",
        "frontend/tests/s2T024ResponsiveContract.test.ts",
        "frontend/src/services/s2T024Acceptance.ts",
    }
    for path, item in planned.items():
        assert item["status"] == "IMPLEMENTED"
        assert (ROOT / path).is_file(), path


def test_t024_uat_contract_keeps_both_viewports_and_accessibility_gates() -> None:
    uat = _trace()["uat"]
    assert [(item["width"], item["height"]) for item in uat["viewports"]] == [
        (375, 812),
        (768, 1024),
    ]
    assert set(uat["requirements"]) == {
        "NO_HORIZONTAL_SCROLL",
        "NO_TEXT_OR_CONTROL_OVERLAP",
        "PRIMARY_ACTION_MIN_44_PX",
        "STATUS_PERMISSION_AND_FAILURE_VISIBLE",
        "KEY_AMOUNTS_TIMES_AND_DIFF_READABLE",
        "KEYBOARD_FOCUS_ORDER_VISIBLE",
        "REDUCED_MOTION_SUPPORTED",
    }
    assert _trace()["task"]["journeyPhases"] == [
        "SIX_QUESTION_CONFIRMATION",
        "UNIQUE_RECOMMENDATION",
        "EXECUTION_AND_GPS",
        "TASK_PHOTO",
        "LATE_OR_FATIGUE_V2",
        "ORGANIZER_DECISION",
        "MEMORY_TIMELINE",
    ]


def test_t024_cross_task_linkages_are_resolvable_and_end_at_pbi_13_a() -> None:
    links = {
        (item["from"], item["to"]): item
        for item in _trace()["crossTaskLinkages"]
    }
    assert set(links) == {
        ("S2-T001~S2-T005", "S2-T024"),
        ("S2-T006~S2-T010", "S2-T024"),
        ("S2-T011~S2-T016", "S2-T024"),
        ("S2-T017~S2-T018", "S2-T024"),
        ("S2-T019~S2-T023", "S2-T024"),
        ("S2-T024", "PBI-13-A"),
    }
    for link in links.values():
        for path in link["evidenceFiles"]:
            assert (ROOT / path).is_file(), path
    assert links[("S2-T024", "PBI-13-A")]["artifact"] == (
        "UAT-S2-012 plus RESP-S2-001 acceptance package"
    )


def test_t024_pending_status_cannot_be_mistaken_for_public_pass() -> None:
    trace = _trace()
    base = trace["verifiedAgainstMainCommit"]
    assert re.fullmatch(r"[0-9a-f]{40}", base)
    assert trace["deliveryBaseCommit"] == base

    implementation = trace["implementationCommit"]
    assert implementation == "67459279e57e666b9cd34918695483b1afd51914"

    verification = trace["localVerification"]
    assert verification["status"] == "PASS"
    assert verification["traceabilityResult"] == "7 passed"
    assert verification["backendFull"].startswith("625 passed")
    assert verification["frontendTest"] == "48 passed"
    assert trace["knownGaps"]["browserBackendMode"] == (
        "MOCKED_UI_INTEGRATION_NOT_A_CONTINUOUS_REAL_BACKEND_CHAIN"
    )
    assert verification["playwright375Result"] == "7 passed"
    assert verification["playwright768Result"] == "7 passed"
    assert verification["frontendBuild"] == "PASS"
    assert verification["diffCheck"] == "PASS"
    assert verification["onlineE2E"] in {
        "NOT_RUN_NOT_CLAIMED",
        "PASS_WITH_RESP_S2_001_EVIDENCE",
    }
    assert trace["uat"]["publicResult"] in {
        "NOT_RUN_NOT_CLAIMED",
        "PASS_WITH_RESP_S2_001_EVIDENCE",
    }
    assert trace["neededInputs"]
