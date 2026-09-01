from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.api import plan_routes
from app.application.collaboration_ports import (
    PlanningAccess,
    ReadinessPermit,
)
from app.application.collaboration_readiness import SqliteCollaborationReadinessGuard
from app.application.collaboration_service import CollaborationService
from app.application.planning_boundary_service import PlanningBoundaryService
from app.application.plan_service import PlanVersionService
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.collaboration import TripFlowKind
from app.domain.collaboration_digest import member_digest, shared_digest
from app.domain.hard_conflicts import DeterministicHardConflictEvaluator
from app.domain.trip_draft import (
    CareDraft,
    CareNapWindow,
    CareWalkLimits,
    TripUnderstandingProposal,
)
from app.application.collaboration_ports import PlanningOperation
from app.application.workflow_service import WorkflowService
from app.schemas.trip import PlanReviewTripSnapshot
from app.schemas.execution_replan import ExecutionReplanReadinessBinding
from app.schemas.execution import CreateExecutionEvent, ExecutionEventType
from app.schemas.execution_adjustment import (
    ConfirmedExecutionAdjustment,
    ExecutionAdjustmentType,
)
from app.schemas.execution_replan import (
    ExecutionAdjustmentReplanRequest,
    ExecutionAdjustmentDecision,
)
from app.schemas.plan import PlanVersion, PlanVersionReason, PlanVersionStatus
from app.schemas.planning import (
    EventDrivenReplanRequest,
    ReplanGenerationRequest,
    ReplanRequestCandidate,
)
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.infrastructure.collaboration_store import SqliteCollaborationRepository
from app.infrastructure.trusted_planning_store import SqliteTrustedPlanningRepository
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.main import create_app
from app.services.planning.models import CandidatePlanRequest
from app.services.planning.planner import (
    candidate_to_proposed_plan_version,
    candidate_to_proposed_plan_version_v2,
    generate_candidate_plan,
    generate_proposed_plan_version,
)
from app.services.replanning import SuffixPlanningInput
from backend.tests.s2_t003_support import FakeRevision, FakeTripDraftRevisionPort
from backend.tests.test_candidate_planner import (
    _payload,
    _payload_for_trip_shape,
    _request,
)
from backend.tests.plan_support import UnusedLocationService


@pytest.mark.parametrize(
    ("mode", "participant_count"),
    [("SINGLE", 1), ("GROUP", 2), ("GROUP", 3)],
    ids=["single-one", "group-two", "group-three"],
)
def test_plan_review_snapshot_admits_unified_participant_matrix(
    mode: str,
    participant_count: int,
) -> None:
    request = _request(_payload_for_trip_shape(mode, participant_count))
    payload = request.trip.model_dump(mode="json", by_alias=True)
    payload["status"] = "PLAN_REVIEW"

    snapshot = PlanReviewTripSnapshot.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )

    assert snapshot.mode.value == mode
    assert len(snapshot.participants) == participant_count


@pytest.mark.parametrize(
    ("mode", "participant_count"),
    [("SINGLE", 2), ("GROUP", 1), ("GROUP", 4)],
    ids=["single-two", "group-one", "group-four"],
)
def test_plan_review_snapshot_rejects_invalid_participant_matrix(
    mode: str,
    participant_count: int,
) -> None:
    payload = deepcopy(_payload())
    payload = payload["request"]["trip"]
    participants = payload["participants"]
    while len(participants) < participant_count:
        clone = deepcopy(participants[-1])
        clone["participantId"] = (
            f"10000000-0000-4000-8000-{len(participants) + 100:012d}"
        )
        clone["nickname"] = f"Member {len(participants) + 1}"
        participants.append(clone)
    payload["mode"] = mode
    payload["participants"] = participants[:participant_count]
    payload["status"] = "PLAN_REVIEW"

    with pytest.raises(ValidationError):
        PlanReviewTripSnapshot.model_validate_json(
            json.dumps(payload, ensure_ascii=False),
            strict=True,
        )


def _request_for_shape(mode: str, participant_count: int) -> CandidatePlanRequest:
    return _request(_payload_for_trip_shape(mode, participant_count))


def _revision_for_request(request: CandidatePlanRequest) -> FakeRevision:
    day = request.trip.days[0]
    trip = request.trip
    understanding = SimpleNamespace(
        trip=SimpleNamespace(
            city_name=trip.city_context.city_name,
            travel_date=trip.start_date,
            start_time=day.time_window.start.strftime("%H:%M"),
            end_time=day.time_window.end.strftime("%H:%M"),
            start_location_text=day.start_location_text,
            end_location_text=day.end_location_text,
            budget_cents=trip.total_budget_cents,
        ),
        participants=[
            SimpleNamespace(
                member_key=f"member-{index}",
                nickname=participant.nickname,
                budget_cap_cents=participant.budget_cap_cents,
                interests=[
                    item.value
                    for item in participant.preferences
                    if item.type.value == "INTEREST"
                ],
                must_visit=[
                    item.value
                    for item in participant.preferences
                    if item.type.value == "MUST_VISIT"
                ],
                avoid_places=[
                    item.value
                    for item in participant.preferences
                    if item.type.value == "AVOID_PLACE"
                ],
                care_draft=(
                    None
                    if participant.assistance_profile is None
                    else CareDraft(
                        assistance_type_hint=participant.assistance_profile.type.value,
                        child_age=participant.assistance_profile.child_age,
                        walk_limits=CareWalkLimits(
                            max_continuous_meters=(
                                participant.assistance_profile.walk_limits.max_continuous_meters
                            ),
                            max_daily_meters=(
                                participant.assistance_profile.walk_limits.max_daily_meters
                            ),
                        ),
                        max_transfers=participant.assistance_profile.max_transfers,
                        rest_interval_minutes=participant.assistance_profile.rest_interval,
                        nap_window=(
                            None
                            if participant.assistance_profile.nap_window is None
                            else CareNapWindow(
                                start=participant.assistance_profile.nap_window.start.strftime(
                                    "%H:%M"
                                ),
                                end=participant.assistance_profile.nap_window.end.strftime(
                                    "%H:%M"
                                ),
                            )
                        ),
                        avoid_stairs=participant.assistance_profile.avoid_stairs,
                    )
                ),
            )
            for index, participant in enumerate(trip.participants, start=1)
        ],
    )
    bindings = {
        f"member-{index}": participant.participant_id
        for index, participant in enumerate(trip.participants, start=1)
    }
    return FakeRevision(
        draft_id=UUID("20000000-0000-4000-8000-000000000001"),
        revision=1,
        trip_id=trip.trip_id,
        understanding=understanding,
        member_bindings=bindings,
        source_digest="a" * 64,
    )


