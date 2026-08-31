from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[2]
TRACE = (
    ROOT
    / "docs"
    / "traceability"
    / "sprint2"
    / "lin_canhan_s2_t032_day3.json"
)


def _trace() -> dict[str, object]:
    return json.loads(TRACE.read_text(encoding="utf-8"))


def test_t032_trace_locks_owner_pbi_ac_and_authoritative_ranges() -> None:
    trace = _trace()
    assert trace["schemaVersion"] == "1.0"
    assert trace["sprint"] == "Sprint2"
    assert trace["deliveryDay"] == "Day3"
    assert trace["owner"] == "林粲涵"
    assert trace["pbi"]["pbiId"] == "PBI-17-A"
    assert trace["pbi"]["acceptanceCriteriaId"] == "AC-17-A"
    assert trace["task"]["taskId"] == "S2-T032"

    source = "doc/行知旅伴_V2.3_Sprint2待办列表_含负责人_新增需求修订版.xlsx"
    assert (ROOT / source).is_file()
    assert {
        (item["sheet"], item["range"], item["role"], item["file"])
        for item in trace["requirementsSource"]
    } == {
        ("SprintBacklog模板", "A36:V36", "AUTHORITATIVE_TASK_ROW", source),
        ("PBI追溯", "A17:J17", "AUTHORITATIVE_PBI_ROW", source),
        (
            "用户功能验收清单",
            "A4:J15",
            "SUPPORTING_SUB_UATS_ONLY",
            source,
        ),
        (
            "LLM接入设计",
            "A9:K10",
            "AUTHORITY_AND_MANUAL_ACCEPTANCE_BOUNDARY",
            source,
        ),
        (
            "版权说明",
            "A10:B14",
            "EVIDENCE_AND_EXTERNAL_INPUT_POLICY",
            source,
        ),
    }


def test_t032_uat_id_is_honestly_scoped_to_backlog_o36() -> None:
    uat = _trace()["uat"]
    assert uat["uatId"] == "UAT-S2-E2E-001"
    assert uat["scenarioName"] == "E2E-S2-新增需求-多人六问到回忆闭环"
    assert uat["sourceCell"] == "SprintBacklog模板!O36"
    assert uat["registrationStatus"] == (
        "PLANNED_ID_IN_BACKLOG_O36_NO_DEDICATED_UAT_ROW"
    )
    assert uat["supportingUatIds"] == [
        f"UAT-S2-{index:03d}" for index in range(1, 13)
    ]
    assert _trace()["knownGaps"]["uatRegistration"] == (
        "UAT_ID_EXISTS_ONLY_IN_BACKLOG_O36_NO_DEDICATED_ACCEPTANCE_ROW"
    )


def test_t032_scope_dependencies_and_all_declared_artifacts_resolve() -> None:
    task = _trace()["task"]
    assert task["owner"] == "林粲涵"
    assert task["collaborators"] == "全员配合"
    assert task["deliveryDay"] == "Day3"
    assert task["priority"] == "Must"
    assert task["storyPoints"] == 3
    assert task["sourceRemainingHours"] == 3
    assert task["sourceStatus"] == "未开始"
    assert task["status"] == "LOCAL_AUTOMATION_PASS_PUBLIC_UAT_NOT_RUN"
    assert task["dependsOn"] == [
        "S2-T025",
        "S2-T026",
        "S2-T027",
        "S2-T028",
        "S2-T029",
        "S2-T030",
        "S2-T031",
        "S2-T012",
        "S2-T023",
    ]
    assert task["requirementImpliedDependencies"] == [
        "S2-T013~S2-T016 GPS_AND_EXECUTION",
        "S2-T017~S2-T018 MEMORY_TIMELINE",
    ]
    for key in (
        "documentationFiles",
        "moduleFiles",
        "integrationFiles",
        "testFiles",
    ):
        for path in task[key]:
            assert (ROOT / path).is_file(), path


def test_t032_journey_and_responsive_contract_cover_the_full_named_scenario() -> None:
    trace = _trace()
    assert trace["task"]["journeyPhases"] == [
        "ORGANIZER_SIX_QUESTION_CONFIRMATION",
        "TWO_ONE_TIME_INVITATIONS",
        "TWO_ISOLATED_MEMBER_SESSIONS",
        "ALL_MEMBER_CONFIRMATION_GATE",
        "HARD_CONFLICT_REVIEW_AND_RELAXATION",
        "ALL_THREE_RECONFIRM_CURRENT_REVISION",
        "READY_TO_PLAN",
        "FACTREF_BACKED_UNIQUE_RECOMMENDATION",
        "SHARED_THREE_PARTICIPANT_V1",
        "EXECUTION_AND_ARRIVAL_EVIDENCE",
        "TASK_BOUND_PHOTO_LIFECYCLE",
        "LATE_OR_FATIGUE_PROPOSED_V2",
        "ORGANIZER_DECISION",
        "ORDERED_MEMORY_TIMELINE",
        "PUBLIC_375_AND_768_ACCEPTANCE",
    ]
    uat = trace["uat"]
    assert [(item["width"], item["height"]) for item in uat["viewports"]] == [
        (375, 812),
        (768, 1024),
    ]
    assert set(uat["responsiveRequirements"]) == {
        "NO_HORIZONTAL_SCROLL",
        "NO_TEXT_OR_CONTROL_OVERLAP",
        "PRIMARY_ACTION_MIN_44_PX",
        "STATUS_PERMISSION_AND_FAILURE_VISIBLE",
        "KEY_AMOUNTS_TIMES_AND_DIFF_READABLE",
        "KEYBOARD_FOCUS_VISIBLE_AND_ORDERED",
        "REDUCED_MOTION_SUPPORTED",
    }


