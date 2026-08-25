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
        "evidence": "backend/tests/test_minimum_disruption_replanning.py",
    }
    assert (REPO_ROOT / boundary["definedIn"]).is_file()
    assert (REPO_ROOT / boundary["evidence"]).is_file()

    implementation_commit = trace["implementationCommit"]
    assert re.fullmatch(r"[0-9a-f]{40}", implementation_commit)
    subprocess.run(
        ["git", "cat-file", "-e", f"{implementation_commit}^{{commit}}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert all(value is None for value in trace["externalEvidence"].values())
