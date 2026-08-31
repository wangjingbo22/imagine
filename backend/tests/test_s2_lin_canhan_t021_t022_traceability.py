from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).parents[2]
TRACE = (
    ROOT
    / "docs"
    / "traceability"
    / "sprint2"
    / "lin_canhan_s2_t021_t022_day2.json"
)
LATEST_MAIN_COMMIT = "90bef1439aee70a3b02675b385bba05f96a65cf6"
DELIVERY_BASE_COMMIT = "a43ad37a5c8b97d2b90507fa9966998bfee038b9"
IMPLEMENTATION_COMMIT = "f376574a5c8c5c577d6ed43efd200293023b3b32"
EVENT_HARDENING_COMMIT = "0856b745075156e3da5365e74852aaa192329325"
CLOSURE_COMMIT = "1a7fcf7169f3e3656507be878e896bf4db1dd9fd"
FRONTEND_INTEGRATION_COMMIT = "e4f9c50f7c9ee6c058030c5d6e6739e9f1a480af"


def _trace() -> dict[str, object]:
    return json.loads(TRACE.read_text(encoding="utf-8"))


def _evidence_paths(task: dict[str, object]) -> set[str]:
    paths: set[str] = set()
    for key in (
        "moduleFiles",
        "integrationFiles",
        "documentationFiles",
        "fixtureFiles",
        "testFiles",
    ):
        paths.update(task.get(key, []))
    return paths


def test_day2_trace_locks_owner_pbi_ac_and_latest_main_base() -> None:
    trace = _trace()
    assert trace["schemaVersion"] == "1.0"
    assert trace["sprint"] == "Sprint2"
    assert trace["deliveryDay"] == "Day2"
    assert trace["owner"] == "林粲涵"
    assert trace["verifiedAgainstMainCommit"] == LATEST_MAIN_COMMIT
    assert trace["deliveryBaseCommit"] == DELIVERY_BASE_COMMIT
    assert trace["implementationCommit"] == IMPLEMENTATION_COMMIT
    assert trace["eventContractHardeningCommit"] == EVENT_HARDENING_COMMIT
    assert trace["compatibilityClosureCommit"] == CLOSURE_COMMIT
    assert trace["frontendIntegrationCommit"] == FRONTEND_INTEGRATION_COMMIT
    for commit in (
        LATEST_MAIN_COMMIT,
        DELIVERY_BASE_COMMIT,
        IMPLEMENTATION_COMMIT,
        EVENT_HARDENING_COMMIT,
        CLOSURE_COMMIT,
        FRONTEND_INTEGRATION_COMMIT,
    ):
        assert re.fullmatch(r"[0-9a-f]{40}", commit)
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    for ancestor in (DELIVERY_BASE_COMMIT, IMPLEMENTATION_COMMIT, EVENT_HARDENING_COMMIT):
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, LATEST_MAIN_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    assert trace["pbi"]["pbiId"] == "PBI-11-B"
    assert trace["pbi"]["acceptanceCriteriaId"] == "AC-11-B"

    requirements = {
        (item["sheet"], item["range"], item["file"])
        for item in trace["requirementsSource"]
    }
    source = "doc/行知旅伴_V2.3_Sprint2待办列表_含负责人_新增需求修订版.xlsx"
    assert (ROOT / source).is_file()
    assert requirements == {
        ("SprintBacklog模板", "A25:V26", source),
        ("PBI追溯", "A11:J11", source),
        ("LLM接入设计", "A7:K7", source),
        ("用户功能验收清单", "A12:J13", source),
    }


