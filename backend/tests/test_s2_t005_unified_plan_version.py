from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.api import plan_routes
from app.application.collaboration_ports import ReadinessPermit
from app.application.planning_boundary_service import PlanningBoundaryService
from app.application.plan_service import PlanVersionService
from app.core.errors import AppError
from app.domain.collaboration import TripFlowKind
from app.domain.trip_draft import CareDraft, CareNapWindow, CareWalkLimits
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
)
from app.schemas.plan import PlanVersion, PlanVersionReason, PlanVersionStatus
from app.schemas.planning import (
    EventDrivenReplanRequest,
    ReplanGenerationRequest,
    ReplanRequestCandidate,
)
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.infrastructure.workflow_store import SqliteWorkflowRepository
from app.services.planning.models import CandidatePlanRequest
from app.services.planning.planner import (
    candidate_to_proposed_plan_version,
    candidate_to_proposed_plan_version_v2,
    generate_candidate_plan,
    generate_proposed_plan_version,
)
from app.services.replanning import SuffixPlanningInput
from backend.tests.s2_t003_support import FakeRevision
from backend.tests.test_candidate_planner import (
    _payload,
    _payload_for_trip_shape,
    _request,
)


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


def _collaboration_permit(revision: FakeRevision) -> ReadinessPermit:
    return ReadinessPermit(
        trip_id=revision.trip_id,
        readiness_digest="a" * 64,
        operation_id="projection-test-0001",
        operation=PlanningOperation.GENERATE_V1,
        flow_kind=TripFlowKind.COLLABORATION_V2,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
        current_revision=revision.revision,
        revision=revision,
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
    database_path = tmp_path / f"{mode.lower()}-{participant_count}-{decision}.sqlite3"
    plan_service = PlanVersionService(
        SqlitePlanVersionRepository(database_path)
    )
    v1_proposal = generate_proposed_plan_version(request)
    v1 = plan_service.register_proposed(
        v1_proposal,
        readiness_permit=_legacy_permit(
            v1_proposal.trip_snapshot.trip_id,
            PlanningOperation.GENERATE_V1,
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

    candidate = generate_candidate_plan(request)
    v2_proposal = candidate_to_proposed_plan_version_v2(
        candidate,
        request,
        current,
        reason=PlanVersionReason.USER_FEEDBACK,
    )
    v2 = plan_service.register_proposed(
        v2_proposal,
        readiness_permit=_legacy_permit(
            trip_id,
            PlanningOperation.GENERATE_V2,
        ),
    )
    before_decision = plan_service.get_trip_state(trip_id)
    assert before_decision.current_plan is not None
    assert before_decision.current_plan.plan_id == v1.plan_id
    assert [item.status for item in plan_service.list_plan_versions(trip_id)] == [
        PlanVersionStatus.CURRENT,
        PlanVersionStatus.PROPOSED,
    ]
    assert len(plan_service.get_diff(trip_id, v2.plan_id).items) >= 0

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
