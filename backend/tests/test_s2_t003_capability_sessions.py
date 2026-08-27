from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from app.infrastructure.collaboration_store import (
    CollaborationStoreError,
    SqliteCollaborationRepository,
)
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


def test_invitation_redeems_once_into_independent_member_session(tmp_path) -> None:
    repository, revision, clock, _, invitation = _issued(tmp_path)
    assert invitation.invitation_url is not None
    assert invitation.invitation_url.startswith("/join#token=")
    raw_invite = invitation.invitation_url.split("=", 1)[1]
    redeemed = repository.redeem_invitation(raw_invite, "2222222222222222")
    assert redeemed.participant_session_token is not None
    actor = repository.authenticate_participant(redeemed.participant_session_token)
    assert actor.participant_id == revision.member_bindings["member-2"]
    assert actor.expires_at == clock.now + timedelta(days=7)
    with pytest.raises(CollaborationStoreError, match="INVITATION_ALREADY_REDEEMED"):
        repository.redeem_invitation(raw_invite, "3333333333333333")


def test_database_and_structured_rows_never_contain_raw_secrets(tmp_path) -> None:
    repository, _, _, bootstrap, invitation = _issued(tmp_path)
    assert invitation.invitation_url is not None
    raw_invite = invitation.invitation_url.split("=", 1)[1]
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


def test_same_invite_concurrent_redemption_has_one_winner(tmp_path) -> None:
    repository, _, _, _, invitation = _issued(tmp_path)
    assert invitation.invitation_url is not None
    raw_invite = invitation.invitation_url.split("=", 1)[1]

    def redeem(key: str) -> str:
        try:
            repository.redeem_invitation(raw_invite, key)
            return "SUCCESS"
        except CollaborationStoreError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(redeem, ("2222222222222222", "3333333333333333")))
    assert results.count("SUCCESS") == 1
    assert results.count("INVITATION_ALREADY_REDEEMED") == 1
