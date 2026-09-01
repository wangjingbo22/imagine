from __future__ import annotations

from pathlib import Path

import pytest

from tools.s3_t003_quality_gate import (
    ALLOWED_SKIPPED_TESTS,
    COVERAGE_GROUPS,
    COVERAGE_MODULES,
    QualityGateContractError,
    assess_backend_test_report,
    assess_coverage,
    assess_defect_register,
    assess_fixed_hard_constraint_cases,
    build_pytest_command,
)


ROOT = Path(__file__).parents[2]


def _coverage_payload(covered: int = 3, statements: int = 4) -> dict[str, object]:
    files: dict[str, object] = {}
    for group in COVERAGE_GROUPS.values():
        for scope in group.scopes:
            path = f"{scope}module.py" if scope.endswith("/") else scope
            files[path.replace("/", "\\")] = {
                "summary": {
                    "covered_lines": covered,
                    "num_statements": statements,
                }
            }
    return {"files": files}


def _defect(*, severity: str, status: str, evidence: list[str]) -> dict[str, object]:
    return {
        "id": "S3-DEF-001",
        "title": "Failure recovery regression",
        "severity": severity,
        "status": status,
        "owner": "S3-T002 owner",
        "sourceTask": "S3-T002",
        "evidence": evidence,
    }


def _register(defects: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "sprint": "Sprint3",
        "updatedAt": "2026-09-01",
        "defects": defects,
    }


def test_coverage_gate_normalizes_windows_paths_and_requires_every_domain() -> None:
    result = assess_coverage(_coverage_payload())
    assert result["status"] == "PASS"
    assert set(result["groups"]) == set(COVERAGE_GROUPS)
    assert all(item["percent"] == 75.0 for item in result["groups"].values())


def test_coverage_gate_fails_below_threshold_or_when_a_scope_disappears() -> None:
    low = _coverage_payload(covered=2, statements=4)
    assert assess_coverage(low)["status"] == "FAIL"

    missing = _coverage_payload()
    missing["files"].pop("app\\domain\\budget.py")
    result = assess_coverage(missing)
    assert result["status"] == "FAIL"
    assert result["groups"]["budget"]["missingScopes"] == [
        "app/domain/budget.py"
    ]


def test_defect_gate_blocks_resolved_p0_p1_until_verified_closed() -> None:
    empty = assess_defect_register(_register([]))
    assert empty["status"] == "PASS"

    unresolved = assess_defect_register(_register([
        _defect(severity="P1", status="RESOLVED", evidence=[])
    ]))
    assert unresolved["status"] == "FAIL"
    assert unresolved["openP0P1Ids"] == ["S3-DEF-001"]

    closed = assess_defect_register(_register([
        _defect(
            severity="P1",
            status="CLOSED",
            evidence=["backend/tests/test_recovery.py::test_retry"],
        )
    ]))
    assert closed["status"] == "PASS"


def test_defect_gate_rejects_duplicate_ids_and_unproven_closure() -> None:
    closed = _defect(severity="P2", status="CLOSED", evidence=[])
    with pytest.raises(QualityGateContractError, match="verification evidence"):
        assess_defect_register(_register([closed]))

    item = _defect(severity="P2", status="OPEN", evidence=[])
    with pytest.raises(QualityGateContractError, match="duplicate defect id"):
        assess_defect_register(_register([item, dict(item)]))


def test_backend_report_rejects_any_skip_outside_the_live_amap_allowlist(
    tmp_path: Path,
) -> None:
    allowed = next(iter(ALLOWED_SKIPPED_TESTS))
    allowed_class, allowed_name = allowed.split("::", 1)
    junit = tmp_path / "junit.xml"
    junit.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite tests="2" failures="0" errors="0" skipped="2">
  <testcase classname="%s" name="%s"><skipped /></testcase>
  <testcase classname="backend.tests.test_s3_t002" name="test_recovery"><skipped /></testcase>
</testsuite></testsuites>
""" % (allowed_class, allowed_name),
        encoding="utf-8",
    )
    result = assess_backend_test_report(0, junit)
    assert result["status"] == "FAIL"
    assert result["unexpectedSkippedTests"] == [
        "backend.tests.test_s3_t002::test_recovery"
    ]


def test_fixed_hard_constraint_manifest_has_zero_violations() -> None:
    result = assess_fixed_hard_constraint_cases(ROOT)
    assert result == {
        "status": "PASS",
        "fixedCaseCount": 2,
        "violationCount": 0,
        "cases": [
            {"name": "one-person-ready", "violationCount": 0, "ruleIds": []},
            {"name": "three-person-ready", "violationCount": 0, "ruleIds": []},
        ],
    }


def test_quality_gate_command_is_full_suite_and_owns_all_report_paths(tmp_path: Path) -> None:
    command = build_pytest_command(
        root=ROOT,
        report_directory=tmp_path,
        python_executable="python",
    )
    assert command[:4] == ["python", "-m", "pytest", "-q"]
    assert not any(item.startswith("backend/tests/") for item in command)
    assert {item.removeprefix("--cov=") for item in command if item.startswith("--cov=")} == set(
        COVERAGE_MODULES
    )
    assert any(item.startswith("--junitxml=") for item in command)
    assert any(item.startswith("--cov-report=json:") for item in command)
