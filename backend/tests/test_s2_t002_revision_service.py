from __future__ import annotations

import asyncio
import importlib
import importlib.util
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from app.application.collaboration_ports import CanonicalRevisionPatch
from app.core.errors import AppError
from app.domain.collaboration import (
    OrganizerConversationRequest,
    RelaxationAction,
    ConversationSubmission,
)
from app.domain.trip_draft import TripUnderstandingProposal
from app.infrastructure.trip_draft_revision_store import (
    SqliteTripDraftRevisionRepository,
    TripDraftRevisionStoreError,
)


FIXTURE = Path(__file__).parent / "fixtures" / "trip_understanding" / "two_participants.json"
TRIP_ID = UUID("30000000-0000-4000-8000-000000000001")


def _service_module():
    spec = importlib.util.find_spec("app.application.trip_draft_revision_service")
    assert spec is not None
    return importlib.import_module("app.application.trip_draft_revision_service")


def _proposal() -> TripUnderstandingProposal:
    return TripUnderstandingProposal.model_validate_json(FIXTURE.read_text(encoding="utf-8"), strict=True)


def _submission(*extra: str) -> ConversationSubmission:
    evidence = " ".join(
        [
            "Shanghai",
            "2026-10-03",
            "08:30",
            "20:00",
            "Hongqiao Station",
            "The Bund",
            "90000",
            "Alex",
            "Bao",
            "50000",
            "40000",
            "architecture",
            "food",
            "crowded malls",
            *extra,
        ]
    )
    return ConversationSubmission(
        naturalLanguageRequest=evidence,
        answers=[
            {"questionId": question_id, "answer": evidence}
            for question_id in ("trip", "party", "endpoints_budget", "preferences", "assistance", "confirm")
        ],
    )


def _organizer_request(*extra: str) -> OrganizerConversationRequest:
    submission = _submission(*extra)
    return OrganizerConversationRequest(
        schemaVersion="1.0",
        referenceDate=date(2026, 8, 27),
        naturalLanguageRequest=submission.natural_language_request,
        answers=submission.answers,
    )


def _extraction(proposal: TripUnderstandingProposal | None = None) -> GatewayResult:
    return GatewayResult(
        decision="MODEL_PROPOSAL",
        proposal=proposal or _proposal(),
        failure_code=None,
        call_count=2,
        model="test-model",
    )


@dataclass
class GatewayResult:
    decision: str
    proposal: TripUnderstandingProposal | None
    failure_code: str | None
    call_count: int
    model: str | None


@dataclass
class CountingTripUnderstandingGateway:
    extraction: GatewayResult
    failure: Exception | None = None
    entered: asyncio.Event | None = None
    release: asyncio.Event | None = None
    calls: int = 0

    async def understand(self, request) -> GatewayResult:
        self.calls += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.failure is not None:
            raise self.failure
        return self.extraction


def _service(tmp_path: Path, gateway: CountingTripUnderstandingGateway):
    service_type = getattr(_service_module(), "TripDraftRevisionService", None)
    assert service_type is not None
    repository = SqliteTripDraftRevisionRepository(tmp_path / "drafts.sqlite3")
    return service_type(repository=repository, gateway=gateway), repository


def _revision_count(repository: SqliteTripDraftRevisionRepository) -> int:
    with repository._connect() as connection:
        return connection.execute("SELECT COUNT(*) FROM trip_draft_revisions").fetchone()[0]


@pytest.mark.asyncio
async def test_initial_answer_revision_calls_gateway_once_and_persists_exact_proposal(tmp_path: Path) -> None:
    gateway = CountingTripUnderstandingGateway(_extraction())
    service, repository = _service(tmp_path, gateway)

    revision = await service.create_initial(_organizer_request(), idempotency_key="initial-key-0001")

    assert gateway.calls == 1
    assert revision.revision == 1
    assert revision.understanding == gateway.extraction.proposal
    assert repository.get_current(revision.trip_id) == revision
    assert _revision_count(repository) == 1


@pytest.mark.asyncio
async def test_initial_replay_does_not_call_gateway_again(tmp_path: Path) -> None:
    gateway = CountingTripUnderstandingGateway(_extraction())
    service, repository = _service(tmp_path, gateway)
    request = _organizer_request()

    first = await service.create_initial(request, idempotency_key="initial-key-0002")
    replay = await service.create_initial(request, idempotency_key="initial-key-0002")

    assert replay == first
    assert gateway.calls == 1
    assert _revision_count(repository) == 1


@pytest.mark.asyncio
async def test_concurrent_initial_same_answer_calls_gateway_once(tmp_path: Path) -> None:
    gateway = CountingTripUnderstandingGateway(
        _extraction(),
        entered=asyncio.Event(),
        release=asyncio.Event(),
    )
    service, repository = _service(tmp_path, gateway)
    request = _organizer_request()

    first = asyncio.create_task(service.create_initial(request, idempotency_key="initial-key-0003"))
    await gateway.entered.wait()
    second = asyncio.create_task(service.create_initial(request, idempotency_key="initial-key-0003"))
    with pytest.raises(AppError, match="草稿解析正在进行"):
        await asyncio.wait_for(second, timeout=2)
    gateway.release.set()
    await first

    assert gateway.calls == 1
    assert _revision_count(repository) == 1


