from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from app.application.collaboration_ports import (
    TripDraftRevisionUnavailable,
    UnavailableTripDraftRevisionPort,
)
from app.application.collaboration_service import CollaborationService
from app.core.errors import AppError
from app.domain.collaboration import (
    IssueCode,
    ParticipantConfirmationStatus,
    ParticipantConversationRequest,
    ParticipantMutationRequest,
    ResolveConfirmationItemRequest,
)
from app.domain.collaboration_digest import member_digest, shared_digest
from app.domain.hard_conflicts import DeterministicHardConflictEvaluator
from app.domain.trip_draft import CareDraft, CareWalkLimits
from app.infrastructure.collaboration_store import (
    CollaborationStoreError,
    SqliteCollaborationRepository,
)
from backend.tests.s2_t003_support import (
    FakeRevision,
    FakeTripDraftRevisionPort,
    load_revision,
    revision_with_member_budget,
    revision_with_trip_budget,
)


@dataclass(slots=True)
class ReadyHarness:
    service: CollaborationService
    revisions: FakeTripDraftRevisionPort
    repository: SqliteCollaborationRepository
    revision: FakeRevision
    organizer_token: str


def _ready_harness(tmp_path) -> ReadyHarness:
    revision = load_revision()
    ordinary = CareDraft(
        assistanceTypeHint="ORDINARY",
        childAge=None,
        walkLimits=CareWalkLimits(
            maxContinuousMeters=None,
            maxDailyMeters=None,
        ),
        maxTransfers=None,
        restIntervalMinutes=None,
        napWindow=None,
        avoidStairs=False,
    )
    participants = [
        item.model_copy(update={"care_draft": ordinary})
        for item in revision.understanding.participants
    ]
    trip = revision.understanding.trip.model_copy(update={"budget_cents": 30_000})
    proposal = revision.understanding.model_copy(update={
        "trip": trip,
        "participants": participants,
        "missing_fields": [],
        "ambiguities": [],
        "confirmation_questions": [],
    })
    revision = replace(revision, understanding=proposal)
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    bootstrap = repository.bootstrap_collaboration(revision, "0123456789abcdef")
    assert bootstrap.organizer_token is not None
    version = 1
    for index, member_key in enumerate(sorted(revision.member_bindings), start=1):
        repository.record_confirmation(
            trip_id=revision.trip_id,
            participant_id=revision.member_bindings[member_key],
            revision=revision.revision,
            source_digest=revision.source_digest,
            shared_digest=shared_digest(revision),
            member_digest=member_digest(revision, member_key),
            expected_version=version,
            idempotency_key=f"confirm-{index:08d}",
        )
        version += 1
    revisions = FakeTripDraftRevisionPort(revision)
    service = CollaborationService(
        repository=repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    return ReadyHarness(service, revisions, repository, revision, bootstrap.organizer_token)


def _member_request(version: int) -> ParticipantConversationRequest:
    question_ids = (
        "trip", "party", "endpoints_budget", "preferences", "assistance", "confirm"
    )
    return ParticipantConversationRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=version,
        naturalLanguageRequest="我想把个人预算改为三百元",
        answers=[{"questionId": key, "answer": "已回答"} for key in question_ids],
    )


def _dump(repository: SqliteCollaborationRepository) -> tuple[tuple[object, ...], ...]:
    with repository._connect() as connection:
        return tuple(
            tuple(row)
            for table in (
                "collaboration_sessions",
                "collaboration_participants",
                "participant_invitations",
                "collaboration_actor_sessions",
                "collaboration_idempotency",
            )
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")
        )


@pytest.mark.asyncio
async def test_unavailable_t002_changes_no_rows_or_downstream_calls(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    invitation = harness.repository.create_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        organizer_token=harness.organizer_token,
        expected_version=3,
        idempotency_key="invite-000000001",
        expires_in_hours=72,
    )
    assert invitation.invitation_url is not None
    session = harness.repository.redeem_invitation(
        invitation.invitation_url.split("=", 1)[1],
        "redeem-000000001",
    )
    assert session.participant_session_token is not None
    service = CollaborationService(
        repository=harness.repository,
        revisions=UnavailableTripDraftRevisionPort(),
        evaluator=DeterministicHardConflictEvaluator(),
    )
    before = _dump(harness.repository)
    with pytest.raises(AppError) as captured:
        await service.submit_member(
            session_token=session.participant_session_token,
            request=_member_request(version=4),
            idempotency_key="7777777777777777",
        )
    assert captured.value.code == "TRIP_DRAFT_REVISION_UNAVAILABLE"
    assert captured.value.http_status == 503
    assert _dump(harness.repository) == before


