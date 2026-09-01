from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any, ContextManager, Literal, Protocol
from unicodedata import normalize
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from app.application.collaboration_ports import (
    CollaborationReadinessGuard,
    PlanningAccess,
    PlanningOperation,
    ReadinessPermit,
    TripDraftRevisionView,
)
from app.application.plan_service import PlanVersionService
from app.application.workflow_service import WorkflowService
from app.core.errors import AppError
from app.infrastructure.trusted_planning_store import (
    SqliteTrustedPlanningRepository,
    TrustedPlanningStoreError,
    proposal_digest,
)
from app.schemas.execution import ExecutionEvent, ExecutionEventType
from app.schemas.execution_adjustment import (
    ConfirmedExecutionAdjustment,
    EventConstraintSet,
    ExecutionAdjustmentType,
    ExecutionConstraintCompileRequest,
)
from app.schemas.execution_replan import (
    ExecutionAdjustmentDecision,
    ExecutionAdjustmentReplanRequest,
    ExecutionReplanReadinessBinding,
    RegisteredExecutionAdjustmentReplan,
)
from app.schemas.plan import (
    PlanV2DecisionResult,
    PlanTransitionResult,
    PlanVersion,
    PlanVersionReason,
    PlanVersionStatus,
    ProposedPlanVersion,
)
from app.schemas.trip import PreferenceType, TripStatus
from app.domain.hard_conflicts import assistance_profile_from_care
from app.schemas.planning import (
    EventDrivenReplanRequest,
    RegisteredReplan,
    ReplanGenerationRequest,
)
from app.services.planning.models import (
    CandidatePlan,
    CandidatePlanRequest,
    CandidatePlanReview,
    CandidateReviewConfirmationRequest,
    CandidateReviewItem,
    CandidateTaskFact,
)
from app.services.planning.planner import (
    CandidatePlanInputError,
    CandidatePlanRejected,
    candidate_to_proposed_plan_version_v2,
    candidate_to_proposed_plan_version,
    generate_candidate_plan,
)
from app.services.planning.replanning_adapter import T011ReplanCandidateValidator
from app.services.execution_adjustments import compile_execution_constraints
from app.services.execution_replanning import (
    EventConstraintReplanValidator,
    ExecutionReplanContextError,
    project_execution_adjustment,
)
from app.services.replanning import (
    DeterministicEventAwareSuffixPlanner,
    DeterministicRetainedSuffixPlanner,
    SuffixPlanner,
    SuffixPlanningError,
    SuffixPlanningInput,
)
from app.services.replanning.models import (
    NoFeasibleReplan,
    ReplanCandidate,
    ReplanValidationReport,
)
from app.services.replanning.selector import (
    MinimumDisruptionSelector,
    ReplanningContractError,
)
from app.services.route_risk import ValidationStatus


class _InMemoryTrustedCandidateFacts:
    def __init__(self, records: Mapping[UUID, CandidatePlanRequest]) -> None:
        self._records = dict(records)

    def get_candidate_request(
        self,
        candidate_plan_id: UUID,
    ) -> CandidatePlanRequest | None:
        return self._records.get(candidate_plan_id)


class ParentTripPlaceMemoryGuard(Protocol):
    def require_unique_candidate_places(
        self,
        child_id: UUID,
        task_facts: Sequence[object],
    ) -> None: ...


