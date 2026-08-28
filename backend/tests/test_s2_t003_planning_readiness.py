from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID

import pytest

from app.application.collaboration_ports import PlanningAccess, PlanningOperation
from app.application.planning_boundary_service import PlanningBoundaryService
from app.core.errors import AppError
from app.services.replanning import DeterministicRetainedSuffixPlanner


TRIP_ID = UUID("66666666-6666-4666-8666-666666666666")


class RejectingReadinessGuard:
    @contextmanager
    def operation(self, access: PlanningAccess):
        raise AppError(
            "COLLABORATION_NOT_READY",
            "全部成员确认并解决冲突后才能继续",
            409,
            False,
        )
        yield


def _access(operation: PlanningOperation) -> PlanningAccess:
    return PlanningAccess(
        trip_id=TRIP_ID,
        organizer_capability="organizer-token",
        operation_id=f"planning-{operation.value.lower()}",
        operation=operation,
    )


def _service() -> PlanningBoundaryService:
    return PlanningBoundaryService(
        plan_service=object(),  # type: ignore[arg-type]
        workflow_service=object(),  # type: ignore[arg-type]
        trust_repository=object(),  # type: ignore[arg-type]
        suffix_planner=DeterministicRetainedSuffixPlanner(),
        readiness_guard=RejectingReadinessGuard(),
    )


@pytest.mark.parametrize(
    ("operation", "invoke"),
    [
        (
            PlanningOperation.GENERATE_V1,
            lambda service, access: service.generate_v1(
                TRIP_ID, None, access=access
            ),
        ),
        (
            PlanningOperation.CONFIRM_REVIEW,
            lambda service, access: service.get_review(
                TRIP_ID, "review-id", access=access
            ),
        ),
        (
            PlanningOperation.CONFIRM_REVIEW,
            lambda service, access: service.confirm_review(
                TRIP_ID, "review-id", None, access=access
            ),
        ),
        (
            PlanningOperation.GENERATE_V2,
            lambda service, access: service.generate_v2(
                TRIP_ID, None, access=access
            ),
        ),
        (
            PlanningOperation.GENERATE_V2,
            lambda service, access: service.generate_v2_from_events(
                TRIP_ID, None, access=access
            ),
        ),
        (
            PlanningOperation.GENERATE_V2,
            lambda service, access: service.generate_v2_from_adjustment(
                TRIP_ID, None, access=access
            ),
        ),
        (
            PlanningOperation.PLAN_DECISION,
            lambda service, access: service.require_v1_confirmation(
                TRIP_ID, UUID(int=1), access=access
            ),
        ),
        (
            PlanningOperation.PLAN_DECISION,
            lambda service, access: service.require_v2_acceptance(
                TRIP_ID, UUID(int=1), access=access
            ),
        ),
        (
            PlanningOperation.PLAN_DECISION,
            lambda service, access: service.require_adjustment_v2_decision(
                TRIP_ID, UUID(int=1), access=access
            ),
        ),
        (
            PlanningOperation.GENERATE_V1,
            lambda service, access: service.get_planning_facts(
                TRIP_ID, access=access
            ),
        ),
    ],
)
def test_not_ready_planning_has_zero_downstream_calls(operation, invoke) -> None:
    service = _service()

    with pytest.raises(AppError, match="全部成员确认"):
        invoke(service, _access(operation))


def test_access_operation_mismatch_is_rejected_before_planning() -> None:
    service = _service()
    access = _access(PlanningOperation.GENERATE_V2)

    with pytest.raises(AppError) as captured:
        service.generate_v1(TRIP_ID, None, access=access)

    assert captured.value.code == "PLANNING_ACCESS_INVALID"