def test_unavailable_t002_still_allows_invitation_revocation(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    invitation = harness.repository.create_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        organizer_token=harness.organizer_token,
        expected_version=3,
        idempotency_key="revoke-invite-0002",
    )
    unavailable = CollaborationService(
        repository=harness.repository,
        revisions=UnavailableTripDraftRevisionPort(),
        evaluator=DeterministicHardConflictEvaluator(),
    )

    result = unavailable.revoke_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        invitation_id=invitation.invitation_id,
        organizer_token=harness.organizer_token,
        expected_version=4,
        idempotency_key="revoke-action-0002",
    )

    assert result["accessStatus"] == "REVOKED"
    assert result["confirmationStatus"] == "NEEDS_RECONFIRMATION"


def test_member_only_change_invalidates_only_that_confirmation(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    changed = revision_with_member_budget(harness.revision, "member-2", 31_000)
    harness.revisions.current = changed
    state = harness.service.organizer_state(
        harness.revision.trip_id,
        harness.organizer_token,
    )
    statuses = {item.member_key: item.confirmation_status for item in state.participants}
    assert statuses == {
        "member-1": ParticipantConfirmationStatus.CONFIRMED,
        "member-2": ParticipantConfirmationStatus.NEEDS_RECONFIRMATION,
    }


def test_shared_change_invalidates_every_confirmation(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    harness.revisions.current = revision_with_trip_budget(harness.revision, 29_000)
    state = harness.service.organizer_state(
        harness.revision.trip_id,
        harness.organizer_token,
    )
    assert {item.confirmation_status for item in state.participants} == {
        ParticipantConfirmationStatus.NEEDS_RECONFIRMATION
    }


def _advance_harness_revision(harness: ReadyHarness, revision: FakeRevision) -> None:
    harness.repository.advance_revision(
        trip_id=harness.revision.trip_id,
        before_revision=1,
        after_revision=2,
        expected_version=3,
        actor_scope="PARTICIPANT",
        actor_id=str(harness.revision.member_bindings["member-2"]),
        idempotency_key="d020-revision-advance",
    )
    harness.revisions.current = replace(revision, revision=2, source_digest="b" * 64)


def _reconfirm_members(
    harness: ReadyHarness,
    member_keys: tuple[str, ...],
) -> None:
    version = harness.repository.get_stored(harness.revision.trip_id).version
    revision = harness.revisions.current
    for member_key in member_keys:
        harness.repository.record_confirmation(
            trip_id=revision.trip_id,
            participant_id=revision.member_bindings[member_key],
            revision=revision.revision,
            source_digest=revision.source_digest,
            shared_digest=shared_digest(revision),
            member_digest=member_digest(revision, member_key),
            expected_version=version,
            idempotency_key=f"d020-reconfirm-{member_key}",
        )
        version += 1


def test_member_only_new_revision_preserves_readiness_for_unaffected_member(
    tmp_path,
) -> None:
    harness = _ready_harness(tmp_path)
    changed = revision_with_member_budget(harness.revision, "member-2", 31_000)
    _advance_harness_revision(harness, changed)

    state = harness.service.organizer_state(
        harness.revision.trip_id,
        harness.organizer_token,
    )
    statuses = {item.member_key: item.confirmation_status for item in state.participants}
    assert statuses == {
        "member-1": ParticipantConfirmationStatus.CONFIRMED,
        "member-2": ParticipantConfirmationStatus.NEEDS_RECONFIRMATION,
    }
    with pytest.raises(AppError) as captured:
        harness.service.require_ready(harness.revision.trip_id, harness.organizer_token)
    assert captured.value.code == "COLLABORATION_NOT_READY"

    _reconfirm_members(harness, ("member-2",))
    assert harness.service.require_ready(
        harness.revision.trip_id,
        harness.organizer_token,
    )


def test_shared_new_revision_requires_and_recovers_all_confirmations(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    changed = revision_with_trip_budget(harness.revision, 31_000)
    _advance_harness_revision(harness, changed)

    state = harness.service.organizer_state(
        harness.revision.trip_id,
        harness.organizer_token,
    )
    assert {item.confirmation_status for item in state.participants} == {
        ParticipantConfirmationStatus.NEEDS_RECONFIRMATION
    }
    with pytest.raises(AppError) as captured:
        harness.service.require_ready(harness.revision.trip_id, harness.organizer_token)
    assert captured.value.code == "COLLABORATION_NOT_READY"

    _reconfirm_members(harness, ("member-1",))
    with pytest.raises(AppError, match="全部成员确认"):
        harness.service.require_ready(harness.revision.trip_id, harness.organizer_token)
    _reconfirm_members(harness, ("member-2",))
    assert harness.service.require_ready(
        harness.revision.trip_id,
        harness.organizer_token,
    )


def test_stale_expected_version_rejects_before_t002(tmp_path, monkeypatch) -> None:
    harness = _ready_harness(tmp_path)
    calls = 0
    original_get_current = harness.revisions.get_current

    def get_current(trip_id):
        nonlocal calls
        calls += 1
        return original_get_current(trip_id)

    monkeypatch.setattr(harness.revisions, "get_current", get_current)
    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=2,
        relaxationId="rx_0000000000000000",
    )

    with pytest.raises(AppError) as captured:
        harness.service.resolve_organizer_issue(
            trip_id=harness.revision.trip_id,
            item_id="ci_0000000000000000",
            request=request,
            organizer_token=harness.organizer_token,
            idempotency_key="resolve-stale-0001",
        )

    assert captured.value.code == "COLLABORATION_VERSION_STALE"
    assert calls == 0


class _AdvancingRevisionPort(FakeTripDraftRevisionPort):
    def apply_relaxation(self, **kwargs):
        self.relaxation_calls += 1
        self.current = replace(
            self.current,
            revision=self.current.revision + 1,
            source_digest="b" * 64,
        )
        return self.current


class _FailOnceAdvancingRevisionPort(_AdvancingRevisionPort):
    def __init__(self, revision):
        super().__init__(revision)
        self.fail_next = True

    def apply_relaxation(self, **kwargs):
        if self.fail_next:
            self.fail_next = False
            self.relaxation_calls += 1
            raise TripDraftRevisionUnavailable("injected apply failure")
        return super().apply_relaxation(**kwargs)


def test_resolution_retries_audit_after_revision_advance(tmp_path, monkeypatch) -> None:
    harness = _ready_harness(tmp_path)
    conflict = revision_with_trip_budget(harness.revision, 45_000)
    revisions = _AdvancingRevisionPort(conflict)
    service = CollaborationService(
        repository=harness.repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    state = service.organizer_state(harness.revision.trip_id, harness.organizer_token)
    issue = next(item for item in state.confirmation_items if item.code is IssueCode.CONFLICT)
    option = next(item for item in issue.relaxations if item.actor_scope.value == "ORGANIZER")
    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=3,
        relaxationId=option.relaxation_id,
    )
    original_audit = harness.repository.record_resolution_audit
    audit_calls = 0

    def fail_once(**kwargs):
        nonlocal audit_calls
        audit_calls += 1
        if audit_calls == 1:
            raise CollaborationStoreError("AUDIT_WRITE_FAILED")
        return original_audit(**kwargs)

    monkeypatch.setattr(harness.repository, "record_resolution_audit", fail_once)
    with pytest.raises(AppError) as captured:
        service.resolve_organizer_issue(
            trip_id=harness.revision.trip_id,
            item_id=issue.item_id,
            request=request,
            organizer_token=harness.organizer_token,
            idempotency_key="resolve-recovery-0001",
        )
    assert captured.value.code == "AUDIT_WRITE_FAILED"
    assert revisions.relaxation_calls == 1

    service.resolve_organizer_issue(
        trip_id=harness.revision.trip_id,
        item_id=issue.item_id,
        request=request,
        organizer_token=harness.organizer_token,
        idempotency_key="resolve-recovery-0001",
    )

    assert revisions.relaxation_calls == 1
    assert audit_calls == 2
    with harness.repository._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_resolution_audit"
        ).fetchone()[0] == 1


def test_first_organizer_resolution_returns_latest_state_and_stable_replay(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    conflict = revision_with_trip_budget(harness.revision, 45_000)
    revisions = _AdvancingRevisionPort(conflict)
    service = CollaborationService(
        repository=harness.repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    state = service.organizer_state(harness.revision.trip_id, harness.organizer_token)
    issue = next(item for item in state.confirmation_items if item.code is IssueCode.CONFLICT)
    option = next(item for item in issue.relaxations if item.actor_scope.value == "ORGANIZER")
    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=3,
        relaxationId=option.relaxation_id,
    )

    result = service.resolve_organizer_issue(
        trip_id=harness.revision.trip_id,
        item_id=issue.item_id,
        request=request,
        organizer_token=harness.organizer_token,
        idempotency_key="d016-organizer-resolution-1",
    )
    replay = service.resolve_organizer_issue(
        trip_id=harness.revision.trip_id,
        item_id=issue.item_id,
        request=request,
        organizer_token=harness.organizer_token,
        idempotency_key="d016-organizer-resolution-1",
    )

    assert result.current_revision == 2
    assert result.collaboration_version == 4
    assert result.model_dump(mode="json", by_alias=True) == replay.model_dump(
        mode="json", by_alias=True
    )
    assert revisions.relaxation_calls == 1
    with harness.repository._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_resolution_audit"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_idempotency "
            "WHERE operation='RESOLVE_CONFIRMATION' AND idempotency_key=?",
            ("d016-organizer-resolution-1",),
        ).fetchone()[0] == 1


def test_first_member_resolution_returns_latest_view_and_stable_replay(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    conflict = revision_with_trip_budget(harness.revision, 45_000)
    revisions = _AdvancingRevisionPort(conflict)
    service = CollaborationService(
        repository=harness.repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    state = service.organizer_state(harness.revision.trip_id, harness.organizer_token)
    issue = next(item for item in state.confirmation_items if item.code is IssueCode.CONFLICT)
    option = next(
        item
        for item in issue.relaxations
        if item.actor_scope.value == "PARTICIPANT"
        and item.participant_id == harness.revision.member_bindings["member-2"]
    )
    invitation = harness.repository.create_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        organizer_token=harness.organizer_token,
        expected_version=3,
        idempotency_key="d016-member-invite-1",
    )
    redeemed = harness.repository.redeem_invitation(
        invitation.invitation_url.split("=", 1)[1],
        "d016-member-redeem-1",
    )
    assert redeemed.participant_session_token is not None
    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=4,
        relaxationId=option.relaxation_id,
    )

    result = service.resolve_member_issue(
        session_token=redeemed.participant_session_token,
        item_id=issue.item_id,
        request=request,
        idempotency_key="d016-member-resolution-1",
    )
    replay = service.resolve_member_issue(
        session_token=redeemed.participant_session_token,
        item_id=issue.item_id,
        request=request,
        idempotency_key="d016-member-resolution-1",
    )

    assert result.current_revision == 2
    assert result.model_dump(mode="json", by_alias=True) == replay.model_dump(
        mode="json", by_alias=True
    )
    assert revisions.relaxation_calls == 1
    with harness.repository._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_resolution_audit"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_idempotency "
            "WHERE operation='RESOLVE_CONFIRMATION' AND idempotency_key=?",
            ("d016-member-resolution-1",),
        ).fetchone()[0] == 1


