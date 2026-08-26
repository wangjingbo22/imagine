from __future__ import annotations

from uuid import UUID, uuid4

from app.application.trip_draft_service import TripDraftParserService
from app.application.workflow_service import WorkflowService
from app.core.errors import AppError
from app.domain.collaboration import CollaborationState, ConversationSubmission, InvitationConversation, InvitationCreated, MemberConversationResult, OrganizerConversationResult
from app.domain.trip_draft import TripDraftParseRequest
from app.infrastructure.collaboration_store import CollaborationStoreError, SqliteCollaborationRepository


class CollaborationService:
    def __init__(
        self,
        repository: SqliteCollaborationRepository,
        parser: TripDraftParserService,
        workflow_service: WorkflowService | None = None,
    ) -> None:
        self._repository = repository
        self._parser = parser
        self._workflow_service = workflow_service

    @staticmethod
    def _error(error: CollaborationStoreError) -> AppError:
        return AppError(error.args[0], "协作会话不可用或邀请已失效", 404, False)

    async def create_organizer(self, submission: ConversationSubmission) -> OrganizerConversationResult:
        trip_id, organizer_id = uuid4(), uuid4()
        parsed = await self._parser.parse(TripDraftParseRequest(trip_id=trip_id, natural_language_request=submission.transcript))
        if not parsed.can_plan:
            return OrganizerConversationResult(state=None, parse=parsed)
        # The six-question confirmation is the S2 equivalent of the legacy
        # trip-confirmation step.  Persist it before saving/confirming the
        # AssistanceProfile, otherwise the planning boundary correctly blocks.
        if self._workflow_service is not None and parsed.trip is None:
            raise AppError("COLLABORATION_TRIP_MISSING", "对话已完成但未生成可确认行程", 422, False)
        if self._workflow_service is not None and parsed.trip is not None:
            self._workflow_service.confirm_trip(parsed.trip)
        state, organizer_access_token = self._repository.create_session(
            trip_id, organizer_id, parsed.parsed, submission.participant_count
        )
        return OrganizerConversationResult(
            state=state,
            parse=parsed,
            organizer_access_token=organizer_access_token,
        )

    def invite(self, trip_id: UUID, organizer_access_token: str | None) -> InvitationCreated:
        try: return self._repository.create_invitation(trip_id, organizer_access_token)
        except CollaborationStoreError as error: raise self._error(error) from error

    def invitation(self, token: str) -> InvitationConversation:
        try: return self._repository.invitation(token)
        except CollaborationStoreError as error: raise self._error(error) from error

    async def submit_member(self, token: str, submission: ConversationSubmission) -> MemberConversationResult:
        parsed = await self._parser.parse(TripDraftParseRequest(natural_language_request=submission.transcript))
        if not parsed.can_plan: raise AppError("PARTICIPANT_CONFIRMATION_REQUIRED", "成员资料仍有待确认字段", 422, False, errors=[item.model_dump(by_alias=True) for item in parsed.confirmation_items])
        try:
            return MemberConversationResult(
                state=self._repository.submit_invitation(token, parsed.parsed),
                parse=parsed,
            )
        except CollaborationStoreError as error: raise self._error(error) from error

    def confirm_member(self, token: str) -> CollaborationState:
        try: return self._repository.confirm_invitation(token)
        except CollaborationStoreError as error: raise self._error(error) from error

    def state(self, trip_id: UUID) -> CollaborationState:
        try: return self._repository.get_state(trip_id)
        except CollaborationStoreError as error: raise self._error(error) from error

    def revoke_invitation(self, trip_id: UUID, participant_id: UUID, organizer_access_token: str | None) -> CollaborationState:
        try: return self._repository.revoke_invitation(trip_id, participant_id, organizer_access_token)
        except CollaborationStoreError as error: raise self._error(error) from error

    def resolve_conflict(self, trip_id: UUID, conflict_id: str, relaxation: str, organizer_access_token: str | None) -> CollaborationState:
        try: return self._repository.resolve_conflict(trip_id, conflict_id, relaxation, organizer_access_token)
        except CollaborationStoreError as error: raise self._error(error) from error

    def assert_planning_ready(self, trip_id: UUID, organizer_access_token: str | None) -> None:
        try:
            self._repository.assert_planning_ready(trip_id, organizer_access_token)
        except CollaborationStoreError as error:
            raise AppError(error.args[0], "请等待全部成员确认、解决硬冲突，并由组织者继续", 409, False) from error