def test_t032_cross_task_linkages_resolve_and_end_at_pbi_17_a() -> None:
    links = {
        (item["from"], item["to"]): item
        for item in _trace()["crossTaskLinkages"]
    }
    assert set(links) == {
        ("S2-T025~S2-T027", "S2-T032"),
        ("S2-T028~S2-T029", "S2-T032"),
        ("S2-T030~S2-T031", "S2-T032"),
        ("S2-T012~S2-T018", "S2-T032"),
        ("S2-T019~S2-T023", "S2-T032"),
        ("S2-T032", "PBI-17-A"),
    }
    for link in links.values():
        for path in link["evidenceFiles"]:
            assert (ROOT / path).is_file(), path
    assert links[("S2-T032", "PBI-17-A")]["artifact"] == (
        "UAT-S2-E2E-001 验收包"
    )


def test_t032_authority_boundaries_keep_llm_provider_frontend_and_sessions_scoped() -> None:
    boundaries = _trace()["authorityBoundaries"]
    assert boundaries["frontend"] == (
        "COLLECT_DISPLAY_CONFIRM_AND_TRIGGER_ONLY_NO_FACT_AMOUNT_SCORE_OR_STATE_REWRITE"
    )
    assert boundaries["llm"] == (
        "ONE_PARSE_PER_COMPLETED_TRANSCRIPT_EXTRACT_AND_EXPLAIN_ONLY_NO_FACT_OR_STATE_AUTHORITY"
    )
    assert boundaries["provider"] == (
        "AMAP_OR_CACHE_OWNS_PLACE_ROUTE_PRICE_AND_FACILITY_FACTS"
    )
    assert boundaries["backend"] == (
        "DETERMINISTIC_CONFLICT_SCORE_ORDER_PASS_PLAN_VERSION_AND_STATE_TRANSITIONS"
    )
    assert boundaries["organizer"] == (
        "ONLY_ORGANIZER_MAY_CONFIRM_OR_REJECT_V1_AND_V2"
    )
    assert boundaries["participantSession"] == (
        "MAY_READ_AND_EDIT_ONLY_BOUND_PARTICIPANT"
    )


def test_t032_local_pass_cannot_be_mistaken_for_public_or_device_pass() -> None:
    trace = _trace()
    base = trace["verifiedAgainstMainCommit"]
    assert base == "e248e9ad88db9b4f40b2ed087844df7fcdeae10b"
    assert re.fullmatch(r"[0-9a-f]{40}", base)
    assert trace["implementationRevision"] == "WORKTREE_PENDING_COMMIT"

    local = trace["localVerification"]
    assert local["status"] == "LOCAL_AUTOMATION_PASS"
    assert local["backendMultiplayerResult"] == (
        "PASS_1_TEST_LOCAL_ASGI_SQLITE_TEST_DOUBLES"
    )
    assert local["traceabilityResult"] == "PASS_8_TESTS"
    assert local["frontendCommand"] == "npm test"
    assert local["frontendResult"] == (
        "PASS_71_TESTS_INCLUDING_4_T032_MEMORY_CONTRACTS"
    )
    assert local["frontendBuild"] == "PASS_WITH_RUNTIME_CONFIG_SCRIPT_WARNING"
    assert local["frontendPlaywrightResult"] == (
        "PASS_4_LOCAL_MOCKED_UI_CONTRACTS_AT_375_AND_768"
    )
    assert local["browserMode"] == (
        "LOCAL_MOCKED_UI_CONTRACT_ONLY_NO_CONTINUOUS_REAL_BACKEND_CLAIM"
    )
    assert local["formalPostRecommendationsOrchestration"] == "NOT_CLAIMED"

    public = trace["publicVerification"]
    assert trace["uat"]["publicResult"] == "PUBLIC_UAT_NOT_RUN"
    assert public["status"] == "PUBLIC_UAT_NOT_RUN"
    assert public["threeIndependentBrowserSessions"] == "NOT_RUN"
    assert public["realAmap"] == "NOT_RUN"
    assert public["realBailian"] == "NOT_RUN"
    assert public["realGps"] == "NOT_RUN"
    assert public["realCameraOrFileUpload"] == "NOT_RUN"
    assert public["viewport375"] == "NOT_RUN"
    assert public["viewport768"] == "NOT_RUN"
    assert public["teacherSignoff"] == "PENDING"
    assert trace["neededInputs"]


def test_t032_public_documents_forbid_mock_and_secret_evidence_as_public_pass() -> None:
    acceptance = (
        ROOT / "docs" / "testing" / "s2_t032_multiplayer_public_acceptance.md"
    ).read_text(encoding="utf-8")
    evidence = (
        ROOT / "docs" / "testing" / "evidence" / "s2_t032" / "README.md"
    ).read_text(encoding="utf-8")

    for text in (acceptance, evidence):
        assert "PUBLIC_UAT_NOT_RUN" in text
        assert "SprintBacklog模板!O36" in text
        assert "一次性邀请 token" in text
        assert "375" in text and "768" in text
        assert "真实高德" in text
        assert "真实" in text and "GPS" in text
    assert "Mock" in acceptance
    assert "占位截图" in evidence
    assert "当前 `NOT_RUN` 不创建 manifest" in evidence
