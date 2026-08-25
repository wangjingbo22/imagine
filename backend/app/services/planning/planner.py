from __future__ import annotations

from collections.abc import Sequence
from datetime import time
from hashlib import sha256
import json
import re
from typing import Final
from unicodedata import normalize
from uuid import UUID

from pydantic import ValidationError

from app.application.route_risk_adapter import (
    RouteRiskAdapterError,
    route_snapshot_to_risk_input,
)
from app.domain.budget import BudgetLine, BudgetStatus, BudgetSummary, summarize_budget
from app.domain.models import Provenance, SourceStatus
from app.schemas.constraint import Constraint
from app.schemas.plan import (
    ConstraintCheckStatus,
    ConstraintHardness,
    ConstraintSnapshot,
    PlanDay,
    PlanMetrics,
    PlanSourceSnapshot,
    PlanSourceStatus,
    PlanTask,
    PlanVersion,
    PlanVersionReason,
    PlanVersionStatus,
    ProposedPlanVersion,
)
from app.schemas.trip import PlanReviewTripSnapshot, TripStatus
from app.services.assistance_constraints import (
    DeterministicAssistanceConstraintCompiler,
    FIELD_NAP_WINDOW,
    FIELD_RETURN,
    RETURN_DEADLINE_PATH,
    RETURN_END_LOCATION_PATH,
)
from app.services.route_risk import (
    RouteRiskContractError,
    RouteRiskInput,
    ValidationStatus,
    evaluate_route_risk,
)

from .models import (
    CandidateConstraintResult,
    CandidatePlan,
    CandidatePlanMetrics,
    CandidatePlanRequest,
    CandidatePlanWarning,
    CandidateTask,
    CandidateTaskFact,
)


RULE_NAP_WINDOW: Final = "CARE.DAY.NAP_WINDOW"
RULE_RETURN: Final = "CARE.DAY.RETURN_BY"
RULE_BUDGET: Final = "PLAN.BUDGET.KNOWN_SUBTOTAL"

_ROUTE_RULE_TO_FIELD: Final = {
    "CARE.ROUTE.STAIRS_FORBIDDEN": "avoidStairs",
    "CARE.ROUTE.WALK_SEGMENT_LIMIT": "walkLimits.maxContinuousMeters",
    "CARE.ROUTE.WALK_DAILY_LIMIT": "walkLimits.maxDailyMeters",
    "CARE.ROUTE.TRANSFER_LIMIT": "maxTransfers",
    "CARE.ROUTE.REST_INTERVAL": "restInterval",
    "CARE.ROUTE.UNSUPPORTED_CONSTRAINT": None,
}
_SECOND_PRECISION_TIME: Final = re.compile(r"^\d{2}:\d{2}:\d{2}$")


class CandidatePlanInputError(ValueError):
    """Fail-closed input or integration error that produces no candidate."""

    def __init__(self, *, code: str, field: str, message: str) -> None:
        self.code = code
        self.field = field
        super().__init__(message)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": str(self)}


class CandidatePlanRejected(ValueError):
    """A valid request whose recomputed HARD result was not PASS."""

    code = "CANDIDATE_PLAN_REJECTED"

    def __init__(
        self,
        results: Sequence[CandidateConstraintResult],
        *,
        all_results: Sequence[CandidateConstraintResult] | None = None,
    ) -> None:
        self.results = tuple(results)
        self.all_results = tuple(all_results or results)
        super().__init__("one or more HARD constraints did not PASS")

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "results": [
                item.model_dump(mode="json", by_alias=True) for item in self.results
            ],
        }