def test_t002_apply_failure_recovery_returns_latest_state(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    conflict = revision_with_trip_budget(harness.revision, 45_000)
    revisions = _FailOnceAdvancingRevisionPort(conflict)
    service = CollaborationService(
        repository=harness.repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    state = service.organizer_state(harness.revision.trip_id, harness.organizer_token)
    issue = next(item for item in state.confirmation_items if item.code is IssueCode.CONFLICT)
    option = next(item for item in issue.relaxations if item.actor_scope.value == "ORGANIZER")
    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=3,
        relaxationId=option.relaxation_id,
    )

    with pytest.raises(AppError) as captured:
        service.resolve_organizer_issue(
            trip_id=harness.revision.trip_id,
            item_id=issue.item_id,
            request=request,
            organizer_token=harness.organizer_token,
            idempotency_key="d016-recovery-1",
        )
    assert captured.value.code == "TRIP_DRAFT_REVISION_UNAVAILABLE"

    result = service.resolve_organizer_issue(
        trip_id=harness.revision.trip_id,
        item_id=issue.item_id,
        request=request,
        organizer_token=harness.organizer_token,
        idempotency_key="d016-recovery-1",
    )

    assert result.current_revision == 2
    assert result.collaboration_version == 4
    assert revisions.relaxation_calls == 2
    with harness.repository._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_resolution_audit"
        ).fetchone()[0] == 1
        row = connection.execute(
            "SELECT result_json, completed_at FROM collaboration_idempotency "
            "WHERE operation='RESOLVE_CONFIRMATION' AND idempotency_key=?",
            ("d016-recovery-1",),
        ).fetchone()
    assert row[0] is not None
    assert row[1] is not None


