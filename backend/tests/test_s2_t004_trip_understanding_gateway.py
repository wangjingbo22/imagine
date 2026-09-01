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


def _member_request() -> TripUnderstandingRequest:
    return TripUnderstandingRequest.model_validate_json(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "scope": "MEMBER_PROFILE",
                "referenceDate": "2026-08-26",
                "rawConversation": (
                    "【用户初始描述】\n我喜欢慢节奏。\n\n"
                    "【个人偏好（兴趣与地点限制）】\n"
                    "兴趣：博物馆；必去：故宫；避开：酒吧\n\n"
                    "【个人限制（预算、步行、换乘、休息、关怀）】\n"
                    "个人预算上限：500元；没有额外关怀限制"
                ),
                "explicitFields": {
                    "cityName": None,
                    "travelDate": None,
                    "startTime": None,
                    "endTime": None,
                    "startLocationText": None,
                    "endLocationText": None,
                    "budgetCents": None,
                    "participants": [],
                },
            },
            ensure_ascii=False,
        ),
        strict=True,
    )


def _member_profile_json() -> str:
    return json.dumps(
        {
            "schemaVersion": "1.0",
            "nickname": None,
            "budgetCapCents": 50_000,
            "interests": ["博物馆"],
            "mustVisit": ["故宫"],
            "avoidPlaces": ["酒吧"],
            "careDraft": {
                "assistanceTypeHint": "ORDINARY",
                "childAge": None,
                "walkLimits": {
                    "maxContinuousMeters": None,
                    "maxDailyMeters": None,
                },
                "maxTransfers": None,
                "restIntervalMinutes": None,
                "napWindow": None,
                "avoidStairs": None,
            },
            "fieldEvidence": [
                {"fieldPath": "budgetCapCents", "sourceText": "500"},
                {"fieldPath": "interests[0]", "sourceText": "博物馆"},
                {"fieldPath": "mustVisit[0]", "sourceText": "故宫"},
                {"fieldPath": "avoidPlaces[0]", "sourceText": "酒吧"},
                {
                    "fieldPath": "careDraft.assistanceTypeHint",
                    "sourceText": "没有额外关怀限制",
                },
            ],
        },
        ensure_ascii=False,
    )


def _organizer_trip_json() -> str:
    payload = _fixture_payload()
    return json.dumps(
        {
            "schemaVersion": "1.0",
            "trip": payload["trip"],
            "participants": payload["participants"],
        },
        ensure_ascii=False,
    )


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

    async def repair_trip_understanding(
        self,
        request: TripUnderstandingRequest,
        *,
        invalid_response: str,
        validation_errors: str,
    ) -> str:
        assert request == _request()
        assert invalid_response
        assert validation_errors
        outcome = self.outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class MemberProfileClient:
    model = "qwen-member-fixture"

    def __init__(self, outcome: str | Exception) -> None:
        self.outcome = outcome
        self.call_count = 0

    async def propose_member_profile(
        self,
        request: TripUnderstandingRequest,
    ) -> str:
        assert request == _member_request()
        self.call_count += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class OrganizerTripClient:
    model = "qwen-organizer-fixture"

    def __init__(
        self,
        outcome: str | Exception,
        *,
        expected_request: TripUnderstandingRequest | None = None,
    ) -> None:
        self.outcome = outcome
        self.expected_request = expected_request or _request()
        self.call_count = 0

    async def propose_organizer_trip(
        self,
        request: TripUnderstandingRequest,
    ) -> str:
        assert request == self.expected_request
        self.call_count += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


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
async def test_invalid_model_content_is_repaired_once(
    raw: str,
    failure_code: str,
) -> None:
    client = SequenceUnderstandingClient([raw, _proposal_json()])

    result = await StrictTripUnderstandingGateway(client).understand(_request())

    assert result.decision == "MODEL_PROPOSAL"
    assert result.failure_code is None
    assert result.call_count == client.call_count == 2


@pytest.mark.asyncio
async def test_evidence_context_mismatch_is_repaired_once() -> None:
    payload = _fixture_payload()
    evidence = payload["fieldEvidence"]
    assert isinstance(evidence, list)
    evidence[0]["sourceText"] = "not present in request"
    invalid_proposal = json.dumps(payload, ensure_ascii=False)
    client = SequenceUnderstandingClient([invalid_proposal, _proposal_json()])

    result = await StrictTripUnderstandingGateway(client).understand(_request())

    assert result.decision == "MODEL_PROPOSAL"
    assert result.failure_code is None
    assert result.call_count == client.call_count == 2


@pytest.mark.asyncio
async def test_organizer_trip_uses_one_compact_call_and_maps_to_unified_proposal() -> None:
    client = OrganizerTripClient(_organizer_trip_json())

    result = await StrictTripUnderstandingGateway(client).understand(_request())

    expected = TripUnderstandingProposal.model_validate_json(
        _proposal_json(),
        strict=True,
    )
    assert result.decision == "MODEL_PROPOSAL"
    assert result.proposal == expected
    assert result.failure_code is None
    assert result.call_count == client.call_count == 1