def _collaboration_permit(
    revision: FakeRevision,
    operation: PlanningOperation = PlanningOperation.GENERATE_V1,
) -> ReadinessPermit:
    return ReadinessPermit(
        trip_id=revision.trip_id,
        readiness_digest="a" * 64,
        operation_id="projection-test-0001",
        operation=operation,
        flow_kind=TripFlowKind.COLLABORATION_V2,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
        current_revision=revision.revision,
        revision=revision,
    )


def _authoritative_revision_for_request(
    request: CandidatePlanRequest,
) -> FakeRevision:
    draft = _revision_for_request(request)
    trip = request.trip
    day = trip.days[0]
    understanding_participants = draft.understanding.participants
    trip_raw = {
        "cityName": trip.city_context.city_name,
        "travelDate": trip.start_date.isoformat(),
        "startTime": day.time_window.start.strftime("%H:%M"),
        "endTime": day.time_window.end.strftime("%H:%M"),
        "startLocationText": day.start_location_text,
        "endLocationText": day.end_location_text,
        "budgetCents": trip.total_budget_cents,
    }
    evidence: list[dict[str, object]] = []

    def add_evidence(
        field_path: str,
        value: object,
        *,
        member_key: str | None = None,
    ) -> None:
        if value is None:
            return
        evidence.append({
            "fieldPath": field_path,
            "memberKey": member_key,
            "sourceType": "EXPLICIT_FIELD",
            "sourceText": str(value),
        })

    for field, value in trip_raw.items():
        add_evidence(f"trip.{field}", value)

    participants_raw: list[dict[str, object]] = []
    for index, (participant, understanding) in enumerate(
        zip(trip.participants, understanding_participants, strict=True)
    ):
        member_key = understanding.member_key
        participant_raw = {
            "memberKey": member_key,
            "nickname": participant.nickname,
            "budgetCapCents": participant.budget_cap_cents,
            "interests": [
                item.value
                for item in participant.preferences
                if item.type.value == "INTEREST"
            ],
            "mustVisit": [
                item.value
                for item in participant.preferences
                if item.type.value == "MUST_VISIT"
            ],
            "avoidPlaces": [
                item.value
                for item in participant.preferences
                if item.type.value == "AVOID_PLACE"
            ],
            "careDraft": (
                understanding.care_draft.model_dump(mode="json", by_alias=True)
                if understanding.care_draft is not None
                else None
            ),
        }
        add_evidence(
            f"participants[{index}].nickname",
            participant_raw["nickname"],
            member_key=member_key,
        )
        add_evidence(
            f"participants[{index}].budgetCapCents",
            participant_raw["budgetCapCents"],
            member_key=member_key,
        )
        for field in ("interests", "mustVisit", "avoidPlaces"):
            for value_index, value in enumerate(participant_raw[field]):
                add_evidence(
                    f"participants[{index}].{field}[{value_index}]",
                    value,
                    member_key=member_key,
                )
        care = participant_raw["careDraft"]
        if isinstance(care, dict):
            care_paths = {
                "assistanceTypeHint": care.get("assistanceTypeHint"),
                "childAge": care.get("childAge"),
                "walkLimits.maxContinuousMeters": (
                    care.get("walkLimits", {}).get("maxContinuousMeters")
                ),
                "walkLimits.maxDailyMeters": (
                    care.get("walkLimits", {}).get("maxDailyMeters")
                ),
                "maxTransfers": care.get("maxTransfers"),
                "restIntervalMinutes": care.get("restIntervalMinutes"),
                "careDraft.napWindow.start": (
                    care.get("napWindow", {}).get("start")
                    if care.get("napWindow") is not None
                    else None
                ),
                "careDraft.napWindow.end": (
                    care.get("napWindow", {}).get("end")
                    if care.get("napWindow") is not None
                    else None
                ),
                "avoidStairs": care.get("avoidStairs"),
            }
            for field, value in care_paths.items():
                if field.startswith("careDraft."):
                    path = f"participants[{index}].{field}"
                else:
                    path = f"participants[{index}].careDraft.{field}"
                add_evidence(path, value, member_key=member_key)
        participants_raw.append(participant_raw)

    understanding = TripUnderstandingProposal.model_validate_json(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "trip": trip_raw,
                "participants": participants_raw,
                "fieldEvidence": evidence,
                "missingFields": [],
                "ambiguities": [],
                "confirmationQuestions": [],
            },
            ensure_ascii=False,
        ),
        strict=True,
    )
    return FakeRevision(
        draft_id=draft.draft_id,
        revision=draft.revision,
        trip_id=draft.trip_id,
        understanding=understanding,
        member_bindings=draft.member_bindings,
        source_digest=draft.source_digest,
    )


def _legacy_permit(trip_id: UUID, operation: PlanningOperation) -> ReadinessPermit:
    return ReadinessPermit(
        trip_id=trip_id,
        readiness_digest="legacy",
        operation_id="unified-state-legacy-0001",
        operation=operation,
        flow_kind=TripFlowKind.LEGACY_SINGLE,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )


def _boundary() -> PlanningBoundaryService:
    return PlanningBoundaryService.__new__(PlanningBoundaryService)


def _collaboration_readiness() -> ExecutionReplanReadinessBinding:
    return ExecutionReplanReadinessBinding(
        readiness_digest="a" * 64,
        current_revision=1,
        flow_kind=TripFlowKind.COLLABORATION_V2,
    )


def test_issued_collaboration_plan_requires_immutable_readiness_evidence() -> None:
    boundary = _boundary()
    plan = SimpleNamespace(plan_id=UUID("33333333-3333-4333-8333-333333333333"))
    boundary.plan_service = SimpleNamespace(
        get_plan_version=lambda _trip_id, _plan_id: plan,
    )
    boundary.trust_repository = SimpleNamespace(
        get_issued_validation=lambda **_kwargs: {"validator": "T011"},
    )

    with pytest.raises(AppError) as captured:
        boundary._require_issued_readiness(
            UUID("11111111-1111-4111-8111-111111111111"),
            plan.plan_id,
            boundary_kind="V1",
            current=_collaboration_readiness(),
        )

    assert captured.value.code == "PLAN_READINESS_BINDING_CHANGED"
    assert captured.value.http_status == 409