def test_task_dependencies_and_day2_evidence_paths_are_machine_resolvable() -> None:
    tasks = {item["taskId"]: item for item in _trace()["tasks"]}
    assert set(tasks) == {"S2-T021", "S2-T022"}
    assert tasks["S2-T021"]["dependsOn"] == [
        "S2-T005",
        "S2-T006",
        "S2-T019",
        "S2-T020",
    ]
    assert tasks["S2-T022"]["dependsOn"] == ["S2-T005", "S2-T021"]

    for task in tasks.values():
        assert task["owner"] == "林粲涵"
        assert task["deliveryDay"] == "Day2"
        assert task["pbiId"] == "PBI-11-B"
        assert task["acceptanceCriteriaId"] == "AC-11-B"
        assert task["remainingHours"] == 0
        assert task["status"] == "VERIFIED"
        for path in _evidence_paths(task):
            assert (ROOT / path).is_file(), path


def test_pbi_linkage_is_complete_through_downstream_consumers() -> None:
    links = {
        (item["from"], item["to"]): item
        for item in _trace()["crossTaskLinkages"]
    }
    assert set(links) == {
        ("S2-T005", "S2-T021"),
        ("S2-T006", "S2-T021"),
        ("S2-T019", "S2-T020"),
        ("S2-T019", "S2-T021"),
        ("S2-T020", "S2-T021"),
        ("S2-T021", "S2-T022"),
        ("S2-T022", "S2-T018"),
        ("S2-T022", "S2-T023"),
    }
    assert links[("S2-T020", "S2-T021")]["artifact"] == (
        "server-recompiled transient EventConstraintSet"
    )
    assert links[("S2-T021", "S2-T022")]["artifact"] == (
        "readiness-bound PROPOSED PlanVersion plus full HARD validation report"
    )
    assert links[("S2-T006", "S2-T021")]["status"] == (
        "REGISTRY_IMPLEMENTED_FORMAL_ONLINE_ROUTE_BUILDER_EXTERNAL_PENDING"
    )
    assert links[("S2-T019", "S2-T021")]["status"] == (
        "VERIFIED_WITH_INLINE_MISMATCH_FAIL_CLOSED"
    )
    assert links[("S2-T022", "S2-T023")]["status"] == (
        "BACKEND_AND_T023_FRONTEND_CONTRACT_INTEGRATED_PUBLIC_E2E_PENDING"
    )
    for link in links.values():
        for path in link["evidenceFiles"]:
            assert (ROOT / path).is_file(), path


def test_acceptance_and_authority_boundaries_cannot_be_silently_weakened() -> None:
    trace = _trace()
    contract = trace["acceptanceContract"]
    assert "only the unfinished suffix is adjusted" in contract["S2-T021"]
    assert "all HARD rules are revalidated" in contract["S2-T021"]
    assert "no infeasible partial candidate is persisted" in contract["S2-T021"]
    assert (
        "persisted adjustmentEventId is restored server-side and inline tampering is rejected"
        in contract["S2-T021"]
    )
    assert "CURRENT is unchanged until candidate acceptance" in contract["S2-T022"]
    assert (
        "explanation failure does not remove structured candidate or Diff"
        in contract["S2-T022"]
    )

    boundaries = trace["integrationBoundaries"]
    assert boundaries["llmAuthority"] == (
        "EXPLANATION_ONLY_BEST_EFFORT_NO_PLAN_WRITE_AUTHORITY"
    )
    assert boundaries["constraintLifetime"] == (
        "S2_T020_EVENT_CONSTRAINTS_ARE_TRANSIENT_AND_NOT_APPENDED_TO_S1_T007_PROFILE"
    )
    assert boundaries["candidateState"] == "PROPOSED_UNTIL_EXPLICIT_ACCEPT"
    assert boundaries["defaultCandidateSource"] == (
        "DETERMINISTIC_EVENT_AWARE_TRUSTED_SUFFIX_PLANNER_PRESERVES_PROVIDER_FACTS_AND_FAILS_CLOSED_WHEN_FACTS_CANNOT_SATISFY_HARD_RULES"
    )
    assert boundaries["readinessBinding"] == (
        "V2_IDENTITY_AND_ISSUED_EVIDENCE_BIND_READINESS_DIGEST_AND_CURRENT_REVISION; DECISION_REVALIDATES_BOTH"
    )
    assert boundaries["decisionAuthority"] == (
        "DELAY_AND_FATIGUE_USE_DEDICATED_ORGANIZER_DECISION; GENERIC_ACCEPT_REJECT_CANNOT_BYPASS_T021_EVIDENCE"
    )
    assert boundaries["frontendScope"] == (
        "T023_FRONTEND_INTEGRATION_COMPLETE_AT_E4F9C50_PUBLIC_E2E_PENDING"
    )


