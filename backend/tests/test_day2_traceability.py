from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACE_PATH = (
    REPO_ROOT
    / "docs"
    / "traceability"
    / "sprint1"
    / "lin_canhan_day2.json"
)
DAY1_TRACE_PATH = (
    REPO_ROOT
    / "docs"
    / "traceability"
    / "sprint1"
    / "lin_canhan_day1.json"
)
INTEGRATED_MAIN_COMMIT = "3b9321c39e794a3e1bcc782cb947219bff197c3d"
LATEST_MAIN_MERGE_COMMIT = "9a7c290a3af2fe7a4afc9627090366fdc0150299"
INTEGRATION_ADAPTATION_COMMIT = "d43442c8ada3c741ed43b629aec5b20a291cae07"
EXPECTED_TASKS = {
    "S1-T011": {
        "pbiId": "PBI-04-A",
        "acId": "AC-04-A",
        "dependsOn": ["S1-T006", "S1-T007", "S1-T009"],
        "consumedBy": ["S1-T012", "S1-T018", "S1-T024"],
    },
    "S1-T018": {
        "pbiId": "PBI-05-B",
        "acId": "AC-05-B",
        "dependsOn": ["S1-T011", "S1-T017"],
        "consumedBy": ["S1-T019", "S1-T024"],
    },
    "S1-T022": {
        "pbiId": "PBI-06-A",
        "acId": "AC-06-A",
        "dependsOn": ["S1-T021"],
        "consumedBy": ["S1-T024"],
    },
}


def _trace() -> dict[str, object]:
    return json.loads(TRACE_PATH.read_text(encoding="utf-8"))


def test_day2_tasks_map_to_real_code_tests_fixtures_and_integrations() -> None:
    trace = _trace()

    assert trace["owner"] == "林粲涵"
    assert trace["scope"] == "DAY_2"
    tasks = {item["taskId"]: item for item in trace["tasks"]}
    assert set(tasks) == set(EXPECTED_TASKS)

    for task_id, expected in EXPECTED_TASKS.items():
        task = tasks[task_id]
        for key, value in expected.items():
            assert task[key] == value
        assert task["status"].startswith("IMPLEMENTED")
        assert task["codeFiles"]
        assert task["integrationFiles"]
        assert task["testFiles"]
        assert task["fixtures"]
        assert task["proves"]

        referenced = (
            task["codeFiles"]
            + task["integrationFiles"]
            + task["testFiles"]
            + task["fixtures"]
            + task.get("testSupportFiles", [])
        )
        assert len(referenced) == len(set(referenced))
        for relative_path in referenced:
            assert (REPO_ROOT / relative_path).is_file(), relative_path

    assert tasks["S1-T022"]["fixtures"] == [
        "backend/tests/fixtures/summary_paths/no_v2.json",
        "backend/tests/fixtures/summary_paths/accepted_v2.json",
        "backend/tests/fixtures/summary_paths/rejected_v2.json",
    ]

    assert {
        "app/api/planning_routes.py",
        "app/application/planning_boundary_service.py",
        "app/infrastructure/trusted_planning_store.py",
        "app/application/trip_draft_service.py",
        "app/infrastructure/workflow_store.py",
        "frontend/src/pages/WorkspacePage.tsx",
        "frontend/src/services/candidateRequestBuilder.ts",
        "frontend/src/services/planningFacts.ts",
    } <= set(tasks["S1-T011"]["integrationFiles"])
    assert {
        "t004-confirmed-profile-and-authoritative-trip-are-required-before-t011",
        "budget-time-endpoint-participant-and-preference-tampering-write-no-plan-or-trust-row",
        "client-direct-plan-registration-is-forbidden",
        "only-server-issued-canonical-digests-can-be-confirmed",
        "confirmed-trip-return-endpoint-and-refresh-facts-survive-the-frontend-runtime",
    } <= set(tasks["S1-T011"]["proves"])

    assert {
        "app/api/planning_routes.py",
        "app/application/planning_boundary_service.py",
        "app/infrastructure/trusted_planning_store.py",
        "frontend/src/pages/WorkspacePage.tsx",
        "frontend/src/services/replanPolicy.ts",
    } <= set(tasks["S1-T018"]["integrationFiles"])
    assert {
        "runtime-replans-endpoint-runs-t011-and-t018-before-registering-only-the-selected-v2",
        "current-v1-must-have-a-matching-issued-digest-before-it-can-parent-v2",
        "client-direct-v2-registration-and-unissued-lineage-are-forbidden",
        "sprint-one-second-replan-is-blocked-after-a-v2-decision",
    } <= set(tasks["S1-T018"]["proves"])

    assert {
        "tests/test_plan_versions.py",
        "tests/test_plan_v2_diff.py",
        "backend/tests/test_planning_http_boundaries.py",
    } <= set(tasks["S1-T022"]["testSupportFiles"])
    assert (
        "all-summary-paths-enter-through-server-issued-v1-and-v2-boundaries"
        in tasks["S1-T022"]["proves"]
    )


def test_pbi_ac_task_linkages_exactly_mirror_task_evidence() -> None:
    trace = _trace()
    tasks = {item["taskId"]: item for item in trace["tasks"]}
    linkages = {item["taskId"]: item for item in trace["linkages"]}

    assert set(linkages) == set(tasks)
    for task_id, task in tasks.items():
        linkage = linkages[task_id]
        assert linkage["pbiId"] == task["pbiId"]
        assert linkage["acId"] == task["acId"]
        assert linkage["moduleFiles"] == task["codeFiles"]
        assert linkage["testFiles"] == task["testFiles"]
        assert linkage["fixtureFiles"] == task["fixtures"]
        assert linkage["upstreamTasks"] == task["dependsOn"]
        assert linkage["downstreamTasks"] == task["consumedBy"]


