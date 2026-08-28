from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from collections.abc import Sequence

import pytest

from app.application.plan_service import PlanVersionService
from app.application.collaboration_ports import PlanningOperation, ReadinessPermit
from app.core.errors import AppError
from app.domain.collaboration import TripFlowKind
from app.infrastructure.plan_store import SqlitePlanVersionRepository
from app.schemas.execution import ExecutionEvent
from app.schemas.plan import PlanVersion, PlanVersionStatus, ProposedPlanVersion
from app.schemas.trip import TripStatus
from app.services.replanning import (
    MinimumDisruptionSelector,
    ReplanCandidate,
    ReplanRuleCheck,
    ReplanRuleDomain,
    ReplanValidationReport,
    SelectedReplan,
)
from app.services.route_risk import ValidationStatus
from backend.tests.plan_support import parse_proposal, v2_payload


def _legacy_permit(trip_id, operation: PlanningOperation) -> ReadinessPermit:
    return ReadinessPermit(
        trip_id=trip_id,
        readiness_digest="legacy",
        operation_id="day2-duplicate-legacy-0001",
        operation=operation,
        flow_kind=TripFlowKind.LEGACY_SINGLE,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )


class PassValidator:
    def validate_candidate(
        self,
        *,
        current_plan: PlanVersion,
        candidate: ProposedPlanVersion,
        events: Sequence[ExecutionEvent],
    ) -> ReplanValidationReport:
        del current_plan, events
        return ReplanValidationReport(
            candidate_plan_id=candidate.plan_id,
            checks=tuple(
                ReplanRuleCheck(
                    rule_id=f"TEST.{domain.value}",
                    domain=domain,
                    hardness="HARD",
                    status=ValidationStatus.PASS,
                )
                for domain in ReplanRuleDomain
            ),
        )


def test_selected_v2_duplicate_registration_is_rejected_atomically(
    tmp_path: Path,
) -> None:
    service = PlanVersionService(
        SqlitePlanVersionRepository(tmp_path / "plan_versions.sqlite3")
    )
    proposed_v1 = parse_proposal()
    service.register_proposed(
        proposed_v1,
        readiness_permit=_legacy_permit(
            proposed_v1.trip_snapshot.trip_id,
            PlanningOperation.GENERATE_V1,
        ),
    )
    service.confirm(proposed_v1.trip_snapshot.trip_id, proposed_v1.plan_id)
    service.start_execution(proposed_v1.trip_snapshot.trip_id)
    current = service.get_trip_state(proposed_v1.trip_snapshot.trip_id).current_plan
    assert current is not None

    proposed_v2 = parse_proposal(v2_payload())
    outcome = MinimumDisruptionSelector(PassValidator()).select(
        current_plan=current,
        candidates=(ReplanCandidate(plan=proposed_v2, satisfaction_loss=0),),
    )
    assert isinstance(outcome, SelectedReplan)
    assert outcome.selected_plan == proposed_v2

    v2_permit = _legacy_permit(
        outcome.selected_plan.trip_snapshot.trip_id,
        PlanningOperation.GENERATE_V2,
    )
    stored = service.register_proposed(
        outcome.selected_plan,
        readiness_permit=v2_permit,
    )
    with pytest.raises(AppError) as duplicate:
        service.register_proposed(
            outcome.selected_plan,
            readiness_permit=v2_permit,
        )

    assert duplicate.value.code == "PLAN_VERSION_ALREADY_EXISTS"
    assert duplicate.value.http_status == 409
    state = service.get_trip_state(current.trip_snapshot.trip_id)
    assert state.trip_status is TripStatus.REPLAN_REVIEW
    assert state.current_plan is not None
    assert state.current_plan.plan_id == current.plan_id
    assert state.current_plan.status is PlanVersionStatus.CURRENT
    assert [plan.plan_id for plan in state.proposed_plans] == [stored.plan_id]
    assert stored.status is PlanVersionStatus.PROPOSED
    assert isinstance(outcome.selected_plan, ProposedPlanVersion)
