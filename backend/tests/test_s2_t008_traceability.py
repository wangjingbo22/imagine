from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACE_PATH = (
    REPO_ROOT
    / "docs"
    / "traceability"
    / "sprint2"
    / "lin_canhan_s2_t008_day1.json"
)
REMOTE_MAIN_COMMIT = "a43ad37a5c8b97d2b90507fa9966998bfee038b9"
IMPLEMENTATION_COMMIT = "f376574a5c8c5c577d6ed43efd200293023b3b32"


def _trace() -> dict[str, object]:
    return json.loads(TRACE_PATH.read_text(encoding="utf-8"))


def test_s2_t008_maps_pbi_ac_task_to_real_evidence() -> None:
    trace = _trace()
    task = trace["task"]

    assert trace["owner"] == "林粲涵"
    assert trace["sprint"] == "Sprint 2"
    assert trace["scope"] == "DAY_1"
    assert task["taskId"] == "S2-T008"
    assert task["pbiId"] == "PBI-08-A"
    assert task["acId"] == "AC-08-A"
    assert task["owner"] == "林粲涵"
    assert task["priority"] == "Must"
    assert task["plannedDay"] == "Day1"
    assert task["estimateHours"] == 3
    assert task["status"] == "IMPLEMENTED_WITH_EXTERNAL_ROUTE_BUILDER_PENDING"
    assert task["dependsOn"] == ["S2-T006"]
    assert task["consumedBy"] == ["S2-T009"]
    assert task["indirectlyVisibleIn"] == ["S2-T010"]

    referenced = (
        task["codeFiles"]
        + task["integrationFiles"]
        + task["testFiles"]
        + task["fixtures"]
        + task["schemaSnapshots"]
    )
    assert len(referenced) == len(set(referenced))
    for relative_path in referenced:
        assert (REPO_ROOT / relative_path).is_file(), relative_path

    pbi_trace = trace["pbiTrace"]
    assert pbi_trace == {
        "pbiId": task["pbiId"],
        "acId": task["acId"],
        "taskId": task["taskId"],
        "moduleFiles": task["codeFiles"] + task["integrationFiles"],
        "testFiles": task["testFiles"],
        "fixtureFiles": task["fixtures"],
        "schemaFiles": task["schemaSnapshots"],
    }


def test_cross_module_linkages_are_explicit_and_honest() -> None:
    trace = _trace()
    linkages = {
        (item["sourceTaskId"], item["targetTaskId"]): item
        for item in trace["moduleLinkages"]
    }
    assert set(linkages) == {
        ("S2-T006", "S2-T008"),
        ("S2-T008", "S2-T009"),
        ("S2-T007", "S2-T009"),
        ("S2-T009", "S2-T010"),
    }

    upstream = linkages[("S2-T006", "S2-T008")]
    assert upstream["status"] == "INTEGRATED_WITH_T006_REGISTRY"
    assert "placeFactId" in upstream["contract"]
    assert "factDigest" in upstream["contract"]
    assert "existing T006 registry restores" in upstream["behavior"]
    assert "remain owned by T006" in upstream["behavior"]

    consumer = linkages[("S2-T008", "S2-T009")]
    assert (
        consumer["status"]
        == "V2_STRICT_GATEWAY_CONNECTED_ROUTE_BUILDER_PENDING"
    )
    assert consumer["contract"].startswith("CandidateSelectionGateway.select")
    assert "DETERMINISTIC_ENUMERATION" in consumer["behavior"]
    assert "v2 recommendation route" in consumer["behavior"]
    assert "external production RouteCandidateBuilderPort" in consumer["behavior"]

    fairness = linkages[("S2-T007", "S2-T009")]
    assert fairness["status"] == "UPSTREAM_IMPLEMENTATION_AVAILABLE_ON_MAIN"
    assert "fairness" in fairness["contract"]
    assert "never calculates or overrides fairness" in fairness["behavior"]
    assert "aggregate providerFactDigest" in fairness["behavior"]
    assert fairness["files"] == [
        "backend/app/services/fairness/models.py",
        "backend/app/services/fairness/service.py",
        "backend/tests/test_s2_t007_fairness.py",
    ]

    ui = linkages[("S2-T009", "S2-T010")]
    assert ui["status"] == "INDIRECT_DOWNSTREAM_ONLY"
    assert ui["files"] == []
    assert "does not emit UI data or claim T010 completion" in ui["behavior"]

    for linkage in linkages.values():
        for relative_path in linkage["files"]:
            assert (REPO_ROOT / relative_path).is_file(), relative_path


