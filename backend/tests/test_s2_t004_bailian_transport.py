from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.application.llm_gateway import StrictTripUnderstandingGateway
from app.core.config import Settings
from app.domain.trip_draft import TripUnderstandingRequest
from app.infrastructure.bailian import BailianTripDraftExtractor


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


def test_trip_understanding_timeout_default_is_forty_five_seconds() -> None:
    settings = Settings(_env_file=None)
    assert settings.bailian_request_timeout_seconds == 45.0
    assert settings.bailian_model == "qwen-plus"


@pytest.mark.parametrize("timeout", [7.99, 45.01])
def test_bailian_timeout_rejects_values_outside_eight_to_forty_five(
    timeout: float,
) -> None:
    with pytest.raises(ValueError):
        Settings(bailian_request_timeout_seconds=timeout)
    with pytest.raises(ValueError):
        BailianTripDraftExtractor(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="qwen-fixture",
            timeout_seconds=timeout,
        )


@pytest.mark.asyncio
async def test_understanding_request_uses_existing_openai_compatible_client() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": _proposal_json()}}]},
        )

    extractor = BailianTripDraftExtractor(
        api_key="test-api-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-fixture",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    try:
        raw = await extractor.propose_trip_understanding(_request())
    finally:
        await extractor.close()

    assert json.loads(raw) == _fixture_payload()
    assert captured["url"] == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert captured["authorization"] == "Bearer test-api-key"
    body = json.loads(captured["body"])
    assert body["model"] == "qwen-fixture"
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert '"schemaVersion"' in body["messages"][0]["content"]
    assert '"additionalProperties":false' in body["messages"][0]["content"]
    assert json.loads(body["messages"][1]["content"]) == _request().model_dump(
        mode="json", by_alias=True
    )
    assert "test-api-key" not in captured["body"]
    assert "Authorization" not in captured["body"]


@pytest.mark.asyncio
async def test_understanding_repair_reuses_schema_and_sends_validation_context() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": _proposal_json()}}]},
        )

    extractor = BailianTripDraftExtractor(
        api_key="test-api-key",
        base_url="https://example.invalid/v1",
        model="qwen-fixture",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    try:
        raw = await extractor.repair_trip_understanding(
            _request(),
            invalid_response="{}",
            validation_errors='[{"loc":["trip"],"msg":"Field required"}]',
        )
    finally:
        await extractor.close()

    assert json.loads(raw) == _fixture_payload()
    body = json.loads(captured["body"])
    assert len(body["messages"]) == 3
    assert '"schemaVersion"' in body["messages"][0]["content"]
    assert "Field required" in body["messages"][2]["content"]
    assert "Previous JSON:\n{}" in body["messages"][2]["content"]


@pytest.mark.asyncio
async def test_read_timeout_is_retryable_and_stops_after_two_attempts() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("fixture timeout", request=request)

    extractor = BailianTripDraftExtractor(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="qwen-fixture",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await StrictTripUnderstandingGateway(extractor).understand(
            _request()
        )
    finally:
        await extractor.close()

    assert result.failure_code == "LLM_TIMEOUT"
    assert result.call_count == calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "failure_code", "expected_calls"),
    [
        (401, "LLM_AUTH_FAILED", 1),
        (403, "LLM_AUTH_FAILED", 1),
        (422, "LLM_UNAVAILABLE", 1),
        (429, "LLM_UNAVAILABLE", 2),
        (500, "LLM_UNAVAILABLE", 2),
    ],
)
async def test_http_statuses_retry_only_when_transient(
    status_code: int,
    failure_code: str,
    expected_calls: int,
) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, json={"providerSecret": "hidden"})

    extractor = BailianTripDraftExtractor(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="qwen-fixture",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await StrictTripUnderstandingGateway(extractor).understand(
            _request()
        )
    finally:
        await extractor.close()

    assert result.failure_code == failure_code
    assert result.call_count == calls == expected_calls


@pytest.mark.asyncio
async def test_provider_envelope_error_is_not_retryable_or_leaked(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider_secret = "distinctive-provider-secret-should-not-leak"
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"providerSecret": provider_secret})

    extractor = BailianTripDraftExtractor(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="qwen-fixture",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await StrictTripUnderstandingGateway(extractor).understand(
            _request()
        )
    finally:
        await extractor.close()

    assert result.failure_code == "LLM_INVALID_RESPONSE"
    assert result.call_count == calls == 1
    assert provider_secret not in caplog.text
    assert provider_secret not in result.model_dump_json()