@pytest.mark.asyncio
async def test_member_correction_preserves_other_members_and_bindings(tmp_path: Path) -> None:
    initial_gateway = CountingTripUnderstandingGateway(_extraction())
    service, repository = _service(tmp_path, initial_gateway)
    initial = await service.create_initial(_organizer_request(), idempotency_key="initial-key-0004")

    corrected_member = initial.understanding.participants[0].model_copy(
        update={"nickname": "Alex corrected"}
    )
    corrected_evidence = [
        item.model_copy(update={"source_text": "Alex corrected"})
        if item.field_path == "participants[0].nickname"
        else item
        for item in initial.understanding.field_evidence
    ]
    corrected = initial.understanding.model_copy(
        update={
            "participants": [corrected_member, initial.understanding.participants[1]],
            "field_evidence": corrected_evidence,
        }
    )
    gateway = CountingTripUnderstandingGateway(_extraction(corrected))
    service.gateway = gateway
    participant_id = initial.member_bindings["member-1"]

    revised = await service.submit_participant_conversation(
        trip_id=initial.trip_id,
        participant_id=participant_id,
        base_revision=initial.revision,
        submission=_submission("Alex corrected"),
        idempotency_key="member-key-0001",
    )

    assert gateway.calls == 1
    assert revised.revision == 2
    assert revised.member_bindings == initial.member_bindings
    assert revised.understanding.trip == initial.understanding.trip
    assert revised.understanding.participants[1] == initial.understanding.participants[1]
    assert _revision_count(repository) == 2


@pytest.mark.asyncio
async def test_member_scope_violation_writes_no_revision(tmp_path: Path) -> None:
    gateway = CountingTripUnderstandingGateway(_extraction())
    service, repository = _service(tmp_path, gateway)
    initial = await service.create_initial(_organizer_request(), idempotency_key="initial-key-0005")
    altered_member = initial.understanding.participants[1].model_copy(
        update={"nickname": "Bao altered"}
    )
    altered_evidence = [
        item.model_copy(update={"source_text": "Bao altered"})
        if item.field_path == "participants[1].nickname"
        else item
        for item in initial.understanding.field_evidence
    ]
    altered = initial.understanding.model_copy(
        update={
            "trip": initial.understanding.trip.model_copy(update={"budget_cents": 95000}),
            "participants": [initial.understanding.participants[0], altered_member],
            "field_evidence": altered_evidence,
        }
    )
    gateway.extraction = _extraction(altered)
    gateway.calls = 0
    participant_id = initial.member_bindings["member-1"]

    with pytest.raises(AppError) as caught:
        await service.submit_participant_conversation(
            trip_id=initial.trip_id,
            participant_id=participant_id,
            base_revision=initial.revision,
            submission=_submission("Bao altered", "95000"),
            idempotency_key="member-key-0002",
        )

    assert caught.value.code == "PARTICIPANT_SCOPE_VIOLATION"
    assert gateway.calls == 1
    assert _revision_count(repository) == 1


def test_relaxation_creates_next_revision_without_gateway_call(tmp_path: Path) -> None:
    gateway = CountingTripUnderstandingGateway(_extraction())
    service, repository = _service(tmp_path, gateway)
    initial = asyncio.run(service.create_initial(_organizer_request(), idempotency_key="initial-key-0006"))

    revised = service.apply_relaxation(
        trip_id=initial.trip_id,
        base_revision=initial.revision,
        patch=CanonicalRevisionPatch(
            action=RelaxationAction.SET_SHARED_FIELD,
            participant_id=None,
            field_path="trip.endTime",
            value="21:00",
        ),
        idempotency_key="relax-key-0001",
    )

    assert gateway.calls == 1
    assert revised.revision == 2
    assert revised.understanding.trip.end_time == "21:00"
    assert _revision_count(repository) == 2


@pytest.mark.asyncio
async def test_failed_gateway_keeps_current_unavailable_and_never_retries_same_command(tmp_path: Path) -> None:
    gateway = CountingTripUnderstandingGateway(
        _extraction(),
        failure=AppError("TRIP_UNDERSTANDING_UNAVAILABLE", "gateway unavailable", 503, True),
    )
    service, repository = _service(tmp_path, gateway)
    request = _organizer_request()

    for _ in range(2):
        with pytest.raises(AppError) as caught:
            await service.create_initial(request, idempotency_key="failed-key-0001")
        assert caught.value.code == "TRIP_UNDERSTANDING_UNAVAILABLE"

    assert gateway.calls == 1
    assert _revision_count(repository) == 0
    with pytest.raises(TripDraftRevisionStoreError, match="TRIP_DRAFT_REVISION_UNAVAILABLE"):
        repository.get_current(TRIP_ID)


@pytest.mark.asyncio
async def test_fixed_questions_persists_failure_and_replay_does_not_call_gateway(tmp_path: Path) -> None:
    gateway = CountingTripUnderstandingGateway(
        GatewayResult(
            decision="FIXED_QUESTIONS",
            proposal=None,
            failure_code="LLM_CONTENT_INVALID",
            call_count=2,
            model="test-model",
        )
    )
    service, repository = _service(tmp_path, gateway)
    request = _organizer_request()

    first = await service.create_initial(request, idempotency_key="fixed-key-0001")
    replay = await service.create_initial(request, idempotency_key="fixed-key-0001")

    assert replay == first
    assert first.recognition.failure_code == "LLM_CONTENT_INVALID"
    assert first.understanding is None
    assert gateway.calls == 1
    assert _revision_count(repository) == 0
