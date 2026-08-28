from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
TRACE = (
    ROOT
    / "docs"
    / "traceability"
    / "sprint2"
    / "lin_canhan_s2_t021_t022_day2.json"
)


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
    assert trace["verifiedAgainstMainCommit"] == (
        "a43ad37a5c8b97d2b90507fa9966998bfee038b9"
    )
    assert trace["deliveryBaseCommit"] == (
        "a43ad37a5c8b97d2b90507fa9966998bfee038b9"
    )
    assert trace["implementationCommit"] == (
        "f376574a5c8c5c577d6ed43efd200293023b3b32"
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
        "BACKEND_CONTRACT_READY_T023_FRONTEND_PENDING"
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
        "T023_FRONTEND_INTEGRATION_PENDING_OUTSIDE_THIS_DELIVERY"
    )


def test_known_upstream_and_external_gaps_are_explicit_not_claimed_done() -> None:
    trace = _trace()
    gaps = trace["knownGaps"]
    assert gaps["s2T006ConcreteFactRefRegistry"] == "IMPLEMENTED"
    assert gaps["s2T006FormalOnlineRouteBuilder"] == "EXTERNAL_PENDING"
    assert gaps["s2T005TwoThreePersonPlanVersionChain"] == (
        "BLOCKED_BY_S2_T005_UPSTREAM_DELIVERY"
    )
    assert gaps["s2T023Frontend"] == "PENDING_OUTSIDE_THIS_DELIVERY"
    assert gaps["fatigueThresholds"] == "PO_CONFIRMATION_PENDING"
    assert gaps["lateBeyondRemainingWindowPolicy"] == "PO_CONFIRMATION_PENDING"
    assert gaps["onlineE2E"] == "NOT_CLAIMED"
    assert trace["localVerification"]["onlineE2E"] == "NOT_RUN_NOT_CLAIMED"
    assert trace["externalAcceptanceStillNeeded"]


def test_verification_is_pending_or_contains_real_final_results() -> None:
    verification = _trace()["localVerification"]
    assert verification["status"] in {"PENDING", "PASS"}
    if verification["status"] == "PENDING":
        assert verification["focusedResult"] == "PENDING"
        assert verification["backendResult"] == "PENDING"
        assert verification["diffCheck"] == "PENDING"
    else:
        assert verification["focusedResult"] == "42 passed"
        assert verification["boundaryResult"] == "43 passed"
        assert verification["backendResult"] == "528 passed"
        assert verification["frontendTest"] == "32 passed"
        assert verification["frontendBuild"] == "PASS"
        assert verification["frontendLint"] == "PASS"
        assert verification["diffCheck"] == "PASS"
