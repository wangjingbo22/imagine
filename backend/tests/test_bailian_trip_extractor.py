from __future__ import annotations

from datetime import date
import json

import httpx
import pytest

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