def test_expired_member_session_uses_required_error_code(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    invitation = harness.repository.create_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        organizer_token=harness.organizer_token,
        expected_version=3,
        idempotency_key="expired-session-invite",
    )
    redeemed = harness.repository.redeem_invitation(
        invitation.invitation_url.split("=", 1)[1],
        "expired-session-redeem",
    )
    assert redeemed.participant_session_token is not None
    with harness.repository._connect() as connection:
        connection.execute(
            "UPDATE collaboration_actor_sessions SET expires_at=? WHERE token_hash=?",
            (
                datetime(2020, 1, 1, tzinfo=UTC).isoformat(),
                harness.repository._token_hash(redeemed.participant_session_token),
            ),
        )

    with pytest.raises(AppError) as captured:
        harness.service.member_view(redeemed.participant_session_token)

    assert captured.value.code == "PARTICIPANT_SESSION_REQUIRED"


@pytest.mark.asyncio
async def test_all_member_apis_hide_invalid_session_reason(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    request = ParticipantMutationRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=4,
    )
    resolve_request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=4,
        relaxationId="rx_0000000000000000",
    )

    async def invoke(operation: str) -> None:
        if operation == "view":
            harness.service.member_view("forged-member-session")
        elif operation == "redeem":
            harness.service.redeem_member(session_token="forged-member-session")
        elif operation == "submit":
            await harness.service.submit_member(
                session_token="forged-member-session",
                request=_member_request(version=4),
                idempotency_key="member-invalid-0001",
            )
        elif operation == "confirm":
            harness.service.confirm_member(
                session_token="forged-member-session",
                request=request,
                idempotency_key="member-invalid-0002",
            )
        else:
            harness.service.resolve_member_issue(
                session_token="forged-member-session",
                item_id="ci_0000000000000000",
                request=resolve_request,
                idempotency_key="member-invalid-0003",
            )

    for operation in ("view", "redeem", "submit", "confirm", "resolve"):
        with pytest.raises(AppError) as captured:
            await invoke(operation)
        assert captured.value.code == "PARTICIPANT_SESSION_REQUIRED"
        assert captured.value.http_status == 401


