from __future__ import annotations

from datetime import date
import json

import httpx
import pytest

from app.domain.trip_draft import TripUnderstandingRequest
from app.infrastructure.bailian import BailianTripDraftExtractor


@pytest.mark.asyncio
async def test_bailian_extractor_uses_openai_compatible_json_contract() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "cityName": "武汉",
                                    "travelDate": "2026-09-03",
                                    "startTime": "09:30",
                                    "endTime": "19:00",
                                    "startLocationText": "武汉站",
                                    "endLocationText": "汉口站",
                                    "budgetCents": 50000,
                                    "interests": ["建筑"],
                                    "mustVisit": ["黄鹤楼"],
                                    "avoidPlaces": ["拥挤商场"],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    extractor = BailianTripDraftExtractor(
        api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-plus",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await extractor.extract(
            text="9月3日从武汉站出发去黄鹤楼",
            reference_date=date(2026, 8, 26),
        )
    finally:
        await extractor.close()

    assert captured["url"] == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert captured["authorization"] == "Bearer test-key"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "qwen3.7-plus"
    assert payload["enable_thinking"] is False
    assert payload["response_format"] == {"type": "json_object"}
    assert result.city_name == "武汉"
    assert result.start_location_text == "武汉站"
    assert result.budget_cents == 50_000


@pytest.mark.asyncio
async def test_bailian_extractor_accepts_json_code_fence() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "```json\n{\"cityName\": \"西安\"}\n```"
                        }
                    }
                ]
            },
        )

    extractor = BailianTripDraftExtractor(
        api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-plus",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await extractor.extract(
            text="去西安",
            reference_date=date(2026, 8, 26),
        )
    finally:
        await extractor.close()

    assert result.city_name == "西安"


@pytest.mark.asyncio
async def test_member_profile_uses_compact_prompt_and_request() -> None:
    captured: dict[str, object] = {}
    compact_response = '{"schemaVersion":"1.0"}'

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": compact_response}}]},
        )

    extractor = BailianTripDraftExtractor(
        api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    request = TripUnderstandingRequest.model_validate(
        {
            "schemaVersion": "1.0",
            "scope": "MEMBER_PROFILE",
            "referenceDate": date(2026, 8, 26),
            "rawConversation": "【个人偏好（兴趣与地点限制）】\n兴趣：博物馆",
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
        }
    )
    try:
        result = await extractor.propose_member_profile(request)
    finally:
        await extractor.close()

    assert result == compact_response
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "qwen-plus"
    assert payload["enable_thinking"] is False
    assert payload["max_tokens"] == 1600
    messages = payload["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert "budgetCapCents" in system_prompt
    assert "confirmationQuestions" not in system_prompt
    compact_request = json.loads(messages[1]["content"])
    assert compact_request == {
        "schemaVersion": "1.0",
        "rawConversation": request.raw_conversation,
    }


@pytest.mark.asyncio
async def test_organizer_trip_uses_compact_prompt_and_request() -> None:
    captured: dict[str, object] = {}
    compact_response = '{"schemaVersion":"1.0"}'

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": compact_response}}]},
        )

    extractor = BailianTripDraftExtractor(
        api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        organizer_model="qwen-turbo",
        timeout_seconds=45,
        transport=httpx.MockTransport(handler),
    )
    request = TripUnderstandingRequest.model_validate(
        {
            "schemaVersion": "1.0",
            "scope": "FULL_TRIP",
            "referenceDate": date(2026, 8, 26),
            "rawConversation": "【行程基础（目标、城市、日期、可用时间）】\n目的城市：北京",
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
        }
    )
    try:
        result = await extractor.propose_organizer_trip(request)
    finally:
        await extractor.close()

    assert result == compact_response
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "qwen-turbo"
    assert payload["enable_thinking"] is False
    assert payload["max_tokens"] == 1400
    messages = payload["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert "participants" in system_prompt
    assert "confirmationQuestions" not in system_prompt
    compact_request = json.loads(messages[1]["content"])
    assert compact_request == {
        "schemaVersion": "1.0",
        "referenceDate": "2026-08-26",
        "rawConversation": request.raw_conversation,
    }