class DeterministicCandidatePlanner:
    """Compose T006/T007/T009 without I/O, clocks, randomness, or alternatives."""

    def __init__(
        self,
        constraint_compiler: DeterministicAssistanceConstraintCompiler | None = None,
    ) -> None:
        self._constraint_compiler = (
            constraint_compiler or DeterministicAssistanceConstraintCompiler()
        )

    def generate(self, request: CandidatePlanRequest) -> CandidatePlan:
        valid = _validated_request(request)
        constraints = self._verified_constraints(valid)
        self._validate_same_city_facts(valid)

        route_facts = self._route_facts(valid.task_facts)
        route_results = self._evaluate_route_constraints(route_facts, constraints)
        day_results = self._evaluate_day_constraints(valid, constraints)
        task_outputs, budget_summary, warnings = self._recompute_tasks(
            valid.task_facts,
        )
        if valid.start_location.provenance.sourceStatus is SourceStatus.UNKNOWN:
            warnings = (
                CandidatePlanWarning(
                    code="UNKNOWN_SOURCE",
                    reference_id="trip.startLocation",
                    field="startLocation.provenance.sourceStatus",
                    message="行程起点来源未知，需要用户确认",
                ),
                *warnings,
            )
        if valid.end_location.provenance.sourceStatus is SourceStatus.UNKNOWN:
            warnings = (
                CandidatePlanWarning(
                    code="UNKNOWN_SOURCE",
                    reference_id="trip.endLocation",
                    field="endLocation.provenance.sourceStatus",
                    message="行程终点来源未知，需要用户确认",
                ),
                *warnings,
            )

        participant_cap = valid.trip.participants[0].budget_cap_cents
        day_budget = valid.trip.days[0].daily_budget_cents
        budget_limit = min(
            valid.trip.total_budget_cents,
            day_budget,
            participant_cap,
        )
        budget_status = (
            ValidationStatus.PASS
            if budget_summary.knownSubtotalCents <= budget_limit
            else ValidationStatus.FAIL
        )
        budget_result = CandidateConstraintResult(
            rule_id=RULE_BUDGET,
            scope="TRIP",
            hardness="HARD",
            status=budget_status,
            observed={
                "knownSubtotalCents": budget_summary.knownSubtotalCents,
                "unknownAmountCount": budget_summary.unknownAmountCount,
                "budgetLimitCents": budget_limit,
            },
            suggestion=(
                None
                if budget_status is ValidationStatus.PASS
                else "Reduce known costs to the confirmed budget limit"
            ),
        )

        constraint_results = (*route_results, *day_results, budget_result)
        failed_hard = tuple(
            item
            for item in constraint_results
            if item.hardness == "HARD" and item.status is not ValidationStatus.PASS
        )
        if failed_hard:
            raise CandidatePlanRejected(
                failed_hard,
                all_results=constraint_results,
            )

        known_total = budget_summary.knownSubtotalCents
        return CandidatePlan(
            schema_version="1.0",
            candidate_id=_candidate_id(valid),
            trip_id=str(valid.trip.trip_id),
            city_code=valid.trip.city_context.city_code,
            day_index=0,
            date=valid.trip.days[0].date,
            tasks=task_outputs,
            metrics=CandidatePlanMetrics(
                total_cost_cents=(
                    known_total
                    if budget_summary.status is BudgetStatus.COMPLETE
                    else None
                ),
                known_total_cost_cents=known_total,
                unknown_amount_count=budget_summary.unknownAmountCount,
                budget_limit_cents=budget_limit,
                known_budget_buffer_cents=budget_limit - known_total,
                total_walk_meters=sum(item.walk_meters for item in task_outputs),
                transfer_count=sum(item.transfer_count for item in task_outputs),
                validation_status=(
                    "NEEDS_CONFIRMATION" if warnings else "PASS"
                ),
            ),
            constraint_results=constraint_results,
            warnings=warnings,
        )

    def _verified_constraints(
        self,
        request: CandidatePlanRequest,
    ) -> tuple[Constraint, ...]:
        profile = request.trip.participants[0].assistance_profile
        expected = (
            self._constraint_compiler.compile(profile) if profile is not None else ()
        )
        if _constraint_payload(request.confirmed_constraints) != _constraint_payload(
            expected
        ):
            raise CandidatePlanInputError(
                code="CONFIRMED_CONSTRAINTS_MISMATCH",
                field="confirmedConstraints",
                message=(
                    "confirmedConstraints must exactly match the T007 compilation "
                    "of the confirmed assistance profile"
                ),
            )
        return expected

    @staticmethod
    def _validate_same_city_facts(request: CandidatePlanRequest) -> None:
        expected_city = request.trip.city_context.city_code
        day = request.trip.days[0]
        start = request.start_location
        if start.city_code != expected_city:
            raise CandidatePlanInputError(
                code="CROSS_CITY_FACT",
                field="startLocation.cityCode",
                message="start location cityCode must match trip.cityContext.cityCode",
            )
        if _normalized_text(start.location_text) != _normalized_text(
            day.start_location_text
        ):
            raise CandidatePlanInputError(
                code="FACT_LINK_MISMATCH",
                field="startLocation.locationText",
                message="start location fact must resolve days[0].startLocationText",
            )

        end = request.end_location
        if end.city_code != expected_city:
            raise CandidatePlanInputError(
                code="CROSS_CITY_FACT",
                field="endLocation.cityCode",
                message="end location cityCode must match trip.cityContext.cityCode",
            )
        if _normalized_text(end.location_text) != _normalized_text(
            day.end_location_text
        ):
            raise CandidatePlanInputError(
                code="FACT_LINK_MISMATCH",
                field="endLocation.locationText",
                message="end location fact must resolve days[0].endLocationText",
            )

        expected_origin = start.location
        previous_end = day.time_window.start
        for index, item in enumerate(request.task_facts):
            prefix = f"taskFacts[{index}]"
            if item.city_code != expected_city:
                raise CandidatePlanInputError(
                    code="CROSS_CITY_FACT",
                    field=f"{prefix}.cityCode",
                    message="task fact cityCode must match trip.cityContext.cityCode",
                )
            if item.place.cityCode != expected_city:
                raise CandidatePlanInputError(
                    code="CROSS_CITY_FACT",
                    field=f"{prefix}.place.cityCode",
                    message="place cityCode must match trip.cityContext.cityCode",
                )
            if item.route.destination != item.place.location:
                raise CandidatePlanInputError(
                    code="FACT_LINK_MISMATCH",
                    field=f"{prefix}.route.destination",
                    message="route destination must equal the selected place location",
                )
            if _normalized_text(item.end_location_text) != _normalized_text(
                item.place.name
            ):
                raise CandidatePlanInputError(
                    code="FACT_LINK_MISMATCH",
                    field=f"{prefix}.endLocationText",
                    message="task endLocationText must identify the selected place",
                )
            if item.route.origin != expected_origin:
                raise CandidatePlanInputError(
                    code="ROUTE_CHAIN_INVALID",
                    field=f"{prefix}.route.origin",
                    message=(
                        "first route must start at the resolved Trip start; later "
                        "routes must start at the previous selected place"
                    ),
                )

            available_seconds = _seconds(item.start_at) - _seconds(previous_end)
            if item.route.durationSeconds > available_seconds:
                raise CandidatePlanInputError(
                    code="ROUTE_SCHEDULE_INVALID",
                    field=f"{prefix}.route.durationSeconds",
                    message=(
                        "route durationSeconds cannot fit between the previous "
                        "activity and this task start"
                    ),
                )
            expected_origin = item.place.location
            previous_end = item.end_at

        if request.task_facts[-1].route.destination != end.location:
            raise CandidatePlanInputError(
                code="RETURN_ENDPOINT_MISMATCH",
                field="taskFacts[-1].route.destination",
                message="last route destination must equal the resolved Trip endpoint",
            )

    @staticmethod
    def _route_facts(task_facts: Sequence[CandidateTaskFact]) -> RouteRiskInput:
        segments = []
        for index, item in enumerate(task_facts):
            try:
                adapted = route_snapshot_to_risk_input(
                    item.route,
                    elapsed_since_rest_minutes=item.elapsed_since_rest_minutes,
                )
            except RouteRiskAdapterError as exc:
                raise CandidatePlanInputError(
                    code=exc.code,
                    field=f"taskFacts[{index}].route.{exc.field}",
                    message=str(exc),
                ) from exc
            segments.extend(adapted.segments)
        return RouteRiskInput(segments=tuple(segments))

    @staticmethod
    def _evaluate_route_constraints(
        route_facts: RouteRiskInput,
        constraints: Sequence[Constraint],
    ) -> tuple[CandidateConstraintResult, ...]:
        try:
            report = evaluate_route_risk(route_facts, constraints)
        except RouteRiskContractError as exc:
            raise CandidatePlanInputError(
                code=exc.code,
                field=f"confirmedConstraints.{exc.field}",
                message=str(exc),
            ) from exc

        by_field = {item.field: item for item in constraints}
        results: list[CandidateConstraintResult] = []
        for item in report.results:
            field = _ROUTE_RULE_TO_FIELD.get(item.rule_id)
            constraint = by_field.get(field) if field is not None else None
            hardness = constraint.hardness if constraint is not None else "SOFT"
            scope = constraint.scope if constraint is not None else "ROUTE"
            results.append(
                CandidateConstraintResult(
                    rule_id=item.rule_id,
                    scope=scope,
                    hardness=hardness,
                    status=item.status,
                    reference_id=item.route_segment,
                    observed=item.observed,
                    suggestion=item.suggestion,
                )
            )
        return tuple(results)

    @staticmethod
    def _evaluate_day_constraints(
        request: CandidatePlanRequest,
        constraints: Sequence[Constraint],
    ) -> tuple[CandidateConstraintResult, ...]:
        results: list[CandidateConstraintResult] = []
        for constraint in constraints:
            if constraint.field == FIELD_NAP_WINDOW:
                results.append(_evaluate_nap_window(request, constraint))
            elif constraint.field == FIELD_RETURN:
                results.append(_evaluate_return(request, constraint))
            elif constraint.scope.strip().upper() == "DAY" and constraint.field not in {
                "walkLimits.maxDailyMeters",
            }:
                if constraint.hardness == "HARD":
                    raise CandidatePlanInputError(
                        code="UNSUPPORTED_HARD_DAY_CONSTRAINT",
                        field=f"confirmedConstraints.{constraint.field}",
                        message="unknown HARD DAY constraint cannot be treated as passing",
                    )
        return tuple(results)

    @staticmethod
    def _recompute_tasks(
        task_facts: Sequence[CandidateTaskFact],
    ) -> tuple[
        tuple[CandidateTask, ...],
        BudgetSummary,
        tuple[CandidatePlanWarning, ...],
    ]:
        all_lines: list[BudgetLine] = []
        tasks: list[CandidateTask] = []
        warnings: list[CandidatePlanWarning] = []

        for item in task_facts:
            place_reference = f"{item.task_id}.placePrice"
            route_reference = f"{item.task_id}.routePrice"
            lines = (
                BudgetLine(
                    referenceId=place_reference,
                    priceFact=item.place.priceReference,
                ),
                BudgetLine(
                    referenceId=route_reference,
                    priceFact=item.route.priceReference,
                ),
            )
            all_lines.extend(lines)
            summary = summarize_budget(lines)

            for warning in summary.warnings:
                warnings.append(
                    CandidatePlanWarning(
                        code="UNKNOWN_PRICE",
                        reference_id=warning.referenceId,
                        field="priceReference.amountCents",
                        message=warning.message,
                    )
                )
            if item.place.provenance.sourceStatus is SourceStatus.UNKNOWN:
                warnings.append(
                    CandidatePlanWarning(
                        code="UNKNOWN_SOURCE",
                        reference_id=place_reference,
                        field="place.provenance.sourceStatus",
                        message="地点来源未知，需要用户确认",
                    )
                )
            if item.route.provenance.sourceStatus is SourceStatus.UNKNOWN:
                warnings.append(
                    CandidatePlanWarning(
                        code="UNKNOWN_SOURCE",
                        reference_id=route_reference,
                        field="route.provenance.sourceStatus",
                        message="路线来源未知，需要用户确认",
                    )
                )

            route_risk = route_snapshot_to_risk_input(
                item.route,
                elapsed_since_rest_minutes=item.elapsed_since_rest_minutes,
            ).segments[0]
            duration_seconds = (
                item.end_at.hour * 3_600
                + item.end_at.minute * 60
                + item.end_at.second
                - item.start_at.hour * 3_600
                - item.start_at.minute * 60
                - item.start_at.second
            )
            tasks.append(
                CandidateTask(
                    task_id=item.task_id,
                    order=item.order,
                    title=item.title,
                    category=item.category,
                    time_range=(
                        f"{item.start_at.isoformat()}-{item.end_at.isoformat()}"
                    ),
                    duration_minutes=(duration_seconds + 59) // 60,
                    transport=item.route.mode.value,
                    cost_cents=(
                        summary.knownSubtotalCents
                        if summary.status is BudgetStatus.COMPLETE
                        else None
                    ),
                    known_cost_cents=summary.knownSubtotalCents,
                    unknown_amount_count=summary.unknownAmountCount,
                    walk_meters=route_risk.walking_distance_meters,
                    transfer_count=route_risk.cumulative_transfers,
                    place_id=item.place.placeId,
                    route_id=item.route.routeId,
                    end_location_text=item.end_location_text,
                    note=item.note,
                )
            )

        return tuple(tasks), summarize_budget(all_lines), tuple(warnings)