def test_missing_historical_legacy_readiness_is_normalized() -> None:
    boundary = _boundary()
    plan = SimpleNamespace(plan_id=UUID("44444444-4444-4444-8444-444444444444"))
    boundary.plan_service = SimpleNamespace(
        get_plan_version=lambda _trip_id, _plan_id: plan,
    )
    boundary.trust_repository = SimpleNamespace(
        get_issued_validation=lambda **_kwargs: {"validator": "T011"},
    )
    current = ExecutionReplanReadinessBinding(
        readiness_digest="legacy",
        current_revision=None,
        flow_kind=TripFlowKind.LEGACY_SINGLE,
    )

    boundary._require_issued_readiness(
        UUID("11111111-1111-4111-8111-111111111111"),
        plan.plan_id,
        boundary_kind="V1",
        current=current,
    )


def _state_machine_request(mode: str, participant_count: int) -> CandidatePlanRequest:
    payload = deepcopy(_payload_for_trip_shape(mode, participant_count))
    payload["request"]["taskFacts"][0]["title"] = "调整后的首个任务"
    return _request(payload)


@pytest.mark.parametrize(
    ("mode", "participant_count"),
    [("SINGLE", 1), ("GROUP", 2), ("GROUP", 3)],
    ids=["single-one", "group-two", "group-three"],
)
@pytest.mark.parametrize("decision", ["reject", "accept"])
def test_unified_state_events_diff_and_current_invariant(
    tmp_path,
    mode: str,
    participant_count: int,
    decision: str,
) -> None:
    request = _state_machine_request(mode, participant_count)
    revision = _revision_for_request(request)
    database_path = tmp_path / f"{mode.lower()}-{participant_count}-{decision}.sqlite3"
    plan_service = PlanVersionService(
        SqlitePlanVersionRepository(database_path)
    )
    v1_proposal = generate_proposed_plan_version(request)
    v1 = plan_service.register_proposed(
        v1_proposal,
        readiness_permit=(
            _legacy_permit(
                v1_proposal.trip_snapshot.trip_id,
                PlanningOperation.GENERATE_V1,
            )
            if participant_count == 1
            else _collaboration_permit(revision, PlanningOperation.GENERATE_V1)
        ),
    )
    trip_id = v1.trip_snapshot.trip_id
    assert v1.status is PlanVersionStatus.PROPOSED
    plan_service.confirm(trip_id, v1.plan_id)
    plan_service.start_execution(trip_id)
    current = plan_service.get_trip_state(trip_id).current_plan
    assert current is not None and current.status is PlanVersionStatus.CURRENT

    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    plan_service.workflow_service = workflow
    first_task = current.days[0].tasks[0]
    if decision == "reject":
        event_request = CreateExecutionEvent(
            task_id=first_task.task_id,
            plan_version_id=current.plan_id,
            event_type=ExecutionEventType.START,
            idempotency_key=f"t005-state-start-{participant_count}",
            occurred_at=datetime.now(UTC),
        )
    else:
        event_request = CreateExecutionEvent(
            task_id=first_task.task_id,
            plan_version_id=current.plan_id,
            event_type=ExecutionEventType.EXPENSE,
            amount_cents=100,
            idempotency_key=f"t005-state-expense-{participant_count}",
            occurred_at=datetime.now(UTC),
        )
    first_event = workflow.create_event(trip_id, event_request)
    replayed_event = workflow.create_event(trip_id, event_request)
    assert replayed_event.event_id == first_event.event_id
    assert len(workflow.list_events(trip_id)) == 1

    v2_payload = deepcopy(_payload_for_trip_shape(mode, participant_count))
    v2_payload["request"]["taskFacts"][1]["startAt"] = "12:00:00"
    v2_payload["request"]["taskFacts"][1]["endAt"] = "13:00:00"
    v2_request = _request(v2_payload)
    candidate = generate_candidate_plan(v2_request)
    v2_proposal = candidate_to_proposed_plan_version_v2(
        candidate,
        v2_request,
        current,
        reason=PlanVersionReason.USER_FEEDBACK,
    )
    v2 = plan_service.register_proposed(
        v2_proposal,
        readiness_permit=(
            _legacy_permit(trip_id, PlanningOperation.GENERATE_V2)
            if participant_count == 1
            else _collaboration_permit(revision, PlanningOperation.GENERATE_V2)
        ),
    )
    before_decision = plan_service.get_trip_state(trip_id)
    assert before_decision.current_plan is not None
    assert before_decision.current_plan.plan_id == v1.plan_id
    assert [item.status for item in plan_service.list_plan_versions(trip_id)] == [
        PlanVersionStatus.CURRENT,
        PlanVersionStatus.PROPOSED,
    ]
    diff = plan_service.get_diff(trip_id, v2.plan_id)
    assert diff.base_plan_id == v1.plan_id
    assert diff.candidate_plan_id == v2.plan_id
    assert diff.items
    assert any(item.key.endswith(":time_range") for item in diff.items)

    if decision == "reject":
        result = plan_service.reject_v2(trip_id, v2.plan_id)
        assert result.candidate_status is PlanVersionStatus.REJECTED
        assert result.previous_current_status is PlanVersionStatus.CURRENT
        expected_current = v1.plan_id
    else:
        result = plan_service.accept_v2(trip_id, v2.plan_id)
        assert result.candidate_status is PlanVersionStatus.CURRENT
        assert result.previous_current_status is PlanVersionStatus.SUPERSEDED
        expected_current = v2.plan_id

    versions = plan_service.list_plan_versions(trip_id)
    assert sum(item.status is PlanVersionStatus.CURRENT for item in versions) == 1
    assert plan_service.get_trip_state(trip_id).current_plan is not None
    assert plan_service.get_trip_state(trip_id).current_plan.plan_id == expected_current
    assert len(plan_service.get_trip_state(trip_id).events) == 1


