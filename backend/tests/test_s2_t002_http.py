from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from app.application.llm_gateway import TripUnderstandingGateway
from app.core.config import Settings
from app.domain.collaboration import OrganizerConversationRequest, QUESTION_IDS
from app.domain.trip_draft import (
    CareDraft,
    CareWalkLimits,
    FieldEvidence,
    TripUnderstandingGatewayResult,
    TripUnderstandingProposal,
)
from app.main import create_app
from app.api import collaboration_routes


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trip_understanding"


def _proposal(name: str = "one_participant.json") -> TripUnderstandingProposal:
    return TripUnderstandingProposal.model_validate_json(
        (FIXTURE_DIR / name).read_text(encoding="utf-8"),
        strict=True,
    )


def _conversation_payload(name: str = "one_participant.json") -> dict[str, object]:
    fixture = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    evidence = " ".join(item["sourceText"] for item in fixture["fieldEvidence"])
    evidence += " ordinary assistance no stair restriction"
    return {
        "schemaVersion": "1.0",
        "referenceDate": "2026-08-27",
        "naturalLanguageRequest": evidence,
        "answers": [
            {"questionId": question_id, "answer": evidence}
            for question_id in QUESTION_IDS
        ],
    }


def _ready_proposal() -> TripUnderstandingProposal:
    proposal = _proposal()
    participant = proposal.participants[0].model_copy(
        update={
            "care_draft": CareDraft(
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
        }
    )
    return proposal.model_copy(
        update={
            "participants": [participant],
            "field_evidence": [
                *proposal.field_evidence,
                FieldEvidence(
                    fieldPath="participants[0].careDraft.assistanceTypeHint",
                    memberKey="member-1",
                    sourceType="USER_TEXT",
                    sourceText="ordinary assistance",
                ),
                FieldEvidence(
                    fieldPath="participants[0].careDraft.avoidStairs",
                    memberKey="member-1",
                    sourceType="USER_TEXT",
                    sourceText="no stair restriction",
                ),
            ],
        }
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        plan_version_db_path=tmp_path / "planning.sqlite3",
        amap_cache_db_path=tmp_path / "amap.sqlite3",
    )


def _app(tmp_path: Path, gateway: TripUnderstandingGateway | None = None):
    return create_app(
        settings=_settings(tmp_path),
        service=object(),  # type: ignore[arg-type]
        trip_understanding_gateway=gateway,
    )


class CountingGateway:
    def __init__(
        self,
        proposal: TripUnderstandingProposal | None,
        *,
        failure_code: str | None = None,
        call_count: int = 1,
    ) -> None:
        self.proposal = proposal
        self.failure_code = failure_code
        self.call_count = call_count
        self.calls = 0

    async def understand(self, request) -> TripUnderstandingGatewayResult:
        self.calls += 1
        decision = "FIXED_QUESTIONS" if self.failure_code else "MODEL_PROPOSAL"
        return TripUnderstandingGatewayResult(
            decision=decision,
            proposal=self.proposal,
            failureCode=self.failure_code,
            callCount=self.call_count,
            model="test-model",
        )


@pytest.mark.asyncio
async def test_conversation_uses_bound_account_model_when_server_key_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The v2 intake must not fall back merely because BAILIAN_API_KEY is unset."""
    proposal = _proposal()

    class BoundAccountService:
        def user_model_credentials(self, token: str):
            assert token == "signed-in-account"
            return ("account-qwen", "account-key", "https://model.example/v1")

    class BoundExtractor:
        def __init__(self, *, model: str, **_: object) -> None:
            self.model = model

        async def propose_trip_understanding(self, request) -> str:
            return proposal.model_dump_json(by_alias=True)

        async def close(self) -> None:
            pass

    monkeypatch.setattr(collaboration_routes, "BailianTripDraftExtractor", BoundExtractor)
    app = create_app(
        settings=_settings(tmp_path),
        service=object(),  # type: ignore[arg-type]
        account_service=BoundAccountService(),  # type: ignore[arg-type]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v2/trips/conversations",
            headers={"Idempotency-Key": "bound-account-key-0001"},
            cookies={"account_session": "signed-in-account"},
            json=_conversation_payload(),
        )

    assert response.status_code == 200
    assert response.json()["data"]["recognition"] == {
        "source": "MODEL_PROPOSAL",
        "model": "account-qwen",
        "degradedReason": None,
        "callCount": 1,
    }


async def _request_conversation(
    app,
    payload: dict[str, object],
    key: str,
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.post(
            "/api/v2/trips/conversations",
            headers={"Idempotency-Key": key},
            json=payload,
        )


@pytest.mark.asyncio
async def test_conversations_creates_revision_and_bootstraps_existing_collaboration(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_proposal())
    app = _app(tmp_path, gateway)

    response = await _request_conversation(
        app,
        _conversation_payload(),
        "t002-http-create-0001",
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert data["revision"]["revision"] == 1
    assert data["revision"]["draftId"]
    assert data["organizerAccess"]["organizerToken"]
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_conversations_replay_reuses_revision_without_replaying_organizer_secret(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_proposal())
    app = _app(tmp_path, gateway)
    payload = _conversation_payload()
    first = await _request_conversation(app, payload, "t002-http-replay-0001")
    replay = await _request_conversation(app, payload, "t002-http-replay-0001")

    assert first.status_code == replay.status_code == 200
    assert first.headers["Cache-Control"] == replay.headers["Cache-Control"] == "no-store"
    first_data = first.json()["data"]
    replay_data = replay.json()["data"]
    assert replay_data["revision"] == first_data["revision"]
    assert replay_data["organizerAccess"]["organizerToken"] is None
    assert replay_data["organizerAccess"]["organizerTokenAvailable"] is False
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_conversations_reused_key_with_new_payload_is_answer_revision_stale(
    tmp_path: Path,
) -> None:
    gateway = CountingGateway(_proposal())
    app = _app(tmp_path, gateway)
    payload = _conversation_payload()
    changed = deepcopy(payload)
    changed["naturalLanguageRequest"] = "a materially different answer set"

    first = await _request_conversation(app, payload, "t002-http-stale-key-0001")
    second = await _request_conversation(app, changed, "t002-http-stale-key-0001")

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "ANSWER_REVISION_STALE"
    assert second.json()["retryable"] is False
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_conversations_without_t004_gateway_fails_closed(tmp_path: Path) -> None:
    app = _app(tmp_path)

    response = await _request_conversation(
        app,
        _conversation_payload(),
        "t002-http-unavailable-0001",
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert data["recognition"] == {
        "source": "FIXED_QUESTIONS",
        "model": None,
        "failureCode": "LLM_NOT_CONFIGURED",
        "callCount": 0,
    }
    assert data["understanding"] is None
    assert data["canPlan"] is False
    assert len(data["fallback"]["items"]) == 6
    with sqlite3.connect(tmp_path / "planning.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM trip_draft_revisions"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_code",
    [
        "LLM_TIMEOUT",
        "LLM_INVALID_JSON",
        "LLM_SCHEMA_INVALID",
    ],
)
async def test_conversations_fixed_question_fallback_has_no_authoritative_revision(
    tmp_path: Path,
    failure_code: str,
) -> None:
    gateway = CountingGateway(None, failure_code=failure_code, call_count=2)
    app = _app(tmp_path, gateway)
    payload = _conversation_payload()

    response = await _request_conversation(
        app,
        payload,
        f"t002-http-fallback-{failure_code}",
    )
    replay = await _request_conversation(
        app,
        payload,
        f"t002-http-fallback-{failure_code}",
    )

    assert response.status_code == replay.status_code == 200
    assert response.headers["Cache-Control"] == replay.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert data == replay.json()["data"]
    assert data["recognition"]["source"] == "FIXED_QUESTIONS"
    assert data["recognition"]["failureCode"] == failure_code
    assert data["understanding"] is None
    assert data["canPlan"] is False
    assert len(data["fallback"]["items"]) == 6
    assert gateway.calls == 1
    with sqlite3.connect(tmp_path / "planning.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM trip_draft_revisions"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_confirm_replay_does_not_increment_gateway_count(tmp_path: Path) -> None:
    gateway = CountingGateway(_ready_proposal())
    app = _app(tmp_path, gateway)
    created = await _request_conversation(
        app,
        _conversation_payload(),
        "t002-http-confirm-0001",
    )
    created_data = created.json()["data"]
    revision = created_data["revision"]
    organizer = created_data["organizerAccess"]
    participant_id = organizer["organizerParticipantId"]
    path = f"/api/v2/trips/{revision['tripId']}/participants/{participant_id}/confirm"
    body = {
        "schemaVersion": "1.0",
        "baseRevision": 1,
        "expectedVersion": 1,
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        first = await client.post(
            path,
            headers={
                "X-Organizer-Token": organizer["organizerToken"],
                "Idempotency-Key": "t002-http-confirm-action",
            },
            json=body,
        )
        replay = await client.post(
            path,
            headers={
                "X-Organizer-Token": organizer["organizerToken"],
                "Idempotency-Key": "t002-http-confirm-action",
            },
            json=body,
        )

    assert first.status_code == replay.status_code == 200
    assert gateway.calls == 1