def test_t008_primary_modules_do_not_import_other_task_cores() -> None:
    trace = _trace()
    task = trace["task"]
    forbidden_prefixes = (
        "app.application.planning_boundary_service",
        "app.infrastructure.plan_store",
        "app.infrastructure.workflow_store",
        "app.services.planning",
        "app.services.replanning",
        "app.services.route_risk",
    )

    for relative_path in task["codeFiles"]:
        tree = ast.parse((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imported_modules |= {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any(
            module.startswith(forbidden_prefixes)
            for module in imported_modules
        ), (relative_path, imported_modules)


def test_requirements_commits_external_evidence_and_needed_inputs_are_truthful() -> None:
    trace = _trace()

    assert trace["verifiedAgainst"]["remoteBranch"] == "origin/main"
    assert trace["verifiedAgainst"]["remoteMainCommit"] == REMOTE_MAIN_COMMIT
    assert trace["verifiedAgainst"]["implementationCommit"] == IMPLEMENTATION_COMMIT
    assert re.fullmatch(r"[0-9a-f]{40}", REMOTE_MAIN_COMMIT)
    assert re.fullmatch(r"[0-9a-f]{40}", IMPLEMENTATION_COMMIT)
    for commit in (REMOTE_MAIN_COMMIT, IMPLEMENTATION_COMMIT):
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            REMOTE_MAIN_COMMIT,
            IMPLEMENTATION_COMMIT,
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    requirements = trace["requirementsSource"]
    assert requirements == {
        "file": "doc/行知旅伴_V2.3_Sprint2待办列表_含负责人_新增需求修订版.xlsx",
        "ranges": [
            "SprintBacklog模板!A12:V12",
            "LLM接入设计!A6:K6",
            "LLM JSON契约!A5:K5",
        ],
    }
    assert (REPO_ROOT / requirements["file"]).is_file()

    assert all(value is None for value in trace["externalEvidence"].values())
    needed = trace["neededInputs"]
    assert any(
        "S2-T009" in item and "RouteCandidateBuilderPort" in item
        for item in needed
    )
    assert not any("T006 final FactRef" in item for item in needed)
    assert any("BAILIAN_API_KEY" in item for item in needed)


def test_responsibility_boundary_forbids_planning_decisions() -> None:
    boundary = _trace()["responsibilityBoundary"]
    not_implemented = " ".join(boundary["notImplementedByS2T008"])

    assert "S2-T006 FactRef registry ownership" in not_implemented
    assert "present and integrated" in not_implemented
    assert "S2-T007 fairness" in not_implemented
    assert "S2-T009 production RouteCandidateBuilderPort" in not_implemented
    for term in ("price", "route", "score", "PASS", "PlanVersion", "persistence"):
        assert term in not_implemented
    assert "S2-T010 frontend" in not_implemented


def test_local_verification_records_the_actual_acceptance_run() -> None:
    assert _trace()["localVerification"] == {
        "status": "VERIFIED_ON_IMPLEMENTATION_COMMIT_AGAINST_MAIN_BASELINE",
        "verifiedAt": "2026-08-28",
        "focusedCommand": (
            "python -B -m pytest -p no:cacheprovider -q "
            "backend/tests/test_s2_t006_provider_fact_registry.py "
            "backend/tests/test_s2_t008_candidate_selection_gateway.py "
            "backend/tests/test_s2_t009_recommendation_orchestration.py "
            "backend/tests/test_s2_t003_recommendation_readiness.py"
        ),
        "focusedResult": "87 passed",
        "fullCommand": "python -B -m pytest -p no:cacheprovider -q",
        "fullResult": "528 passed",
        "frontendTest": "npm test: 32 passed",
        "frontendBuild": "npm run build passed",
        "frontendLint": "npm run lint passed",
    }