def test_member_cannot_use_organizer_relaxation(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    conflict = revision_with_trip_budget(harness.revision, 45_000)
    harness.revisions.current = conflict
    state = harness.service.organizer_state(harness.revision.trip_id, harness.organizer_token)
    issue = next(item for item in state.confirmation_items if item.code is IssueCode.CONFLICT)
    organizer_option = next(
        item for item in issue.relaxations if item.actor_scope.value == "ORGANIZER"
    )
    invitation = harness.repository.create_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        organizer_token=harness.organizer_token,
        expected_version=3,
        idempotency_key="scope-invite-0001",
    )
    redeemed = harness.repository.redeem_invitation(
        invitation.invitation_url.split("=", 1)[1],
        "scope-redeem-0001",
    )
    assert redeemed.participant_session_token is not None

    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=4,
        relaxationId=organizer_option.relaxation_id,
    )
    with pytest.raises(AppError) as captured:
        harness.service.resolve_member_issue(
            session_token=redeemed.participant_session_token,
            item_id=issue.item_id,
            request=request,
            idempotency_key="scope-resolution-0001",
        )

    assert captured.value.code == "RELAXATION_PERMISSION_DENIED"
    assert harness.revisions.relaxation_calls == 0


def test_missing_confirmation_item_is_stale_without_idempotency_write(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=3,
        relaxationId="rx_0000000000000000",
    )

    with pytest.raises(AppError) as captured:
        harness.service.resolve_organizer_issue(
            trip_id=harness.revision.trip_id,
            item_id="ci_ffffffffffffffff",
            request=request,
            organizer_token=harness.organizer_token,
            idempotency_key="resolve-missing-item-1",
        )

    assert captured.value.code == "CONFIRMATION_ITEM_STALE"
    assert captured.value.http_status == 409
    assert harness.revisions.relaxation_calls == 0
    with harness.repository._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_idempotency "
            "WHERE operation='RESOLVE_CONFIRMATION' AND idempotency_key=?",
            ("resolve-missing-item-1",),
        ).fetchone()[0] == 0


def test_missing_relaxation_is_stale_without_idempotency_write(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    conflict = revision_with_trip_budget(harness.revision, 45_000)
    harness.revisions.current = conflict
    state = harness.service.organizer_state(
        harness.revision.trip_id,
        harness.organizer_token,
    )
    issue = next(item for item in state.confirmation_items if item.code is IssueCode.CONFLICT)
    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=3,
        relaxationId="rx_ffffffffffffffff",
    )

    with pytest.raises(AppError) as captured:
        harness.service.resolve_organizer_issue(
            trip_id=harness.revision.trip_id,
            item_id=issue.item_id,
            request=request,
            organizer_token=harness.organizer_token,
            idempotency_key="resolve-missing-option-1",
        )

    assert captured.value.code == "CONFIRMATION_ITEM_STALE"
    assert captured.value.http_status == 409
    assert harness.revisions.relaxation_calls == 0
    with harness.repository._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_idempotency "
            "WHERE operation='RESOLVE_CONFIRMATION' AND idempotency_key=?",
            ("resolve-missing-option-1",),
        ).fetchone()[0] == 0


