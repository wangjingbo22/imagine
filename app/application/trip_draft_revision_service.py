from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, ValidationError

from app.application.llm_gateway import (
    TripUnderstandingGateway,
    UnavailableTripUnderstandingGateway,
)
from app.application.collaboration_ports import (
    CanonicalRevisionPatch,
    TripDraftRevisionPort,
    TripDraftRevisionUnavailable,
    TripDraftRevisionView,
)
from app.core.errors import AppError
from app.domain.collaboration import (
    CollaborationModel,
    ConversationAnswer,
    ConversationSubmission,
    FixedQuestionFallback,
    OrganizerConversationRequest,
    RelaxationAction,
    fixed_question_fallback,
)
from app.domain.collaboration_digest import canonical_sha256
from app.domain.trip_draft import (
    TripDraftRevision,
    TripUnderstandingExplicitFields,
    TripUnderstandingExtraction,
    TripUnderstandingFailureCode,
    TripUnderstandingGatewayResult,
    TripUnderstandingProposal,
    TripUnderstandingRequest,
    validate_trip_understanding,
)
from app.infrastructure.trip_draft_revision_store import (
    AnswerCommand,
    ClaimedCommand,
    CommandInProgress,
    CompletedCommand,
    FailedCommand,
    SqliteTripDraftRevisionRepository,
    TripDraftRevisionStoreError,
)
from app.schemas.validation_error import TripSchemaError


class TripUnderstandingRecognition(CollaborationModel):
    source: Literal["FIXED_QUESTIONS"] = "FIXED_QUESTIONS"
    model: str | None
    failure_code: TripUnderstandingFailureCode
    call_count: int = Field(ge=0, le=2)


class TripUnderstandingFallbackResponse(CollaborationModel):
    answer_revision: int = Field(ge=1)
    natural_language_request: str = Field(min_length=1, max_length=1000)
    answers: list[ConversationAnswer] = Field(min_length=6, max_length=6)
    recognition: TripUnderstandingRecognition
    understanding: None = None
    fallback: FixedQuestionFallback
    can_plan: Literal[False] = False


TripUnderstandingOutcome = TripDraftRevision | TripUnderstandingFallbackResponse


