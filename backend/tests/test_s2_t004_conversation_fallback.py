from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.application.trip_draft_revision_service import TripDraftRevisionService
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.collaboration import OrganizerConversationRequest, QUESTION_IDS
from app.domain.trip_draft import (
    TripDraftRevision,
    TripUnderstandingGatewayResult,
    TripUnderstandingProposal,
)
from app.infrastructure.trip_draft_revision_store import (
    SqliteTripDraftRevisionRepository,
)
from app.main import create_app


FIXTURE = Path(__file__).parent / "fixtures" / "trip_understanding" / "one_participant.json"


def _proposal() -> TripUnderstandingProposal:
    return TripUnderstandingProposal.model_validate_json(
        FIXTURE.read_text(encoding="utf-8"),
        strict=True,
    )


def _request(*extra: str) -> OrganizerConversationRequest:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    evidence = " ".join(item["sourceText"] for item in fixture["fieldEvidence"])
    evidence = " ".join((evidence, "ordinary assistance no stair restriction", *extra))
    return OrganizerConversationRequest(
        schemaVersion="1.0",
        referenceDate="2026-08-27",
        naturalLanguageRequest=evidence,
        answers=[
            {"questionId": question_id, "answer": evidence}
            for question_id in QUESTION_IDS
        ],
    )


def _result(
    *,
    proposal: TripUnderstandingProposal | None = None,
    failure_code: str | None = None,
    call_count: int = 2,
    model: str | None = "test-model",
) -> TripUnderstandingGatewayResult:
    return TripUnderstandingGatewayResult(
        decision="FIXED_QUESTIONS" if failure_code else "MODEL_PROPOSAL",
        proposal=proposal if failure_code is None else None,
        failureCode=failure_code,
        callCount=call_count,
        model=model,
    )


class CountingGateway:
    def __init__(self, result: TripUnderstandingGatewayResult) -> None:
        self.result = result
        self.calls = 0

    async def understand(self, request: Any) -> TripUnderstandingGatewayResult:
        self.calls += 1
        return self.result


def _service(
    tmp_path: Path,
    gateway: CountingGateway,
) -> tuple[TripDraftRevisionService, SqliteTripDraftRevisionRepository]:
    repository = SqliteTripDraftRevisionRepository(tmp_path / "planning.sqlite3")
    return TripDraftRevisionService(repository=repository, gateway=gateway), repository


def _app(tmp_path: Path, gateway: CountingGateway | None = None):
    settings = Settings(
        _env_file=None,
        plan_version_db_path=tmp_path / "planning.sqlite3",
        amap_cache_db_path=tmp_path / "amap.sqlite3",
    )
    return create_app(
        settings=settings,
        service=object(),  # type: ignore[arg-type]
        trip_understanding_gateway=gateway,
    )


async def _post(app, request: OrganizerConversationRequest, key: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.post(
            "/api/v2/trips/conversations",
            headers={"Idempotency-Key": key},
            json=request.model_dump(mode="json", by_alias=True),
        )


def _revision_count(repository: SqliteTripDraftRevisionRepository) -> int:
    with repository._connect() as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM trip_draft_revisions"
        ).fetchone()[0]