def test_stale_base_revision_rejects_before_idempotency_and_t002(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    conflict = revision_with_trip_budget(harness.revision, 45_000)
    revision2 = replace(conflict, revision=2, source_digest="b" * 64)
    harness.repository.advance_revision(
        trip_id=harness.revision.trip_id,
        before_revision=1,
        after_revision=2,
        expected_version=3,
        actor_scope="ORGANIZER",
        actor_id=str(harness.revision.member_bindings["member-1"]),
        idempotency_key="d014-prep-advance-1",
    )
    revisions = FakeTripDraftRevisionPort(revision2)
    service = CollaborationService(
        repository=harness.repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    state = service.organizer_state(harness.revision.trip_id, harness.organizer_token)
    issue = next(item for item in state.confirmation_items if item.code is IssueCode.CONFLICT)
    option = next(item for item in issue.relaxations if item.actor_scope.value == "ORGANIZER")
    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=4,
        relaxationId=option.relaxation_id,
    )

    with pytest.raises(AppError) as captured:
        service.resolve_organizer_issue(
            trip_id=harness.revision.trip_id,
            item_id=issue.item_id,
            request=request,
            organizer_token=harness.organizer_token,
            idempotency_key="d014-stale-base-1",
        )

    assert captured.value.code == "DRAFT_REVISION_STALE"
    assert captured.value.http_status == 409
    assert revisions.relaxation_calls == 0
    with harness.repository._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_idempotency "
            "WHERE operation='RESOLVE_CONFIRMATION' AND idempotency_key=?",
            ("d014-stale-base-1",),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_resolution_audit"
        ).fetchone()[0] == 0
        session = connection.execute(
            "SELECT current_revision, version FROM collaboration_sessions WHERE trip_id=?",
            (str(harness.revision.trip_id),),
        ).fetchone()
    assert (session["current_revision"], session["version"]) == (2, 4)


@pytest.mark.asyncio
async def test_member_submit_stale_expected_version_rejects_before_t002(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    invitation = harness.repository.create_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        organizer_token=harness.organizer_token,
        expected_version=3,
        idempotency_key="d018-stale-submit-invite",
    )
    redeemed = harness.repository.redeem_invitation(
        invitation.invitation_url.split("=", 1)[1],
        "d018-stale-submit-redeem",
    )
    assert redeemed.participant_session_token is not None

    with pytest.raises(AppError) as captured:
        await harness.service.submit_member(
            session_token=redeemed.participant_session_token,
            request=_member_request(version=999),
            idempotency_key="d018-stale-submit",
        )

    assert captured.value.code == "COLLABORATION_VERSION_STALE"
    assert harness.revisions.submit_calls == 0


class _ReplayableSubmitRevisionPort(FakeTripDraftRevisionPort):
    def __init__(self, revision: FakeRevision) -> None:
        super().__init__(revision)
        self.gateway_calls = 0
        self._saved_result = None

    async def submit_participant_conversation(self, **kwargs):
        self.submit_calls += 1
        if self._saved_result is not None:
            return self._saved_result
        self.gateway_calls += 1
        self._saved_result = replace(
            self.current,
            revision=self.current.revision + 1,
            source_digest="b" * 64,
        )
        self.current = self._saved_result
        return self._saved_result