def generate_candidate_plan(request: CandidatePlanRequest) -> CandidatePlan:
    """Convenience composition root; returns one CandidatePlan, never a list."""

    return DeterministicCandidatePlanner().generate(request)


def candidate_to_proposed_plan_version(
    candidate: CandidatePlan,
    request: CandidatePlanRequest,
) -> ProposedPlanVersion:
    """Convert one complete PASS candidate to the existing T014 V1 contract.

    The request is required so the immutable Trip and source snapshots come from
    normalized facts rather than from presentation fields on CandidatePlan.
    The candidate is regenerated before conversion, preventing a mutated or
    unrelated object from being registered through this bridge.
    """

    valid_candidate, valid_request = _validated_complete_candidate(
        candidate,
        request,
    )
    return _build_proposed_plan_version(
        valid_candidate,
        valid_request,
        trip_snapshot=_trip_snapshot_from_request(valid_request),
        plan_id=_plan_uuid(valid_request),
        version=1,
        parent_id=None,
        reason=PlanVersionReason.INITIAL_PLAN,
    )


def candidate_to_proposed_plan_version_v2(
    candidate: CandidatePlan,
    request: CandidatePlanRequest,
    current_plan: PlanVersion,
    *,
    reason: PlanVersionReason = PlanVersionReason.USER_FEEDBACK,
) -> ProposedPlanVersion:
    """Create a deterministic V2 tied to one immutable CURRENT V1 snapshot."""

    current = _validated_current_plan(current_plan)
    if not isinstance(reason, PlanVersionReason):
        raise CandidatePlanInputError(
            code="CANDIDATE_V2_REASON_INVALID",
            field="reason",
            message="reason must be a PlanVersionReason",
        )
    if current.version != 1:
        raise CandidatePlanInputError(
            code="CANDIDATE_V2_PARENT_INVALID",
            field="currentPlan.version",
            message="the S1 V2 bridge requires CURRENT Plan V1",
        )
    if reason is PlanVersionReason.INITIAL_PLAN:
        raise CandidatePlanInputError(
            code="CANDIDATE_V2_REASON_INVALID",
            field="reason",
            message="Plan V2 reason cannot be INITIAL_PLAN",
        )

    valid_candidate, valid_request = _validated_complete_candidate(
        candidate,
        request,
    )
    request_snapshot = _trip_snapshot_from_request(valid_request)
    if request_snapshot != current.trip_snapshot:
        raise CandidatePlanInputError(
            code="CANDIDATE_V2_TRIP_MISMATCH",
            field="request.trip",
            message="Plan V2 must reuse the immutable CURRENT Trip snapshot",
        )
    return _build_proposed_plan_version(
        valid_candidate,
        valid_request,
        trip_snapshot=current.trip_snapshot,
        plan_id=_plan_uuid_v2(valid_request, current, reason),
        version=2,
        parent_id=current.plan_id,
        reason=reason,
    )


