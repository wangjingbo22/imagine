from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACE_PATH = (
    REPO_ROOT
    / "docs"
    / "traceability"
    / "sprint1"
    / "lin_canhan_day1.json"
)


def test_day1_traceability_is_complete_and_points_to_real_files():
    trace = json.loads(TRACE_PATH.read_text(encoding="utf-8"))

    assert trace["owner"] == "林粲涵"
    assert trace["scope"] == "DAY_1_ONLY"
    assert [task["taskId"] for task in trace["tasks"]] == [
        "S1-T003",
        "S1-T008",
        "S1-T009",
    ]

    for task in trace["tasks"]:
        assert task["pbiId"].startswith("PBI-")
        assert task["acId"].startswith("AC-")
        assert task["dependsOn"]
        assert task["consumedBy"]
        assert task["codeFiles"]
        assert task["testFiles"]
        assert task["proves"]
        for relative_path in (
            task["codeFiles"] + task["testFiles"] + task["fixtures"]
        ):
            assert (REPO_ROOT / relative_path).is_file(), relative_path


def test_day2_continuation_points_to_separate_trace():
    trace = json.loads(TRACE_PATH.read_text(encoding="utf-8"))

    assert "deferredByUser" not in trace
    assert trace["day2Continuation"] == {
        "status": "IMPLEMENTED_IN_SEPARATE_TRACE",
        "trace": "docs/traceability/sprint1/lin_canhan_day2.json",
        "tasks": ["S1-T011", "S1-T018", "S1-T022"],
    }
    assert (REPO_ROOT / trace["day2Continuation"]["trace"]).is_file()