@pytest.mark.asyncio
async def test_organizer_fixed_question_budgets_and_evidence_are_server_grounded() -> None:
    request = TripUnderstandingRequest.model_validate_json(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "scope": "FULL_TRIP",
                "referenceDate": "2026-08-26",
                "rawConversation": (
                    "目的城市：北京；出行日期：2026-09-06；可用时间：09:00到18:00；"
                    "从北京站出发；结束地：北京站；共享预算：900；"
                    "组织者昵称：测试用户；组织者个人预算上限：500元；"
                    "关怀模式：ORDINARY"
                ),
                "explicitFields": {
                    "cityName": None,
                    "travelDate": None,
                    "startTime": None,
                    "endTime": None,
                    "startLocationText": None,
                    "endLocationText": None,
                    "budgetCents": None,
                    "participants": [],
                },
            },
            ensure_ascii=False,
        ),
        strict=True,
    )
    compact = json.dumps(
        {
            "schemaVersion": "1.0",
            "trip": {
                "cityName": "北京",
                "travelDate": "2026-09-06",
                "startTime": "09:00",
                "endTime": "18:00",
                "startLocationText": "北京站",
                "endLocationText": "北京站",
                "budgetCents": 900,
            },
            "participants": [
                {
                    "memberKey": "member-1",
                    "nickname": "测试用户",
                    "budgetCapCents": 500,
                    "interests": [],
                    "mustVisit": [],
                    "avoidPlaces": [],
                    "careDraft": {
                        "assistanceTypeHint": "ORDINARY",
                        "childAge": None,
                        "walkLimits": {
                            "maxContinuousMeters": None,
                            "maxDailyMeters": None,
                        },
                        "maxTransfers": None,
                        "restIntervalMinutes": None,
                        "napWindow": None,
                        "avoidStairs": None,
                    },
                }
            ],
        },
        ensure_ascii=False,
    )
    client = OrganizerTripClient(compact, expected_request=request)

    result = await StrictTripUnderstandingGateway(client).understand(request)

    assert result.decision == "MODEL_PROPOSAL"
    assert result.proposal is not None
    assert result.proposal.trip.budget_cents == 90_000
    assert result.proposal.participants[0].budget_cap_cents == 50_000
    evidence = {item.field_path: item.source_text for item in result.proposal.field_evidence}
    assert evidence["trip.budgetCents"] == "900"
    assert evidence["participants[0].budgetCapCents"] == "500"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "failure_code"),
    [
        ("not-json", "LLM_INVALID_JSON"),
        ("{}", "LLM_SCHEMA_INVALID"),
    ],
)
async def test_invalid_organizer_trip_falls_back_after_one_call(
    raw: str,
    failure_code: str,
) -> None:
    client = OrganizerTripClient(raw)

    result = await StrictTripUnderstandingGateway(client).understand(_request())

    assert result.decision == "FIXED_QUESTIONS"
    assert result.failure_code == failure_code
    assert result.call_count == client.call_count == 1


@pytest.mark.asyncio
async def test_retryable_organizer_transport_failure_is_not_retried() -> None:
    client = OrganizerTripClient(
        TripUnderstandingTransportError("LLM_TIMEOUT", retryable=True)
    )

    result = await StrictTripUnderstandingGateway(client).understand(_request())

    assert result.decision == "FIXED_QUESTIONS"
    assert result.failure_code == "LLM_TIMEOUT"
    assert result.call_count == client.call_count == 1


@pytest.mark.asyncio
async def test_member_profile_uses_one_compact_call_and_maps_to_unified_proposal() -> None:
    client = MemberProfileClient(_member_profile_json())

    result = await StrictTripUnderstandingGateway(client).understand(_member_request())

    assert result.decision == "MODEL_PROPOSAL"
    assert result.failure_code is None
    assert result.call_count == client.call_count == 1
    assert result.proposal is not None
    assert result.proposal.trip.city_name is None
    assert len(result.proposal.participants) == 1
    participant = result.proposal.participants[0]
    assert participant.member_key == "member-1"
    assert participant.budget_cap_cents == 50_000
    assert participant.interests == ["博物馆"]
    assert participant.must_visit == ["故宫"]
    assert participant.avoid_places == ["酒吧"]
    assert {item.field_path for item in result.proposal.field_evidence} == {
        "participants[0].budgetCapCents",
        "participants[0].interests[0]",
        "participants[0].mustVisit[0]",
        "participants[0].avoidPlaces[0]",
        "participants[0].careDraft.assistanceTypeHint",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "failure_code"),
    [
        ("not-json", "LLM_INVALID_JSON"),
        ("{}", "LLM_SCHEMA_INVALID"),
    ],
)
async def test_invalid_member_profile_falls_back_after_one_call(
    raw: str,
    failure_code: str,
) -> None:
    client = MemberProfileClient(raw)

    result = await StrictTripUnderstandingGateway(client).understand(_member_request())

    assert result.decision == "FIXED_QUESTIONS"
    assert result.failure_code == failure_code
    assert result.call_count == client.call_count == 1


@pytest.mark.asyncio
async def test_member_profile_evidence_mismatch_falls_back_without_repair() -> None:
    payload = json.loads(_member_profile_json())
    payload["fieldEvidence"][0]["sourceText"] = "not in conversation"
    client = MemberProfileClient(json.dumps(payload, ensure_ascii=False))

    result = await StrictTripUnderstandingGateway(client).understand(_member_request())

    assert result.decision == "FIXED_QUESTIONS"
    assert result.failure_code == "LLM_CONTENT_INVALID"
    assert result.call_count == client.call_count == 1


@pytest.mark.asyncio
async def test_retryable_member_transport_failure_is_not_retried() -> None:
    client = MemberProfileClient(
        TripUnderstandingTransportError("LLM_TIMEOUT", retryable=True)
    )

    result = await StrictTripUnderstandingGateway(client).understand(_member_request())

    assert result.decision == "FIXED_QUESTIONS"
    assert result.failure_code == "LLM_TIMEOUT"
    assert result.call_count == client.call_count == 1


@pytest.mark.asyncio
async def test_unconfigured_understanding_gateway_returns_zero_call_fallback() -> None:
    result = await UnavailableTripUnderstandingGateway().understand(_request())

    assert result.decision == "FIXED_QUESTIONS"
    assert result.failure_code == "LLM_NOT_CONFIGURED"
    assert result.call_count == 0
    assert result.model is None