@pytest.mark.asyncio
async def test_member_submit_replay_finishes_collaboration_advance_without_reparse(
    tmp_path, monkeypatch
) -> None:
    harness = _ready_harness(tmp_path)
    invitation = harness.repository.create_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        organizer_token=harness.organizer_token,
        expected_version=3,
        idempotency_key="d019-replay-submit-invite",
    )
    redeemed = harness.repository.redeem_invitation(
        invitation.invitation_url.split("=", 1)[1],
        "d019-replay-submit-redeem",
    )
    assert redeemed.participant_session_token is not None
    revisions = _ReplayableSubmitRevisionPort(harness.revision)
    service = CollaborationService(
        repository=harness.repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )

    original_advance = harness.repository.advance_revision
    failed_after_commit = True

    def fail_after_commit(**kwargs):
        nonlocal failed_after_commit
        result = original_advance(**kwargs)
        if failed_after_commit:
            failed_after_commit = False
            raise RuntimeError("simulated response loss")
        return result

    monkeypatch.setattr(harness.repository, "advance_revision", fail_after_commit)
    request = _member_request(version=4)
    with pytest.raises(RuntimeError, match="simulated response loss"):
        await service.submit_member(
            session_token=redeemed.participant_session_token,
            request=request,
            idempotency_key="d019-replay-submit",
        )

    result = await service.submit_member(
        session_token=redeemed.participant_session_token,
        request=request,
        idempotency_key="d019-replay-submit",
    )

    assert result.current_revision == 2
    assert revisions.submit_calls == 2
    assert revisions.gateway_calls == 1
    with harness.repository._connect() as connection:
        row = connection.execute(
            "SELECT current_revision, version FROM collaboration_sessions WHERE trip_id=?",
            (str(harness.revision.trip_id),),
        ).fetchone()
        assert (row["current_revision"], row["version"]) == (2, 5)


def test_actor_scope_rejects_before_idempotency_and_t002(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    conflict = revision_with_trip_budget(harness.revision, 45_000)
    revisions = FakeTripDraftRevisionPort(conflict)
    service = CollaborationService(
        repository=harness.repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    state = service.organizer_state(harness.revision.trip_id, harness.organizer_token)
    issue = next(item for item in state.confirmation_items if item.code is IssueCode.CONFLICT)
    organizer_option = next(
        item for item in issue.relaxations if item.actor_scope.value == "ORGANIZER"
    )
    participant_option = next(
        item for item in issue.relaxations if item.actor_scope.value == "PARTICIPANT"
    )
    invitation = harness.repository.create_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        organizer_token=harness.organizer_token,
        expected_version=3,
        idempotency_key="d015-scope-invite-1",
    )
    redeemed = harness.repository.redeem_invitation(
        invitation.invitation_url.split("=", 1)[1],
        "d015-scope-redeem-1",
    )
    assert redeemed.participant_session_token is not None
    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=4,
        relaxationId=organizer_option.relaxation_id,
    )
    participant_request = request.model_copy(
        update={"relaxation_id": participant_option.relaxation_id}
    )

    def snapshot() -> tuple[tuple[object, ...], int]:
        with harness.repository._connect() as connection:
            session = tuple(
                connection.execute(
                    "SELECT current_revision, version FROM collaboration_sessions WHERE trip_id=?",
                    (str(harness.revision.trip_id),),
                ).fetchone()
            )
            audit_count = connection.execute(
                "SELECT COUNT(*) FROM collaboration_resolution_audit"
            ).fetchone()[0]
        return session, audit_count

    before = snapshot()
    with pytest.raises(AppError) as member_error:
        service.resolve_member_issue(
            session_token=redeemed.participant_session_token,
            item_id=issue.item_id,
            request=request,
            idempotency_key="d015-member-denied-1",
        )
    with pytest.raises(AppError) as organizer_error:
        service.resolve_organizer_issue(
            trip_id=harness.revision.trip_id,
            item_id=issue.item_id,
            request=participant_request,
            organizer_token=harness.organizer_token,
            idempotency_key="d015-organizer-denied-1",
        )
    after = snapshot()

    assert member_error.value.code == "RELAXATION_PERMISSION_DENIED"
    assert member_error.value.http_status == 403
    assert organizer_error.value.code == "RELAXATION_PERMISSION_DENIED"
    assert organizer_error.value.http_status == 403
    assert revisions.relaxation_calls == 0
    assert before == after
    with harness.repository._connect() as connection:
        for key in ("d015-member-denied-1", "d015-organizer-denied-1"):
            assert connection.execute(
                "SELECT COUNT(*) FROM collaboration_idempotency "
                "WHERE operation='RESOLVE_CONFIRMATION' AND idempotency_key=?",
                (key,),
            ).fetchone()[0] == 0


