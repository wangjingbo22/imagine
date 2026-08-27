from __future__ import annotations

import json

import pytest

from app.domain.collaboration_digest import member_digest, shared_digest
from app.infrastructure.collaboration_store import (
    CollaborationStoreError,
    SqliteCollaborationRepository,
)
from backend.tests.s2_t003_support import load_revision


@pytest.fixture
def revision():
    return load_revision()


@pytest.fixture
def repository(tmp_path, revision):
    value = SqliteCollaborationRepository(tmp_path / "collaboration.sqlite3")
    value.bootstrap_collaboration(revision, "0123456789abcdef")
    return value


def dump_collaboration_rows(repository) -> str:
    with repository._connect() as connection:
        payload = {
            table: [tuple(row) for row in connection.execute(
                f"SELECT * FROM {table} ORDER BY rowid"
            )]
            for table in (
                "collaboration_sessions",
                "collaboration_participants",
                "collaboration_idempotency",
                "collaboration_resolution_audit",
            )
        }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def test_confirmation_binds_exact_revision_and_digests(repository, revision) -> None:
    participant_id = revision.member_bindings["member-2"]
    repository.record_confirmation(
        trip_id=revision.trip_id,
        participant_id=participant_id,
        revision=revision.revision,
        source_digest=revision.source_digest,
        shared_digest=shared_digest(revision),
        member_digest=member_digest(revision, "member-2"),
        expected_version=1,
        idempotency_key="4444444444444444",
    )
    record = repository.confirmation_records(revision.trip_id)[participant_id]
    assert record.confirmed_revision == revision.revision
    assert record.confirmed_shared_digest == shared_digest(revision)


def test_stale_version_writes_nothing(repository, revision) -> None:
    before = dump_collaboration_rows(repository)
    with pytest.raises(CollaborationStoreError, match="COLLABORATION_VERSION_STALE"):
        repository.advance_revision(
            trip_id=revision.trip_id,
            before_revision=1,
            after_revision=2,
            expected_version=999,
            actor_scope="PARTICIPANT",
            actor_id=str(revision.member_bindings["member-2"]),
            idempotency_key="5555555555555555",
        )
    assert dump_collaboration_rows(repository) == before


def test_same_idempotency_key_with_different_digest_is_rejected(repository) -> None:
    repository.begin_idempotent_operation(
        actor_scope="PARTICIPANT", actor_id="member-2", operation="CONFIRM",
        idempotency_key="6666666666666666", request_digest="a" * 64,
    )
    with pytest.raises(CollaborationStoreError, match="IDEMPOTENCY_KEY_REUSED"):
        repository.begin_idempotent_operation(
            actor_scope="PARTICIPANT", actor_id="member-2", operation="CONFIRM",
            idempotency_key="6666666666666666", request_digest="b" * 64,
        )