def test_external_boundaries_and_commit_evidence_are_honest() -> None:
    trace = _trace()
    boundary = trace["integrationBoundaries"]["S1-T017"]

    assert boundary == {
        "status": "UPSTREAM_IMPLEMENTATION_ABSENT_PORT_ONLY",
        "implementedByThisDelivery": False,
        "port": "ReplanCandidateSource",
        "definedIn": "backend/app/services/replanning/selector.py",
        "runtimeCandidateSupplier": "frontend/src/services/amapPlan.ts",
        "runtimeBoundary": "POST /api/v1/trips/{tripId}/replans",
        "evidence": [
            "backend/tests/test_minimum_disruption_replanning.py",
            "backend/tests/test_planning_http_boundaries.py",
            "frontend/tests/candidateRequestBuilder.test.ts",
        ],
    }
    assert (REPO_ROOT / boundary["definedIn"]).is_file()
    assert (REPO_ROOT / boundary["runtimeCandidateSupplier"]).is_file()
    for evidence_path in boundary["evidence"]:
        assert (REPO_ROOT / evidence_path).is_file(), evidence_path

    assert trace["compatibilityBaseline"]["teamMainCommit"] == INTEGRATED_MAIN_COMMIT
    assert trace["integratedMainCommit"] == INTEGRATED_MAIN_COMMIT
    assert trace["latestMainMergeCommit"] == LATEST_MAIN_MERGE_COMMIT
    assert trace["integrationAdaptationCommit"] == INTEGRATION_ADAPTATION_COMMIT
    for commit_key in (
        "implementationCommit",
        "integratedMainCommit",
        "latestMainMergeCommit",
        "integrationAdaptationCommit",
    ):
        commit = trace[commit_key]
        assert re.fullmatch(r"[0-9a-f]{40}", commit)
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    assert all(value is None for value in trace["externalEvidence"].values())


def test_cross_task_integrations_are_machine_traceable() -> None:
    trace = _trace()
    linkages = {
        (item["sourceTaskId"], item["targetTaskId"]): item
        for item in trace["crossTaskLinkages"]
    }
    assert set(linkages) == {
        ("S1-T002", "S1-T011"),
        ("S1-T004", "S1-T011"),
        ("S1-T010", "S1-T011"),
        ("S1-T013", "S1-T018"),
        ("S1-T016", "S1-T018"),
    }

    trip = linkages[("S1-T002", "S1-T011")]
    assert trip["contract"] == "CreateSingleDayTrip authoritative snapshot"
    assert "one canonical Trip" in trip["behavior"]
    assert "only status from DRAFT to PLANNING" in trip["behavior"]
    assert "rejects any participant, preference, budget, time-window or endpoint drift" in trip["behavior"]

    assistance = linkages[("S1-T004", "S1-T011")]
    assert assistance["contract"] == "ConstraintProfileState.CONSTRAINT_CONFIRMED"
    assert "must exactly match the canonical Trip profile" in assistance["behavior"]
    assert "before T011 compilation, trust staging or PlanVersion registration" in assistance["behavior"]

    facility = linkages[("S1-T010", "S1-T011")]
    assert facility["contract"] == "Route.facilityEvidence"
    assert "exactly one item for each FacilityType" in facility["behavior"]
    assert "never promoted to PASS" in facility["behavior"]

    registration = linkages[("S1-T013", "S1-T018")]
    assert registration["contract"] == "PlanVersionService.register_proposed"
    assert "PLAN_VERSION_ALREADY_EXISTS" in registration["behavior"]

    expenses = linkages[("S1-T016", "S1-T018")]
    assert expenses["contract"] == "ExecutionEvent.EXPENSE.amountCents"
    assert "without double counting" in expenses["behavior"]

    for linkage in linkages.values():
        referenced = (
            linkage["sourceFiles"]
            + linkage["consumerFiles"]
            + linkage["testFiles"]
        )
        assert len(referenced) == len(set(referenced))
        for relative_path in referenced:
            assert (REPO_ROOT / relative_path).is_file(), relative_path


def test_local_verification_records_latest_full_and_frontend_results() -> None:
    trace = _trace()

    assert trace["localVerification"] == {
        "status": "VERIFIED_AFTER_LATEST_MAIN_TRUSTED_RUNTIME_INTEGRATION",
        "backendCommand": "python -B -m pytest -p no:cacheprovider -q",
        "backendResult": "261 passed in 4.54s",
        "focusedCommand": (
            "python -B -m pytest -p no:cacheprovider -q "
            "backend/tests/test_candidate_planner.py "
            "backend/tests/test_minimum_disruption_replanning.py "
            "backend/tests/test_planning_replanning_integration.py "
            "backend/tests/test_planning_http_boundaries.py "
            "backend/tests/test_s1_t022_summary_paths.py "
            "tests/test_trip_draft_parser.py "
            "tests/test_execution_expenses.py"
        ),
        "focusedResult": "76 passed in 2.75s",
        "frontendTest": "npm test: 16 passed",
        "frontendBuild": "npm run build passed",
        "frontendLint": "npm run lint passed",
    }


def test_day1_trace_keeps_the_day2_continuation_pointer() -> None:
    day1 = json.loads(DAY1_TRACE_PATH.read_text(encoding="utf-8"))

    assert day1["day2Continuation"] == {
        "status": "IMPLEMENTED_IN_SEPARATE_TRACE",
        "trace": "docs/traceability/sprint1/lin_canhan_day2.json",
        "tasks": ["S1-T011", "S1-T018", "S1-T022"],
    }
    assert (REPO_ROOT / day1["day2Continuation"]["trace"]).is_file()
