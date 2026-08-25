from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

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
from app.services.planning.models import (
    CandidatePlan,
    CandidatePlanRequest,
    CandidatePlanReview,
    CandidateReviewConfirmationRequest,
    CandidateReviewItem,
)
from app.services.planning.planner import (
    CandidatePlanInputError,
    CandidatePlanRejected,
    candidate_to_proposed_plan_version_v2,
    candidate_to_proposed_plan_version,
    generate_candidate_plan,
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
            candidate = generate_candidate_plan(request)
        except CandidatePlanInputError as error:
            raise self._planner_error(error) from error
        except CandidatePlanRejected as error:
            raise self._rejected_error(error) from error

        if candidate.warnings:
            review = self._stage_review(candidate, request)
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

    def get_review(self, trip_id: UUID, review_id: str) -> CandidatePlanReview:
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

        candidate = self._review_candidate(row)
        request = self._review_request(row)
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

        try:
            self.trust_repository.stage_candidate(
                plan=proposal,
                request=confirmed_request,
                boundary_kind="V1",
                validation=self._proposal_validation(proposal),
            )
            stored = self._register_generated(proposal)
            self.trust_repository.mark_issued(stored)
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
    ) -> CandidatePlanReview:
        review_id = str(
            uuid5(
                NAMESPACE_URL,
                f"xingzhi:candidate-review:{request.trip.trip_id}:{candidate.candidate_id}",
            )
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
