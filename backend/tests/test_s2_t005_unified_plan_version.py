from __future__ import annotations

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
from app.schemas.trip import PlanReviewTripSnapshot
from app.schemas.execution_replan import ExecutionReplanReadinessBinding
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.services.planning.models import CandidatePlanRequest
from app.services.planning.planner import generate_proposed_plan_version
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
