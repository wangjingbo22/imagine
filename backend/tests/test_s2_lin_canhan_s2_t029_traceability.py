from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[2]
TRACE = ROOT / "docs" / "traceability" / "sprint2" / "lin_canhan_s2_t029_day2.json"


def _trace() -> dict[str, object]:
    return json.loads(TRACE.read_text(encoding="utf-8"))


def test_t029_trace_locks_owner_pbi_ac_and_requirement_ranges() -> None:
    trace = _trace()
    assert trace["owner"] == "林粲涵"
    assert trace["verifiedAgainstMainCommit"] == "10d1742885675694ea0b13c5d20d2e498ef67608"
    implementation = trace["implementationCommit"]
    assert implementation == "00f7ef692b5b3a5ef1b5d711af68456eeff41a66"
    assert re.fullmatch(r"[0-9a-f]{40}", implementation)
    assert trace["pbi"]["pbiId"] == "PBI-15-A"
    assert trace["pbi"]["acceptanceCriteriaId"] == "AC-15-B"
    source = "doc/行知旅伴_V2.3_Sprint2待办列表_含负责人_新增需求修订版.xlsx"
    assert (ROOT / source).is_file()
    assert {
        (item["sheet"], item["range"])
        for item in trace["requirementsSource"]
    } == {
        ("SprintBacklog模板", "A33:V33"),
        ("PBI追溯", "A15:J15"),
        ("用户功能验收清单", "A6:J6"),
        ("用户功能验收清单", "A8:J8"),
    }


def test_t029_task_scope_and_every_evidence_path_are_resolvable() -> None:
    task = _trace()["task"]
    assert task["taskId"] == "S2-T029"
    assert task["dependsOn"] == ["S2-T003"]
    assert task["owner"] == "林粲涵"
    assert task["deliveryDay"] == "Day2"
    assert task["remainingHours"] == 2
    for key in (
        "moduleFiles",
        "integrationFiles",
        "contractFiles",
        "fixtureFiles",
        "testFiles",
    ):
        for path in task[key]:
            assert (ROOT / path).is_file(), path


def test_t029_linkages_and_authority_boundaries_remain_fail_closed() -> None:
    trace = _trace()
    links = {(item["from"], item["to"]): item for item in trace["crossTaskLinkages"]}
    assert set(links) == {
        ("S2-T003", "S2-T029"),
        ("S2-T027", "S2-T029"),
        ("S2-T029", "S2-T028"),
        ("S2-T029", "S2-T030"),
    }
    for link in links.values():
        for path in link["evidenceFiles"]:
            assert (ROOT / path).is_file(), path
    boundaries = trace["authorityBoundaries"]
    assert boundaries["llm"] == "NO_AUTHORITY_CONFLICTS_AND_RELAXATIONS_ARE_DETERMINISTIC"
    assert boundaries["organizer"] == "MAY_EXECUTE_ONLY_ORGANIZER_SCOPED_RELAXATIONS"
    assert boundaries["participant"] == "MAY_EXECUTE_ONLY_OWN_PARTICIPANT_SCOPED_RELAXATIONS"
    assert boundaries["readiness"] == "ALL_MEMBERS_CURRENT_REVISION_CONFIRMED_AND_ZERO_ISSUES_REQUIRED"


def test_t029_upstream_gaps_are_explicit_and_not_claimed_complete() -> None:
    trace = _trace()
    gaps = trace["knownGaps"]
    assert gaps["t002ProductionRevisionPort"] == "UNAVAILABLE_CREATE_CONVERSATION_RETURNS_503"
    assert gaps["memberConversationFrontendMigration"] == "OWNED_BY_UPSTREAM_S2_T027_AND_NOT_CLAIMED"
    assert gaps["publicNetworkE2E"] == "NOT_RUN_NOT_CLAIMED"
    assert trace["localVerification"]["onlineE2E"] == "NOT_RUN_NOT_CLAIMED"
    assert trace["localVerification"]["status"] == "PASS"
    assert trace["localVerification"]["focusedBackendResult"] == "67 passed"
    assert trace["localVerification"]["backendResult"] == "537 passed"
    assert trace["localVerification"]["frontendTest"] == "37 passed"
    assert trace["localVerification"]["frontendBuild"] == "PASS"
    assert trace["localVerification"]["frontendLint"] == "PASS_WITH_2_EXISTING_WARNINGS"
    assert trace["localVerification"]["diffCheck"] == "PASS"
    assert trace["neededInputs"]
