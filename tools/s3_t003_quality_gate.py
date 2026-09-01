#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


REPO_ROOT = Path(__file__).resolve().parents[1]
MINIMUM_COVERAGE_PERCENT = 75.0
DEFAULT_REPORT_DIRECTORY = REPO_ROOT / ".quality-reports" / "s3-t003"
DEFECT_REGISTER = REPO_ROOT / "docs" / "quality" / "s3_defects.json"
HARD_CONSTRAINT_MANIFEST = (
    REPO_ROOT
    / "backend"
    / "tests"
    / "fixtures"
    / "s3_t003"
    / "fixed_hard_constraint_cases.json"
)


@dataclass(frozen=True, slots=True)
class CoverageGroup:
    scopes: tuple[str, ...]


COVERAGE_GROUPS: dict[str, CoverageGroup] = {
    "planning": CoverageGroup((
        "app/application/planning_boundary_service.py",
        "backend/app/services/planning/",
    )),
    "care": CoverageGroup((
        "app/domain/hard_conflicts.py",
        "backend/app/services/assistance_constraints/",
    )),
    "validation": CoverageGroup((
        "backend/app/services/execution_replanning/",
        "backend/app/services/route_risk/",
    )),
    "budget": CoverageGroup(("app/domain/budget.py",)),
    "replanning": CoverageGroup((
        "app/application/execution_replan_service.py",
        "backend/app/services/replanning/",
    )),
}

COVERAGE_MODULES = (
    "app.application.planning_boundary_service",
    "app.application.execution_replan_service",
    "app.domain.budget",
    "app.domain.hard_conflicts",
    "app.services.assistance_constraints",
    "app.services.execution_replanning",
    "app.services.planning",
    "app.services.replanning",
    "app.services.route_risk",
)

DEFECT_SEVERITIES = frozenset({"P0", "P1", "P2", "P3"})
DEFECT_STATUSES = frozenset({
    "OPEN",
    "IN_PROGRESS",
    "BLOCKED",
    "RESOLVED",
    "CLOSED",
})
ALLOWED_SKIPPED_TESTS = frozenset({
    (
        "backend.tests.test_s3_t005_t006_city_verification::"
        "test_s3_t006_xian_hangzhou_live_place_route_and_care_smoke[xian]"
    ),
    (
        "backend.tests.test_s3_t005_t006_city_verification::"
        "test_s3_t006_xian_hangzhou_live_place_route_and_care_smoke[hangzhou]"
    ),
})