@pytest.mark.parametrize(
    ("mode", "participant_count", "decision"),
    [
        ("SINGLE", 1, "accept"),
        ("GROUP", 2, "reject"),
        ("GROUP", 3, "accept"),
    ],
    ids=["real-single-accept", "real-group-reject", "real-group-accept"],
)
def test_real_collaboration_core_chain_recovers_after_restart(
    tmp_path,
    mode: str,
    participant_count: int,
    decision: str,
) -> None:
    request = _state_machine_request(mode, participant_count)
    revision = _authoritative_revision_for_request(request)
    database_path = tmp_path / f"real-{mode.lower()}-{participant_count}-{decision}.sqlite3"

    collaboration_repository = SqliteCollaborationRepository(database_path)
    bootstrap = collaboration_repository.bootstrap_collaboration(
        revision,
        f"t005-real-bootstrap-{participant_count}-{decision}",
    )
    assert bootstrap.organizer_token is not None
    expected_version = 1
    for index, member_key in enumerate(sorted(revision.member_bindings), start=1):
        expected_version = collaboration_repository.record_confirmation(
            trip_id=revision.trip_id,
            participant_id=revision.member_bindings[member_key],
            revision=revision.revision,
            source_digest=revision.source_digest,
            shared_digest=shared_digest(revision),
            member_digest=member_digest(revision, member_key),
            expected_version=expected_version,
            idempotency_key=(
                f"t005-real-confirm-{participant_count}-{decision}-{index}"
            ),
        )

    revision_port = FakeTripDraftRevisionPort(revision)
    collaboration = CollaborationService(
        repository=collaboration_repository,
        revisions=revision_port,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    readiness = SqliteCollaborationReadinessGuard(
        database_path=database_path,
        repository=collaboration_repository,
        collaboration=collaboration,
    )
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    plan_service = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=workflow,
    )
    boundary = PlanningBoundaryService(
        plan_service=plan_service,
        workflow_service=workflow,
        trust_repository=SqliteTrustedPlanningRepository(database_path),
        readiness_guard=readiness,
    )

    def access(operation: PlanningOperation, suffix: str) -> PlanningAccess:
        return PlanningAccess(
            trip_id=revision.trip_id,
            organizer_capability=bootstrap.organizer_token,
            operation_id=(
                f"t005-real-{participant_count}-{decision}-{suffix}"
            ),
            operation=operation,
        )

    v1 = boundary.generate_v1(
        revision.trip_id,
        request,
        access=access(PlanningOperation.GENERATE_V1, "v1"),
    )
    boundary.confirm_v1(
        revision.trip_id,
        v1.plan_id,
        access=access(PlanningOperation.PLAN_DECISION, "confirm"),
    )
    plan_service.start_execution(revision.trip_id)
    current = plan_service.get_trip_state(revision.trip_id).current_plan
    assert current is not None and current.plan_id == v1.plan_id

    event_request = CreateExecutionEvent(
        task_id=current.days[0].tasks[0].task_id,
        plan_version_id=current.plan_id,
        event_type=ExecutionEventType.START,
        idempotency_key=f"t005-real-event-{participant_count}-{decision}",
        occurred_at=datetime.now(UTC),
    )
    first_event = workflow.create_event(revision.trip_id, event_request)
    assert workflow.create_event(revision.trip_id, event_request).event_id == (
        first_event.event_id
    )

    v2_payload = deepcopy(_payload_for_trip_shape(mode, participant_count))
    v2_payload["request"]["taskFacts"][1]["startAt"] = "12:00:00"
    v2_payload["request"]["taskFacts"][1]["endAt"] = "13:00:00"
    v2_request = _request(v2_payload)
    generation = ReplanGenerationRequest(
        schemaVersion="1.0",
        reason=PlanVersionReason.USER_FEEDBACK,
        candidates=(
            ReplanRequestCandidate(request=v2_request, satisfaction_loss=0),
        ),
    )
    registered = boundary.generate_v2(
        revision.trip_id,
        generation,
        access=access(PlanningOperation.GENERATE_V2, "v2"),
    )
    v2 = registered.plan
    diff = plan_service.get_diff(revision.trip_id, v2.plan_id)
    assert diff.base_plan_id == v1.plan_id
    assert diff.candidate_plan_id == v2.plan_id
    assert any(item.key.endswith(":time_range") for item in diff.items)

    decision_result = boundary.decide_v2(
        revision.trip_id,
        v2.plan_id,
        accept=decision == "accept",
        access=access(PlanningOperation.PLAN_DECISION, "decision"),
    )
    assert decision_result.candidate_plan_id == v2.plan_id
    expected_current_id = v2.plan_id if decision == "accept" else v1.plan_id
    state = plan_service.get_trip_state(revision.trip_id)
    assert state.current_plan is not None
    assert state.current_plan.plan_id == expected_current_id
    assert len(state.events) == 1
    assert sum(item.status is PlanVersionStatus.CURRENT for item in (
        plan_service.list_plan_versions(revision.trip_id)
    )) == 1

    rebuilt_workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    rebuilt_service = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=rebuilt_workflow,
    )
    restored = rebuilt_service.get_trip_state(revision.trip_id)
    assert restored.current_plan is not None
    assert restored.current_plan.plan_id == expected_current_id
    assert len(restored.events) == 1
    restored_diff = rebuilt_service.get_diff(revision.trip_id, v2.plan_id)
    assert restored_diff.base_plan_id == diff.base_plan_id
    assert restored_diff.candidate_plan_id == diff.candidate_plan_id
    assert restored_diff.items == diff.items