class PlanningBoundaryService:
    """Trusted HTTP boundary joining T011, T018 and PlanVersion storage."""

    def __init__(
        self,
        *,
        plan_service: PlanVersionService,
        workflow_service: WorkflowService,
        trust_repository: SqliteTrustedPlanningRepository,
        readiness_guard: CollaborationReadinessGuard,
        suffix_planner: SuffixPlanner | None = None,
        parent_trip_place_memory_guard: ParentTripPlaceMemoryGuard | None = None,
    ) -> None:
        self.plan_service = plan_service
        self.workflow_service = workflow_service
        self.trust_repository = trust_repository
        self.readiness_guard = readiness_guard
        self.parent_trip_place_memory_guard = parent_trip_place_memory_guard
        self.suffix_planner = suffix_planner or DeterministicEventAwareSuffixPlanner()
        if not isinstance(self.suffix_planner, SuffixPlanner):
            raise TypeError("suffix_planner must implement SuffixPlanner")

    def _planning_operation(
        self,
        *,
        trip_id: UUID,
        access: PlanningAccess,
        expected: PlanningOperation,
    ) -> ContextManager[ReadinessPermit]:
        if access.trip_id != trip_id or access.operation is not expected:
            raise AppError(
                "PLANNING_ACCESS_INVALID",
                "规划访问上下文不匹配",
                409,
                False,
            )
        return self.readiness_guard.operation(access)

    @staticmethod
    def _require_unexpired_permit(permit: ReadinessPermit) -> None:
        if permit.expires_at <= datetime.now(UTC):
            raise AppError(
                "PLANNING_ACCESS_INVALID",
                "规划操作租约已过期，不能执行状态迁移",
                409,
                False,
            )

    def _require_parent_trip_places_unique(
        self,
        trip_id: UUID,
        task_facts: Sequence[object],
    ) -> None:
        if self.parent_trip_place_memory_guard is not None:
            self.parent_trip_place_memory_guard.require_unique_candidate_places(
                trip_id,
                task_facts,
            )

    @staticmethod
    def _readiness_binding(
        permit: ReadinessPermit,
    ) -> ExecutionReplanReadinessBinding:
        return ExecutionReplanReadinessBinding(
            readiness_digest=permit.readiness_digest,
            current_revision=permit.current_revision,
            flow_kind=permit.flow_kind,
        )

    @staticmethod
    def _projection_text(value: str) -> str:
        return normalize("NFKC", value).strip().casefold()

    @classmethod
    def _projection_city_name(cls, value: str) -> str:
        normalized = cls._projection_text(value)
        if len(normalized) > 1 and normalized.endswith("市"):
            return normalized[:-1]
        return normalized

    @classmethod
    def _projection_time(cls, value: object) -> str:
        if hasattr(value, "strftime"):
            return value.strftime("%H:%M")
        return cls._projection_text(str(value))[:5]

    @staticmethod
    def _assistance_projection(profile: object) -> dict[str, Any] | None:
        if profile is None:
            return None
        return profile.model_dump(mode="json", by_alias=True)

    @classmethod
    def _participant_projection(
        cls,
        *,
        member_key: str,
        participant_id: UUID,
        nickname: str | None,
        budget_cap_cents: int | None,
        interests: Sequence[str],
        must_visit: Sequence[str],
        avoid_places: Sequence[str],
        assistance_profile: object,
    ) -> dict[str, Any]:
        return {
            "memberKey": member_key,
            "participantId": str(participant_id),
            "nickname": (
                cls._projection_text(nickname) if nickname is not None else None
            ),
            "budgetCents": budget_cap_cents,
            "interests": [cls._projection_text(value) for value in interests],
            "mustVisit": [cls._projection_text(value) for value in must_visit],
            "avoidPlaces": [cls._projection_text(value) for value in avoid_places],
            "assistanceProfile": cls._assistance_projection(assistance_profile),
        }

    @classmethod
    def _revision_planning_projection(
        cls,
        revision: TripDraftRevisionView,
    ) -> dict[str, Any]:
        trip = revision.understanding.trip
        participants_by_key = {
            participant.member_key: participant
            for participant in revision.understanding.participants
        }
        participants: list[dict[str, Any]] = []
        for index, member_key in enumerate(sorted(revision.member_bindings), start=1):
            participant = participants_by_key.get(member_key)
            participant_id = revision.member_bindings.get(member_key)
            if participant is None or participant_id is None:
                continue
            participants.append(
                cls._participant_projection(
                    member_key=member_key,
                    participant_id=participant_id,
                    nickname=participant.nickname or f"成员 {index}",
                    budget_cap_cents=(
                        participant.budget_cap_cents
                        if participant.budget_cap_cents is not None
                        else trip.budget_cents
                    ),
                    interests=participant.interests,
                    must_visit=participant.must_visit,
                    avoid_places=participant.avoid_places,
                    assistance_profile=(
                        assistance_profile_from_care(participant.care_draft)
                        if participant.care_draft is not None
                        else None
                    ),
                )
            )
        return {
            "tripId": str(revision.trip_id),
            "mode": "SINGLE" if len(participants) == 1 else "GROUP",
            "cityName": cls._projection_city_name(trip.city_name or ""),
            "date": trip.travel_date.isoformat() if trip.travel_date else None,
            "time": {
                "start": cls._projection_time(trip.start_time),
                "end": cls._projection_time(trip.end_time),
            },
            "location": {
                "start": cls._projection_text(trip.start_location_text or ""),
                "end": cls._projection_text(trip.end_location_text or ""),
            },
            "budget": {"totalCents": trip.budget_cents},
            "participants": participants,
        }

    @classmethod
    def _request_planning_projection(
        cls,
        request: CandidatePlanRequest,
    ) -> dict[str, Any]:
        trip = request.trip
        day = trip.days[0]
        participants: list[dict[str, Any]] = []
        for index, participant in enumerate(trip.participants, start=1):
            values: dict[PreferenceType, list[str]] = {
                PreferenceType.INTEREST: [],
                PreferenceType.MUST_VISIT: [],
                PreferenceType.AVOID_PLACE: [],
            }
            for preference in participant.preferences:
                values[preference.type].append(preference.value)
            participants.append(
                cls._participant_projection(
                    member_key=f"member-{index}",
                    participant_id=participant.participant_id,
                    nickname=participant.nickname,
                    budget_cap_cents=participant.budget_cap_cents,
                    interests=values[PreferenceType.INTEREST],
                    must_visit=values[PreferenceType.MUST_VISIT],
                    avoid_places=values[PreferenceType.AVOID_PLACE],
                    assistance_profile=participant.assistance_profile,
                )
            )
        return {
            "tripId": str(trip.trip_id),
            "mode": trip.mode.value,
            "cityName": cls._projection_city_name(trip.city_context.city_name),
            "date": trip.start_date.isoformat(),
            "time": {
                "start": cls._projection_time(day.time_window.start),
                "end": cls._projection_time(day.time_window.end),
            },
            "location": {
                "start": cls._projection_text(day.start_location_text),
                "end": cls._projection_text(day.end_location_text),
            },
            "budget": {"totalCents": trip.total_budget_cents},
            "participants": participants,
        }

    @staticmethod
    def _projection_mismatch_paths(
        expected: object,
        actual: object,
        path: str = "",
    ) -> list[str]:
        if isinstance(expected, dict) and isinstance(actual, dict):
            paths: list[str] = []
            for key in sorted(set(expected) | set(actual)):
                child = f"{path}.{key}" if path else key
                if key not in expected or key not in actual:
                    paths.append(child)
                else:
                    paths.extend(
                        PlanningBoundaryService._projection_mismatch_paths(
                            expected[key], actual[key], child
                        )
                    )
            return paths
        if isinstance(expected, list) and isinstance(actual, list):
            paths = []
            for index in range(max(len(expected), len(actual))):
                child = f"{path}[{index}]"
                if index >= len(expected) or index >= len(actual):
                    paths.append(child)
                else:
                    paths.extend(
                        PlanningBoundaryService._projection_mismatch_paths(
                            expected[index], actual[index], child
                        )
                    )
            return paths
        return [] if expected == actual else [path or "trip"]

    def _require_collaboration_request_matches_revision(
        self,
        request: CandidatePlanRequest,
        permit: ReadinessPermit,
    ) -> None:
        revision = permit.revision
        if (
            permit.flow_kind.value != "COLLABORATION_V2"
            or revision is None
            or revision.trip_id != permit.trip_id
            or permit.current_revision != revision.revision
            or request.trip.trip_id != permit.trip_id
        ):
            raise AppError(
                code="COLLABORATION_PLAN_SNAPSHOT_MISMATCH",
                message="规划请求与当前协作修订快照不一致",
                http_status=409,
                retryable=False,
                errors=[{"field": "trip.tripId"}],
            )
        expected = self._revision_planning_projection(revision)
        actual = self._request_planning_projection(request)
        paths = self._projection_mismatch_paths(expected, actual)
        # cityContext is Provider-derived. A county-level input such as 瑞安 can
        # legitimately materialize as the 温州市 planning scope. The exact
        # server-confirmed Trip below remains authoritative for that field.
        revision_paths = [path for path in paths if path != "cityName"]
        if revision_paths:
            raise AppError(
                code="COLLABORATION_PLAN_SNAPSHOT_MISMATCH",
                message="规划请求与当前协作修订快照不一致",
                http_status=409,
                retryable=False,
                errors=[{"field": path} for path in revision_paths],
            )
        if paths:
            try:
                self.workflow_service.require_confirmed_trip(
                    permit.trip_id,
                    request.trip,
                )
            except AppError as error:
                if error.code not in {
                    "TRIP_NOT_CONFIRMED",
                    "CONFIRMED_TRIP_MISMATCH",
                }:
                    raise
                raise AppError(
                    code="COLLABORATION_PLAN_SNAPSHOT_MISMATCH",
                    message="规划请求与当前协作修订快照不一致",
                    http_status=409,
                    retryable=False,
                    errors=[{"field": path} for path in paths],
                ) from error

    @staticmethod
    def _adjustment_identity_digest(
        event_constraints: EventConstraintSet,
        readiness: ExecutionReplanReadinessBinding,
        adjustment_event_id: UUID | None,
    ) -> str:
        identity: dict[str, Any] = {
            "eventConstraintDigest": event_constraints.input_digest,
            "collaborationReadiness": readiness.model_dump(
                mode="json",
                by_alias=True,
            ),
        }
        if adjustment_event_id is not None:
            identity["confirmedAdjustmentEventId"] = str(adjustment_event_id)
        canonical = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(canonical).hexdigest()

    def _restore_confirmed_adjustment(
        self,
        *,
        trip_id: UUID,
        current_plan_id: UUID | None,
        event_id: UUID,
        inline: ConfirmedExecutionAdjustment,
    ) -> ConfirmedExecutionAdjustment:
        event = self.workflow_service.get_adjustment_event(trip_id, event_id)
        if current_plan_id is None or event.plan_version_id != current_plan_id:
            raise AppError(
                code="S2_T021_ADJUSTMENT_EVENT_PLAN_MISMATCH",
                message="The confirmed adjustment event must belong to CURRENT.",
                http_status=409,
                retryable=False,
            )
        persisted = ConfirmedExecutionAdjustment(
            event_type=event.event_type,
            task_id=event.task_id,
            late_minutes=event.late_minutes,
            fatigue_level=event.fatigue_level,
        )
        if persisted != inline:
            raise AppError(
                code="S2_T021_ADJUSTMENT_EVENT_PAYLOAD_MISMATCH",
                message=(
                    "Inline adjustment must exactly match the server-confirmed "
                    "adjustment event."
                ),
                http_status=409,
                retryable=False,
            )
        return persisted

    @staticmethod
    def _require_trip_id(trip_id: UUID, request: CandidatePlanRequest) -> None:
        if request.trip.trip_id != trip_id:
            raise AppError(
                code="PLANNING_TRIP_ID_MISMATCH",
                message="CandidatePlanRequest.trip.tripId 必须与请求路径一致",
                http_status=409,
                errors=[
                    {
                        "field": "trip.tripId",
                        "expected": str(trip_id),
                        "actual": str(request.trip.trip_id),
                    }
                ],
            )

    @staticmethod
    def _planner_error(error: CandidatePlanInputError) -> AppError:
        return AppError(
            code=error.code,
            message=str(error),
            http_status=422,
            errors=[error.as_dict()],
        )

    @staticmethod
    def _rejected_error(error: CandidatePlanRejected) -> AppError:
        return AppError(
            code=error.code,
            message=str(error),
            http_status=422,
            errors=[
                result.model_dump(mode="json", by_alias=True)
                for result in error.results
            ],
        )

    @staticmethod
    def _contract_error(error: ReplanningContractError) -> AppError:
        return AppError(
            code=error.code,
            message=str(error),
            http_status=422,
            errors=[error.as_dict()],
        )

    @staticmethod
    def _trust_error(error: TrustedPlanningStoreError) -> AppError:
        return AppError(
            code=error.code,
            message=error.message,
            http_status=409,
            retryable=False,
        )

    @staticmethod
    def _proposal_validation(
        plan: Any,
        readiness_binding: ExecutionReplanReadinessBinding | None = None,
    ) -> dict[str, Any]:
        validation = {
            "validator": "T011",
            "metrics": plan.metrics.model_dump(mode="json", by_alias=True),
            "constraintsSnapshot": [
                item.model_dump(mode="json", by_alias=True)
                for item in plan.constraints_snapshot
            ],
            "sourcesSnapshot": [
                item.model_dump(mode="json", by_alias=True)
                for item in plan.sources_snapshot
            ],
        }

        if readiness_binding is not None:
            validation["collaborationReadiness"] = readiness_binding.model_dump(
                mode="json",
                by_alias=True,
            )
        return validation

    def _register_generated(
        self,
        proposal: ProposedPlanVersion,
        *,
        readiness_permit: ReadinessPermit,
    ) -> PlanVersion:
        """Register once, or recover an identical prior partial attempt.

        Staging and PlanVersion storage use separate fail-closed transactions. If
        registration committed but mark_issued did not, a retry must be able to
        load the exact immutable proposal and finish issuing it.
        """

        try:
            return self.plan_service.register_proposed(
                proposal,
                readiness_permit=readiness_permit,
            )
        except AppError as error:
            if error.code != "PLAN_VERSION_ALREADY_EXISTS":
                raise
            stored = self.plan_service.get_plan_version(
                proposal.trip_snapshot.trip_id,
                proposal.plan_id,
            )
            if proposal_digest(stored) != proposal_digest(proposal):
                raise AppError(
                    code="PLANNING_PROPOSAL_DIGEST_MISMATCH",
                    message="已存在的 PlanVersion 与本次服务端生成提案摘要不一致",
                    http_status=409,
                ) from error
            if (
                proposal.version == 2
                and stored.status is not PlanVersionStatus.PROPOSED
            ):
                raise AppError(
                    code="REPLAN_S1_VERSION_LIMIT",
                    message="Sprint 1 only supports one Plan V2 adjustment.",
                    http_status=409,
                ) from error
            return stored

    def generate_v1(
        self,
        trip_id: UUID,
        request: CandidatePlanRequest,
        *,
        access: PlanningAccess,
    ) -> PlanVersion:
        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.GENERATE_V1,
        ) as permit:
            return self._generate_v1_ready(
                trip_id,
                request,
                readiness_permit=permit,
            )

    def _generate_v1_ready(
        self,
        trip_id: UUID,
        request: CandidatePlanRequest,
        *,
        readiness_permit: ReadinessPermit,
    ) -> PlanVersion:
        self._require_trip_id(trip_id, request)
        if readiness_permit.flow_kind.value == "COLLABORATION_V2":
            self._require_collaboration_request_matches_revision(
                request,
                readiness_permit,
            )
        else:
            self.workflow_service.require_constraint_confirmed(
                trip_id,
                request.trip.participants[0].assistance_profile,
            )
            self.workflow_service.require_confirmed_trip(trip_id, request.trip)
        self._require_parent_trip_places_unique(trip_id, request.task_facts)
        try:
            candidate = generate_candidate_plan(request)
        except CandidatePlanInputError as error:
            raise self._planner_error(error) from error
        except CandidatePlanRejected as error:
            raise self._rejected_error(error) from error

        if candidate.warnings:
            review = self._stage_review(
                candidate,
                request,
                readiness_permit=readiness_permit,
            )
            raise AppError(
                code="CANDIDATE_CONFIRMATION_REQUIRED",
                message="候选计划包含需要用户确认的价格、设施或来源事实",
                http_status=422,
                errors=[
                    {
                        "code": "CANDIDATE_CONFIRMATION_REQUIRED",
                        "field": "candidate.metrics.validationStatus",
                        "message": "only a complete PASS candidate can become ProposedPlanVersion",
                        "reviewId": review.review_id,
                        "review": review.model_dump(mode="json", by_alias=True),
                    }
                ],
            )

        try:
            proposal = candidate_to_proposed_plan_version(candidate, request)
        except CandidatePlanInputError as error:
            raise self._planner_error(error) from error

        readiness_binding = self._readiness_binding(readiness_permit)
        validation = self._proposal_validation(proposal, readiness_binding)
        try:
            self.trust_repository.stage_candidate(
                plan=proposal,
                request=request,
                boundary_kind="V1",
                validation=validation,
            )
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error

        stored = self._register_generated(
            proposal,
            readiness_permit=readiness_permit,
        )
        try:
            self.trust_repository.mark_issued(stored, validation=validation)
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error
        return stored

    def get_review(
        self,
        trip_id: UUID,
        review_id: str,
        *,
        access: PlanningAccess,
    ) -> CandidatePlanReview:
        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.CONFIRM_REVIEW,
        ):
            return self._get_review_ready(trip_id, review_id)

    def _get_review_ready(self, trip_id: UUID, review_id: str) -> CandidatePlanReview:
        row = self.trust_repository.get_review(review_id)
        if row is None:
            raise AppError(
                code="PLANNING_REVIEW_NOT_FOUND",
                message="未找到候选计划确认记录",
                http_status=404,
            )
        if row["trip_id"] != str(trip_id):
            raise AppError(
                code="PLANNING_REVIEW_SCOPE_MISMATCH",
                message="候选计划确认记录不属于当前 Trip",
                http_status=409,
            )
        candidate = self._review_candidate(row)
        return self._review_from_row(row, candidate)

    def confirm_review(
        self,
        trip_id: UUID,
        review_id: str,
        confirmation: CandidateReviewConfirmationRequest,
        *,
        access: PlanningAccess,
    ) -> PlanVersion:
        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.CONFIRM_REVIEW,
        ) as permit:
            return self._confirm_review_ready(
                trip_id,
                review_id,
                confirmation,
                readiness_permit=permit,
            )

    def _confirm_review_ready(
        self,
        trip_id: UUID,
        review_id: str,
        confirmation: CandidateReviewConfirmationRequest,
        *,
        readiness_permit: ReadinessPermit,
    ) -> PlanVersion:
        row = self.trust_repository.get_review(review_id)
        if row is None:
            raise AppError(
                code="PLANNING_REVIEW_NOT_FOUND",
                message="未找到候选计划确认记录",
                http_status=404,
            )
        if row["trip_id"] != str(trip_id):
            raise AppError(
                code="PLANNING_REVIEW_SCOPE_MISMATCH",
                message="候选计划确认记录不属于当前 Trip",
                http_status=409,
            )

        candidate = self._review_candidate(row)
        request = self._review_request(row)
        if (
            self._review_id(
                candidate,
                request,
                readiness_permit=readiness_permit,
            )
            != review_id
        ):
            raise AppError(
                code="PLAN_READINESS_BINDING_CHANGED",
                message="候选 review 的 readiness 绑定已变化，请重新生成候选",
                http_status=409,
                retryable=False,
                errors=[{"field": "reviewId"}],
            )

        confirmation_digest = sha256(
            json.dumps(
                confirmation.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if row["review_state"] == "CONFIRMED":
            if row["confirmation_digest"] != confirmation_digest:
                raise AppError(
                    code="PLANNING_REVIEW_ALREADY_CONFIRMED",
                    message="该候选已使用不同的确认内容完成签发",
                    http_status=409,
                )
            assert row["issued_plan_id"]
            return self.plan_service.get_plan_version(
                trip_id,
                UUID(row["issued_plan_id"]),
            )

        items = self._review_items(candidate, request)
        expected_ids = {item.item_id for item in items}
        supplied = {item.item_id: item for item in confirmation.confirmations}
        if set(supplied) != expected_ids:
            raise AppError(
                code="PLANNING_REVIEW_INCOMPLETE",
                message="必须逐项确认当前候选的全部未知事实",
                http_status=422,
                errors=[
                    {
                        "missingItemIds": sorted(expected_ids - set(supplied)),
                        "unexpectedItemIds": sorted(set(supplied) - expected_ids),
                    }
                ],
            )

        confirmed_request = self._apply_confirmations(
            request,
            items,
            supplied,
            confirmed_at=datetime.fromisoformat(row["created_at"]),
        )
        if readiness_permit.flow_kind.value == "COLLABORATION_V2":
            self._require_collaboration_request_matches_revision(
                confirmed_request,
                readiness_permit,
            )
        self._require_parent_trip_places_unique(
            trip_id,
            confirmed_request.task_facts,
        )
        try:
            confirmed_candidate = generate_candidate_plan(confirmed_request)
            proposal = candidate_to_proposed_plan_version(
                confirmed_candidate,
                confirmed_request,
            )
        except CandidatePlanInputError as error:
            raise self._planner_error(error) from error
        except CandidatePlanRejected as error:
            raise self._rejected_error(error) from error

        readiness_binding = self._readiness_binding(readiness_permit)
        validation = self._proposal_validation(proposal, readiness_binding)
        try:
            self.trust_repository.stage_candidate(
                plan=proposal,
                request=confirmed_request,
                boundary_kind="V1",
                validation=validation,
            )
            stored = self._register_generated(
                proposal,
                readiness_permit=readiness_permit,
            )
            self.trust_repository.mark_issued(stored, validation=validation)
            self.trust_repository.mark_review_confirmed(
                review_id=review_id,
                confirmation_digest=confirmation_digest,
                confirmed_request=confirmed_request,
                issued_plan_id=stored.plan_id,
            )
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error
        return stored

    def _stage_review(
        self,
        candidate: CandidatePlan,
        request: CandidatePlanRequest,
        *,
        readiness_permit: ReadinessPermit,
    ) -> CandidatePlanReview:
        review_id = self._review_id(
            candidate,
            request,
            readiness_permit=readiness_permit,
        )
        try:
            row = self.trust_repository.stage_review(
                review_id=review_id,
                request=request,
                candidate=candidate,
            )
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error
        return self._review_from_row(row, candidate)

    @staticmethod
    def _review_id(
        candidate: CandidatePlan,
        request: CandidatePlanRequest,
        *,
        readiness_permit: ReadinessPermit,
    ) -> str:
        identity = (
            f"xingzhi:candidate-review:{request.trip.trip_id}:{candidate.candidate_id}"
        )
        if readiness_permit.flow_kind.value == "COLLABORATION_V2":
            identity += ":" + json.dumps(
                PlanningBoundaryService._readiness_binding(
                    readiness_permit
                ).model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        return str(uuid5(NAMESPACE_URL, identity))

    @staticmethod
    def _review_candidate(row: dict[str, Any]) -> CandidatePlan:
        try:
            return CandidatePlan.model_validate_json(
                row["candidate_json"], strict=True
            )
        except ValidationError as error:
            raise AppError(
                code="PLANNING_REVIEW_INVALID",
                message="保存的候选计划确认记录无法通过严格校验",
                http_status=409,
            ) from error

    @staticmethod
    def _review_request(row: dict[str, Any]) -> CandidatePlanRequest:
        try:
            return CandidatePlanRequest.model_validate_json(
                row["request_json"], strict=True
            )
        except ValidationError as error:
            raise AppError(
                code="PLANNING_REVIEW_INVALID",
                message="保存的候选计划事实无法通过严格校验",
                http_status=409,
            ) from error

    @classmethod
    def _review_from_row(
        cls,
        row: dict[str, Any],
        candidate: CandidatePlan,
    ) -> CandidatePlanReview:
        request = cls._review_request(row)
        return CandidatePlanReview(
            review_id=row["review_id"],
            trip_id=row["trip_id"],
            candidate_id=row["candidate_id"],
            status=row["review_state"],
            created_at=datetime.fromisoformat(row["created_at"]),
            confirmed_at=(
                datetime.fromisoformat(row["confirmed_at"])
                if row["confirmed_at"]
                else None
            ),
            items=cls._review_items(candidate, request),
        )

    @staticmethod
    def _review_items(
        candidate: CandidatePlan,
        request: CandidatePlanRequest,
    ) -> tuple[CandidateReviewItem, ...]:
        tasks = {item.task_id: item for item in request.task_facts}
        facility_labels = {
            "ELEVATOR": "电梯",
            "RAMP": "坡道",
            "NURSING_ROOM": "母婴室",
            "ACCESSIBLE_ENTRANCE": "无障碍入口",
        }
        output: list[CandidateReviewItem] = []
        for warning in candidate.warnings:
            task_id = next(
                (
                    candidate_task_id
                    for candidate_task_id in sorted(tasks, key=len, reverse=True)
                    if warning.reference_id.startswith(f"{candidate_task_id}.")
                ),
                "",
            )
            task = tasks.get(task_id)
            title = task.title if task is not None else "行程"
            facility_type = (
                warning.reference_id.rsplit(".", 1)[-1]
                if warning.code == "UNKNOWN_FACILITY"
                else None
            )
            if warning.code == "UNKNOWN_PRICE":
                kind = "地点费用" if warning.reference_id.endswith(".placePrice") else "交通费用"
                label = f"{title} · {kind}"
                value_type = "PRICE_CENTS"
            elif warning.code == "UNKNOWN_FACILITY":
                label = f"{title} · {facility_labels.get(facility_type or '', facility_type or '设施')}"
                value_type = "FACILITY_STATUS"
            else:
                label = f"{title} · 数据来源"
                value_type = "SOURCE_CONFIRMATION"
            output.append(
                CandidateReviewItem(
                    item_id=f"{warning.code}:{warning.reference_id}",
                    code=warning.code,
                    reference_id=warning.reference_id,
                    field=warning.field,
                    label=label,
                    value_type=value_type,
                    facility_type=facility_type,
                )
            )
        return tuple(output)

    @staticmethod
    def _apply_confirmations(
        request: CandidatePlanRequest,
        items: tuple[CandidateReviewItem, ...],
        supplied: dict[str, Any],
        *,
        confirmed_at: datetime,
    ) -> CandidatePlanRequest:
        payload = deepcopy(request.model_dump(mode="json", by_alias=True))
        task_by_id = {
            item["taskId"]: item for item in payload["taskFacts"]
        }
        provenance = {
            "provider": "AMAP",
            "sourceStatus": "USER_CONFIRMED",
            "fetchedAt": confirmed_at.isoformat(),
            "isStale": False,
        }
        for item in items:
            value = supplied[item.item_id]
            task_id = next(
                (
                    candidate_task_id
                    for candidate_task_id in sorted(task_by_id, key=len, reverse=True)
                    if item.reference_id.startswith(f"{candidate_task_id}.")
                ),
                "",
            )
            task = task_by_id.get(task_id)
            if item.value_type == "PRICE_CENTS":
                if value.amount_cents is None or value.facility_status is not None or value.source_confirmed is not None:
                    raise AppError(
                        code="PLANNING_REVIEW_VALUE_INVALID",
                        message=f"{item.label} 必须填写确认金额（免费填 0）",
                        http_status=422,
                    )
                assert task is not None
                target = task["place"] if item.reference_id.endswith(".placePrice") else task["route"]
                target["priceReference"]["amountCents"] = value.amount_cents
                target["priceReference"]["provenance"] = provenance
                task["note"] = task["note"].replace(
                    "仅累计 Provider 已返回的金额，未知价格仍需确认",
                    "费用已由用户确认并经服务端复算",
                )
            elif item.value_type == "FACILITY_STATUS":
                if value.facility_status is None or value.amount_cents is not None or value.source_confirmed is not None:
                    raise AppError(
                        code="PLANNING_REVIEW_VALUE_INVALID",
                        message=f"{item.label} 必须确认存在或不存在",
                        http_status=422,
                    )
                assert task is not None and item.facility_type is not None
                matches = [
                    fact for fact in task["route"]["facilityEvidence"]
                    if fact["facilityType"] == item.facility_type
                ]
                if len(matches) > 1:
                    raise AppError(
                        code="PLANNING_REVIEW_REFERENCE_INVALID",
                        message=f"{item.label} 无法绑定唯一设施证据",
                        http_status=409,
                    )
                if not matches:
                    fact = {
                        "facilityType": item.facility_type,
                        "label": item.label.rsplit(" · ", 1)[-1],
                        "status": value.facility_status,
                        "message": value.note or "用户现场确认",
                        "referenceId": f"user-confirmed:{item.reference_id}",
                        "provenance": provenance,
                    }
                    task["route"]["facilityEvidence"].append(fact)
                else:
                    matches[0]["status"] = value.facility_status
                    matches[0]["message"] = value.note or "用户现场确认"
                    matches[0]["provenance"] = provenance
            else:
                if value.source_confirmed is not True or value.amount_cents is not None or value.facility_status is not None:
                    raise AppError(
                        code="PLANNING_REVIEW_VALUE_INVALID",
                        message=f"{item.label} 必须明确确认来源",
                        http_status=422,
                    )
                if item.reference_id == "trip.startLocation":
                    payload["startLocation"]["provenance"] = provenance
                elif item.reference_id == "trip.endLocation":
                    payload["endLocation"]["provenance"] = provenance
                else:
                    assert task is not None
                    target = task["place"] if item.reference_id.endswith(".placePrice") else task["route"]
                    target["provenance"] = provenance
        try:
            return CandidatePlanRequest.model_validate_json(
                json.dumps(payload, ensure_ascii=False), strict=True
            )
        except ValidationError as error:
            raise AppError(
                code="PLANNING_REVIEW_RESULT_INVALID",
                message="用户确认后的候选事实未通过严格契约校验",
                http_status=422,
            ) from error

    def generate_v2_from_events(
        self,
        trip_id: UUID,
        request: EventDrivenReplanRequest,
        *,
        access: PlanningAccess,
    ) -> RegisteredReplan:
        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.GENERATE_V2,
        ) as permit:
            return self._generate_v2_from_events_ready(
                trip_id,
                request,
                readiness_permit=permit,
            )

    def _generate_v2_from_events_ready(
        self,
        trip_id: UUID,
        request: EventDrivenReplanRequest,
        *,
        readiness_permit: ReadinessPermit,
    ) -> RegisteredReplan:
        current, events = self._load_current_v1_context(trip_id)
        current_request = self._load_current_candidate_request(trip_id, current)
        candidate_request, frozen_task_ids = self._event_driven_candidate_request(
            current=current,
            current_request=current_request,
            events=events,
        )
        return self._select_and_register_v2(
            trip_id=trip_id,
            current=current,
            events=events,
            reason=request.reason,
            locked_task_ids=frozen_task_ids,
            candidate_inputs=((candidate_request, 0),),
            registration_permit=readiness_permit,
            readiness_binding=self._readiness_binding(readiness_permit),
        )

    def generate_v2_from_adjustment(
        self,
        trip_id: UUID,
        request: ExecutionAdjustmentReplanRequest,
        *,
        access: PlanningAccess,
    ) -> RegisteredExecutionAdjustmentReplan:
        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.GENERATE_V2,
        ) as permit:
            return self._generate_v2_from_adjustment_ready(
                trip_id,
                request,
                readiness_permit=permit,
                readiness=self._readiness_binding(permit),
            )

    def _generate_v2_from_adjustment_ready(
        self,
        trip_id: UUID,
        request: ExecutionAdjustmentReplanRequest,
        *,
        readiness_permit: ReadinessPermit,
        readiness: ExecutionReplanReadinessBinding,
    ) -> RegisteredExecutionAdjustmentReplan:
        """S2-T021: replan a trusted suffix under a transient T020 overlay."""

        self._require_adjustment_execution_state(trip_id)
        if isinstance(self.suffix_planner, DeterministicRetainedSuffixPlanner):
            raise AppError(
                code="S2_T021_CANDIDATE_SOURCE_UNAVAILABLE",
                message=(
                    "S2-T021 requires an event-aware trusted suffix planner; "
                    "the retained-suffix fallback cannot issue an adjustment V2."
                ),
                http_status=503,
                retryable=True,
            )
        current, events = self._load_current_v1_context(trip_id)
        self._require_issued_readiness(
            trip_id,
            current.plan_id,
            boundary_kind="V1",
            current=readiness,
        )
        current_request = self._load_current_candidate_request(trip_id, current)
        adjustment = request.adjustment
        if request.adjustment_event_id is not None:
            adjustment = self._restore_confirmed_adjustment(
                trip_id=trip_id,
                current_plan_id=current.plan_id,
                event_id=request.adjustment_event_id,
                inline=request.adjustment,
            )
        try:
            projection = project_execution_adjustment(
                current_plan=current,
                current_request=current_request,
                events=events,
                adjustment=adjustment,
                locked_task_ids=request.locked_task_ids,
            )
        except ExecutionReplanContextError as error:
            raise AppError(
                code=error.code,
                message=error.message,
                http_status=409,
                retryable=False,
                errors=[error.as_dict()],
            ) from error

        event_constraints = compile_execution_constraints(
            ExecutionConstraintCompileRequest(
                event=adjustment,
                current_constraints=projection.remaining_context,
            )
        )
        prefix_length = len(projection.frozen_task_ids)
        original_suffix = tuple(current_request.task_facts[prefix_length:])
        planned_suffix = self._plan_suffix(
            SuffixPlanningInput(
                task_facts=original_suffix,
                frozen_task_ids=projection.frozen_task_ids,
                actual_spent_cents=projection.actual_spent_cents,
                event_constraints=event_constraints,
                source_event_task_id=adjustment.task_id,
                anchor_end_at=current_request.task_facts[
                    prefix_length - 1
                ].end_at,
            ),
            original_suffix=original_suffix,
            start_order=prefix_length + 1,
        )
        payload = current_request.model_dump(mode="json", by_alias=True)
        payload["taskFacts"] = [
            item.model_dump(mode="json", by_alias=True)
            for item in (
                *current_request.task_facts[:prefix_length],
                *planned_suffix,
            )
        ]
        try:
            candidate_request = CandidatePlanRequest.model_validate_json(
                json.dumps(payload, ensure_ascii=False),
                strict=True,
            )
        except ValidationError as error:
            raise AppError(
                code="S2_T021_SUFFIX_PLANNER_INVALID",
                message="transient suffix output is not a valid CandidatePlanRequest",
                http_status=422,
                errors=[{"path": "taskFacts", "message": str(error)}],
            ) from error

        reason = (
            PlanVersionReason.DELAY
            if adjustment.event_type is ExecutionAdjustmentType.LATE
            else PlanVersionReason.FATIGUE
        )
        registered = self._select_and_register_v2(
            trip_id=trip_id,
            current=current,
            events=events,
            reason=reason,
            locked_task_ids=projection.frozen_task_ids,
            candidate_inputs=((candidate_request, 0),),
            event_constraints=event_constraints,
            readiness_binding=readiness,
            adjustment_event_id=request.adjustment_event_id,
            registration_permit=readiness_permit,
        )
        return RegisteredExecutionAdjustmentReplan(
            current_plan_id=current.plan_id,
            replan=registered,
            event_constraints=event_constraints,
            derived_context=projection.remaining_context,
        )

    def _load_current_v1_context(
        self,
        trip_id: UUID,
    ) -> tuple[PlanVersion, tuple[ExecutionEvent, ...]]:
        state = self.plan_service.get_trip_state(trip_id)
        current = state.current_plan
        if current is None:
            raise AppError(
                code="REPLAN_CURRENT_PLAN_REQUIRED",
                message="A CURRENT PlanVersion is required before Plan V2 replanning.",
                http_status=409,
            )
        if current.version != 1:
            raise AppError(
                code="REPLAN_S1_VERSION_LIMIT",
                message="Sprint 1 only supports replanning from CURRENT Plan V1.",
                http_status=409,
            )
        try:
            self.trust_repository.require_issued(
                trip_id=trip_id,
                plan=current,
                boundary_kind="V1",
            )
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error
        return current, tuple(self.workflow_service.list_events(trip_id))

    def _require_adjustment_execution_state(self, trip_id: UUID) -> None:
        state = self.plan_service.get_trip_state(trip_id)
        if state.trip_status is not TripStatus.EXECUTING:
            raise AppError(
                code="REPLAN_EXECUTION_REQUIRED",
                message="Trip must be EXECUTING before server-side replanning.",
                http_status=409,
            )
        if state.proposed_plans:
            raise AppError(
                code="REPLAN_CANDIDATE_PENDING",
                message="Resolve the existing proposed Plan V2 before replanning again.",
                http_status=409,
            )

    def _load_current_candidate_request(
        self,
        trip_id: UUID,
        current: PlanVersion,
    ) -> CandidatePlanRequest:
        try:
            facts = self.trust_repository.get_candidate_request(current.plan_id)
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error
        if facts is None or facts.trip.trip_id != trip_id:
            raise AppError(
                code="PLANNING_FACTS_INVALID",
                message="CURRENT Plan V1 is missing trusted CandidatePlanRequest facts.",
                http_status=409,
            )
        self._require_current_request_matches_plan(current, facts)
        return facts

    @staticmethod
    def _require_current_request_matches_plan(
        current: PlanVersion,
        request: CandidatePlanRequest,
    ) -> None:
        plan_tasks = tuple(current.days[0].tasks)
        fact_ids = tuple(fact.task_id for fact in request.task_facts)
        plan_ids = tuple(task.task_id for task in plan_tasks)
        fact_orders = tuple(fact.order for fact in request.task_facts)
        plan_orders = tuple(task.order for task in plan_tasks)
        if fact_ids != plan_ids or fact_orders != plan_orders:
            raise AppError(
                code="REPLAN_CURRENT_FACTS_MISMATCH",
                message="CURRENT Plan V1 tasks do not match trusted planning facts.",
                http_status=409,
                errors=[
                    {
                        "planTaskIds": list(plan_ids),
                        "factTaskIds": list(fact_ids),
                    }
                ],
            )

    def _event_driven_candidate_request(
        self,
        *,
        current: PlanVersion,
        current_request: CandidatePlanRequest,
        events: Sequence[ExecutionEvent],
    ) -> tuple[CandidatePlanRequest, tuple[str, ...]]:
        self._require_current_request_matches_plan(current, current_request)
        tasks = tuple(current.days[0].tasks)
        task_index = {task.task_id: index for index, task in enumerate(tasks)}
        prefix_length, actual_spent_cents = self._project_event_prefix(
            current=current,
            events=events,
            task_index=task_index,
        )
        if prefix_length >= len(tasks):
            raise AppError(
                code="REPLAN_SUFFIX_EMPTY",
                message="No unfinished suffix remains for S1-T017 replanning.",
                http_status=409,
            )

        frozen_task_ids = tuple(task.task_id for task in tasks[:prefix_length])
        suffix_facts = tuple(current_request.task_facts[prefix_length:])
        planned_suffix = self._plan_suffix(
            SuffixPlanningInput(
                task_facts=suffix_facts,
                frozen_task_ids=frozen_task_ids,
                actual_spent_cents=actual_spent_cents,
            ),
            original_suffix=suffix_facts,
            start_order=prefix_length + 1,
        )
        payload = current_request.model_dump(mode="json", by_alias=True)
        payload["taskFacts"] = [
            item.model_dump(mode="json", by_alias=True)
            for item in (
                *current_request.task_facts[:prefix_length],
                *planned_suffix,
            )
        ]
        try:
            candidate_request = CandidatePlanRequest.model_validate_json(
                json.dumps(payload, ensure_ascii=False),
                strict=True,
            )
        except ValidationError as error:
            raise AppError(
                code="REPLAN_SUFFIX_PLANNER_INVALID",
                message="Suffix planner output did not produce a valid CandidatePlanRequest.",
                http_status=422,
                errors=[{"path": "taskFacts", "message": str(error)}],
            ) from error
        return candidate_request, frozen_task_ids

    @staticmethod
    def _project_event_prefix(
        *,
        current: PlanVersion,
        events: Sequence[ExecutionEvent],
        task_index: Mapping[str, int],
    ) -> tuple[int, int]:
        if not events:
            raise AppError(
                code="REPLAN_EVENTS_REQUIRED",
                message="Event-driven replanning requires at least one execution event.",
                http_status=409,
            )

        frozen_indexes: list[int] = []
        expense_task_ids: set[str] = set()
        completed_task_ids: set[str] = set()
        actual_spent_cents = 0
        for index, event in enumerate(events):
            if event.trip_id != current.trip_snapshot.trip_id:
                raise AppError(
                    code="REPLAN_EVENT_TRIP_MISMATCH",
                    message="Execution event belongs to another Trip.",
                    http_status=409,
                    errors=[{"path": f"events[{index}].tripId"}],
                )
            if event.plan_version_id != current.plan_id:
                raise AppError(
                    code="REPLAN_EVENT_PLAN_MISMATCH",
                    message="Execution event does not belong to CURRENT Plan V1.",
                    http_status=409,
                    errors=[{"path": f"events[{index}].planVersionId"}],
                )
            if event.task_id not in task_index:
                raise AppError(
                    code="REPLAN_EVENT_TASK_NOT_FOUND",
                    message="Execution event task is not in CURRENT Plan V1.",
                    http_status=409,
                    errors=[{"path": f"events[{index}].taskId"}],
                )
            if event.event_type is ExecutionEventType.EXPENSE:
                if event.amount_cents is None:
                    raise AppError(
                        code="REPLAN_EXPENSE_AMOUNT_REQUIRED",
                        message="EXPENSE events must include amountCents.",
                        http_status=409,
                    )
                expense_task_ids.add(event.task_id)
                actual_spent_cents += event.amount_cents
            elif event.event_type is ExecutionEventType.COMPLETE:
                completed_task_ids.add(event.task_id)
                frozen_indexes.append(task_index[event.task_id])
            elif event.event_type in {ExecutionEventType.START, ExecutionEventType.SKIP}:
                frozen_indexes.append(task_index[event.task_id])

        missing_expense = tuple(
            sorted(completed_task_ids - expense_task_ids, key=task_index.__getitem__)
        )
        if missing_expense:
            raise AppError(
                code="REPLAN_EXPENSE_INCOMPLETE",
                message="Every COMPLETE task must have an explicit EXPENSE event.",
                http_status=409,
                errors=[{"taskIds": list(missing_expense)}],
            )

        if not expense_task_ids:
            raise AppError(
                code="REPLAN_EXPENSE_REQUIRED",
                message="EXPENSE_CHANGE replanning requires an EXPENSE event.",
                http_status=409,
            )

        prefix_length = max(frozen_indexes) + 1 if frozen_indexes else 0
        return prefix_length, actual_spent_cents

    def _plan_suffix(
        self,
        planning_input: SuffixPlanningInput,
        *,
        original_suffix: Sequence[CandidateTaskFact],
        start_order: int,
    ) -> tuple[CandidateTaskFact, ...]:
        try:
            planned = self.suffix_planner.plan_suffix(planning_input)
        except SuffixPlanningError as error:
            raise AppError(
                code=error.code,
                message=error.message,
                http_status=422,
                retryable=False,
                errors=[error.as_dict()],
            ) from error
        except Exception as error:
            raise AppError(
                code="REPLAN_SUFFIX_PLANNER_FAILED",
                message="Suffix planner failed while producing a candidate suffix.",
                http_status=422,
            ) from error
        return self._normalize_suffix_facts(
            planned,
            original_suffix=original_suffix,
            frozen_task_ids=planning_input.frozen_task_ids,
            start_order=start_order,
        )

    @classmethod
    def _normalize_suffix_facts(
        cls,
        planned: object,
        *,
        original_suffix: Sequence[CandidateTaskFact],
        frozen_task_ids: Sequence[str],
        start_order: int,
    ) -> tuple[CandidateTaskFact, ...]:
        if not isinstance(planned, Sequence) or isinstance(planned, (str, bytes)):
            raise cls._suffix_planner_invalid(
                "suffix",
                "Suffix planner must return a sequence of CandidateTaskFact objects.",
            )
        if len(planned) != len(original_suffix):
            raise cls._suffix_planner_invalid(
                "suffix",
                "Suffix planner must return exactly the unfinished suffix length.",
            )

        frozen = set(frozen_task_ids)
        original_order_by_task = {
            fact.task_id: fact.order for fact in original_suffix
        }
        seen: set[str] = set()
        output: list[CandidateTaskFact] = []
        for offset, item in enumerate(planned):
            fact = cls._strict_task_fact(item, path=f"suffix[{offset}]")
            expected_order = start_order + offset
            if fact.order != expected_order:
                raise cls._suffix_planner_invalid(
                    f"suffix[{offset}].order",
                    "Suffix planner must preserve contiguous suffix order.",
                )
            if fact.task_id in frozen:
                raise cls._suffix_planner_invalid(
                    f"suffix[{offset}].taskId",
                    "Suffix planner must not return frozen tasks.",
                )
            original_order = original_order_by_task.get(fact.task_id)
            if original_order is not None and original_order != fact.order:
                raise cls._suffix_planner_invalid(
                    f"suffix[{offset}].taskId",
                    "Existing suffix task ids cannot move across order slots.",
                )
            if fact.task_id in seen:
                raise cls._suffix_planner_invalid(
                    f"suffix[{offset}].taskId",
                    "Suffix planner returned duplicate task ids.",
                )
            seen.add(fact.task_id)
            output.append(fact)
        return tuple(output)

    @staticmethod
    def _strict_task_fact(value: object, *, path: str) -> CandidateTaskFact:
        try:
            if not isinstance(value, CandidateTaskFact):
                raise TypeError("expected CandidateTaskFact")
            raw = value.model_dump_json(by_alias=True, warnings="error")
            return CandidateTaskFact.model_validate_json(raw, strict=True)
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            raise PlanningBoundaryService._suffix_planner_invalid(
                path,
                str(error),
            ) from error

    @staticmethod
    def _suffix_planner_invalid(path: str, message: str) -> AppError:
        return AppError(
            code="REPLAN_SUFFIX_PLANNER_INVALID",
            message="Suffix planner returned invalid output.",
            http_status=422,
            errors=[{"path": path, "message": message}],
        )

    def _select_and_register_v2(
        self,
        *,
        trip_id: UUID,
        current: PlanVersion,
        events: Sequence[ExecutionEvent],
        reason: Any,
        locked_task_ids: Sequence[str],
        candidate_inputs: Sequence[tuple[CandidatePlanRequest, int]],
        event_constraints: EventConstraintSet | None = None,
        readiness_binding: ExecutionReplanReadinessBinding | None = None,
        adjustment_event_id: UUID | None = None,
        registration_permit: ReadinessPermit | None = None,
    ) -> RegisteredReplan:
        if registration_permit is None:
            raise AppError(
                code="PLANNING_ACCESS_INVALID",
                message="V2 登记缺少服务端规划许可",
                http_status=409,
                retryable=False,
            )
        current_readiness = self._readiness_binding(registration_permit)
        if readiness_binding is None:
            readiness_binding = current_readiness
        elif readiness_binding != current_readiness:
            raise AppError(
                code="PLAN_READINESS_BINDING_CHANGED",
                message="V2 候选的 readiness 绑定已变化，请重新生成候选",
                http_status=409,
                retryable=False,
            )
        self._require_issued_readiness(
            trip_id,
            current.plan_id,
            boundary_kind="V1",
            current=current_readiness,
        )
        identity_digest = (
            self._adjustment_identity_digest(
                event_constraints,
                readiness_binding,
                adjustment_event_id,
            )
            if event_constraints is not None and readiness_binding is not None
            else (
                event_constraints.input_digest
                if event_constraints is not None
                else None
            )
        )
        candidates: list[ReplanCandidate] = []
        candidate_requests: dict[UUID, CandidatePlanRequest] = {}
        satisfaction_loss_by_plan_id: dict[UUID, int] = {}
        generation_failures: list[dict[str, Any]] = []
        for index, (candidate_request, satisfaction_loss) in enumerate(candidate_inputs):
            self._require_trip_id(trip_id, candidate_request)
            if registration_permit.flow_kind.value == "COLLABORATION_V2":
                self._require_collaboration_request_matches_revision(
                    candidate_request,
                    registration_permit,
                )
            try:
                self._require_parent_trip_places_unique(
                    trip_id,
                    candidate_request.task_facts,
                )
                generated = generate_candidate_plan(candidate_request)
                proposal = candidate_to_proposed_plan_version_v2(
                    generated,
                    candidate_request,
                    current,
                    reason=reason,
                    identity_digest=identity_digest,
                )
            except CandidatePlanRejected as error:
                generation_failures.append(
                    {
                        "candidateIndex": index,
                        "code": error.code,
                        "affectedRuleIds": [
                            result.rule_id for result in error.results
                        ],
                        "results": [
                            result.model_dump(mode="json", by_alias=True)
                            for result in error.results
                        ],
                    }
                )
                continue
            except CandidatePlanInputError as error:
                generation_failures.append(
                    {
                        "candidateIndex": index,
                        **error.as_dict(),
                    }
                )
                continue
            except AppError as error:
                if error.code != "PARENT_TRIP_PLACE_REUSED":
                    raise
                generation_failures.append(
                    {
                        "candidateIndex": index,
                        "code": error.code,
                        "message": error.message,
                        "conflicts": error.errors,
                    }
                )
                continue

            candidate_requests[proposal.plan_id] = candidate_request
            satisfaction_loss_by_plan_id[proposal.plan_id] = satisfaction_loss
            candidates.append(
                ReplanCandidate(
                    plan=proposal,
                    satisfaction_loss=satisfaction_loss,
                )
            )

        if not candidates:
            memory_failures = [
                failure for failure in generation_failures
                if failure.get("code") == "PARENT_TRIP_PLACE_REUSED"
            ]
            if memory_failures and len(memory_failures) == len(candidate_inputs):
                raise AppError(
                    code="PARENT_TRIP_PLACE_REUSED",
                    message="全部重规划候选都复用了父行程其他日期的地点。",
                    http_status=409,
                    retryable=False,
                    errors=memory_failures,
                )
            if event_constraints is not None:
                affected = sorted(
                    {
                        rule_id
                        for failure in generation_failures
                        for rule_id in failure.get("affectedRuleIds", ())
                    }
                    | {
                        str(failure.get("code"))
                        for failure in generation_failures
                        if failure.get("code")
                    }
                )
                raise AppError(
                    code="REPLAN_NO_FEASIBLE_CANDIDATE",
                    message="No adjustment candidate passed server-side HARD validation.",
                    http_status=422,
                    errors=[
                        {
                            "frozenTaskIds": list(locked_task_ids),
                            "affectedRuleIds": affected,
                            "conflicts": [
                                {
                                    "candidateIndex": failure.get("candidateIndex"),
                                    "code": failure.get("code"),
                                    "affectedRuleIds": failure.get(
                                        "affectedRuleIds", []
                                    ),
                                }
                                for failure in generation_failures
                            ],
                            "relaxations": [],
                        }
                    ],
                )
            raise AppError(
                code="REPLAN_NO_FEASIBLE_CANDIDATE",
                message="No candidate passed server-side T011 validation.",
                http_status=422,
                errors=generation_failures,
            )

        fact_source = _InMemoryTrustedCandidateFacts(candidate_requests)
        validator = T011ReplanCandidateValidator(
            fact_source,
            identity_digest_by_plan_id=(
                {
                    plan_id: identity_digest
                    for plan_id in candidate_requests
                }
                if identity_digest is not None
                else None
            ),
        )
        if event_constraints is not None:
            validator = EventConstraintReplanValidator(
                base_validator=validator,
                fact_source=fact_source,
                event_constraints=event_constraints,
                frozen_task_ids=locked_task_ids,
            )
        selector = MinimumDisruptionSelector(validator)
        try:
            outcome = selector.select(
                current_plan=current,
                candidates=tuple(candidates),
                events=events,
                locked_task_ids=locked_task_ids,
            )
        except ReplanningContractError as error:
            raise self._contract_error(error) from error

        if isinstance(outcome, NoFeasibleReplan):
            if event_constraints is not None:
                raise AppError(
                    code="REPLAN_NO_FEASIBLE_CANDIDATE",
                    message="No adjustment candidate satisfied frozen-prefix and HARD constraints.",
                    http_status=422,
                    errors=[
                        {
                            "frozenTaskIds": list(outcome.frozen_task_ids),
                            "affectedRuleIds": list(outcome.affected_rule_ids),
                            "conflicts": [
                                {"ruleId": rule_id}
                                for rule_id in outcome.affected_rule_ids
                            ],
                            "relaxations": [
                                item.model_dump(mode="json", by_alias=True)
                                for item in outcome.relaxations
                            ],
                        }
                    ],
                )
            raise AppError(
                code="REPLAN_NO_FEASIBLE_CANDIDATE",
                message="T018 found no candidate satisfying frozen-prefix and HARD constraints.",
                http_status=422,
                errors=[
                    *generation_failures,
                    {
                        "affectedRuleIds": list(outcome.affected_rule_ids),
                        "relaxations": [
                            item.model_dump(mode="json", by_alias=True)
                            for item in outcome.relaxations
                        ],
                        "assessments": [
                            item.model_dump(mode="json", by_alias=True)
                            for item in outcome.assessments
                        ],
                    },
                ],
            )

        selected_plan_id = outcome.selected_plan.plan_id
        assessment = next(
            item
            for item in outcome.assessments
            if item.candidate_plan_id == selected_plan_id
        )
        assert assessment.modified_task_count is not None
        if event_constraints is not None and assessment.modified_task_count == 0:
            raise AppError(
                code="REPLAN_ADJUSTMENT_NO_CHANGE",
                message="当前安排已满足本次调整后的限制，没有实际任务变化；保留原计划，不签发空白 V2。",
                http_status=422,
                retryable=False,
            )
        selected_request = candidate_requests[selected_plan_id]
        selected_satisfaction_loss = satisfaction_loss_by_plan_id[selected_plan_id]
        selection_validation = {
            **self._proposal_validation(outcome.selected_plan),
            "selector": "T018_MINIMUM_DISRUPTION",
            "validationReport": outcome.validation_report.model_dump(
                mode="json",
                by_alias=True,
            ),
            "assessments": [
                item.model_dump(mode="json", by_alias=True)
                for item in outcome.assessments
            ],
        }
        if event_constraints is not None:
            selection_validation["transientEventConstraints"] = (
                event_constraints.model_dump(mode="json", by_alias=True)
            )
        if readiness_binding is not None:
            selection_validation["collaborationReadiness"] = (
                readiness_binding.model_dump(mode="json", by_alias=True)
            )
        if adjustment_event_id is not None:
            selection_validation["confirmedAdjustmentEventId"] = str(
                adjustment_event_id
            )
        try:
            self.trust_repository.stage_candidate(
                plan=outcome.selected_plan,
                request=selected_request,
                boundary_kind="V2",
                validation=selection_validation,
            )
            stored = self._register_generated(
                outcome.selected_plan,
                readiness_permit=registration_permit,
            )
            self.trust_repository.mark_issued(
                stored,
                validation=selection_validation,
            )
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error

        return RegisteredReplan(
            plan=stored,
            disruption_score=assessment.modified_task_count,
            satisfaction_loss=selected_satisfaction_loss,
            frozen_task_ids=outcome.frozen_task_ids,
            assessments=outcome.assessments,
            validation_report=outcome.validation_report,
        )

    def generate_v2(
        self,
        trip_id: UUID,
        request: ReplanGenerationRequest,
        *,
        access: PlanningAccess,
    ) -> RegisteredReplan:
        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.GENERATE_V2,
        ) as permit:
            return self._generate_v2_ready(
                trip_id,
                request,
                readiness_permit=permit,
            )

    def _generate_v2_ready(
        self,
        trip_id: UUID,
        request: ReplanGenerationRequest,
        *,
        readiness_permit: ReadinessPermit,
    ) -> RegisteredReplan:
        current, events = self._load_current_v1_context(trip_id)
        candidate_inputs = tuple(
            (candidate_input.request, candidate_input.satisfaction_loss)
            for candidate_input in request.candidates
        )
        return self._select_and_register_v2(
            trip_id=trip_id,
            current=current,
            events=events,
            reason=request.reason,
            locked_task_ids=request.locked_task_ids,
            candidate_inputs=candidate_inputs,
            registration_permit=readiness_permit,
            readiness_binding=self._readiness_binding(readiness_permit),
        )

    def require_v1_confirmation(
        self,
        trip_id: UUID,
        plan_id: UUID,
        *,
        access: PlanningAccess,
    ) -> None:
        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.PLAN_DECISION,
        ) as permit:
            self._require_unexpired_permit(permit)
            self._require_v1_confirmation_ready(
                trip_id,
                plan_id,
                current_readiness=self._readiness_binding(permit),
            )
            self._require_unexpired_permit(permit)
            plan = self.plan_service.get_plan_version(trip_id, plan_id)
            self._require_parent_trip_places_unique(trip_id, plan.days[0].tasks)

    def confirm_v1(
        self,
        trip_id: UUID,
        plan_id: UUID,
        *,
        access: PlanningAccess,
    ) -> PlanTransitionResult:
        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.PLAN_DECISION,
        ) as permit:
            self._require_unexpired_permit(permit)
            self._require_v1_confirmation_ready(
                trip_id,
                plan_id,
                current_readiness=self._readiness_binding(permit),
            )
            self._require_unexpired_permit(permit)
            plan = self.plan_service.get_plan_version(trip_id, plan_id)
            self._require_parent_trip_places_unique(trip_id, plan.days[0].tasks)
            self._require_unexpired_permit(permit)
            return self.plan_service.confirm(trip_id, plan_id)

    def _require_v1_confirmation_ready(
        self,
        trip_id: UUID,
        plan_id: UUID,
        *,
        current_readiness: ExecutionReplanReadinessBinding,
    ) -> None:
        self._require_issued(trip_id, plan_id, boundary_kind="V1")
        self._require_issued_readiness(
            trip_id,
            plan_id,
            boundary_kind="V1",
            current=current_readiness,
        )

    def require_v2_acceptance(
        self,
        trip_id: UUID,
        plan_id: UUID,
        *,
        access: PlanningAccess,
    ) -> None:
        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.PLAN_DECISION,
        ) as permit:
            self._require_unexpired_permit(permit)
            self._require_v2_acceptance_ready(
                trip_id,
                plan_id,
                current_readiness=self._readiness_binding(permit),
            )

    def _require_v2_acceptance_ready(
        self,
        trip_id: UUID,
        plan_id: UUID,
        *,
        current_readiness: ExecutionReplanReadinessBinding,
    ) -> None:
        plan = self.plan_service.get_plan_version(trip_id, plan_id)
        if plan.reason in {PlanVersionReason.DELAY, PlanVersionReason.FATIGUE}:
            raise AppError(
                code="S2_T022_DEDICATED_DECISION_REQUIRED",
                message=(
                    "LATE/FATIGUE candidates must use the adjustment decision endpoint "
                    "so collaboration readiness and T021 evidence are revalidated."
                ),
                http_status=409,
                retryable=False,
            )
        self._require_issued(trip_id, plan_id, boundary_kind="V2")
        self._require_issued_readiness(
            trip_id,
            plan_id,
            boundary_kind="V2",
            current=current_readiness,
        )

    def decide_v2(
        self,
        trip_id: UUID,
        plan_id: UUID,
        *,
        accept: bool,
        access: PlanningAccess,
    ) -> PlanV2DecisionResult:
        """Keep generic V2 validation and the state transition in one lease."""

        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.PLAN_DECISION,
        ) as permit:
            self._require_unexpired_permit(permit)
            self._require_v2_acceptance_ready(
                trip_id,
                plan_id,
                current_readiness=self._readiness_binding(permit),
            )
            self._require_unexpired_permit(permit)
            if accept:
                candidate = self.plan_service.get_plan_version(trip_id, plan_id)
                self._require_parent_trip_places_unique(
                    trip_id,
                    candidate.days[0].tasks,
                )
            self._require_unexpired_permit(permit)
            return (
                self.plan_service.accept_v2(trip_id, plan_id)
                if accept
                else self.plan_service.reject_v2(trip_id, plan_id)
            )

    def require_adjustment_v2_decision(
        self,
        trip_id: UUID,
        plan_id: UUID,
        *,
        access: PlanningAccess,
    ) -> None:
        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.PLAN_DECISION,
        ) as permit:
            self._require_unexpired_permit(permit)
            self._require_adjustment_v2_decision_ready(
                trip_id,
                plan_id,
                current_readiness=self._readiness_binding(permit),
            )

    def decide_adjustment_v2(
        self,
        trip_id: UUID,
        plan_id: UUID,
        *,
        decision: ExecutionAdjustmentDecision,
        access: PlanningAccess,
    ) -> PlanV2DecisionResult:
        """Revalidate T021 evidence and change state inside one readiness lease."""

        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.PLAN_DECISION,
        ) as permit:
            self._require_unexpired_permit(permit)
            self._require_adjustment_v2_decision_ready(
                trip_id,
                plan_id,
                current_readiness=self._readiness_binding(permit),
            )
            self._require_unexpired_permit(permit)
            if decision is ExecutionAdjustmentDecision.ACCEPT:
                candidate = self.plan_service.get_plan_version(trip_id, plan_id)
                self._require_parent_trip_places_unique(
                    trip_id,
                    candidate.days[0].tasks,
                )
                parent = self.plan_service.get_plan_version(trip_id, candidate.parent_id)
                if candidate.days[0].tasks == parent.days[0].tasks:
                    raise AppError(
                        code="REPLAN_ADJUSTMENT_NO_CHANGE",
                        message="此旧候选没有实际任务变化，不能接受；请拒绝它并继续原计划。",
                        http_status=409,
                        retryable=False,
                    )
                self._require_unexpired_permit(permit)
            return (
                self.plan_service.accept_v2(trip_id, plan_id)
                if decision is ExecutionAdjustmentDecision.ACCEPT
                else self.plan_service.reject_v2(trip_id, plan_id)
            )

    def _require_adjustment_v2_decision_ready(
        self,
        trip_id: UUID,
        plan_id: UUID,
        *,
        current_readiness: ExecutionReplanReadinessBinding,
    ) -> None:
        """Require immutable T021 evidence, not merely any issued V2."""

        plan = self.plan_service.get_plan_version(trip_id, plan_id)
        if plan.reason not in {PlanVersionReason.DELAY, PlanVersionReason.FATIGUE}:
            raise AppError(
                code="S2_T022_ADJUSTMENT_V2_REQUIRED",
                message="This decision endpoint only accepts S2-T021 adjustment V2 plans.",
                http_status=409,
            )
        try:
            validation = self.trust_repository.get_issued_validation(
                trip_id=trip_id,
                plan=plan,
                boundary_kind="V2",
            )
            constraints = EventConstraintSet.model_validate_json(
                json.dumps(
                    validation["transientEventConstraints"],
                    ensure_ascii=False,
                ),
                strict=True,
            )
            report = ReplanValidationReport.model_validate_json(
                json.dumps(validation["validationReport"], ensure_ascii=False),
                strict=True,
            )
            issued_readiness = ExecutionReplanReadinessBinding.model_validate_json(
                json.dumps(
                    validation["collaborationReadiness"],
                    ensure_ascii=False,
                ),
                strict=True,
            )
            adjustment_event_id = (
                UUID(validation["confirmedAdjustmentEventId"])
                if validation.get("confirmedAdjustmentEventId") is not None
                else None
            )
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise AppError(
                code="S2_T022_VALIDATION_EVIDENCE_INVALID",
                message="The issued V2 lacks strict S2-T021 validation evidence.",
                http_status=409,
            ) from error

        expected_event = (
            ExecutionAdjustmentType.LATE
            if plan.reason is PlanVersionReason.DELAY
            else ExecutionAdjustmentType.FATIGUE
        )
        hard_checks = tuple(
            check for check in report.checks if check.hardness == "HARD"
        )
        if issued_readiness != current_readiness:
            raise AppError(
                code="S2_T022_READINESS_CHANGED",
                message=(
                    "Collaboration requirements changed after this V2 preview; "
                    "generate a new adjustment candidate before deciding."
                ),
                http_status=409,
                retryable=False,
                errors=[
                    {
                        "issued": issued_readiness.model_dump(
                            mode="json",
                            by_alias=True,
                        ),
                        "current": current_readiness.model_dump(
                            mode="json",
                            by_alias=True,
                        ),
                    }
                ],
            )
        if adjustment_event_id is not None:
            self._restore_confirmed_adjustment(
                trip_id=trip_id,
                current_plan_id=plan.parent_id,
                event_id=adjustment_event_id,
                inline=constraints.source_event,
            )
        if (
            constraints.source_event.event_type is not expected_event
            or report.candidate_plan_id != plan.plan_id
            or not constraints.constraints
            or not hard_checks
            or any(
                check.status is not ValidationStatus.PASS for check in hard_checks
            )
        ):
            raise AppError(
                code="S2_T022_VALIDATION_EVIDENCE_INVALID",
                message="The issued V2 has inconsistent event or HARD validation evidence.",
                http_status=409,
            )

    def get_planning_facts(
        self,
        trip_id: UUID,
        *,
        access: PlanningAccess,
    ) -> CandidatePlanRequest:
        with self._planning_operation(
            trip_id=trip_id,
            access=access,
            expected=PlanningOperation.GENERATE_V1,
        ):
            return self._get_planning_facts_ready(trip_id)

    def _get_planning_facts_ready(self, trip_id: UUID) -> CandidatePlanRequest:
        """Restore facts only for the active server-issued planning lineage."""

        state = self.plan_service.get_trip_state(trip_id)
        target = state.current_plan
        if target is None:
            target = next(
                (
                    plan
                    for plan in state.proposed_plans
                    if plan.version == 1
                ),
                None,
            )
        if target is None:
            raise AppError(
                code="PLANNING_FACTS_NOT_FOUND",
                message="当前 Trip 没有可恢复的签发规划事实",
                http_status=404,
            )

        boundary_kind: Literal["V1", "V2"] = (
            "V1" if target.version == 1 else "V2"
        )
        try:
            self.trust_repository.require_issued(
                trip_id=trip_id,
                plan=target,
                boundary_kind=boundary_kind,
            )
            facts = self.trust_repository.get_candidate_request(target.plan_id)
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error
        if facts is None or facts.trip.trip_id != trip_id:
            raise AppError(
                code="PLANNING_FACTS_INVALID",
                message="签发记录缺少与当前 Trip 一致的 CandidatePlanRequest",
                http_status=409,
            )
        return facts

    def _require_issued(
        self,
        trip_id: UUID,
        plan_id: UUID,
        *,
        boundary_kind: Literal["V1", "V2"],
    ) -> None:
        plan = self.plan_service.get_plan_version(trip_id, plan_id)
        try:
            self.trust_repository.require_issued(
                trip_id=trip_id,
                plan=plan,
                boundary_kind=boundary_kind,
            )
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error

    def _require_issued_readiness(
        self,
        trip_id: UUID,
        plan_id: UUID,
        *,
        boundary_kind: Literal["V1", "V2"],
        current: ExecutionReplanReadinessBinding,
    ) -> None:
        plan = self.plan_service.get_plan_version(trip_id, plan_id)
        try:
            validation = self.trust_repository.get_issued_validation(
                trip_id=trip_id,
                plan=plan,
                boundary_kind=boundary_kind,
            )
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error

        if "collaborationReadiness" not in validation:
            if (
                current.flow_kind.value == "LEGACY_SINGLE"
                and current.readiness_digest == "legacy"
                and current.current_revision is None
            ):
                return
            raise AppError(
                code="PLAN_READINESS_BINDING_CHANGED",
                message="已签发规划缺少 readiness 绑定证据，请重新生成",
                http_status=409,
                retryable=False,
            )

        try:
            issued = ExecutionReplanReadinessBinding.model_validate_json(
                json.dumps(
                    validation["collaborationReadiness"],
                    ensure_ascii=False,
                ),
                strict=True,
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise AppError(
                code="PLAN_READINESS_BINDING_CHANGED",
                message="已签发规划的 readiness 绑定证据无效，请重新生成",
                http_status=409,
                retryable=False,
            ) from error

        if issued != current:
            issued_data = issued.model_dump(mode="json", by_alias=True)
            current_data = current.model_dump(mode="json", by_alias=True)
            raise AppError(
                code="PLAN_READINESS_BINDING_CHANGED",
                message="已签发规划的 readiness 绑定已变化，请重新生成",
                http_status=409,
                retryable=False,
                errors=[
                    {
                        "issued": {
                            "flowKind": issued_data["flowKind"],
                            "currentRevision": issued_data["currentRevision"],
                            "readinessDigest": issued_data["readinessDigest"][:12],
                        },
                        "current": {
                            "flowKind": current_data["flowKind"],
                            "currentRevision": current_data["currentRevision"],
                            "readinessDigest": current_data["readinessDigest"][:12],
                        },
                    }
                ],
            )


__all__ = ["ParentTripPlaceMemoryGuard", "PlanningBoundaryService"]