class TripDraftRevisionService(TripDraftRevisionPort):
    _INITIAL_OPERATION = "INITIAL_ANSWER"
    _MEMBER_OPERATION = "MEMBER_ANSWER"
    _RELAXATION_OPERATION = "RELAXATION"

    def __init__(
        self,
        *,
        repository: SqliteTripDraftRevisionRepository,
        gateway: TripUnderstandingGateway,
        clock: object | None = None,
    ) -> None:
        self.repository = repository
        self.gateway = gateway
        self._clock = clock if callable(clock) else (lambda: datetime.now().astimezone())

    @staticmethod
    def _app_error(code: str) -> AppError:
        details = {
            "IDEMPOTENCY_KEY_REUSED": ("相同幂等键对应不同请求", 409, False),
            "ANSWER_REVISION_STALE": ("答案版本已经变化", 409, False),
            "DRAFT_REVISION_STALE": ("草稿版本已经变化", 409, False),
            "DRAFT_BINDINGS_IMMUTABLE": ("草稿成员绑定不可变更", 409, False),
            "PARTICIPANT_SCOPE_VIOLATION": ("成员只能修改自己的草稿字段", 403, False),
            "COLLABORATION_OPERATION_IN_PROGRESS": ("协作操作正在进行", 409, True),
            "TRIP_DRAFT_REVISION_UNAVAILABLE": ("行程草稿版本服务不可用", 503, True),
            "DRAFT_PARSE_IN_PROGRESS": ("草稿解析正在进行", 409, True),
            "TRIP_UNDERSTANDING_INVALID": ("行程理解结果无效", 502, False),
            "TRIP_UNDERSTANDING_UNAVAILABLE": ("行程理解服务不可用", 503, True),
        }
        message, status, retryable = details.get(
            code,
            ("行程草稿版本服务不可用", 503, True),
        )
        return AppError(code, message, status, retryable)

    @classmethod
    def _store_error(cls, error: TripDraftRevisionStoreError) -> AppError:
        if error.code == "IDEMPOTENCY_KEY_REUSED":
            return cls._app_error("ANSWER_REVISION_STALE")
        return cls._app_error(error.code)

    @classmethod
    def _saved_failure_to_app_error(cls, code: str) -> AppError:
        return cls._app_error(code)

    @classmethod
    def _map_revision_failure(cls, error: Exception) -> AppError:
        if isinstance(error, AppError):
            return error
        if isinstance(error, (ValidationError, TripSchemaError)):
            return cls._app_error("TRIP_UNDERSTANDING_INVALID")
        return cls._app_error("TRIP_UNDERSTANDING_UNAVAILABLE")

    @staticmethod
    def _claim_result(
        claim: object,
    ) -> TripUnderstandingOutcome | None:
        if isinstance(claim, CompletedCommand):
            return claim.revision
        if isinstance(claim, CommandInProgress):
            raise TripDraftRevisionService._app_error("DRAFT_PARSE_IN_PROGRESS")
        if isinstance(claim, FailedCommand):
            if claim.outcome_json:
                try:
                    return TripUnderstandingFallbackResponse.model_validate_json(
                        claim.outcome_json,
                        strict=True,
                    )
                except ValidationError:
                    pass
            raise TripDraftRevisionService._saved_failure_to_app_error(claim.code)
        if isinstance(claim, ClaimedCommand):
            return None
        raise TripDraftRevisionService._app_error("TRIP_DRAFT_REVISION_UNAVAILABLE")

    @staticmethod
    def _request_digest(value: object) -> str:
        return canonical_sha256(value)

    @staticmethod
    def _empty_explicit_fields() -> TripUnderstandingExplicitFields:
        return TripUnderstandingExplicitFields(
            cityName=None,
            travelDate=None,
            startTime=None,
            endTime=None,
            startLocationText=None,
            endLocationText=None,
            budgetCents=None,
            participants=[],
        )

    @classmethod
    def _understanding_request(
        cls,
        submission: ConversationSubmission,
        reference_date: date,
    ) -> TripUnderstandingRequest:
        return TripUnderstandingRequest(
            schemaVersion="1.0",
            referenceDate=reference_date,
            rawConversation=submission.transcript,
            explicitFields=cls._empty_explicit_fields(),
        )

    async def _understand(
        self,
        request: TripUnderstandingRequest,
    ) -> TripUnderstandingGatewayResult:
        result = await self.gateway.understand(request)
        if result.decision == "FIXED_QUESTIONS":
            if result.failure_code is None or result.proposal is not None:
                raise self._app_error("TRIP_UNDERSTANDING_INVALID")
            return result
        if result.decision != "MODEL_PROPOSAL" or result.proposal is None:
            raise self._app_error("TRIP_UNDERSTANDING_INVALID")
        return result

    @staticmethod
    def _fallback_response(
        *,
        submission: ConversationSubmission,
        answer_revision: int,
        result: TripUnderstandingGatewayResult,
    ) -> TripUnderstandingFallbackResponse:
        if result.failure_code is None:
            raise TripDraftRevisionService._app_error("TRIP_UNDERSTANDING_INVALID")
        return TripUnderstandingFallbackResponse(
            answerRevision=answer_revision,
            naturalLanguageRequest=submission.natural_language_request,
            answers=submission.answers,
            recognition=TripUnderstandingRecognition(
                source="FIXED_QUESTIONS",
                model=result.model,
                failureCode=result.failure_code,
                callCount=result.call_count,
            ),
            understanding=None,
            fallback=fixed_question_fallback(submission),
            canPlan=False,
        )

    @staticmethod
    def _build_revision(
        *,
        claim: ClaimedCommand,
        proposal: TripUnderstandingProposal,
        member_bindings: dict[str, UUID],
        created_at: datetime,
    ) -> TripDraftRevision:
        source_digest = canonical_sha256(
            {
                "draftId": str(claim.draft_id),
                "revision": claim.target_revision,
                "tripId": str(claim.trip_id),
                "understanding": proposal,
                "memberBindings": {
                    key: str(member_bindings[key])
                    for key in sorted(member_bindings)
                },
                "sourceRequestDigest": claim.command.request_digest,
            }
        )
        return TripDraftRevision(
            schemaVersion="1.0",
            draftId=claim.draft_id,
            revision=claim.target_revision,
            tripId=claim.trip_id,
            understanding=proposal,
            memberBindings=member_bindings,
            sourceDigest=source_digest,
            createdAt=created_at,
        )

    async def create_initial(
        self,
        payload: OrganizerConversationRequest,
        *,
        idempotency_key: str,
    ) -> TripUnderstandingOutcome:
        request_digest = self._request_digest(
            payload.model_dump(mode="json", by_alias=True)
        )
        command = AnswerCommand(
            actor_scope="SYSTEM",
            actor_id="INITIAL_CONVERSATION",
            operation=self._INITIAL_OPERATION,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        draft_id, trip_id = uuid4(), uuid4()
        try:
            claim = self.repository.claim_initial(
                command,
                draft_id=draft_id,
                trip_id=trip_id,
            )
        except TripDraftRevisionStoreError as error:
            raise self._store_error(error) from error
        replay = self._claim_result(claim)
        if replay is not None:
            return replay
        assert isinstance(claim, ClaimedCommand)
        request = self._understanding_request(payload, payload.reference_date)
        try:
            extraction = await self._understand(request)
            if extraction.decision == "FIXED_QUESTIONS":
                outcome = self._fallback_response(
                    submission=payload,
                    answer_revision=claim.target_revision,
                    result=extraction,
                )
                self.repository.fail(
                    claim,
                    code=extraction.failure_code or "TRIP_UNDERSTANDING_INVALID",
                    outcome_json=outcome.model_dump_json(by_alias=True),
                )
                return outcome
            assert extraction.proposal is not None
            proposal = validate_trip_understanding(request, extraction.proposal)
            bindings = {
                participant.member_key: uuid4()
                for participant in proposal.participants
            }
            revision = self._build_revision(
                claim=claim,
                proposal=proposal,
                member_bindings=bindings,
                created_at=self._clock(),
            )
        except Exception as error:
            failure = self._map_revision_failure(error)
            try:
                self.repository.fail(claim, code=failure.code)
            except TripDraftRevisionStoreError as store_error:
                raise self._store_error(store_error) from store_error
            raise failure from error
        self.repository.complete(claim, revision, extraction)
        return revision

    def get_current(self, trip_id: UUID) -> TripDraftRevisionView:
        try:
            return self.repository.get_current(trip_id)
        except TripDraftRevisionStoreError as error:
            raise TripDraftRevisionUnavailable(error.code) from error

    @staticmethod
    def _member_key(
        revision: TripDraftRevisionView,
        participant_id: UUID,
    ) -> str:
        for member_key, binding in revision.member_bindings.items():
            if binding == participant_id:
                return member_key
        raise AppError("PARTICIPANT_NOT_BOUND", "成员绑定不存在", 404, False)

    @classmethod
    def _merge_member_scope(
        cls,
        *,
        current: TripDraftRevisionView,
        candidate: TripUnderstandingProposal,
        participant_id: UUID,
    ) -> TripUnderstandingProposal:
        if len(candidate.participants) != len(current.understanding.participants):
            raise cls._app_error("DRAFT_BINDINGS_IMMUTABLE")
        current_keys = [item.member_key for item in current.understanding.participants]
        candidate_keys = [item.member_key for item in candidate.participants]
        if candidate_keys != current_keys:
            raise cls._app_error("DRAFT_BINDINGS_IMMUTABLE")
        own_key = cls._member_key(current, participant_id)
        if candidate.trip != current.understanding.trip:
            raise cls._app_error("PARTICIPANT_SCOPE_VIOLATION")
        for before, after in zip(
            current.understanding.participants,
            candidate.participants,
            strict=True,
        ):
            if before.member_key != own_key and before != after:
                raise cls._app_error("PARTICIPANT_SCOPE_VIOLATION")
        return candidate

    async def submit_participant_conversation(
        self,
        *,
        trip_id: UUID,
        participant_id: UUID,
        base_revision: int,
        submission: ConversationSubmission,
        idempotency_key: str,
    ) -> TripDraftRevisionView | TripUnderstandingFallbackResponse:
        current = self.get_current(trip_id)
        request_digest = self._request_digest(
            {
                "tripId": str(trip_id),
                "participantId": str(participant_id),
                "baseRevision": base_revision,
                "submission": submission.model_dump(mode="json", by_alias=True),
            }
        )
        command = AnswerCommand(
            actor_scope="PARTICIPANT",
            actor_id=str(participant_id),
            operation=self._MEMBER_OPERATION,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        try:
            claim = self.repository.claim_next(
                command,
                draft_id=current.draft_id,
                trip_id=trip_id,
                base_revision=base_revision,
            )
        except TripDraftRevisionStoreError as error:
            raise self._store_error(error) from error
        replay = self._claim_result(claim)
        if replay is not None:
            return replay
        assert isinstance(claim, ClaimedCommand)
        reference_date = current.understanding.trip.travel_date or date.today()
        request = self._understanding_request(submission, reference_date)
        try:
            extraction = await self._understand(request)
            if extraction.decision == "FIXED_QUESTIONS":
                outcome = self._fallback_response(
                    submission=submission,
                    answer_revision=claim.target_revision,
                    result=extraction,
                )
                self.repository.fail(
                    claim,
                    code=extraction.failure_code or "TRIP_UNDERSTANDING_INVALID",
                    outcome_json=outcome.model_dump_json(by_alias=True),
                )
                return outcome
            assert extraction.proposal is not None
            proposal = validate_trip_understanding(request, extraction.proposal)
            candidate = self._merge_member_scope(
                current=current,
                candidate=proposal,
                participant_id=participant_id,
            )
            revision = self._build_revision(
                claim=claim,
                proposal=candidate,
                member_bindings=dict(current.member_bindings),
                created_at=self._clock(),
            )
        except Exception as error:
            failure = self._map_revision_failure(error)
            try:
                self.repository.fail(claim, code=failure.code)
            except TripDraftRevisionStoreError as store_error:
                raise self._store_error(store_error) from store_error
            raise failure from error
        self.repository.complete(claim, revision, extraction)
        return revision

    @classmethod
    def _participant_index(
        cls,
        revision: TripDraftRevisionView,
        participant_id: UUID,
        field_path: str,
    ) -> int:
        own_key = cls._member_key(revision, participant_id)
        match = re.fullmatch(r"participants\[(\d+)\]\..+", field_path)
        if match is None:
            raise cls._app_error("TRIP_UNDERSTANDING_INVALID")
        index = int(match.group(1))
        participants = revision.understanding.participants
        if index >= len(participants) or participants[index].member_key != own_key:
            raise cls._app_error("PARTICIPANT_SCOPE_VIOLATION")
        return index

    @staticmethod
    def _set_path(payload: dict[str, object], field_path: str, value: object) -> None:
        if field_path.startswith("trip."):
            payload["trip"][field_path.removeprefix("trip.")] = value  # type: ignore[index]
            return
        match = re.fullmatch(r"participants\[(\d+)\]\.(.+)", field_path)
        if match is None:
            raise TripDraftRevisionService._app_error("TRIP_UNDERSTANDING_INVALID")
        participant = payload["participants"][int(match.group(1))]  # type: ignore[index]
        tail = match.group(2)
        list_match = re.fullmatch(r"(interests|mustVisit|avoidPlaces)\[(\d+)\]", tail)
        if list_match is not None:
            values = participant[list_match.group(1)]  # type: ignore[index]
            values[int(list_match.group(2))] = value  # type: ignore[index]
            return
        parts = tail.split(".")
        target = participant  # type: ignore[assignment]
        for part in parts[:-1]:
            target = target[part]  # type: ignore[index]
        target[parts[-1]] = value  # type: ignore[index]

    @staticmethod
    def _remove_path(payload: dict[str, object], field_path: str) -> None:
        match = re.fullmatch(
            r"participants\[(\d+)\]\.(interests|mustVisit|avoidPlaces)\[(\d+)\]",
            field_path,
        )
        if match is None:
            raise TripDraftRevisionService._app_error("TRIP_UNDERSTANDING_INVALID")
        values = payload["participants"][int(match.group(1))][match.group(2)]  # type: ignore[index]
        index = int(match.group(3))
        if index >= len(values):
            raise TripDraftRevisionService._app_error("TRIP_UNDERSTANDING_INVALID")
        values.pop(index)

    @classmethod
    def _apply_patch(
        cls,
        current: TripDraftRevisionView,
        patch: CanonicalRevisionPatch,
    ) -> TripUnderstandingProposal:
        payload = current.understanding.model_dump(mode="json", by_alias=True)
        action = patch.action
        member_actions = {
            RelaxationAction.SET_MEMBER_FIELD,
            RelaxationAction.RAISE_MEMBER_BUDGET_CAP,
            RelaxationAction.CHANGE_NAP_WINDOW,
            RelaxationAction.REMOVE_MUST_VISIT,
            RelaxationAction.REMOVE_AVOID_PLACE,
        }
        shared_actions = {
            RelaxationAction.SET_SHARED_FIELD,
            RelaxationAction.LOWER_SHARED_BUDGET,
            RelaxationAction.EXTEND_SHARED_TIME,
        }
        if action in member_actions:
            if patch.participant_id is None:
                raise cls._app_error("PARTICIPANT_SCOPE_VIOLATION")
            cls._participant_index(current, patch.participant_id, patch.field_path)
        elif action in shared_actions:
            if not patch.field_path.startswith("trip."):
                raise cls._app_error("TRIP_UNDERSTANDING_INVALID")
        elif action is RelaxationAction.SELECT_CANDIDATE:
            if patch.participant_id is not None:
                cls._participant_index(current, patch.participant_id, patch.field_path)
        else:
            raise cls._app_error("TRIP_UNDERSTANDING_INVALID")

        if action in {
            RelaxationAction.REMOVE_MUST_VISIT,
            RelaxationAction.REMOVE_AVOID_PLACE,
        }:
            cls._remove_path(payload, patch.field_path)
        else:
            cls._set_path(payload, patch.field_path, patch.value)
        if action is RelaxationAction.SELECT_CANDIDATE:
            ambiguities = payload["ambiguities"]  # type: ignore[index]
            questions = payload["confirmationQuestions"]  # type: ignore[index]
            ambiguities[:] = [
                item
                for item in ambiguities
                if not (
                    item["fieldPath"] == patch.field_path
                    and item["memberKey"] == cls._member_key(current, patch.participant_id)
                    if patch.participant_id is not None
                    else item["fieldPath"] == patch.field_path and item["memberKey"] is None
                )
            ]
            questions[:] = [
                item
                for item in questions
                if not (
                    item["fieldPath"] == patch.field_path
                    and item["memberKey"] == cls._member_key(current, patch.participant_id)
                    if patch.participant_id is not None
                    else item["fieldPath"] == patch.field_path and item["memberKey"] is None
                )
            ]
        try:
            return TripUnderstandingProposal.model_validate_json(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                strict=True,
            )
        except (ValidationError, TypeError, ValueError) as error:
            raise cls._app_error("TRIP_UNDERSTANDING_INVALID") from error

    def apply_relaxation(
        self,
        *,
        trip_id: UUID,
        base_revision: int,
        patch: CanonicalRevisionPatch,
        idempotency_key: str,
    ) -> TripDraftRevisionView:
        current = self.get_current(trip_id)
        request_digest = self._request_digest(
            {
                "tripId": str(trip_id),
                "baseRevision": base_revision,
                "patch": {
                    "action": patch.action.value,
                    "participantId": str(patch.participant_id) if patch.participant_id else None,
                    "fieldPath": patch.field_path,
                    "value": patch.value,
                },
            }
        )
        command = AnswerCommand(
            actor_scope="SYSTEM",
            actor_id=str(trip_id),
            operation=self._RELAXATION_OPERATION,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        try:
            claim = self.repository.claim_next(
                command,
                draft_id=current.draft_id,
                trip_id=trip_id,
                base_revision=base_revision,
            )
        except TripDraftRevisionStoreError as error:
            raise self._store_error(error) from error
        replay = self._claim_result(claim)
        if replay is not None:
            return replay
        assert isinstance(claim, ClaimedCommand)
        try:
            candidate = self._apply_patch(current, patch)
            extraction = TripUnderstandingExtraction(
                proposal=candidate,
                recognitionSource="RELAXATION",
                recognitionModel=None,
                degradedReason=None,
                llmCallCount=0,
            )
            revision = self._build_revision(
                claim=claim,
                proposal=candidate,
                member_bindings=dict(current.member_bindings),
                created_at=self._clock(),
            )
        except Exception as error:
            failure = self._map_revision_failure(error)
            try:
                self.repository.fail(claim, code=failure.code)
            except TripDraftRevisionStoreError as store_error:
                raise self._store_error(store_error) from store_error
            raise failure from error
        self.repository.complete(claim, revision, extraction)
        return revision


__all__ = [
    "TripDraftRevisionService",
    "TripUnderstandingFallbackResponse",
    "TripUnderstandingGateway",
    "TripUnderstandingOutcome",
    "TripUnderstandingRecognition",
    "TripUnderstandingGatewayResult",
    "UnavailableTripUnderstandingGateway",
]
