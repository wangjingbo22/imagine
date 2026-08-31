from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.infrastructure.collaboration_store import (
    CollaborationStoreError,
    SqliteCollaborationRepository,
)
from app.domain.collaboration import ParticipantConfirmationStatus
from backend.tests.test_s2_t003_collaboration_service import _ready_harness
from backend.tests.s2_t003_support import FrozenClock, load_revision


def _issued(tmp_path):
    clock = FrozenClock(datetime(2026, 8, 27, 10, tzinfo=UTC))
    repository = SqliteCollaborationRepository(
        tmp_path / "collaboration.sqlite3",
        clock=clock,
    )
    revision = load_revision()
    bootstrap = repository.bootstrap_collaboration(revision, "0123456789abcdef")
    assert bootstrap.organizer_token is not None
    invitation = repository.create_invitation(
        trip_id=revision.trip_id,
        participant_id=revision.member_bindings["member-2"],
        organizer_token=bootstrap.organizer_token,
        expected_version=1,
        idempotency_key="1111111111111111",
        expires_in_hours=72,
    )
    return repository, revision, clock, bootstrap, invitation


def test_invitation_can_reopen_and_rotates_the_member_session(tmp_path) -> None:
    repository, revision, clock, _, invitation = _issued(tmp_path)
    assert invitation.invitation_url is not None
    assert invitation.invitation_url.startswith("/join/")
    raw_invite = invitation.invitation_url.rsplit("/", 1)[1]
    redeemed = repository.redeem_invitation(raw_invite, "2222222222222222")
    assert redeemed.participant_session_token is not None
    actor = repository.authenticate_participant(redeemed.participant_session_token)
    assert actor.participant_id == revision.member_bindings["member-2"]
    assert actor.expires_at == clock.now + timedelta(days=7)
    reopened = repository.redeem_invitation(raw_invite, "3333333333333333")
    assert reopened.participant_session_token is not None
    with pytest.raises(CollaborationStoreError, match="PARTICIPANT_SESSION_REVOKED"):
        repository.authenticate_participant(redeemed.participant_session_token)
    reopened_actor = repository.authenticate_participant(reopened.participant_session_token)
    assert reopened_actor.participant_id == revision.member_bindings["member-2"]


def test_database_and_structured_rows_never_contain_raw_secrets(tmp_path) -> None:
    repository, _, _, bootstrap, invitation = _issued(tmp_path)
    assert invitation.invitation_url is not None
    raw_invite = invitation.invitation_url.rsplit("/", 1)[1]
    redeemed = repository.redeem_invitation(raw_invite, "2222222222222222")
    assert bootstrap.organizer_token is not None
    assert redeemed.participant_session_token is not None
    raw = {
        bootstrap.organizer_token,
        raw_invite,
        redeemed.participant_session_token,
    }
    with repository._connect() as connection:
        serialized = "\n".join(
            "|".join("" if value is None else str(value) for value in row)
            for table in (
                "collaboration_sessions",
                "participant_invitations",
                "collaboration_actor_sessions",
                "collaboration_idempotency",
            )
            for row in connection.execute(f"SELECT * FROM {table}").fetchall()
        )
    assert all(secret not in serialized for secret in raw)


def test_same_invite_concurrent_redemption_keeps_only_latest_session_active(tmp_path) -> None:
    repository, _, _, _, invitation = _issued(tmp_path)
    assert invitation.invitation_url is not None
    raw_invite = invitation.invitation_url.rsplit("/", 1)[1]

    def redeem(key: str) -> str:
        try:
            outcome = repository.redeem_invitation(raw_invite, key)
            assert outcome.participant_session_token is not None
            return outcome.participant_session_token
        except CollaborationStoreError as error:
            return f"ERROR:{error}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(redeem, ("2222222222222222", "3333333333333333")))
    assert all(not item.startswith("ERROR:") for item in results)
    active_count = 0
    for token in results:
        try:
            repository.authenticate_participant(token)
            active_count += 1
        except CollaborationStoreError as error:
            assert str(error) == "PARTICIPANT_SESSION_REVOKED"
    assert active_count == 1