@pytest.mark.asyncio
async def test_cross_trip_organizer_token_rejects_v1_before_plan_or_trust_write(
    tmp_path,
) -> None:
    request_a = _request_for_shape("GROUP", 2)
    request_b = request_a.model_copy(update={
        "trip": request_a.trip.model_copy(update={
            "trip_id": UUID("11111111-1111-4111-8111-111111111112")
        })
    })
    revision_a = _authoritative_revision_for_request(request_a)
    revision_b = _authoritative_revision_for_request(request_b)
    revisions_by_trip = {
        revision_a.trip_id: revision_a,
        revision_b.trip_id: revision_b,
    }

    class MultiRevisionPort:
        def get_current(self, trip_id: UUID):
            return revisions_by_trip[trip_id]

    database_path = tmp_path / "cross-trip-permission.sqlite3"
    collaboration_repository = SqliteCollaborationRepository(database_path)
    tokens: dict[UUID, str] = {}
    for index, revision in enumerate((revision_a, revision_b), start=1):
        bootstrap = collaboration_repository.bootstrap_collaboration(
            revision,
            f"t005-cross-bootstrap-{index}",
        )
        assert bootstrap.organizer_token is not None
        tokens[revision.trip_id] = bootstrap.organizer_token
        expected_version = 1
        for member_index, member_key in enumerate(
            sorted(revision.member_bindings),
            start=1,
        ):
            expected_version = collaboration_repository.record_confirmation(
                trip_id=revision.trip_id,
                participant_id=revision.member_bindings[member_key],
                revision=revision.revision,
                source_digest=revision.source_digest,
                shared_digest=shared_digest(revision),
                member_digest=member_digest(revision, member_key),
                expected_version=expected_version,
                idempotency_key=f"t005-cross-confirm-{index}-{member_index}",
            )

    revision_port = MultiRevisionPort()
    collaboration = CollaborationService(
        repository=collaboration_repository,
        revisions=revision_port,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    readiness = SqliteCollaborationReadinessGuard(
        database_path=database_path,
        repository=collaboration_repository,
        collaboration=collaboration,
    )
    workflow = WorkflowService(SqliteWorkflowRepository(database_path))
    plan_service = PlanVersionService(
        SqlitePlanVersionRepository(database_path),
        workflow_service=workflow,
    )
    boundary = PlanningBoundaryService(
        plan_service=plan_service,
        workflow_service=workflow,
        trust_repository=SqliteTrustedPlanningRepository(database_path),
        readiness_guard=readiness,
    )
    app = create_app(
        settings=Settings(
            amap_web_service_key="test-amap",
            amap_cache_db_path=tmp_path / "amap.sqlite3",
            plan_version_db_path=database_path,
        ),
        service=UnusedLocationService(),  # type: ignore[arg-type]
        plan_service=plan_service,
        workflow_service=workflow,
        planning_boundary_service=boundary,
        collaboration_repository=collaboration_repository,
        collaboration_readiness_guard=readiness,
        trip_draft_revision_port=revision_port,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        cross_trip_response = await client.post(
            f"/api/v1/trips/{revision_a.trip_id}/plan-versions/generate",
            headers={
                "X-Organizer-Token": tokens[revision_b.trip_id],
                "Idempotency-Key": "t005-cross-trip-generate-0001",
            },
            json=request_a.model_dump(mode="json", by_alias=True),
        )

        assert cross_trip_response.status_code == 403
        assert cross_trip_response.json()["code"] == "ORGANIZER_PERMISSION_REQUIRED"
        with collaboration_repository._connect() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM plan_versions"
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM trusted_plan_issuances"
            ).fetchone()[0] == 0

        generated = await client.post(
            f"/api/v1/trips/{revision_a.trip_id}/plan-versions/generate",
            headers={
                "X-Organizer-Token": tokens[revision_a.trip_id],
                "Idempotency-Key": "t005-cross-trip-generate-authorized",
            },
            json=request_a.model_dump(mode="json", by_alias=True),
        )
        assert generated.status_code == 200, generated.text
        v1_id = generated.json()["data"]["planId"]

        forged_confirm = await client.post(
            f"/api/v1/trips/{revision_a.trip_id}/plan-versions/{v1_id}/confirm",
            headers={
                "X-Organizer-Token": tokens[revision_b.trip_id],
                "Idempotency-Key": "t005-cross-trip-confirm-forged",
            },
        )
        assert forged_confirm.status_code == 403
        assert forged_confirm.json()["code"] == "ORGANIZER_PERMISSION_REQUIRED"

    assert plan_service.get_plan_version(revision_a.trip_id, UUID(v1_id)).status is (
        PlanVersionStatus.PROPOSED
    )


def test_generate_v2_keeps_one_permit_through_unified_registration() -> None:
    request = _request_for_shape("SINGLE", 1)
    proposal = generate_proposed_plan_version(request)
    current = PlanVersion.model_validate(
        {
            **proposal.model_dump(),
            "status": PlanVersionStatus.CURRENT,
            "created_at": datetime.now(UTC),
        },
        strict=True,
    )
    generation = ReplanGenerationRequest(
        schema_version="1.0",
        reason=PlanVersionReason.USER_FEEDBACK,
        candidates=(
            ReplanRequestCandidate(request=request, satisfaction_loss=0),
        ),
    )
    permit = _legacy_permit(
        current.trip_snapshot.trip_id,
        PlanningOperation.GENERATE_V2,
    )
    boundary = _boundary()
    boundary._load_current_v1_context = lambda _trip_id: (current, ())
    captured: dict[str, object] = {}

    def select(**kwargs):
        captured.update(kwargs)
        return "registered"

    boundary._select_and_register_v2 = select

    assert boundary._generate_v2_ready(
        current.trip_snapshot.trip_id,
        generation,
        readiness_permit=permit,
    ) == "registered"
    assert captured["registration_permit"] is permit
    assert captured["readiness_binding"] == boundary._readiness_binding(permit)


def test_generate_v2_from_events_uses_same_registration_permit() -> None:
    request = _request_for_shape("SINGLE", 1)
    proposal = generate_proposed_plan_version(request)
    current = PlanVersion.model_validate(
        {
            **proposal.model_dump(),
            "status": PlanVersionStatus.CURRENT,
            "created_at": datetime.now(UTC),
        },
        strict=True,
    )
    trigger = EventDrivenReplanRequest(
        schemaVersion="1.0",
        reason=PlanVersionReason.EXPENSE_CHANGE,
    )
    permit = _legacy_permit(
        current.trip_snapshot.trip_id,
        PlanningOperation.GENERATE_V2,
    )
    boundary = _boundary()
    boundary._load_current_v1_context = lambda _trip_id: (current, ())
    boundary._load_current_candidate_request = lambda _trip_id, _current: request
    boundary._event_driven_candidate_request = lambda **_kwargs: (request, ())
    captured: dict[str, object] = {}

    def select(**kwargs):
        captured.update(kwargs)
        return "registered"

    boundary._select_and_register_v2 = select

    assert boundary._generate_v2_from_events_ready(
        current.trip_snapshot.trip_id,
        trigger,
        readiness_permit=permit,
    ) == "registered"
    assert captured["registration_permit"] is permit


def test_generic_v2_revision_mismatch_rejects_before_candidate_planner(monkeypatch) -> None:
    request = _request_for_shape("GROUP", 2)
    revision = _revision_for_request(request)
    permit = _collaboration_permit(revision)
    proposal = generate_proposed_plan_version(request)
    current = PlanVersion.model_validate(
        {
            **proposal.model_dump(),
            "status": PlanVersionStatus.CURRENT,
            "created_at": datetime.now(UTC),
        },
        strict=True,
    )
    mismatched = request.model_copy(update={
        "trip": request.trip.model_copy(
            update={"total_budget_cents": request.trip.total_budget_cents + 1}
        )
    })
    boundary = _boundary()
    boundary._require_issued_readiness = lambda *args, **kwargs: None
    planner_calls = 0

    def forbidden(_request):
        nonlocal planner_calls
        planner_calls += 1
        raise AssertionError("candidate planner must not run")

    monkeypatch.setattr(
        "app.application.planning_boundary_service.generate_candidate_plan",
        forbidden,
    )
    with pytest.raises(AppError) as captured:
        boundary._select_and_register_v2(
            trip_id=current.trip_snapshot.trip_id,
            current=current,
            events=(),
            reason=PlanVersionReason.USER_FEEDBACK,
            locked_task_ids=(),
            candidate_inputs=((mismatched, 0),),
            readiness_binding=boundary._readiness_binding(permit),
            registration_permit=permit,
        )

    assert captured.value.code == "COLLABORATION_PLAN_SNAPSHOT_MISMATCH"
    assert planner_calls == 0


def test_adjustment_readiness_stale_rejects_before_suffix_planner() -> None:
    request = _request_for_shape("SINGLE", 1)
    proposal = generate_proposed_plan_version(request)
    current = PlanVersion.model_validate(
        {
            **proposal.model_dump(),
            "status": PlanVersionStatus.CURRENT,
            "created_at": datetime.now(UTC),
        },
        strict=True,
    )
    revision = _revision_for_request(request)
    permit = _collaboration_permit(revision)
    adjustment_request = ExecutionAdjustmentReplanRequest(
        schemaVersion="1.0",
        adjustment=ConfirmedExecutionAdjustment(
            schemaVersion="1.0",
            eventType=ExecutionAdjustmentType.LATE,
            taskId=current.days[0].tasks[0].task_id,
            lateMinutes=30,
            fatigueLevel=None,
        ),
    )

    class RecordingSuffixPlanner:
        calls = 0

        def plan_suffix(self, _planning_input: SuffixPlanningInput):
            self.calls += 1
            return ()

    suffix_planner = RecordingSuffixPlanner()
    boundary = _boundary()
    boundary.suffix_planner = suffix_planner
    boundary._require_adjustment_execution_state = lambda _trip_id: None
    boundary._load_current_v1_context = lambda _trip_id: (current, ())
    boundary.plan_service = SimpleNamespace(
        get_plan_version=lambda _trip_id, _plan_id: current,
    )
    boundary.trust_repository = SimpleNamespace(
        get_issued_validation=lambda **_kwargs: {
            "collaborationReadiness": {
                "flowKind": "COLLABORATION_V2",
                "readinessDigest": "b" * 64,
                "currentRevision": 1,
            }
        },
    )

    with pytest.raises(AppError) as captured:
        boundary._generate_v2_from_adjustment_ready(
            current.trip_snapshot.trip_id,
            adjustment_request,
            readiness_permit=permit,
            readiness=boundary._readiness_binding(permit),
        )

    assert captured.value.code == "PLAN_READINESS_BINDING_CHANGED"
    assert suffix_planner.calls == 0


@pytest.mark.parametrize("accept", [True, False], ids=["accept", "reject"])
def test_generic_v2_decision_revalidates_readiness_before_state_transition(
    accept: bool,
) -> None:
    plan = SimpleNamespace(
        reason=PlanVersionReason.USER_FEEDBACK,
        plan_id=UUID("55555555-5555-4555-8555-555555555555"),
    )
    permit = _legacy_permit(
        UUID("11111111-1111-4111-8111-111111111111"),
        PlanningOperation.PLAN_DECISION,
    )
    boundary = _boundary()
    boundary._planning_operation = lambda **_kwargs: nullcontext(permit)
    boundary._require_issued = lambda *args, **kwargs: None
    boundary.plan_service = SimpleNamespace(
        get_plan_version=lambda _trip_id, _plan_id: plan,
        accept_v2=lambda *_args: (_ for _ in ()).throw(
            AssertionError("stale V2 must not be accepted")
        ),
        reject_v2=lambda *_args: (_ for _ in ()).throw(
            AssertionError("stale V2 must not be rejected")
        ),
    )
    boundary.trust_repository = SimpleNamespace(
        get_issued_validation=lambda **_kwargs: {
            "collaborationReadiness": {
                "flowKind": "COLLABORATION_V2",
                "readinessDigest": "a" * 64,
                "currentRevision": 1,
            }
        },
    )

    with pytest.raises(AppError) as captured:
        boundary.decide_v2(
            permit.trip_id,
            plan.plan_id,
            accept=accept,
            access=object(),
        )

    assert captured.value.code == "PLAN_READINESS_BINDING_CHANGED"


@pytest.mark.parametrize(
    "action",
    [
        "confirm_v1",
        "accept_v2",
        "reject_v2",
        "adjustment_accept",
        "adjustment_reject",
    ],
)
def test_expired_decision_permit_is_rejected_before_state_transition(action: str) -> None:
    boundary = _boundary()
    expired = _legacy_permit(
        UUID("11111111-1111-4111-8111-111111111111"),
        PlanningOperation.PLAN_DECISION,
    )
    expired = replace(
        expired,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    boundary._planning_operation = lambda **_kwargs: nullcontext(expired)
    boundary._require_v1_confirmation_ready = lambda *args, **kwargs: None
    boundary._require_v2_acceptance_ready = lambda *args, **kwargs: None
    boundary.plan_service = SimpleNamespace(
        confirm=lambda *_args: (_ for _ in ()).throw(
            AssertionError("expired V1 permit must not confirm")
        ),
        accept_v2=lambda *_args: (_ for _ in ()).throw(
            AssertionError("expired V2 permit must not accept")
        ),
        reject_v2=lambda *_args: (_ for _ in ()).throw(
            AssertionError("expired V2 permit must not reject")
        ),
    )

    with pytest.raises(AppError) as captured:
        if action == "confirm_v1":
            boundary.confirm_v1(
                expired.trip_id,
                UUID("66666666-6666-4666-8666-666666666666"),
                access=object(),
            )
        elif action in {"accept_v2", "reject_v2"}:
            boundary.decide_v2(
                expired.trip_id,
                UUID("66666666-6666-4666-8666-666666666666"),
                accept=action == "accept_v2",
                access=object(),
            )
        else:
            boundary._require_adjustment_v2_decision_ready = (
                lambda *args, **kwargs: None
            )
            boundary.decide_adjustment_v2(
                expired.trip_id,
                UUID("66666666-6666-4666-8666-666666666666"),
                decision=(
                    ExecutionAdjustmentDecision.ACCEPT
                    if action == "adjustment_accept"
                    else ExecutionAdjustmentDecision.REJECT
                ),
                access=object(),
            )

    assert captured.value.code == "PLANNING_ACCESS_INVALID"


@pytest.mark.parametrize(
    "action",
    ["confirm_v1", "decide_v2", "decide_adjustment_v2"],
)
def test_decision_rechecks_permit_after_readiness_validation(action: str) -> None:
    boundary = _boundary()
    permit = _legacy_permit(
        UUID("11111111-1111-4111-8111-111111111111"),
        PlanningOperation.PLAN_DECISION,
    )
    boundary._planning_operation = lambda **_kwargs: nullcontext(permit)
    checks = 0
    readiness_calls = 0

    def require_unexpired(_permit: ReadinessPermit) -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise AppError(
                "PLANNING_ACCESS_INVALID",
                "permit expired during readiness validation",
                409,
                False,
            )

    def require_ready(*_args, **_kwargs) -> None:
        nonlocal readiness_calls
        readiness_calls += 1

    boundary._require_unexpired_permit = require_unexpired
    boundary._require_v1_confirmation_ready = require_ready
    boundary._require_v2_acceptance_ready = require_ready
    boundary._require_adjustment_v2_decision_ready = require_ready
    boundary.plan_service = SimpleNamespace(
        confirm=lambda *_args: (_ for _ in ()).throw(
            AssertionError("expired V1 permit must not confirm")
        ),
        accept_v2=lambda *_args: (_ for _ in ()).throw(
            AssertionError("expired V2 permit must not accept")
        ),
        reject_v2=lambda *_args: (_ for _ in ()).throw(
            AssertionError("expired V2 permit must not reject")
        ),
    )

    with pytest.raises(AppError) as captured:
        if action == "confirm_v1":
            boundary.confirm_v1(
                permit.trip_id,
                UUID("66666666-6666-4666-8666-666666666666"),
                access=object(),
            )
        elif action == "decide_v2":
            boundary.decide_v2(
                permit.trip_id,
                UUID("66666666-6666-4666-8666-666666666666"),
                accept=True,
                access=object(),
            )
        else:
            boundary.decide_adjustment_v2(
                permit.trip_id,
                UUID("66666666-6666-4666-8666-666666666666"),
                decision=ExecutionAdjustmentDecision.ACCEPT,
                access=object(),
            )

    assert captured.value.code == "PLANNING_ACCESS_INVALID"
    assert checks == 2
    assert readiness_calls == 1


@pytest.mark.parametrize(
    ("mode", "participant_count"),
    [("SINGLE", 1), ("GROUP", 2), ("GROUP", 3)],
    ids=["single-one", "group-two", "group-three"],
)
def test_collaboration_request_matches_authoritative_revision_projection(
    mode: str,
    participant_count: int,
) -> None:
    request = _request_for_shape(mode, participant_count)
    revision = _revision_for_request(request)

    _boundary()._require_collaboration_request_matches_revision(
        request,
        _collaboration_permit(revision),
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda request: request.model_copy(update={
            "trip": request.trip.model_copy(
                update={"total_budget_cents": request.trip.total_budget_cents + 1}
            )
        }),
        lambda request: request.model_copy(update={
            "trip": request.trip.model_copy(
                update={
                    "participants": [
                        request.trip.participants[0].model_copy(
                            update={
                                "participant_id": UUID(
                                    "99999999-9999-4999-8999-999999999999"
                                )
                            }
                        ),
                        *request.trip.participants[1:],
                    ]
                }
            )
        }),
        lambda request: request.model_copy(update={
            "trip": request.trip.model_copy(
                update={
                    "participants": [
                        request.trip.participants[0].model_copy(
                            update={"nickname": "伪造成员"}
                        ),
                        *request.trip.participants[1:],
                    ]
                }
            )
        }),
    ],
    ids=["shared-budget", "member-binding", "nickname"],
)
def test_collaboration_request_rejects_revision_projection_mismatch(mutation) -> None:
    request = _request_for_shape("GROUP", 2)
    revision = _revision_for_request(request)

    with pytest.raises(AppError) as captured:
        _boundary()._require_collaboration_request_matches_revision(
            mutation(request),
            _collaboration_permit(revision),
        )

    assert captured.value.code == "COLLABORATION_PLAN_SNAPSHOT_MISMATCH"
    assert captured.value.http_status == 409


def test_plan_registration_requires_readiness_permit_before_repository_write(
    tmp_path,
) -> None:
    proposal = generate_proposed_plan_version(_request_for_shape("SINGLE", 1))
    service = PlanVersionService(SqlitePlanVersionRepository(tmp_path / "plans.sqlite3"))

    with pytest.raises(AppError) as captured:
        service.register_proposed(proposal)

    assert captured.value.code == "PLANNING_ACCESS_INVALID"
    with pytest.raises(AppError) as empty:
        service.list_plan_versions(proposal.trip_snapshot.trip_id)
    assert empty.value.code == "PLAN_VERSION_NOT_FOUND"


def test_legacy_permit_rejects_group_plan_before_repository_write(tmp_path) -> None:
    proposal = generate_proposed_plan_version(_request_for_shape("GROUP", 2))
    service = PlanVersionService(SqlitePlanVersionRepository(tmp_path / "plans.sqlite3"))

    with pytest.raises(AppError) as captured:
        service.register_proposed(
            proposal,
            readiness_permit=_legacy_permit(
                proposal.trip_snapshot.trip_id,
                PlanningOperation.GENERATE_V1,
            ),
        )

    assert captured.value.code == "PLANNING_ACCESS_INVALID"
    with pytest.raises(AppError) as empty:
        service.list_plan_versions(proposal.trip_snapshot.trip_id)
    assert empty.value.code == "PLAN_VERSION_NOT_FOUND"


def test_collaboration_permit_rejects_participant_id_shape_before_repository_write(
    tmp_path,
) -> None:
    request = _request_for_shape("GROUP", 2)
    revision = _revision_for_request(request)
    changed_request = request.model_copy(update={
        "trip": request.trip.model_copy(update={
            "participants": [
                request.trip.participants[0].model_copy(update={
                    "participant_id": UUID("99999999-9999-4999-8999-999999999999")
                }),
                request.trip.participants[1],
            ]
        })
    })
    proposal = generate_proposed_plan_version(changed_request)
    service = PlanVersionService(SqlitePlanVersionRepository(tmp_path / "plans.sqlite3"))

    with pytest.raises(AppError) as captured:
        service.register_proposed(
            proposal,
            readiness_permit=_collaboration_permit(revision),
        )

    assert captured.value.code == "PLANNING_ACCESS_INVALID"
    with pytest.raises(AppError) as empty:
        service.list_plan_versions(proposal.trip_snapshot.trip_id)
    assert empty.value.code == "PLAN_VERSION_NOT_FOUND"


def test_direct_collaboration_v1_city_mismatch_stops_planner_and_state(monkeypatch) -> None:
    request = _request_for_shape("SINGLE", 1)
    revision = _revision_for_request(request)
    permit = _collaboration_permit(revision)
    changed_request = request.model_copy(update={
        "trip": request.trip.model_copy(update={
            "city_context": request.trip.city_context.model_copy(
                update={"city_name": "上海市"}
            )
        })
    })
    boundary = _boundary()
    boundary.workflow_service = SimpleNamespace(
        require_confirmed_trip=lambda _trip_id, _trip: (_ for _ in ()).throw(
            AppError("CONFIRMED_TRIP_MISMATCH", "mismatch", 409, False)
        ),
    )
    stage_calls = 0
    planner_calls = 0

    def stage_candidate(**_kwargs):
        nonlocal stage_calls
        stage_calls += 1

    def forbidden(_request):
        nonlocal planner_calls
        planner_calls += 1
        raise AssertionError("city mismatch must stop before candidate planner")

    boundary.trust_repository = SimpleNamespace(stage_candidate=stage_candidate)
    monkeypatch.setattr(
        "app.application.planning_boundary_service.generate_candidate_plan",
        forbidden,
    )
    with pytest.raises(AppError) as captured:
        boundary._generate_v1_ready(
            request.trip.trip_id,
            changed_request,
            readiness_permit=permit,
        )

    assert captured.value.code == "COLLABORATION_PLAN_SNAPSHOT_MISMATCH"
    assert planner_calls == 0
    assert stage_calls == 0


def test_planning_projection_accepts_city_administrative_suffix_alias() -> None:
    request = _request_for_shape("SINGLE", 1)
    revision = _revision_for_request(request)
    revision.understanding.trip.city_name = "北京"
    alias_request = request.model_copy(update={
        "trip": request.trip.model_copy(update={
            "city_context": request.trip.city_context.model_copy(
                update={"city_name": "北京市"}
            )
        })
    })
    boundary = _boundary()

    paths = boundary._projection_mismatch_paths(
        boundary._revision_planning_projection(revision),
        boundary._request_planning_projection(alias_request),
    )

    assert "cityName" not in paths


def test_collaboration_boundary_accepts_provider_county_city_canonical_name() -> None:
    request = _request_for_shape("SINGLE", 1)
    revision = _revision_for_request(request)
    revision.understanding.trip.city_name = "瑞安"
    canonical_request = request.model_copy(update={
        "trip": request.trip.model_copy(update={
            "city_context": request.trip.city_context.model_copy(
                update={"city_name": "温州市", "city_code": "330300"}
            )
        })
    })
    confirmed: list[object] = []
    boundary = _boundary()
    boundary.workflow_service = SimpleNamespace(
        require_confirmed_trip=lambda _trip_id, trip: confirmed.append(trip),
    )

    boundary._require_collaboration_request_matches_revision(
        canonical_request,
        _collaboration_permit(revision),
    )

    assert confirmed == [canonical_request.trip]


def test_collaboration_boundary_rejects_unconfirmed_provider_city_alias() -> None:
    request = _request_for_shape("SINGLE", 1)
    revision = _revision_for_request(request)
    revision.understanding.trip.city_name = "瑞安"
    changed_request = request.model_copy(update={
        "trip": request.trip.model_copy(update={
            "city_context": request.trip.city_context.model_copy(
                update={"city_name": "温州市", "city_code": "330300"}
            )
        })
    })
    boundary = _boundary()
    boundary.workflow_service = SimpleNamespace(
        require_confirmed_trip=lambda _trip_id, _trip: (_ for _ in ()).throw(
            AppError("CONFIRMED_TRIP_MISMATCH", "mismatch", 409, False)
        ),
    )

    with pytest.raises(AppError) as captured:
        boundary._require_collaboration_request_matches_revision(
            changed_request,
            _collaboration_permit(revision),
        )

    assert captured.value.code == "COLLABORATION_PLAN_SNAPSHOT_MISMATCH"


def test_planning_projection_fills_missing_member_identity_and_budget() -> None:
    request = _request_for_shape("GROUP", 2)
    revision = _revision_for_request(request)
    for participant in revision.understanding.participants:
        participant.nickname = None
        participant.budget_cap_cents = None

    projected = _boundary()._revision_planning_projection(revision)

    assert [item["nickname"] for item in projected["participants"]] == [
        "成员 1",
        "成员 2",
    ]
    assert [item["budgetCents"] for item in projected["participants"]] == [
        revision.understanding.trip.budget_cents,
        revision.understanding.trip.budget_cents,
    ]


def test_planning_projection_exposes_city_name_mismatch_path() -> None:
    request = _request_for_shape("SINGLE", 1)
    revision = _revision_for_request(request)
    changed_request = request.model_copy(update={
        "trip": request.trip.model_copy(update={
            "city_context": request.trip.city_context.model_copy(
                update={"city_name": "上海市"}
            )
        })
    })
    boundary = _boundary()

    paths = boundary._projection_mismatch_paths(
        boundary._revision_planning_projection(revision),
        boundary._request_planning_projection(changed_request),
    )

    assert "cityName" in paths


@pytest.mark.asyncio
async def test_v1_confirm_route_uses_boundary_atomic_confirmation(monkeypatch) -> None:
    trip_id = UUID("11111111-1111-4111-8111-111111111111")
    plan_id = UUID("22222222-2222-4222-8222-222222222222")
    access = object()
    result = object()

    class Boundary:
        def confirm_v1(self, received_trip_id, received_plan_id, *, access):
            assert (received_trip_id, received_plan_id, access) == (
                trip_id,
                plan_id,
                access,
            )
            return result

        def require_v1_confirmation(self, *args, **kwargs):
            raise AssertionError("confirmation must stay inside boundary lease")

    monkeypatch.setattr(plan_routes, "build_planning_access", lambda *args: access)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})

    response = await plan_routes.confirm_plan_version(
        trip_id,
        plan_id,
        request,
        service=object(),  # type: ignore[arg-type]
        planning=Boundary(),  # type: ignore[arg-type]
    )

    assert response.data is result