def generate_proposed_plan_version(
    request: CandidatePlanRequest,
) -> ProposedPlanVersion:
    """Generate and bridge one accepted T011 candidate for direct registration."""

    candidate = generate_candidate_plan(request)
    return candidate_to_proposed_plan_version(candidate, request)


def generate_proposed_plan_version_v2(
    request: CandidatePlanRequest,
    current_plan: PlanVersion,
    *,
    reason: PlanVersionReason = PlanVersionReason.USER_FEEDBACK,
) -> ProposedPlanVersion:
    candidate = generate_candidate_plan(request)
    return candidate_to_proposed_plan_version_v2(
        candidate,
        request,
        current_plan,
        reason=reason,
    )


def _validated_request(request: CandidatePlanRequest) -> CandidatePlanRequest:
    if not isinstance(request, CandidatePlanRequest):
        raise CandidatePlanInputError(
            code="CANDIDATE_PLAN_INPUT_INVALID",
            field="",
            message="request must be a CandidatePlanRequest",
        )
    try:
        raw = request.model_dump_json(by_alias=True, warnings="error")
        return CandidatePlanRequest.model_validate_json(raw, strict=True)
    except (ValidationError, TypeError, ValueError) as exc:
        raise CandidatePlanInputError(
            code="CANDIDATE_PLAN_INPUT_INVALID",
            field="",
            message=str(exc),
        ) from exc