def test_revoke_invitation_revokes_linked_session_and_invalidates_confirmation(tmp_path) -> None:
    harness = _ready_harness(tmp_path)
    invitation = harness.repository.create_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        organizer_token=harness.organizer_token,
        expected_version=3,
        idempotency_key="revoke-invite-0001",
    )
    assert invitation.invitation_url is not None
    redeemed = harness.repository.redeem_invitation(
        invitation.invitation_url.rsplit("/", 1)[1],
        "revoke-redeem-0001",
    )
    assert redeemed.participant_session_token is not None

    result = harness.repository.revoke_invitation(
        trip_id=harness.revision.trip_id,
        participant_id=harness.revision.member_bindings["member-2"],
        invitation_id=invitation.invitation_id,
        organizer_token=harness.organizer_token,
        expected_version=4,
        idempotency_key="revoke-action-0001",
    )

    assert result["accessStatus"] == "REVOKED"
    assert result["confirmationStatus"] == "NEEDS_RECONFIRMATION"
    with pytest.raises(CollaborationStoreError, match="PARTICIPANT_SESSION_REVOKED"):
        harness.repository.authenticate_participant(redeemed.participant_session_token)
    state = harness.service.organizer_state(harness.revision.trip_id, harness.organizer_token)
    member = next(item for item in state.participants if item.member_key == "member-2")
    assert member.confirmation_status is ParticipantConfirmationStatus.NEEDS_RECONFIRMATION


def test_bootstrap_idempotency_returns_metadata_without_replaying_secret(tmp_path) -> None:
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    revision = load_revision()

    first = repository.bootstrap_collaboration(revision, "bootstrap-idempotent-1")
    replay = repository.bootstrap_collaboration(revision, "bootstrap-idempotent-1")

    assert first.organizer_token is not None
    assert replay.organizer_token is None
    assert replay.organizer_token_available is False
    assert replay.trip_id == first.trip_id
    assert replay.organizer_participant_id == first.organizer_participant_id
    with pytest.raises(CollaborationStoreError, match="IDEMPOTENCY_KEY_REUSED"):
        repository.bootstrap_collaboration(
            replace(revision, source_digest="b" * 64),
            "bootstrap-idempotent-1",
        )


def test_invitation_idempotency_returns_same_metadata_without_replaying_link(tmp_path) -> None:
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    revision = load_revision()
    bootstrap = repository.bootstrap_collaboration(revision, "bootstrap-idempotent-2")
    assert bootstrap.organizer_token is not None

    first = repository.create_invitation(
        trip_id=revision.trip_id,
        participant_id=revision.member_bindings["member-2"],
        organizer_token=bootstrap.organizer_token,
        expected_version=1,
        idempotency_key="invite-idempotent-1",
    )
    replay = repository.create_invitation(
        trip_id=revision.trip_id,
        participant_id=revision.member_bindings["member-2"],
        organizer_token=bootstrap.organizer_token,
        expected_version=1,
        idempotency_key="invite-idempotent-1",
    )

    assert first.invitation_url is not None
    assert replay.invitation_url is None
    assert replay.link_available is False
    assert replay.invitation_id == first.invitation_id
    with pytest.raises(CollaborationStoreError, match="IDEMPOTENCY_KEY_REUSED"):
        repository.create_invitation(
            trip_id=revision.trip_id,
            participant_id=revision.member_bindings["member-1"],
            organizer_token=bootstrap.organizer_token,
            expected_version=1,
            idempotency_key="invite-idempotent-1",
        )


def test_active_invitation_duplicate_uses_frozen_error_code(tmp_path) -> None:
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    revision = load_revision()
    bootstrap = repository.bootstrap_collaboration(revision, "bootstrap-active-dup")
    assert bootstrap.organizer_token is not None

    repository.create_invitation(
        trip_id=revision.trip_id,
        participant_id=revision.member_bindings["member-2"],
        organizer_token=bootstrap.organizer_token,
        expected_version=1,
        idempotency_key="invite-active-dup-1",
    )

    with pytest.raises(CollaborationStoreError, match="INVITATION_ACTIVE_EXISTS"):
        repository.create_invitation(
            trip_id=revision.trip_id,
            participant_id=revision.member_bindings["member-2"],
            organizer_token=bootstrap.organizer_token,
            expected_version=2,
            idempotency_key="invite-active-dup-2",
        )


def test_redeem_idempotency_returns_same_metadata_without_replaying_session_secret(tmp_path) -> None:
    repository = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    revision = load_revision()
    bootstrap = repository.bootstrap_collaboration(revision, "bootstrap-idempotent-3")
    assert bootstrap.organizer_token is not None
    invitation = repository.create_invitation(
        trip_id=revision.trip_id,
        participant_id=revision.member_bindings["member-2"],
        organizer_token=bootstrap.organizer_token,
        expected_version=1,
        idempotency_key="invite-idempotent-2",
    )
    assert invitation.invitation_url is not None
    raw_token = invitation.invitation_url.rsplit("/", 1)[1]

    first = repository.redeem_invitation(raw_token, "redeem-idempotent-1")
    replay = repository.redeem_invitation(raw_token, "redeem-idempotent-1")

    assert first.participant_session_token is not None
    assert replay.participant_session_token is None
    assert replay.session_token_available is False
    assert replay.session_id == first.session_id
    with pytest.raises(CollaborationStoreError, match="IDEMPOTENCY_KEY_REUSED"):
        repository.redeem_invitation("different-token-value", "redeem-idempotent-1")