def test_known_upstream_and_external_gaps_are_explicit_not_claimed_done() -> None:
    trace = _trace()
    gaps = trace["knownGaps"]
    assert gaps["s2T006ConcreteFactRefRegistry"] == "IMPLEMENTED"
    assert gaps["s2T006FormalOnlineRouteBuilder"] == "EXTERNAL_PENDING"
    assert gaps["s2T005UnifiedPlanVersionChain"] == (
        "AVAILABLE_ON_MAIN_ONE_TWO_THREE_PERSON_SHARED_STATE_MACHINE"
    )
    assert gaps["s2T023Frontend"] == (
        "LOCAL_CONTRACT_AND_UI_INTEGRATION_PASS_PUBLIC_E2E_PENDING"
    )
    assert gaps["fatigueThresholds"] == "PO_CONFIRMATION_PENDING"
    assert gaps["lateBeyondRemainingWindowPolicy"] == "PO_CONFIRMATION_PENDING"
    assert gaps["onlineE2E"] == "NOT_CLAIMED"
    assert trace["localVerification"]["onlineE2E"] == "NOT_RUN_NOT_CLAIMED"
    assert trace["externalAcceptanceStillNeeded"]
    assert not any(
        "must deliver" in item and "S2-T005" in item
        for item in trace["externalAcceptanceStillNeeded"]
    )


def test_verification_separates_latest_trace_from_historical_functional_runs() -> None:
    verification = _trace()["localVerification"]
    assert verification["status"] == (
        "LATEST_MAIN_POST_TRACE_REFRESH_FULL_PASS"
    )
    assert verification["latestMainCommit"] == LATEST_MAIN_COMMIT
    assert verification["latestMainTraceResult"] == "6 passed"
    assert verification["historicalBaselineCommit"] == DELIVERY_BASE_COMMIT
    assert verification["historicalFocusedResult"] == "42 passed"
    assert verification["historicalBoundaryResult"] == "43 passed"
    assert verification["historicalBackendResult"] == "528 passed"
    assert verification["historicalFrontendTest"] == "32 passed"
    assert verification["historicalFrontendBuild"] == "PASS"
    assert verification["historicalFrontendLint"] == (
        "PASS_WITH_2_EXISTING_WARNINGS"
    )
    assert verification["historicalDiffCheck"] == "PASS"
    assert verification["latestMainClosureCommit"] == CLOSURE_COMMIT
    assert verification["baselineAuditScope"] == (
        "ORIGIN_MAIN_PRE_TRACEABILITY_REFRESH"
    )
    assert verification["preClosureBackendResult"] == "685 passed"
    assert verification["latestMainBackendResult"] == "688 passed"
    assert verification["baselineLinFocusedResult"] == "119 passed"
    assert verification["postClosureLinFocusedResult"] == "188 passed"
    assert verification["latestMainFrontendTest"] == "56 passed"
    assert verification["latestMainFrontendBuild"] == "PASS"
    assert verification["latestMainFrontendLint"] == "PASS"
    assert verification["latestMainPlaywrightT024"] == "14 passed"
    assert verification["latestMainDiffCheck"] == "PASS"
    assert verification["latestMainFunctionalRegression"] == "FULL_PASS"
    assert verification["postTraceRefreshFullVerification"] == "PASS"
    assert verification["onlineE2E"] == "NOT_RUN_NOT_CLAIMED"
