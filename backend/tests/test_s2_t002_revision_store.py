from __future__ import annotations

import importlib
import importlib.util
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from app.domain.trip_draft import TripDraftRevision, TripUnderstandingExtraction, TripUnderstandingProposal


FIXTURE = Path(__file__).parent / "fixtures" / "trip_understanding" / "two_participants.json"
DRAFT_ID = UUID("20000000-0000-4000-8000-000000000001")
TRIP_ID = UUID("30000000-0000-4000-8000-000000000001")


def _store_module():
    spec = importlib.util.find_spec("app.infrastructure.trip_draft_revision_store")
    assert spec is not None
    return importlib.import_module("app.infrastructure.trip_draft_revision_store")


def _repository(path: Path):
    repository_type = getattr(_store_module(), "SqliteTripDraftRevisionRepository", None)
    assert repository_type is not None
    return repository_type(path)


def _command(*, key: str = "0123456789abcdef", digest: str = "b" * 64):
    command_type = getattr(_store_module(), "AnswerCommand", None)
    assert command_type is not None
    return command_type(
        actor_scope="SYSTEM",
        actor_id="INITIAL_CONVERSATION",
        operation="INITIAL_ANSWER",
        idempotency_key=key,
        request_digest=digest,
    )


def _proposal() -> TripUnderstandingProposal:
    return TripUnderstandingProposal.model_validate_json(FIXTURE.read_text(encoding="utf-8"), strict=True)


def _revision(revision: int = 1) -> TripDraftRevision:
    return TripDraftRevision(
        schemaVersion="1.0",
        draftId=DRAFT_ID,
        revision=revision,
        tripId=TRIP_ID,
        understanding=_proposal(),
        memberBindings={
            "member-1": UUID("10000000-0000-4000-8000-000000000001"),
            "member-2": UUID("10000000-0000-4000-8000-000000000002"),
        },
        sourceDigest=f"{revision:064x}",
        createdAt=datetime(2026, 8, 27, tzinfo=UTC),
    )


def _extraction() -> TripUnderstandingExtraction:
    return TripUnderstandingExtraction(
        proposal=_proposal(),
        recognitionSource="TEST",
        recognitionModel="test-model",
        degradedReason=None,
        llmCallCount=1,
    )


def _claimed_type():
    claimed_type = getattr(_store_module(), "ClaimedCommand", None)
    assert claimed_type is not None
    return claimed_type


def _completed_type():
    completed_type = getattr(_store_module(), "CompletedCommand", None)
    assert completed_type is not None
    return completed_type


def test_completed_revision_survives_restart_and_rows_are_immutable(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "drafts.sqlite3")
    claim = repository.claim_initial(_command(), draft_id=DRAFT_ID, trip_id=TRIP_ID)
    assert isinstance(claim, _claimed_type())
    revision = _revision()
    repository.complete(claim, revision, _extraction())

    expected = revision.model_dump_json(by_alias=True)
    restarted = _repository(tmp_path / "drafts.sqlite3")
    loaded = restarted.get_current(TRIP_ID)
    assert loaded.model_dump_json(by_alias=True) == expected
    assert loaded.source_digest == revision.source_digest

    with pytest.raises(_store_module().TripDraftRevisionStoreError, match="DRAFT_REVISION_IMMUTABLE"):
        restarted.complete(claim, revision, _extraction())


def test_same_command_replays_saved_revision_and_digest_conflict_is_rejected(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "drafts.sqlite3")
    command = _command()
    claim = repository.claim_initial(command, draft_id=DRAFT_ID, trip_id=TRIP_ID)
    repository.complete(claim, _revision(), _extraction())

    replay = repository.claim_initial(command, draft_id=DRAFT_ID, trip_id=TRIP_ID)
    assert isinstance(replay, _completed_type())
    assert replay.revision == repository.get_current(TRIP_ID)

    with pytest.raises(_store_module().TripDraftRevisionStoreError, match="IDEMPOTENCY_KEY_REUSED"):
        repository.claim_initial(
            replace(command, request_digest="c" * 64),
            draft_id=DRAFT_ID,
            trip_id=TRIP_ID,
        )


def test_concurrent_same_answer_command_claims_once(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "drafts.sqlite3")
    command = _command()

    def claim() -> object:
        return repository.claim_initial(command, draft_id=DRAFT_ID, trip_id=TRIP_ID)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim(), range(2)))

    assert sum(isinstance(result, _claimed_type()) for result in results) == 1
    assert sum(type(result).__name__ in {"CommandInProgress", "CompletedCommand"} for result in results) == 1


def test_stale_base_revision_is_rejected_before_claim(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "drafts.sqlite3")
    initial_claim = repository.claim_initial(_command(), draft_id=DRAFT_ID, trip_id=TRIP_ID)
    repository.complete(initial_claim, _revision(), _extraction())

    with pytest.raises(_store_module().TripDraftRevisionStoreError, match="DRAFT_REVISION_STALE"):
        repository.claim_next(
            _command(key="fedcba9876543210"),
            draft_id=DRAFT_ID,
            trip_id=TRIP_ID,
            base_revision=0,
        )

    with sqlite3.connect(tmp_path / "drafts.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM trip_draft_commands").fetchone()[0] == 1


def test_pending_command_hides_old_current_revision(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "drafts.sqlite3")
    initial_claim = repository.claim_initial(_command(), draft_id=DRAFT_ID, trip_id=TRIP_ID)
    repository.complete(initial_claim, _revision(), _extraction())
    repository.claim_next(
        _command(key="fedcba9876543210"),
        draft_id=DRAFT_ID,
        trip_id=TRIP_ID,
        base_revision=1,
    )

    with pytest.raises(_store_module().TripDraftRevisionStoreError, match="TRIP_DRAFT_REVISION_UNAVAILABLE"):
        repository.get_current(TRIP_ID)


def test_completed_revision_preserves_two_transport_attempts(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "drafts.sqlite3")
    claim = repository.claim_initial(_command(), draft_id=DRAFT_ID, trip_id=TRIP_ID)
    extraction = TripUnderstandingExtraction(
        proposal=_proposal(),
        recognitionSource="TEST",
        recognitionModel="test-model",
        degradedReason=None,
        llmCallCount=2,
    )

    repository.complete(claim, _revision(), extraction)

    with sqlite3.connect(tmp_path / "drafts.sqlite3") as connection:
        assert connection.execute(
            "SELECT llm_call_count FROM trip_draft_revisions"
        ).fetchone()[0] == 2