def _validated_candidate(candidate: CandidatePlan) -> CandidatePlan:
    if not isinstance(candidate, CandidatePlan):
        raise CandidatePlanInputError(
            code="CANDIDATE_PLAN_INPUT_INVALID",
            field="candidate",
            message="candidate must be a CandidatePlan",
        )
    try:
        raw = candidate.model_dump_json(by_alias=True, warnings="error")
        return CandidatePlan.model_validate_json(raw, strict=True)
    except (ValidationError, TypeError, ValueError) as exc:
        raise CandidatePlanInputError(
            code="CANDIDATE_PLAN_INPUT_INVALID",
            field="candidate",
            message=str(exc),
        ) from exc


def _validated_current_plan(current_plan: PlanVersion) -> PlanVersion:
    if not isinstance(current_plan, PlanVersion):
        raise CandidatePlanInputError(
            code="CANDIDATE_V2_PARENT_INVALID",
            field="currentPlan",
            message="currentPlan must be a PlanVersion",
        )
    try:
        raw = current_plan.model_dump_json(by_alias=True, warnings="error")
        current = PlanVersion.model_validate_json(raw, strict=True)
    except (ValidationError, TypeError, ValueError) as exc:
        raise CandidatePlanInputError(
            code="CANDIDATE_V2_PARENT_INVALID",
            field="currentPlan",
            message=str(exc),
        ) from exc
    if current.status is not PlanVersionStatus.CURRENT:
        raise CandidatePlanInputError(
            code="CANDIDATE_V2_PARENT_INVALID",
            field="currentPlan.status",
            message="Plan V2 parent must be CURRENT",
        )
    return current