class QualityGateContractError(ValueError):
    """Raised when a machine-readable quality artifact is malformed."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QualityGateContractError(f"cannot read valid JSON from {path}") from error
    if not isinstance(payload, dict):
        raise QualityGateContractError(f"{path} must contain a JSON object")
    return payload


def _normalize_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _scope_matches(path: str, scope: str) -> bool:
    normalized_path = _normalize_path(path)
    normalized_scope = _normalize_path(scope)
    if normalized_scope.endswith("/"):
        return (
            normalized_path.startswith(normalized_scope)
            or f"/{normalized_scope}" in normalized_path
        )
    return (
        normalized_path == normalized_scope
        or normalized_path.endswith(f"/{normalized_scope}")
    )


def assess_coverage(
    payload: Mapping[str, Any],
    *,
    threshold: float = MINIMUM_COVERAGE_PERCENT,
    groups: Mapping[str, CoverageGroup] = COVERAGE_GROUPS,
) -> dict[str, Any]:
    raw_files = payload.get("files")
    if not isinstance(raw_files, dict):
        raise QualityGateContractError("coverage report must contain a files object")

    files: dict[str, Any] = {
        _normalize_path(str(path)): value for path, value in raw_files.items()
    }
    results: dict[str, Any] = {}
    for name, group in groups.items():
        matched: set[str] = set()
        missing_scopes: list[str] = []
        for scope in group.scopes:
            scope_matches = {
                path for path in files if _scope_matches(path, scope)
            }
            if not scope_matches:
                missing_scopes.append(scope)
            matched.update(scope_matches)

        covered_lines = 0
        statement_count = 0
        for path in sorted(matched):
            entry = files[path]
            summary = entry.get("summary") if isinstance(entry, dict) else None
            if not isinstance(summary, dict):
                raise QualityGateContractError(
                    f"coverage entry {path} must contain a summary object"
                )
            covered = summary.get("covered_lines")
            statements = summary.get("num_statements")
            if (
                not isinstance(covered, int)
                or isinstance(covered, bool)
                or not isinstance(statements, int)
                or isinstance(statements, bool)
                or covered < 0
                or statements < 0
                or covered > statements
            ):
                raise QualityGateContractError(
                    f"coverage entry {path} has invalid line totals"
                )
            covered_lines += covered
            statement_count += statements

        percent = (
            covered_lines * 100.0 / statement_count
            if statement_count
            else 0.0
        )
        passed = (
            not missing_scopes
            and statement_count > 0
            and percent + 1e-9 >= threshold
        )
        results[name] = {
            "status": "PASS" if passed else "FAIL",
            "percent": round(percent, 2),
            "coveredLines": covered_lines,
            "statementCount": statement_count,
            "scopes": list(group.scopes),
            "matchedFiles": sorted(matched),
            "missingScopes": missing_scopes,
        }

    return {
        "status": (
            "PASS"
            if results and all(item["status"] == "PASS" for item in results.values())
            else "FAIL"
        ),
        "minimumPercent": threshold,
        "groups": results,
    }


def assess_defect_register(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schemaVersion") != "1.0":
        raise QualityGateContractError("defect register schemaVersion must be 1.0")
    if payload.get("sprint") != "Sprint3":
        raise QualityGateContractError("defect register sprint must be Sprint3")
    updated_at = payload.get("updatedAt")
    if not isinstance(updated_at, str):
        raise QualityGateContractError("defect register updatedAt must be an ISO date")
    try:
        datetime.strptime(updated_at, "%Y-%m-%d")
    except ValueError as error:
        raise QualityGateContractError(
            "defect register updatedAt must be an ISO date"
        ) from error
    defects = payload.get("defects")
    if not isinstance(defects, list):
        raise QualityGateContractError("defect register defects must be an array")

    seen_ids: set[str] = set()
    open_high_priority: list[str] = []
    open_by_severity = {severity: 0 for severity in sorted(DEFECT_SEVERITIES)}
    for index, defect in enumerate(defects):
        if not isinstance(defect, dict):
            raise QualityGateContractError(f"defects[{index}] must be an object")
        for field in ("id", "title", "severity", "status", "owner", "sourceTask"):
            if not isinstance(defect.get(field), str) or not defect[field].strip():
                raise QualityGateContractError(
                    f"defects[{index}].{field} must be a non-empty string"
                )
        defect_id = defect["id"]
        if not re.fullmatch(r"S3-DEF-[0-9]{3,}", defect_id):
            raise QualityGateContractError(
                f"defects[{index}].id must match S3-DEF-NNN"
            )
        if defect_id in seen_ids:
            raise QualityGateContractError(f"duplicate defect id {defect_id}")
        seen_ids.add(defect_id)

        severity = defect["severity"]
        status = defect["status"]
        if severity not in DEFECT_SEVERITIES:
            raise QualityGateContractError(f"{defect_id} has invalid severity")
        if status not in DEFECT_STATUSES:
            raise QualityGateContractError(f"{defect_id} has invalid status")
        evidence = defect.get("evidence")
        if (
            not isinstance(evidence, list)
            or any(not isinstance(item, str) or not item.strip() for item in evidence)
        ):
            raise QualityGateContractError(
                f"{defect_id}.evidence must be an array of non-empty strings"
            )
        if status == "CLOSED" and not evidence:
            raise QualityGateContractError(
                f"closed defect {defect_id} must include verification evidence"
            )
        if status != "CLOSED":
            open_by_severity[severity] += 1
            if severity in {"P0", "P1"}:
                open_high_priority.append(defect_id)

    return {
        "status": "PASS" if not open_high_priority else "FAIL",
        "registeredCount": len(defects),
        "openBySeverity": open_by_severity,
        "openP0P1Count": len(open_high_priority),
        "openP0P1Ids": sorted(open_high_priority),
    }


def assess_fixed_hard_constraint_cases(
    root: Path = REPO_ROOT,
    *,
    evaluator: Callable[[dict[str, str]], Sequence[Any]] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = (
        root
        / "backend"
        / "tests"
        / "fixtures"
        / "s3_t003"
        / "fixed_hard_constraint_cases.json"
    )
    manifest = _read_json(manifest_path)
    if manifest.get("schemaVersion") != "1.0":
        raise QualityGateContractError(
            "hard-constraint manifest schemaVersion must be 1.0"
        )
    source_fixture = manifest.get("sourceFixture")
    case_names = manifest.get("fixedCaseNames")
    if not isinstance(source_fixture, str) or not source_fixture:
        raise QualityGateContractError("hard-constraint sourceFixture is required")
    if (
        not isinstance(case_names, list)
        or not case_names
        or any(not isinstance(name, str) or not name for name in case_names)
        or len(case_names) != len(set(case_names))
    ):
        raise QualityGateContractError(
            "hard-constraint fixedCaseNames must be a unique non-empty string array"
        )

    source_path = (manifest_path.parent / source_fixture).resolve()
    try:
        source_path.relative_to(root)
    except ValueError as error:
        raise QualityGateContractError(
            "hard-constraint sourceFixture must stay inside the repository"
        ) from error
    source = _read_json(source_path)
    raw_cases = source.get("cases")
    if not isinstance(raw_cases, list):
        raise QualityGateContractError("hard-constraint source cases must be an array")
    cases: dict[str, dict[str, str]] = {}
    for index, case in enumerate(raw_cases):
        if not isinstance(case, dict) or not isinstance(case.get("name"), str):
            raise QualityGateContractError(f"source cases[{index}] is invalid")
        name = case["name"]
        if name in cases:
            raise QualityGateContractError(f"duplicate source case {name}")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in case.items()):
            raise QualityGateContractError(f"source case {name} must use string fields")
        cases[name] = case

    if evaluator is None:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from backend.tests.s2_t003_support import evaluate_fixture_case

        evaluator = evaluate_fixture_case

    case_results: list[dict[str, Any]] = []
    violation_count = 0
    for name in case_names:
        if name not in cases:
            raise QualityGateContractError(f"fixed case {name} is not in sourceFixture")
        issues = tuple(evaluator(cases[name]))
        violation_count += len(issues)
        case_results.append({
            "name": name,
            "violationCount": len(issues),
            "ruleIds": [str(getattr(issue, "rule_id", "UNKNOWN")) for issue in issues],
        })

    return {
        "status": "PASS" if violation_count == 0 else "FAIL",
        "fixedCaseCount": len(case_results),
        "violationCount": violation_count,
        "cases": case_results,
    }


def summarize_junit(path: Path) -> dict[str, Any]:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise QualityGateContractError(f"cannot read JUnit report {path}") from error
    suites = [root] if root.tag.endswith("testsuite") else [
        item for item in root if item.tag.endswith("testsuite")
    ]
    if not suites:
        raise QualityGateContractError("JUnit report contains no testsuite")

    def total(attribute: str) -> int:
        try:
            return sum(int(float(item.attrib.get(attribute, "0"))) for item in suites)
        except ValueError as error:
            raise QualityGateContractError(
                f"JUnit report has invalid {attribute} count"
            ) from error

    skipped_tests = sorted(
        f"{item.attrib.get('classname', '')}::{item.attrib.get('name', '')}"
        for suite in suites
        for item in suite.iter()
        if item.tag.endswith("testcase")
        and any(child.tag.endswith("skipped") for child in item)
    )
    return {
        "tests": total("tests"),
        "failures": total("failures"),
        "errors": total("errors"),
        "skipped": total("skipped"),
        "skippedTests": skipped_tests,
    }


def assess_backend_test_report(exit_code: int, junit_path: Path) -> dict[str, Any]:
    summary = summarize_junit(junit_path)
    unexpected_skips = sorted(
        set(summary["skippedTests"]) - ALLOWED_SKIPPED_TESTS
    )
    passed = (
        exit_code == 0
        and summary["failures"] == 0
        and summary["errors"] == 0
        and not unexpected_skips
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "exitCode": exit_code,
        **summary,
        "allowedSkippedTests": sorted(ALLOWED_SKIPPED_TESTS),
        "unexpectedSkippedTests": unexpected_skips,
    }


def build_pytest_command(
    *,
    root: Path,
    report_directory: Path,
    python_executable: str = sys.executable,
) -> list[str]:
    def relative(path: Path) -> str:
        return os.path.relpath(path, root)

    command = [
        python_executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        f"--basetemp={relative(root / '.tmp-tests' / 's3-t003-quality-gate')}",
        f"--junitxml={relative(report_directory / 'junit.xml')}",
    ]
    command.extend(f"--cov={module}" for module in COVERAGE_MODULES)
    command.extend((
        "--cov-report=term",
        f"--cov-report=json:{relative(report_directory / 'coverage.json')}",
    ))
    return command


def _failed_check(error: Exception) -> dict[str, Any]:
    return {"status": "FAIL", "error": str(error)}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _print_summary(report: Mapping[str, Any], report_path: Path) -> None:
    checks = report["checks"]
    print(f"S3-T003 quality gate: {report['status']}")
    print(f"Backend tests: {checks['backendTests']['status']}")
    hard = checks["fixedHardConstraints"]
    print(
        "Fixed hard constraints: "
        f"{hard['status']} ({hard.get('violationCount', 'unknown')} violations)"
    )
    coverage = checks["coverage"]
    if "groups" in coverage:
        values = ", ".join(
            f"{name}={group['percent']:.2f}%"
            for name, group in coverage["groups"].items()
        )
        print(f"Coverage: {coverage['status']} ({values})")
    else:
        print(f"Coverage: {coverage['status']}")
    defects = checks["defects"]
    print(
        f"Defects: {defects['status']} "
        f"({defects.get('openP0P1Count', 'unknown')} open P0/P1)"
    )
    print(f"Report: {report_path}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the S3-T003 backend quality gate and write JSON/JUnit reports."
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIRECTORY.relative_to(REPO_ROOT)),
        help="report directory relative to the repository (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    report_directory = Path(args.report_dir)
    if not report_directory.is_absolute():
        report_directory = REPO_ROOT / report_directory
    report_directory = report_directory.resolve()
    report_directory.mkdir(parents=True, exist_ok=True)
    coverage_path = report_directory / "coverage.json"
    junit_path = report_directory / "junit.xml"
    report_path = report_directory / "quality-gate.json"
    coverage_path.unlink(missing_ok=True)
    junit_path.unlink(missing_ok=True)

    try:
        hard_constraints = assess_fixed_hard_constraint_cases(REPO_ROOT)
    except Exception as error:  # The final report must preserve contract failures.
        hard_constraints = _failed_check(error)
    try:
        defects = assess_defect_register(_read_json(DEFECT_REGISTER))
    except Exception as error:
        defects = _failed_check(error)

    command = build_pytest_command(
        root=REPO_ROOT,
        report_directory=report_directory,
    )
    environment = os.environ.copy()
    environment["COVERAGE_FILE"] = str(report_directory / "coverage.data")
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        check=False,
    )
    backend_tests: dict[str, Any]
    if junit_path.is_file():
        try:
            backend_tests = assess_backend_test_report(
                completed.returncode,
                junit_path,
            )
            backend_tests["junitPath"] = str(junit_path.relative_to(REPO_ROOT))
        except QualityGateContractError as error:
            backend_tests = {
                "status": "FAIL",
                "exitCode": completed.returncode,
                "junitPath": str(junit_path.relative_to(REPO_ROOT)),
                "error": str(error),
            }
    else:
        backend_tests = {
            "status": "FAIL",
            "exitCode": completed.returncode,
            "junitPath": str(junit_path.relative_to(REPO_ROOT)),
            "error": "pytest did not produce a JUnit report",
        }

    if coverage_path.is_file():
        try:
            coverage = assess_coverage(_read_json(coverage_path))
        except QualityGateContractError as error:
            coverage = _failed_check(error)
    else:
        coverage = _failed_check(
            QualityGateContractError("pytest did not produce a coverage report")
        )

    checks = {
        "backendTests": backend_tests,
        "fixedHardConstraints": hard_constraints,
        "coverage": coverage,
        "defects": defects,
    }
    status = (
        "PASS"
        if all(check.get("status") == "PASS" for check in checks.values())
        else "FAIL"
    )
    report = {
        "schemaVersion": "1.0",
        "taskId": "S3-T003",
        "status": status,
        "generatedAt": datetime.now(UTC).isoformat(),
        "repositoryRevision": _repository_revision(REPO_ROOT),
        "command": command,
        "checks": checks,
    }
    _write_json(report_path, report)
    _print_summary(report, report_path)
    return 0 if status == "PASS" else 1


def _repository_revision(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


if __name__ == "__main__":
    raise SystemExit(main())