def test_member_resolution_uses_entry_actor_after_session_expires(
    tmp_path, monkeypatch
) -> None:
    harness = _ready_harness(tmp_path)
    conflict = revision_with_trip_budget(harness.revision, 45_000)
    revisions = _AdvancingRevisionPort(conflict)
    service = CollaborationService(
        repository=harness.repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    state = service.organizer_state(harness.revision.trip_id, harness.organizer_token)
    issue = next(item for item in state.confirmation_items if item.code is IssueCode.CONFLICT)
    option = next(
        item
        for item in issue.relaxations
        if item.actor_scope.value == "PARTICIPANT"
        and item.participant_id == harness.revision.member_bindings["member-2"]
    )
    invitation = harness.repository.create_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        organizer_token=harness.organizer_token,
        expected_version=3,
        idempotency_key="d017-entry-invite-1",
    )
    redeemed = harness.repository.redeem_invitation(
        invitation.invitation_url.split("=", 1)[1],
        "d017-entry-redeem-1",
    )
    assert redeemed.participant_session_token is not None
    token = redeemed.participant_session_token
    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=4,
        relaxationId=option.relaxation_id,
    )
    original_auth = harness.repository.authenticate_participant
    auth_calls = 0

    def expire_after_entry_auth(value):
        nonlocal auth_calls
        auth_calls += 1
        actor = original_auth(value)
        if auth_calls == 1:
            with harness.repository._connect() as connection:
                connection.execute(
                    "UPDATE collaboration_actor_sessions SET expires_at=? WHERE token_hash=?",
                    ("2020-01-01T00:00:00+00:00", harness.repository._token_hash(token)),
                )
        return actor

    monkeypatch.setattr(
        harness.repository, "authenticate_participant", expire_after_entry_auth
    )

    result = service.resolve_member_issue(
        session_token=token,
        item_id=issue.item_id,
        request=request,
        idempotency_key="d017-expiry-boundary-1",
    )

    assert auth_calls == 1
    assert result.current_revision == 2
    assert result.confirmation_status is ParticipantConfirmationStatus.NEEDS_RECONFIRMATION
    serialized = result.model_dump_json()
    assert harness.organizer_token not in serialized
    assert token not in serialized
    assert "Alex" not in serialized
    assert "architecture" not in serialized
    assert revisions.relaxation_calls == 1
    with harness.repository._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_resolution_audit"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_idempotency "
            "WHERE operation='RESOLVE_CONFIRMATION' AND idempotency_key=?",
            ("d017-expiry-boundary-1",),
        ).fetchone()[0] == 1


@pytest.mark.parametrize("session_state", ("expired", "revoked"))
def test_member_resolution_rejects_expired_or_revoked_session_at_entry(
    tmp_path, session_state
) -> None:
    harness = _ready_harness(tmp_path)
    conflict = revision_with_trip_budget(harness.revision, 45_000)
    revisions = _AdvancingRevisionPort(conflict)
    service = CollaborationService(
        repository=harness.repository,
        revisions=revisions,
        evaluator=DeterministicHardConflictEvaluator(),
    )
    state = service.organizer_state(harness.revision.trip_id, harness.organizer_token)
    issue = next(item for item in state.confirmation_items if item.code is IssueCode.CONFLICT)
    invitation = harness.repository.create_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        organizer_token=harness.organizer_token,
        expected_version=3,
        idempotency_key=f"d017-entry-{session_state}-invite-1",
    )
    redeemed = harness.repository.redeem_invitation(
        invitation.invitation_url.split("=", 1)[1],
        f"d017-entry-{session_state}-redeem-1",
    )
    assert redeemed.participant_session_token is not None
    token_hash = harness.repository._token_hash(redeemed.participant_session_token)
    with harness.repository._connect() as connection:
        if session_state == "expired":
            connection.execute(
                "UPDATE collaboration_actor_sessions SET expires_at=? WHERE token_hash=?",
                ("2020-01-01T00:00:00+00:00", token_hash),
            )
        else:
            connection.execute(
                "UPDATE collaboration_actor_sessions SET revoked_at=? WHERE token_hash=?",
                (datetime.now(UTC).isoformat(), token_hash),
            )
    request = ResolveConfirmationItemRequest(
        schemaVersion="1.0",
        baseRevision=1,
        expectedVersion=4,
        relaxationId="rx_0000000000000000",
    )

    with pytest.raises(AppError) as captured:
        service.resolve_member_issue(
            session_token=redeemed.participant_session_token,
            item_id=issue.item_id,
            request=request,
            idempotency_key=f"d017-entry-{session_state}-resolve-1",
        )

    assert captured.value.code == "PARTICIPANT_SESSION_REQUIRED"
    assert captured.value.http_status == 401
    assert revisions.relaxation_calls == 0
    with harness.repository._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_resolution_audit"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_idempotency "
            "WHERE operation='RESOLVE_CONFIRMATION' AND idempotency_key=?",
            (f"d017-entry-{session_state}-resolve-1",),
        ).fetchone()[0] == 0
