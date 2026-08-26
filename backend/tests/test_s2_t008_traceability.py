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
    / "lin_canhan_day1.json"
)
REMOTE_MAIN_COMMIT = "3e60435fcfde0705149dbc5f340d60e1aa63103c"


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
    assert task["status"] == "IMPLEMENTED_WITH_UPSTREAM_FIXTURE_PENDING"
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
    assert upstream["status"] == "UPSTREAM_FIXTURE_CONTRACT_PENDING"
    assert "placeFactId" in upstream["contract"]
    assert "factDigest" in upstream["contract"]
    assert "neither creates nor restores Provider facts" in upstream["behavior"]

    consumer = linkages[("S2-T008", "S2-T009")]
    assert consumer["status"] == "READY_FOR_CONSUMER_INTEGRATION"
    assert consumer["contract"].startswith("CandidateSelectionGateway.select")
    assert "DETERMINISTIC_ENUMERATION" in consumer["behavior"]
    assert "T009 owns" in consumer["behavior"]

    fairness = linkages[("S2-T007", "S2-T009")]
    assert fairness["status"] == "SIBLING_UPSTREAM_NOT_IMPLEMENTED_BY_T008"
    assert "fairness" in fairness["contract"]
    assert "never calculates or overrides fairness" in fairness["behavior"]
    assert fairness["files"] == []

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


def test_remote_baseline_external_evidence_and_needed_inputs_are_truthful() -> None:
    trace = _trace()

    assert trace["verifiedAgainst"]["remoteBranch"] == "origin/main"
    assert trace["verifiedAgainst"]["remoteMainCommit"] == REMOTE_MAIN_COMMIT
    assert re.fullmatch(r"[0-9a-f]{40}", REMOTE_MAIN_COMMIT)
    subprocess.run(
        ["git", "cat-file", "-e", f"{REMOTE_MAIN_COMMIT}^{{commit}}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert all(value is None for value in trace["externalEvidence"].values())
    needed = trace["neededInputs"]
    assert any("S2-T006" in item for item in needed)
    assert any("S2-T009" in item for item in needed)
    assert any("BAILIAN_API_KEY" in item for item in needed)


def test_responsibility_boundary_forbids_planning_decisions() -> None:
    boundary = _trace()["responsibilityBoundary"]
    not_implemented = " ".join(boundary["notImplementedByS2T008"])

    assert "S2-T006 FactRef registry" in not_implemented
    assert "S2-T007 fairness" in not_implemented
    assert "S2-T009 deterministic enumeration" in not_implemented
    for term in ("price", "route", "score", "PASS", "PlanVersion", "persistence"):
        assert term in not_implemented
    assert "S2-T010 frontend" in not_implemented


def test_local_verification_records_the_actual_acceptance_run() -> None:
    assert _trace()["localVerification"] == {
        "status": "VERIFIED_ON_REMOTE_MAIN_WITH_STRICT_GATEWAY_AND_TRACEABILITY",
        "verifiedAt": "2026-08-26",
        "focusedCommand": (
            "python -B -m pytest -p no:cacheprovider -q "
            "backend/tests/test_s2_t008_candidate_selection_gateway.py "
            "backend/tests/test_s2_t008_traceability.py "
            "backend/tests/test_bailian_trip_extractor.py "
            "backend/tests/test_trip_draft_llm_integration.py"
        ),
        "focusedResult": "64 passed in 0.92s",
        "fullCommand": "python -B -m pytest -p no:cacheprovider -q",
        "fullResult": "228 passed in 10.16s",
        "frontendTest": "npm test: 31 passed",
        "frontendBuild": "npm run build passed",
        "frontendLint": "npm run lint passed",
    }
