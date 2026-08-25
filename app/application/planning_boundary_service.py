from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from app.application.plan_service import PlanVersionService
from app.application.workflow_service import WorkflowService
from app.core.errors import AppError
from app.infrastructure.trusted_planning_store import (
    SqliteTrustedPlanningRepository,
    TrustedPlanningStoreError,
    proposal_digest,
)
from app.schemas.plan import PlanVersion, ProposedPlanVersion
from app.schemas.planning import RegisteredReplan, ReplanGenerationRequest
from app.services.planning.models import CandidatePlanRequest
from app.services.planning.planner import (
    CandidatePlanInputError,
    CandidatePlanRejected,
    candidate_to_proposed_plan_version_v2,
    generate_candidate_plan,
    generate_proposed_plan_version,
)
from app.services.planning.replanning_adapter import T011ReplanCandidateValidator
from app.services.replanning.models import NoFeasibleReplan, ReplanCandidate
from app.services.replanning.selector import (
    MinimumDisruptionSelector,
    ReplanningContractError,
)


class PlanningBoundaryService:
    """Trusted HTTP boundary joining T011, T018 and PlanVersion storage."""

    def __init__(
        self,
        *,
        plan_service: PlanVersionService,
        workflow_service: WorkflowService,
        trust_repository: SqliteTrustedPlanningRepository,
    ) -> None:
        self.plan_service = plan_service
        self.workflow_service = workflow_service
        self.trust_repository = trust_repository

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
    def _proposal_validation(plan: Any) -> dict[str, Any]:
        return {
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

    def _register_generated(self, proposal: ProposedPlanVersion) -> PlanVersion:
        """Register once, or recover an identical prior partial attempt.

        Staging and PlanVersion storage use separate fail-closed transactions. If
        registration committed but mark_issued did not, a retry must be able to
        load the exact immutable proposal and finish issuing it.
        """

        try:
            return self.plan_service.register_proposed(proposal)
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
            return stored

    def generate_v1(
        self,
        trip_id: UUID,
        request: CandidatePlanRequest,
    ) -> PlanVersion:
        self._require_trip_id(trip_id, request)
        self.workflow_service.require_constraint_confirmed(
            trip_id,
            request.trip.participants[0].assistance_profile,
        )
        self.workflow_service.require_confirmed_trip(trip_id, request.trip)
        try:
            proposal = generate_proposed_plan_version(request)
        except CandidatePlanInputError as error:
            raise self._planner_error(error) from error
        except CandidatePlanRejected as error:
            raise self._rejected_error(error) from error

        try:
            self.trust_repository.stage_candidate(
                plan=proposal,
                request=request,
                boundary_kind="V1",
                validation=self._proposal_validation(proposal),
            )
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error

        stored = self._register_generated(proposal)
        try:
            self.trust_repository.mark_issued(stored)
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error
        return stored

    def generate_v2(
        self,
        trip_id: UUID,
        request: ReplanGenerationRequest,
    ) -> RegisteredReplan:
        state = self.plan_service.get_trip_state(trip_id)
        current = state.current_plan
        if current is None:
            raise AppError(
                code="REPLAN_CURRENT_PLAN_REQUIRED",
                message="生成 Plan V2 前必须存在 CURRENT PlanVersion",
                http_status=409,
            )
        if current.version != 1:
            raise AppError(
                code="REPLAN_S1_VERSION_LIMIT",
                message="Sprint 1 仅支持从服务端签发的 CURRENT Plan V1 生成一次 V2",
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

        events = tuple(self.workflow_service.list_events(trip_id))
        candidates: list[ReplanCandidate] = []
        generation_failures: list[dict[str, Any]] = []
        for index, candidate_input in enumerate(request.candidates):
            self._require_trip_id(trip_id, candidate_input.request)
            try:
                generated = generate_candidate_plan(candidate_input.request)
                proposal = candidate_to_proposed_plan_version_v2(
                    generated,
                    candidate_input.request,
                    current,
                    reason=request.reason,
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

            try:
                self.trust_repository.stage_candidate(
                    plan=proposal,
                    request=candidate_input.request,
                    boundary_kind="V2",
                    validation=self._proposal_validation(proposal),
                )
            except TrustedPlanningStoreError as error:
                raise self._trust_error(error) from error
            candidates.append(
                ReplanCandidate(
                    plan=proposal,
                    satisfaction_loss=candidate_input.satisfaction_loss,
                )
            )

        if not candidates:
            raise AppError(
                code="REPLAN_NO_FEASIBLE_CANDIDATE",
                message="所有候选均未通过服务端 T011 校验",
                http_status=422,
                errors=generation_failures,
            )

        selector = MinimumDisruptionSelector(
            T011ReplanCandidateValidator(self.trust_repository)
        )
        try:
            outcome = selector.select(
                current_plan=current,
                candidates=tuple(candidates),
                events=events,
                locked_task_ids=request.locked_task_ids,
            )
        except ReplanningContractError as error:
            raise self._contract_error(error) from error

        if isinstance(outcome, NoFeasibleReplan):
            raise AppError(
                code="REPLAN_NO_FEASIBLE_CANDIDATE",
                message="T018 未找到满足执行冻结前缀和 HARD 约束的候选",
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
        selected_input = next(
            item for item in candidates if item.plan.plan_id == selected_plan_id
        )

        stored = self._register_generated(outcome.selected_plan)
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
        try:
            self.trust_repository.mark_issued(
                stored,
                validation=selection_validation,
            )
        except TrustedPlanningStoreError as error:
            raise self._trust_error(error) from error

        return RegisteredReplan(
            plan=stored,
            disruption_score=assessment.modified_task_count,
            satisfaction_loss=selected_input.satisfaction_loss,
            frozen_task_ids=outcome.frozen_task_ids,
            assessments=outcome.assessments,
            validation_report=outcome.validation_report,
        )

    def require_v1_confirmation(self, trip_id: UUID, plan_id: UUID) -> None:
        self._require_issued(trip_id, plan_id, boundary_kind="V1")

    def require_v2_acceptance(self, trip_id: UUID, plan_id: UUID) -> None:
        self._require_issued(trip_id, plan_id, boundary_kind="V2")

    def get_planning_facts(self, trip_id: UUID) -> CandidatePlanRequest:
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


__all__ = ["PlanningBoundaryService"]
