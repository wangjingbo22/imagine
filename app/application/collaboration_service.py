from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from app.application.collaboration_ports import (
    CanonicalRevisionPatch,
    TripDraftRevisionPort,
    TripDraftRevisionUnavailable,
    TripDraftRevisionView,
)
from app.core.errors import AppError
from app.domain.collaboration import (
    ActorScope,
    CollaborationAggregate,
    CollaborationIssue,
    CollaborationProgress,
    CollaborationStatus,
    ConversationSubmission,
    InvitationCreated,
    InvitationRedeemed,
    IssueCode,
    MemberSessionView,
    OrganizerBootstrapResult,
    ParticipantAccessStatus,
    ParticipantConfirmationStatus,
    ParticipantConversationRequest,
    ParticipantMutationRequest,
    ParticipantProgress,
    ResolveConfirmationItemRequest,
)
from app.domain.collaboration_digest import (
    canonical_sha256,
    member_digest,
    readiness_digest,
    shared_digest,
)
from app.domain.hard_conflicts import DeterministicHardConflictEvaluator
from app.infrastructure.collaboration_store import (
    CollaborationActor,
    CollaborationStoreError,
    SqliteCollaborationRepository,
    StoredCollaboration,
)


class CollaborationService:
    def __init__(
        self,
        *,
        repository: SqliteCollaborationRepository,
        revisions: TripDraftRevisionPort,
        evaluator: DeterministicHardConflictEvaluator,
    ) -> None:
        self.repository = repository
        self.revisions = revisions
        self.evaluator = evaluator

    @staticmethod
    def _revision_error(error: TripDraftRevisionUnavailable) -> AppError:
        return AppError(
            code="TRIP_DRAFT_REVISION_UNAVAILABLE",
            message="行程草稿版本服务尚未就绪",
            http_status=503,
            retryable=True,
        )

    @staticmethod
    def _store_error(error: CollaborationStoreError) -> AppError:
        code = str(error)
        if code in {"ORGANIZER_PERMISSION_REQUIRED", "ORGANIZER_SELF_INVITE_FORBIDDEN"}:
            status = 403
        elif code in {
            "PARTICIPANT_SESSION_REQUIRED",
            "PARTICIPANT_SESSION_INVALID",
            "PARTICIPANT_SESSION_REVOKED",
            "PARTICIPANT_SESSION_EXPIRED",
        }:
            status = 401
        elif code in {"INVITATION_UNAVAILABLE", "INVITATION_ALREADY_REDEEMED", "INVITATION_EXPIRED"}:
            status = 410
        elif code in {"PARTICIPANT_CONFIRMATION_REQUIRED", "PARTICIPANT_DRAFT_MISSING"}:
            status = 422
        elif code in {"COLLABORATION_NOT_FOUND", "PARTICIPANT_NOT_BOUND", "CONFLICT_NOT_FOUND"}:
            status = 404
        else:
            status = 409
        return AppError(code, "协作操作无法完成", status, status == 503)

    def _current(self, trip_id: UUID) -> TripDraftRevisionView:
        try:
            revision = self.revisions.get_current(trip_id)
        except TripDraftRevisionUnavailable as error:
            raise self._revision_error(error) from error
        if revision.trip_id != trip_id:
            raise AppError("DRAFT_REVISION_STALE", "T002 返回了不匹配的行程草稿", 409, False)
        return revision

    def bootstrap(
        self,
        revision: TripDraftRevisionView,
        idempotency_key: str,
    ) -> OrganizerBootstrapResult:
        try:
            return self.repository.bootstrap_collaboration(revision, idempotency_key)
        except CollaborationStoreError as error:
            raise self._store_error(error) from error

    def assert_planning_ready(
        self,
        trip_id: UUID,
        organizer_token: str | None,
    ) -> None:
        """Keep the pre-guard route shim fail-closed for S2 rows.

        Planning routes are migrated to the operation guard in Task 15.  Until
        then, preserve the explicit legacy behavior of the existing routes,
        while making every collaboration-backed trip use the same authoritative
        readiness calculation as the new guard.
        """
        try:
            self.repository.get_stored(trip_id)
        except CollaborationStoreError as error:
            if str(error) == "COLLABORATION_NOT_FOUND":
                return
            raise self._store_error(error) from error
        self.require_ready(trip_id, organizer_token)

    def create_invitation(
        self,
        *,
        trip_id: UUID,
        participant_id: UUID,
        organizer_token: str | None,
        expected_version: int,
        idempotency_key: str,
        expires_in_hours: int = 72,
    ) -> InvitationCreated:
        self._current(trip_id)
        try:
            return self.repository.create_invitation(
                trip_id=trip_id,
                participant_id=participant_id,
                organizer_token=organizer_token,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                expires_in_hours=expires_in_hours,
            )
        except CollaborationStoreError as error:
            raise self._store_error(error) from error

    def redeem_invitation(
        self,
        *,
        token: str,
        idempotency_key: str,
    ) -> InvitationRedeemed:
        try:
            trip_id, _ = self.repository.inspect_invitation(token, idempotency_key)
            self._current(trip_id)
            return self.repository.redeem_invitation(token, idempotency_key)
        except TripDraftRevisionUnavailable:
            raise
        except AppError:
            raise
        except CollaborationStoreError as error:
            raise self._store_error(error) from error

    @staticmethod
    def _member_key(revision: TripDraftRevisionView, participant_id: UUID) -> str:
        for key, value in revision.member_bindings.items():
            if value == participant_id:
                return key
        raise AppError("PARTICIPANT_NOT_BOUND", "成员绑定不存在", 404, False)

    @staticmethod
    def _status(
        *,
        progress: list[ParticipantProgress],
        issues: tuple[CollaborationIssue, ...],
        can_plan: bool,
    ) -> CollaborationStatus:
        if can_plan:
            return CollaborationStatus.READY_TO_PLAN
        if issues:
            return CollaborationStatus.CONFLICT_REVIEW
        if any(item.confirmation_status is ParticipantConfirmationStatus.CONFIRMED for item in progress):
            return CollaborationStatus.COLLECTING_MEMBERS
        return CollaborationStatus.DRAFT_CONVERSATION

    def _access_status(
        self,
        *,
        stored: StoredCollaboration,
        participant_id: UUID,
    ) -> ParticipantAccessStatus:
        if participant_id == stored.organizer_participant_id:
            return ParticipantAccessStatus.ORGANIZER_ACTIVE
        try:
            return self.repository.participant_access_status(stored.trip_id, participant_id)
        except CollaborationStoreError:
            return ParticipantAccessStatus.NOT_INVITED

    def _progress(
        self,
        *,
        stored: StoredCollaboration,
        revision: TripDraftRevisionView,
        member_key: str,
        participant_id: UUID,
    ) -> ParticipantProgress:
        confirmation = stored.confirmations.get(participant_id)
        current_member = member_digest(revision, member_key)
        access_status = self._access_status(
            stored=stored,
            participant_id=participant_id,
        )
        confirmed = bool(
            confirmation
            and access_status is not ParticipantAccessStatus.REVOKED
            and confirmation.confirmed_revision == revision.revision
            and confirmation.confirmed_source_digest == revision.source_digest
            and confirmation.confirmed_shared_digest == shared_digest(revision)
            and confirmation.confirmed_member_digest == current_member
        )
        confirmation_status = (
            ParticipantConfirmationStatus.CONFIRMED
            if confirmed
            else (
                ParticipantConfirmationStatus.NEEDS_RECONFIRMATION
                if confirmation is not None
                else ParticipantConfirmationStatus.DRAFT
            )
        )
        return ParticipantProgress(
            participantId=participant_id,
            memberKey=member_key,
            role="ORGANIZER" if participant_id == stored.organizer_participant_id else "MEMBER",
            accessStatus=access_status,
            confirmationStatus=confirmation_status,
            confirmedRevision=(confirmation.confirmed_revision if confirmed else None),
        )

    def _derive(
        self,
        revision: TripDraftRevisionView,
        stored: StoredCollaboration,
    ) -> CollaborationAggregate:
        issues = self.evaluator.evaluate(
            revision,
            organizer_participant_id=stored.organizer_participant_id,
        )
        progress = [
            self._progress(
                stored=stored,
                revision=revision,
                member_key=member_key,
                participant_id=revision.member_bindings[member_key],
            )
            for member_key in sorted(revision.member_bindings)
        ]
        all_confirmed = all(
            item.confirmation_status is ParticipantConfirmationStatus.CONFIRMED
            for item in progress
        )
        can_plan = all_confirmed and not issues and stored.current_revision == revision.revision
        digest = (
            readiness_digest(
                revision,
                {key: member_digest(revision, key) for key in revision.member_bindings},
            )
            if can_plan
            else None
        )
        return CollaborationAggregate(
            tripId=revision.trip_id,
            draftId=revision.draft_id,
            currentRevision=revision.revision,
            organizerParticipantId=stored.organizer_participant_id,
            status=self._status(progress=progress, issues=issues, can_plan=can_plan),
            collaborationVersion=stored.version,
            readinessDigest=digest,
            canPlan=can_plan,
            progress=CollaborationProgress(
                expectedCount=len(revision.member_bindings),
                confirmedCount=sum(
                    item.confirmation_status is ParticipantConfirmationStatus.CONFIRMED
                    for item in progress
                ),
                openIssueCount=len(issues),
            ),
            participants=progress,
            confirmationItems=list(issues),
        )

    def organizer_state(
        self,
        trip_id: UUID,
        organizer_token: str | None,
    ) -> CollaborationAggregate:
        try:
            actor = self.repository.authenticate_organizer(organizer_token)
            if actor.trip_id != trip_id:
                raise CollaborationStoreError("ORGANIZER_PERMISSION_REQUIRED")
            revision = self._current(trip_id)
            return self._derive(revision, self.repository.get_stored(trip_id))
        except AppError:
            raise
        except CollaborationStoreError as error:
            raise self._store_error(error) from error

    def member_view(self, session_token: str | None) -> MemberSessionView:
        try:
            actor = self.repository.authenticate_participant(session_token)
            revision = self._current(actor.trip_id)
            stored = self.repository.get_stored(actor.trip_id)
            member_key = self._member_key(revision, actor.participant_id)
            participant = next(
                item for item in revision.understanding.participants
                if item.member_key == member_key
            )
            aggregate = self._derive(revision, stored)
            visible = [
                item for item in aggregate.confirmation_items
                if item.participant_id is None
                or item.participant_id == actor.participant_id
                or actor.participant_id in item.related_participant_ids
            ]
            progress = next(item for item in aggregate.participants if item.participant_id == actor.participant_id)
            return MemberSessionView(
                tripId=actor.trip_id,
                participantId=actor.participant_id,
                currentRevision=revision.revision,
                sharedTrip=revision.understanding.trip,
                participant=participant,
                accessStatus=progress.access_status,
                confirmationStatus=progress.confirmation_status,
                confirmationItems=visible,
            )
        except AppError:
            raise
        except CollaborationStoreError as error:
            raise self._store_error(error) from error

    async def submit_member(
        self,
        *,
        session_token: str | None,
        request: ParticipantConversationRequest,
        idempotency_key: str,
    ) -> MemberSessionView:
        try:
            actor = self.repository.authenticate_participant(session_token)
            current = self._current(actor.trip_id)
            if request.base_revision != current.revision:
                raise AppError("DRAFT_REVISION_STALE", "成员草稿版本已经变化", 409, False)
            try:
                revised = await self.revisions.submit_participant_conversation(
                    trip_id=actor.trip_id,
                    participant_id=actor.participant_id,
                    base_revision=request.base_revision,
                    submission=request.submission(),
                    idempotency_key=idempotency_key,
                )
            except TripDraftRevisionUnavailable as error:
                raise self._revision_error(error) from error
            if revised.trip_id != actor.trip_id or revised.revision != current.revision + 1:
                raise AppError("DRAFT_REVISION_STALE", "T002 返回了非连续草稿版本", 409, False)
            self.repository.advance_revision(
                trip_id=actor.trip_id,
                before_revision=current.revision,
                after_revision=revised.revision,
                expected_version=request.expected_version,
                actor_scope="PARTICIPANT",
                actor_id=str(actor.participant_id),
                idempotency_key=idempotency_key,
            )
            return self.member_view(session_token)
        except AppError:
            raise
        except CollaborationStoreError as error:
            raise self._store_error(error) from error

    def _confirm(
        self,
        *,
        trip_id: UUID,
        participant_id: UUID,
        request: ParticipantMutationRequest,
        idempotency_key: str,
    ) -> CollaborationAggregate:
        revision = self._current(trip_id)
        if request.base_revision != revision.revision:
            raise AppError("DRAFT_REVISION_STALE", "确认的草稿版本已经变化", 409, False)
        aggregate = self._derive(revision, self.repository.get_stored(trip_id))
        blocking = [
            issue for issue in aggregate.confirmation_items
            if issue.code in {IssueCode.MISSING, IssueCode.AMBIGUOUS, IssueCode.INVALID}
            and (
                issue.participant_id is None
                or issue.participant_id == participant_id
                or participant_id in issue.related_participant_ids
            )
        ]
        if blocking:
            raise AppError(
                "PARTICIPANT_CONFIRMATION_REQUIRED",
                "本人或共享字段仍需确认",
                422,
                False,
                [item.model_dump(mode="json", by_alias=True) for item in blocking],
            )
        member_key = self._member_key(revision, participant_id)
        try:
            self.repository.record_confirmation(
                trip_id=trip_id,
                participant_id=participant_id,
                revision=revision.revision,
                source_digest=revision.source_digest,
                shared_digest=shared_digest(revision),
                member_digest=member_digest(revision, member_key),
                expected_version=request.expected_version,
                idempotency_key=idempotency_key,
            )
            return self._derive(revision, self.repository.get_stored(trip_id))
        except CollaborationStoreError as error:
            raise self._store_error(error) from error

    def confirm_member(
        self,
        *,
        session_token: str | None,
        request: ParticipantMutationRequest,
        idempotency_key: str,
    ) -> MemberSessionView:
        try:
            actor = self.repository.authenticate_participant(session_token)
            self._confirm(
                trip_id=actor.trip_id,
                participant_id=actor.participant_id,
                request=request,
                idempotency_key=idempotency_key,
            )
            return self.member_view(session_token)
        except AppError:
            raise
        except CollaborationStoreError as error:
            raise self._store_error(error) from error

    def confirm_organizer(
        self,
        *,
        trip_id: UUID,
        participant_id: UUID,
        organizer_token: str | None,
        request: ParticipantMutationRequest,
        idempotency_key: str,
    ) -> CollaborationAggregate:
        try:
            actor = self.repository.authenticate_organizer(organizer_token)
            if actor.trip_id != trip_id or actor.participant_id != participant_id:
                raise CollaborationStoreError("ORGANIZER_PERMISSION_REQUIRED")
            return self._confirm(
                trip_id=trip_id,
                participant_id=participant_id,
                request=request,
                idempotency_key=idempotency_key,
            )
        except AppError:
            raise
        except CollaborationStoreError as error:
            raise self._store_error(error) from error

    def redeem_member(
        self,
        *,
        session_token: str | None,
    ) -> MemberSessionView:
        return self.member_view(session_token)

    def _resolve(
        self,
        *,
        trip_id: UUID,
        item_id: str,
        request: ResolveConfirmationItemRequest,
        actor: CollaborationActor,
        idempotency_key: str,
        organizer: bool,
    ) -> CollaborationAggregate | MemberSessionView | None:
        actor_scope = "ORGANIZER" if organizer else "PARTICIPANT"
        actor_id = str(actor.participant_id)
        request_digest = canonical_sha256({
            "tripId": str(trip_id),
            "itemId": item_id,
            "relaxationId": request.relaxation_id,
            "baseRevision": request.base_revision,
            "expectedVersion": request.expected_version,
            "actorScope": actor_scope,
            "actorId": actor_id,
        })
        existing = self.repository.get_idempotency_record(
            actor_scope=actor_scope,
            actor_id=actor_id,
            operation="RESOLVE_CONFIRMATION",
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            if existing[0] != request_digest:
                raise AppError("IDEMPOTENCY_KEY_REUSED", "相同幂等键对应不同请求", 409, False)
            if existing[1] is not None:
                return None
            stored = self.repository.get_stored(trip_id)
            advance = self.repository.get_idempotency_record(
                actor_scope=actor_scope,
                actor_id=actor_id,
                operation="ADVANCE_REVISION",
                idempotency_key=idempotency_key,
            )
            if (
                advance is not None
                and stored.current_revision == request.base_revision + 1
            ):
                try:
                    self.repository.record_resolution_audit(
                        trip_id=trip_id,
                        item_id=item_id,
                        relaxation_id=request.relaxation_id,
                        actor_id=actor_id,
                        before_revision=request.base_revision,
                        after_revision=stored.current_revision,
                    )
                    self.repository.complete_idempotent_operation(
                        actor_scope=actor_scope,
                        actor_id=actor_id,
                        operation="RESOLVE_CONFIRMATION",
                        idempotency_key=idempotency_key,
                        result={"afterRevision": stored.current_revision},
                    )
                except CollaborationStoreError as error:
                    raise self._store_error(error) from error
                return None
        else:
            stored = self.repository.get_stored(trip_id)
            if stored.version != request.expected_version:
                raise AppError("COLLABORATION_VERSION_STALE", "协作版本已经变化", 409, False)
            self.repository.begin_idempotent_operation(
                actor_scope=actor_scope,
                actor_id=actor_id,
                operation="RESOLVE_CONFIRMATION",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
        stored = self.repository.get_stored(trip_id)
        if stored.version != request.expected_version:
            raise AppError("COLLABORATION_VERSION_STALE", "协作版本已经变化", 409, False)
        revision = self._current(trip_id)
        aggregate = self._derive(revision, stored)
        issue = next((item for item in aggregate.confirmation_items if item.item_id == item_id), None)
        if issue is None:
            raise AppError("CONFIRMATION_ITEM_NOT_FOUND", "确认项不存在", 404, False)
        option = next((item for item in issue.relaxations if item.relaxation_id == request.relaxation_id), None)
        if option is None:
            raise AppError("RELAXATION_OPTION_INVALID", "放宽选项无效", 422, False)
        if organizer:
            if option.actor_scope is not ActorScope.ORGANIZER:
                raise AppError("ACTOR_SCOPE_FORBIDDEN", "该放宽选项不属于组织者", 403, False)
        elif option.actor_scope is not ActorScope.PARTICIPANT or option.participant_id != actor.participant_id:
            raise AppError("ACTOR_SCOPE_FORBIDDEN", "该放宽选项不属于当前成员", 403, False)
        try:
            revised = self.revisions.apply_relaxation(
                trip_id=trip_id,
                base_revision=request.base_revision,
                patch=CanonicalRevisionPatch(
                    action=option.action,
                    participant_id=option.participant_id,
                    field_path=option.field_path,
                    value=option.proposed_value,
                ),
                idempotency_key=idempotency_key,
            )
            if revised.trip_id != trip_id or revised.revision != revision.revision + 1:
                raise AppError("DRAFT_REVISION_STALE", "T002 返回了非连续草稿版本", 409, False)
            self.repository.advance_revision(
                trip_id=trip_id,
                before_revision=revision.revision,
                after_revision=revised.revision,
                expected_version=request.expected_version,
                actor_scope="ORGANIZER" if organizer else "PARTICIPANT",
                actor_id=str(actor.participant_id),
                idempotency_key=idempotency_key,
            )
            self.repository.record_resolution_audit(
                trip_id=trip_id,
                item_id=item_id,
                relaxation_id=request.relaxation_id,
                actor_id=str(actor.participant_id),
                before_revision=revision.revision,
                after_revision=revised.revision,
            )
            self.repository.complete_idempotent_operation(
                actor_scope=actor_scope,
                actor_id=actor_id,
                operation="RESOLVE_CONFIRMATION",
                idempotency_key=idempotency_key,
                result={"afterRevision": revised.revision},
            )
        except TripDraftRevisionUnavailable as error:
            raise self._revision_error(error) from error
        except CollaborationStoreError as error:
            raise self._store_error(error) from error
        if organizer:
            return self.organizer_state(trip_id, None)  # pragma: no cover - replaced below
        return self.member_view(None)  # pragma: no cover - replaced below

    def resolve_member_issue(
        self,
        *,
        session_token: str | None,
        item_id: str,
        request: ResolveConfirmationItemRequest,
        idempotency_key: str,
    ) -> MemberSessionView:
        actor = self.repository.authenticate_participant(session_token)
        self._resolve(
            trip_id=actor.trip_id,
            item_id=item_id,
            request=request,
            actor=actor,
            idempotency_key=idempotency_key,
            organizer=False,
        )
        return self.member_view(session_token)

    def resolve_organizer_issue(
        self,
        *,
        trip_id: UUID,
        item_id: str,
        request: ResolveConfirmationItemRequest,
        organizer_token: str | None,
        idempotency_key: str,
    ) -> CollaborationAggregate:
        actor = self.repository.authenticate_organizer(organizer_token)
        if actor.trip_id != trip_id:
            raise AppError("ORGANIZER_PERMISSION_REQUIRED", "组织者权限不足", 403, False)
        self._resolve(
            trip_id=trip_id,
            item_id=item_id,
            request=request,
            actor=actor,
            idempotency_key=idempotency_key,
            organizer=True,
        )
        return self.organizer_state(trip_id, organizer_token)

    def revoke_invitation(
        self,
        *,
        trip_id: UUID,
        participant_id: UUID,
        invitation_id: UUID,
        organizer_token: str | None,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        try:
            return self.repository.revoke_invitation(
                trip_id=trip_id,
                participant_id=participant_id,
                invitation_id=invitation_id,
                organizer_token=organizer_token,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
        except CollaborationStoreError as error:
            raise self._store_error(error) from error

    def require_ready(self, trip_id: UUID, organizer_capability: str | None) -> str:
        try:
            actor = self.repository.authenticate_organizer(organizer_capability)
            if actor.trip_id != trip_id:
                raise CollaborationStoreError("ORGANIZER_PERMISSION_REQUIRED")
            revision = self._current(trip_id)
            aggregate = self._derive(revision, self.repository.get_stored(trip_id))
            if not aggregate.can_plan or aggregate.readiness_digest is None:
                raise AppError(
                    "COLLABORATION_NOT_READY",
                    "全部成员确认且冲突解决后才能继续",
                    409,
                    False,
                )
            return aggregate.readiness_digest
        except AppError:
            raise
        except CollaborationStoreError as error:
            raise self._store_error(error) from error

    def ready_revision(
        self,
        trip_id: UUID,
        organizer_token: str | None,
    ) -> TripDraftRevisionView:
        self.require_ready(trip_id, organizer_token)
        return self._current(trip_id)


__all__ = ["CollaborationService"]
