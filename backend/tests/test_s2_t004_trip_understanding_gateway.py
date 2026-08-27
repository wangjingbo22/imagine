from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import pytest
from pydantic import ValidationError

from app.application.llm_gateway import (
    StrictTripUnderstandingGateway,
    TripUnderstandingTransportError,
    UnavailableTripUnderstandingGateway,
)
from app.domain.trip_draft import (
    TripUnderstandingProposal,
    TripUnderstandingRequest,
    TripUnderstandingGatewayResult,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trip_understanding"


def _fixture_payload() -> dict[str, object]:
    return json.loads(
        (FIXTURE_DIR / "one_participant.json").read_text(encoding="utf-8")
    )


def _request() -> TripUnderstandingRequest:
    payload = _fixture_payload()
    trip = payload["trip"]
    participants = payload["participants"]
    evidence = payload["fieldEvidence"]
    assert isinstance(trip, dict)
    assert isinstance(participants, list)
    assert isinstance(evidence, list)
    return TripUnderstandingRequest.model_validate_json(
        json.dumps(
        {
            "schemaVersion": "1.0",
            "referenceDate": "2026-08-26",
            "rawConversation": " ".join(
                item["sourceText"] for item in evidence
            ),
            "explicitFields": {
                "cityName": trip["cityName"],
                "travelDate": trip["travelDate"],
                "startTime": trip["startTime"],
                "endTime": trip["endTime"],
                "startLocationText": trip["startLocationText"],
                "endLocationText": trip["endLocationText"],
                "budgetCents": trip["budgetCents"],
                "participants": [
                    {
                        "memberKey": participant["memberKey"],
                        "nickname": participant["nickname"],
                        "budgetCapCents": participant["budgetCapCents"],
                        "interests": participant["interests"],
                        "mustVisit": participant["mustVisit"],
                        "avoidPlaces": participant["avoidPlaces"],
                        "careText": None,
                    }
                    for participant in participants
                ],
            },
        },
        ensure_ascii=False,
        ),
        strict=True,
    )


def _proposal_json() -> str:
    return json.dumps(_fixture_payload(), ensure_ascii=False)


class SequenceUnderstandingClient:
    model = "qwen-fixture"

    def __init__(self, outcomes: Sequence[str | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.call_count = 0

    async def propose_trip_understanding(
        self,
        request: TripUnderstandingRequest,
    ) -> str:
        assert request == _request()
        outcome = self.outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.mark.parametrize(
    "result_kwargs",
    [
        {
            "decision": "MODEL_PROPOSAL",
            "proposal": None,
            "failure_code": None,
            "call_count": 1,
            "model": "qwen-fixture",
        },
        {
            "decision": "FIXED_QUESTIONS",
            "proposal": None,
            "failure_code": "LLM_TIMEOUT",
            "call_count": -1,
            "model": "qwen-fixture",
        },
        {
            "decision": "FIXED_QUESTIONS",
            "proposal": None,
            "failure_code": "LLM_TIMEOUT",
            "call_count": 3,
            "model": "qwen-fixture",
        },
    ],
)
def test_gateway_result_rejects_inconsistent_decision_shape(
    result_kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TripUnderstandingGatewayResult(**result_kwargs)


@pytest.mark.asyncio
async def test_valid_understanding_proposal_is_validated_once_and_returned() -> None:
    client = SequenceUnderstandingClient([_proposal_json()])

    result = await StrictTripUnderstandingGateway(client).understand(_request())

    expected = TripUnderstandingProposal.model_validate_json(
        _proposal_json(), strict=True
    )
    assert result.decision == "MODEL_PROPOSAL"
    assert result.proposal == expected
    assert result.failure_code is None
    assert result.call_count == client.call_count == 1


@pytest.mark.asyncio
async def test_retryable_transport_failure_recovers_on_the_second_attempt() -> None:
    client = SequenceUnderstandingClient(
        [
            TripUnderstandingTransportError(
                "LLM_UNAVAILABLE", retryable=True
            ),
            _proposal_json(),
        ]
    )

    result = await StrictTripUnderstandingGateway(client).understand(_request())

    assert result.decision == "MODEL_PROPOSAL"
    assert result.failure_code is None
    assert result.call_count == client.call_count == 2


@pytest.mark.asyncio
async def test_two_retryable_transport_failures_stop_at_two_calls() -> None:
    timeout = TripUnderstandingTransportError("LLM_TIMEOUT", retryable=True)
    client = SequenceUnderstandingClient([timeout, timeout, _proposal_json()])

    result = await StrictTripUnderstandingGateway(client).understand(_request())

    assert result.decision == "FIXED_QUESTIONS"
    assert result.failure_code == "LLM_TIMEOUT"
    assert result.call_count == client.call_count == 2
    assert client.outcomes[2] == _proposal_json()


@pytest.mark.asyncio
async def test_non_retryable_transport_failure_stops_at_one_call() -> None:
    client = SequenceUnderstandingClient(
        [
            TripUnderstandingTransportError(
                "LLM_AUTH_FAILED", retryable=False
            ),
            _proposal_json(),
        ]
    )

    result = await StrictTripUnderstandingGateway(client).understand(_request())

    assert result.decision == "FIXED_QUESTIONS"
    assert result.failure_code == "LLM_AUTH_FAILED"
    assert result.call_count == client.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "failure_code"),
    [
        ("not-json", "LLM_INVALID_JSON"),
        ("```json\n{}\n```", "LLM_INVALID_JSON"),
        ("{}", "LLM_SCHEMA_INVALID"),
    ],
)
async def test_invalid_model_content_never_starts_a_repair_call(
    raw: str,
    failure_code: str,
) -> None:
    client = SequenceUnderstandingClient([raw, _proposal_json()])

    result = await StrictTripUnderstandingGateway(client).understand(_request())

    assert result.decision == "FIXED_QUESTIONS"
    assert result.failure_code == failure_code
    assert result.call_count == client.call_count == 1


@pytest.mark.asyncio
async def test_evidence_context_mismatch_is_content_invalid_without_retry() -> None:
    payload = _fixture_payload()
    evidence = payload["fieldEvidence"]
    assert isinstance(evidence, list)
    evidence[0]["sourceText"] = "not present in request"
    invalid_proposal = json.dumps(payload, ensure_ascii=False)
    client = SequenceUnderstandingClient([invalid_proposal, _proposal_json()])

    result = await StrictTripUnderstandingGateway(client).understand(_request())

    assert result.decision == "FIXED_QUESTIONS"
    assert result.failure_code == "LLM_CONTENT_INVALID"
    assert result.call_count == client.call_count == 1


@pytest.mark.asyncio
async def test_unconfigured_understanding_gateway_returns_zero_call_fallback() -> None:
    result = await UnavailableTripUnderstandingGateway().understand(_request())

    assert result.decision == "FIXED_QUESTIONS"
    assert result.failure_code == "LLM_NOT_CONFIGURED"
    assert result.call_count == 0
    assert result.model is None
