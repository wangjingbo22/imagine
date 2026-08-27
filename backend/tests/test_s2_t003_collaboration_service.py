from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from app.application.collaboration_ports import UnavailableTripDraftRevisionPort
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