@pytest.mark.asyncio
async def test_model_failure_preserves_input_and_six_answers_without_canonical_write(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_TIMEOUT"))
    service, repository = _service(tmp_path, gateway)
    request = _request()

    outcome = await service.create_initial(request, idempotency_key="t004-fallback-0001")

    assert outcome.answer_revision == 1
    assert outcome.natural_language_request == request.natural_language_request
    assert outcome.answers == request.answers
    assert outcome.recognition.source == "FIXED_QUESTIONS"
    assert outcome.recognition.failure_code == "LLM_TIMEOUT"
    assert outcome.recognition.call_count == 2
    assert outcome.recognition.model == "test-model"
    assert outcome.understanding is None
    assert outcome.fallback.mode == "FIXED_QUESTIONS"
    assert len(outcome.fallback.items) == 6
    assert outcome.can_plan is False
    assert _revision_count(repository) == 0

    with repository._connect() as connection:
        stored = connection.execute(
            "SELECT status, outcome_json FROM trip_draft_commands"
        ).fetchone()
    assert stored["status"] == "FAILED"
    assert stored["outcome_json"]
    assert "LLM_TIMEOUT" in stored["outcome_json"]
    assert "rawConversation" not in stored["outcome_json"]


@pytest.mark.asyncio
async def test_same_answer_revision_replay_does_not_call_gateway_again(tmp_path: Path) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_INVALID_JSON"))
    service, repository = _service(tmp_path, gateway)
    request = _request()

    first = await service.create_initial(request, idempotency_key="t004-fallback-0002")
    replay = await service.create_initial(request, idempotency_key="t004-fallback-0002")

    assert replay == first
    assert gateway.calls == 1
    assert _revision_count(repository) == 0


@pytest.mark.asyncio
async def test_same_revision_with_different_source_digest_is_rejected_before_gateway(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_SCHEMA_INVALID"))
    service, repository = _service(tmp_path, gateway)

    await service.create_initial(_request(), idempotency_key="t004-fallback-0003")
    with pytest.raises(AppError) as caught:
        await service.create_initial(
            _request("changed answer"),
            idempotency_key="t004-fallback-0003",
        )

    assert caught.value.code == "ANSWER_REVISION_STALE"
    assert gateway.calls == 1
    assert _revision_count(repository) == 0


@pytest.mark.asyncio
async def test_new_answer_revision_is_the_only_way_to_start_a_new_call(tmp_path: Path) -> None:
    gateway = CountingGateway(_result(proposal=_proposal()))
    service, repository = _service(tmp_path, gateway)
    initial = await service.create_initial(_request(), idempotency_key="t004-model-0001")
    participant_id = initial.member_bindings["member-1"]

    gateway.result = _result(proposal=_proposal())
    revised = await service.submit_participant_conversation(
        trip_id=initial.trip_id,
        participant_id=participant_id,
        base_revision=initial.revision,
        submission=_request(),
        idempotency_key="t004-member-0001",
    )
    replay = await service.submit_participant_conversation(
        trip_id=initial.trip_id,
        participant_id=participant_id,
        base_revision=initial.revision,
        submission=_request(),
        idempotency_key="t004-member-0001",
    )

    assert isinstance(revised, TripDraftRevision)
    assert revised.revision == 2
    assert replay == revised
    assert gateway.calls == 2
    assert _revision_count(repository) == 2


@pytest.mark.asyncio
async def test_success_appends_only_the_strict_non_authoritative_proposal(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(proposal=_proposal()))
    service, repository = _service(tmp_path, gateway)

    revision = await service.create_initial(_request(), idempotency_key="t004-model-0002")

    assert isinstance(revision, TripDraftRevision)
    assert revision.understanding == gateway.result.proposal
    assert _revision_count(repository) == 1


@pytest.mark.asyncio
async def test_fallback_does_not_call_workflow_constraints_plans_confirmations_or_provider(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_TIMEOUT"))
    app = _app(tmp_path, gateway)

    response = await _post(app, _request(), "t004-http-0003-xx")

    assert response.status_code == 200
    with sqlite3.connect(tmp_path / "planning.sqlite3") as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        for table in tables:
            if any(
                marker in table
                for marker in ("workflow", "plan", "provider", "confirmation")
            ):
                assert connection.execute(
                    f"SELECT COUNT(*) FROM [{table}]"
                ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM trip_draft_commands"
        ).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_conversation_http_returns_fixed_questions_and_no_store_on_llm_failure(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_result(failure_code="LLM_SCHEMA_INVALID"))
    app = _app(tmp_path, gateway)
    request = _request()

    response = await _post(app, request, "t004-http-0001-xx")
    replay = await _post(app, request, "t004-http-0001-xx")

    assert response.status_code == replay.status_code == 200
    assert response.headers["Cache-Control"] == replay.headers["Cache-Control"] == "no-store"
    first_data = response.json()["data"]
    replay_data = replay.json()["data"]
    assert first_data == replay_data
    assert first_data["answerRevision"] == 1
    assert first_data["naturalLanguageRequest"] == request.natural_language_request
    assert first_data["answers"] == request.model_dump(mode="json", by_alias=True)["answers"]
    assert first_data["recognition"]["source"] == "FIXED_QUESTIONS"
    assert first_data["recognition"]["failureCode"] == "LLM_SCHEMA_INVALID"
    assert first_data["recognition"]["callCount"] == 2
    assert first_data["understanding"] is None
    assert first_data["canPlan"] is False
    assert len(first_data["fallback"]["items"]) == 6
    assert gateway.calls == 1

    with sqlite3.connect(tmp_path / "planning.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM trip_draft_revisions"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM collaboration_sessions"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_http_without_bailian_key_returns_fixed_questions_with_zero_calls(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)

    response = await _post(app, _request(), "t004-http-0002-xx")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["recognition"]["source"] == "FIXED_QUESTIONS"
    assert data["recognition"]["failureCode"] == "LLM_NOT_CONFIGURED"
    assert data["recognition"]["callCount"] == 0
    assert data["recognition"]["model"] is None
    assert data["understanding"] is None
    assert data["canPlan"] is False
    assert len(data["fallback"]["items"]) == 6