def _validated_complete_candidate(
    candidate: CandidatePlan,
    request: CandidatePlanRequest,
) -> tuple[CandidatePlan, CandidatePlanRequest]:
    valid_request = _validated_request(request)
    expected = DeterministicCandidatePlanner().generate(valid_request)
    valid_candidate = _validated_candidate(candidate)
    if valid_candidate != expected:
        raise CandidatePlanInputError(
            code="CANDIDATE_REQUEST_MISMATCH",
            field="candidate",
            message="candidate must exactly match the deterministic request result",
        )
    if (
        valid_candidate.metrics.validation_status != "PASS"
        or valid_candidate.metrics.total_cost_cents is None
        or valid_candidate.warnings
    ):
        raise CandidatePlanInputError(
            code="CANDIDATE_CONFIRMATION_REQUIRED",
            field="candidate.metrics.validationStatus",
            message="only a complete PASS candidate can become ProposedPlanVersion",
        )
    return valid_candidate, valid_request


def _trip_snapshot_from_request(
    request: CandidatePlanRequest,
) -> PlanReviewTripSnapshot:
    trip_payload = request.trip.model_dump(mode="json", by_alias=True)
    trip_payload["status"] = TripStatus.PLAN_REVIEW.value
    return PlanReviewTripSnapshot.model_validate_json(
        json.dumps(
            trip_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        strict=True,
    )


def _build_proposed_plan_version(
    candidate: CandidatePlan,
    request: CandidatePlanRequest,
    *,
    trip_snapshot: PlanReviewTripSnapshot,
    plan_id: UUID,
    version: int,
    parent_id: UUID | None,
    reason: PlanVersionReason,
) -> ProposedPlanVersion:
    plan_tasks: list[PlanTask] = []
    for item in candidate.tasks:
        assert item.cost_cents is not None
        plan_tasks.append(
            PlanTask(
                task_id=item.task_id,
                order=item.order,
                title=item.title,
                category=item.category,
                time_range=item.time_range,
                duration_minutes=item.duration_minutes,
                transport=item.transport,
                cost_cents=item.cost_cents,
                walk_meters=item.walk_meters,
                note=item.note,
            )
        )

    constraints_snapshot = [
        ConstraintSnapshot(
            rule_id=item.rule_id,
            scope=item.scope,
            hardness=ConstraintHardness(item.hardness),
            status=ConstraintCheckStatus(item.status.value),
            description=_constraint_description(item),
            details=_string_details(item),
        )
        for item in candidate.constraint_results
    ]

    sources_snapshot: list[PlanSourceSnapshot] = [
        _source_snapshot(
            request.start_location.provenance,
            reference_id="trip.startLocation",
        ),
        _source_snapshot(
            request.end_location.provenance,
            reference_id="trip.endLocation",
        ),
    ]
    for item in request.task_facts:
        sources_snapshot.extend(
            (
                _source_snapshot(
                    item.place.provenance,
                    reference_id=f"{item.task_id}.place",
                ),
                _source_snapshot(
                    item.place.priceReference.provenance,
                    reference_id=f"{item.task_id}.placePrice",
                ),
                _source_snapshot(
                    item.route.provenance,
                    reference_id=f"{item.task_id}.route",
                ),
                _source_snapshot(
                    item.route.priceReference.provenance,
                    reference_id=f"{item.task_id}.routePrice",
                ),
            )
        )

    total_cost = candidate.metrics.total_cost_cents
    assert total_cost is not None
    return ProposedPlanVersion(
        schema_version="1.0",
        plan_id=plan_id,
        trip_snapshot=trip_snapshot,
        version=version,
        parent_id=parent_id,
        reason=reason,
        metrics=PlanMetrics(
            total_cost_cents=total_cost,
            buffer_cents=request.trip.total_budget_cents - total_cost,
            total_walk_meters=candidate.metrics.total_walk_meters,
            transfer_count=candidate.metrics.transfer_count,
            validation_status="PASS",
        ),
        days=[
            PlanDay(
                day_index=0,
                date=candidate.date,
                tasks=plan_tasks,
            )
        ],
        constraints_snapshot=constraints_snapshot,
        sources_snapshot=sources_snapshot,
    )


def _constraint_payload(constraints: Sequence[Constraint]) -> list[dict[str, object]]:
    return [
        item.model_dump(mode="json", by_alias=True) for item in constraints
    ]


def _candidate_id(request: CandidatePlanRequest) -> str:
    return f"candidate-{_request_digest(request).hex()[:24]}"


def _request_digest(request: CandidatePlanRequest) -> bytes:
    canonical = json.dumps(
        request.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).digest()


def _plan_uuid(request: CandidatePlanRequest) -> UUID:
    return _uuid4_from_digest(_request_digest(request))


def _plan_uuid_v2(
    request: CandidatePlanRequest,
    current: PlanVersion,
    reason: PlanVersionReason,
) -> UUID:
    digest = sha256(
        _request_digest(request) + current.plan_id.bytes + reason.value.encode("utf-8")
    ).digest()
    return _uuid4_from_digest(digest)


def _uuid4_from_digest(digest: bytes) -> UUID:
    raw = bytearray(digest[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def _source_snapshot(
    provenance: Provenance,
    *,
    reference_id: str,
) -> PlanSourceSnapshot:
    # All T006 Provenance instances share this frozen field contract.  Keeping
    # the conversion here avoids widening CandidatePlan with mutable raw facts.
    return PlanSourceSnapshot(
        provider=provenance.provider,
        source_status=PlanSourceStatus(provenance.sourceStatus.value),
        fetched_at=provenance.fetchedAt,
        is_stale=provenance.isStale,
        reference_id=reference_id,
    )


def _constraint_description(item: CandidateConstraintResult) -> str:
    if item.rule_id == RULE_BUDGET:
        return "服务端按原始价格事实复算的已知金额未超过预算"
    if item.rule_id == RULE_NAP_WINDOW:
        return "候选任务未占用已确认的午休时间窗"
    if item.rule_id == RULE_RETURN:
        return "末项任务在截止时间前抵达已确认的返程地点"
    return "服务端基于 T006 路线事实与 T009 规则重新校验"


def _string_details(item: CandidateConstraintResult) -> dict[str, str]:
    details = {
        key: (
            value
            if isinstance(value, str)
            else json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        for key, value in item.observed.items()
    }
    if item.reference_id is not None:
        details["referenceId"] = item.reference_id
    return details


def _evaluate_nap_window(
    request: CandidatePlanRequest,
    constraint: Constraint,
) -> CandidateConstraintResult:
    if (
        constraint.operator != "BLOCK"
        or not isinstance(constraint.value, dict)
        or set(constraint.value) != {"start", "end"}
    ):
        raise CandidatePlanInputError(
            code="INVALID_DAY_CONSTRAINT",
            field=f"confirmedConstraints.{constraint.field}",
            message="napWindow requires BLOCK with exact start/end values",
        )
    start = _parse_time(constraint.value["start"], field="napWindow.start")
    end = _parse_time(constraint.value["end"], field="napWindow.end")
    if end <= start:
        raise CandidatePlanInputError(
            code="INVALID_DAY_CONSTRAINT",
            field="confirmedConstraints.napWindow",
            message="napWindow.end must be later than start",
        )

    overlap = next(
        (
            item
            for item in request.task_facts
            if item.start_at < end and item.end_at > start
        ),
        None,
    )
    status = ValidationStatus.PASS
    if overlap is not None:
        status = (
            ValidationStatus.FAIL
            if constraint.hardness == "HARD"
            else ValidationStatus.WARNING
        )
    return CandidateConstraintResult(
        rule_id=RULE_NAP_WINDOW,
        scope=constraint.scope,
        hardness=constraint.hardness,
        status=status,
        reference_id=overlap.task_id if overlap is not None else None,
        observed={
            "blockedStart": start.isoformat(),
            "blockedEnd": end.isoformat(),
            "overlappingTaskId": overlap.task_id if overlap is not None else None,
        },
        suggestion=(
            "Move the activity outside the confirmed nap window"
            if overlap is not None
            else None
        ),
    )


def _evaluate_return(
    request: CandidatePlanRequest,
    constraint: Constraint,
) -> CandidateConstraintResult:
    expected_value = {
        "endLocationPath": RETURN_END_LOCATION_PATH,
        "deadlinePath": RETURN_DEADLINE_PATH,
    }
    if constraint.operator != "ARRIVE_BY" or constraint.value != expected_value:
        raise CandidatePlanInputError(
            code="INVALID_DAY_CONSTRAINT",
            field=f"confirmedConstraints.{constraint.field}",
            message="return must use the exact T007 Trip snapshot references",
        )

    final_task = request.task_facts[-1]
    day = request.trip.days[0]
    location_matches = _normalized_text(final_task.end_location_text) == _normalized_text(
        day.end_location_text
    )
    deadline_matches = final_task.end_at <= day.time_window.end
    passed = location_matches and deadline_matches
    status = ValidationStatus.PASS
    if not passed:
        status = (
            ValidationStatus.FAIL
            if constraint.hardness == "HARD"
            else ValidationStatus.WARNING
        )
    return CandidateConstraintResult(
        rule_id=RULE_RETURN,
        scope=constraint.scope,
        hardness=constraint.hardness,
        status=status,
        reference_id=final_task.task_id,
        observed={
            "endLocationText": final_task.end_location_text,
            "requiredEndLocationText": day.end_location_text,
            "arrivalTime": final_task.end_at.isoformat(),
            "deadline": day.time_window.end.isoformat(),
        },
        suggestion=(
            "End the last task at the confirmed return location before the deadline"
            if not passed
            else None
        ),
    )


def _parse_time(value: object, *, field: str) -> time:
    if not isinstance(value, str) or not _SECOND_PRECISION_TIME.fullmatch(value):
        raise CandidatePlanInputError(
            code="INVALID_DAY_CONSTRAINT",
            field=f"confirmedConstraints.{field}",
            message="time must use HH:mm:ss",
        )
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise CandidatePlanInputError(
            code="INVALID_DAY_CONSTRAINT",
            field=f"confirmedConstraints.{field}",
            message="time must use a valid HH:mm:ss value",
        ) from exc


def _normalized_text(value: str) -> str:
    return normalize("NFKC", value).strip().casefold()


def _seconds(value: time) -> int:
    return value.hour * 3_600 + value.minute * 60 + value.second


__all__ = [
    "CandidatePlanInputError",
    "CandidatePlanRejected",
    "DeterministicCandidatePlanner",
    "candidate_to_proposed_plan_version",
    "candidate_to_proposed_plan_version_v2",
    "generate_candidate_plan",
    "generate_proposed_plan_version",
    "generate_proposed_plan_version_v2",
]
