from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACE_JSON = (
    REPO_ROOT
    / "docs"
    / "traceability"
    / "sprint1"
    / "chen_ziyuan_s1_t007.json"
)
TRACE_MD = TRACE_JSON.with_suffix(".md")


def test_s1_t007_traceability_identifies_contract_and_real_files():
    trace = json.loads(TRACE_JSON.read_text(encoding="utf-8"))

    assert trace["taskId"] == "S1-T007"
    assert trace["pbiId"] == "PBI-03-A"
    assert trace["acId"] == "AC-03-A"
    assert trace["owner"] == "陈梓元"
    assert trace["baseline"] == (
        "67206f2c55dcb011c61304de94f95b8b83a72ba0"
    )
    assert trace["dependsOn"] == ["S1-T003"]
    assert trace["consumedBy"] == ["S1-T008", "S1-T009", "S1-T011"]

    for group in (
        "codeFiles",
        "contractFiles",
        "testFiles",
        "snapshots",
    ):
        assert trace[group]
        for relative_path in trace[group]:
            assert (REPO_ROOT / relative_path).is_file(), relative_path


def test_s1_t007_traceability_lists_acceptance_proofs_and_handoff():
    trace = json.loads(TRACE_JSON.read_text(encoding="utf-8"))

    assert TRACE_MD.is_file()
    assert trace["proves"] == [
        "four-profile-canonical-snapshot",
        "repeatable-order-and-json-bytes",
        "null-source-constraint-omission",
        "walking-transfer-rest-nap-return-stairs-covered",
        "field-level-invalid-profile-fails-closed",
        "t008-protocol-and-rewrite-guard-compatible",
        "t009-route-fields-and-day-scope-compatible",
    ]
    assert trace["nonGoals"] == [
        "profile-schema-change",
        "agent-adapter-change",
        "route-risk-algorithm-change",
        "planner-or-return-reference-resolution",
    ]
