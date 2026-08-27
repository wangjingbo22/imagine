from __future__ import annotations

import asyncio
import json
from time import monotonic
from uuid import UUID

import httpx
from pydantic import ValidationError
import pytest

from app.infrastructure.bailian_replan_explanation import (
    BailianReplanExplanationClient,
    ReplanExplanationError,
)
from app.schemas.plan import (
    PlanDiffCategory,
    PlanDiffChangeType,
    PlanDiffItem,
    PlanMetricsDelta,
    PlanVersionDiff,
)
from app.schemas.replan_explanation import (
    LlmReplanExplanationPayload,
    ReplanDifferenceExplanation,
    ReplanExplanationProjection,
)


def _diff() -> PlanVersionDiff:
    return PlanVersionDiff(
        trip_id=UUID("11111111-1111-4111-8111-111111111111"),
        base_plan_id=UUID("22222222-2222-4222-8222-222222222222"),
        candidate_plan_id=UUID("33333333-3333-4333-8333-333333333333"),
        base_version=1,
        candidate_version=2,
        items=[
            PlanDiffItem(
                category=PlanDiffCategory.TIME,
                change_type=PlanDiffChangeType.CHANGED,
                key="private-task-id-2",
                label="博物馆参观时间",
                before="10:00-11:30",
                after="10:20-11:30",
            ),
            PlanDiffItem(
                category=PlanDiffCategory.COST,
                change_type=PlanDiffChangeType.CHANGED,
                key="metrics.totalCostCents",
                label="总费用",
                before=33_500,
                after=32_000,
            ),
        ],
        metrics_delta=PlanMetricsDelta(
            total_cost_cents=-1_500,
            total_walk_meters=-800,
            transfer_count=0,
        ),
    )


@pytest.mark.asyncio
async def test_client_sends_only_immutable_server_diff_projection() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
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
                                    "summary": (
                                        "参观时间顺延20分钟，总费用减少15元，"
                                        "步行减少800米。"
                                    )
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    client = BailianReplanExplanationClient(
        api_key="test-secret-key",
        base_url="https://example.invalid/v1",
        model="qwen-test",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.explain(_diff())
    finally:
        await client.close()

    assert result == ReplanDifferenceExplanation(
        summary="参观时间顺延20分钟，总费用减少15元，步行减少800米。",
        model="qwen-test",
    )
    assert captured["authorization"] == "Bearer test-secret-key"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["temperature"] == 0
    user_projection = json.loads(payload["messages"][1]["content"])
    assert set(user_projection) == {"changes", "metricsDelta"}
    assert set(user_projection["changes"][0]) == {
        "category",
        "changeType",
        "label",
        "before",
        "after",
    }
    assert user_projection["metricsDelta"] == {
        "costCents": -1_500,
        "walkMeters": -800,
        "transferCount": 0,
    }
    serialized = json.dumps(user_projection, ensure_ascii=False)
    for forbidden in (
        "tripId",
        "basePlanId",
        "candidatePlanId",
        "private-task-id-2",
        "CURRENT",
        "test-secret-key",
    ):
        assert forbidden not in serialized


def test_projection_and_output_contracts_are_strict_and_immutable() -> None:
    projection = ReplanExplanationProjection.from_plan_version_diff(_diff())

    with pytest.raises(ValidationError, match="frozen"):
        projection.metrics_delta = projection.metrics_delta

    model_schema = LlmReplanExplanationPayload.model_json_schema(by_alias=True)
    result_schema = ReplanDifferenceExplanation.model_json_schema(by_alias=True)
    assert model_schema["additionalProperties"] is False
    assert set(model_schema["properties"]) == {"summary"}
    assert result_schema["additionalProperties"] is False
    assert set(result_schema["properties"]) == {"summary", "model"}

    with pytest.raises(ValidationError):
        ReplanExplanationProjection.model_validate(
            {
                **projection.model_dump(by_alias=True),
                "planId": "forged-plan",
            },
            strict=True,
        )


@pytest.mark.asyncio
async def test_projection_failure_is_a_sanitized_non_retryable_error() -> None:
    diff = _diff()
    oversized = diff.model_copy(
        update={
            "items": [
                diff.items[0].model_copy(update={"label": "敏" * 121}),
            ]
        }
    )
    client = BailianReplanExplanationClient(
        api_key="test-secret-key",
        base_url="https://example.invalid/v1",
        model="qwen-test",
    )
    try:
        with pytest.raises(ReplanExplanationError) as caught:
            await client.explain(oversized)
    finally:
        await client.close()

    assert caught.value.code == "BAILIAN_REPLAN_EXPLANATION_INVALID_INPUT"
    assert caught.value.retryable is False
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '```json\n{"summary":"有变化"}\n```',
        '{"summary":"有变化","taskId":"forged-task"}',
        '{"summary":"有变化","amountCents":1}',
        '{"summary":"有变化","status":"CURRENT"}',
        '{"summary":"第一段\\n第二段"}',
        json.dumps({"summary": "过" * 241}, ensure_ascii=False),
    ],
)
async def test_non_json_extra_or_unsafe_shape_fails_closed(content: str) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    client = BailianReplanExplanationClient(
        api_key="test-secret-key",
        base_url="https://example.invalid/v1",
        model="qwen-test",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ReplanExplanationError) as caught:
            await client.explain(_diff())
    finally:
        await client.close()

    assert calls == 1
    assert caught.value.code == "BAILIAN_REPLAN_EXPLANATION_INVALID_RESPONSE"
    assert caught.value.retryable is False
    assert str(caught.value) == caught.value.code
    assert caught.value.__cause__ is None
    assert "test-secret-key" not in str(caught.value)
    assert "只解释服务端" not in str(caught.value)


@pytest.mark.asyncio
async def test_timeout_is_sanitized_and_never_retried() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("provider leaked prompt", request=request)

    client = BailianReplanExplanationClient(
        api_key="test-secret-key",
        base_url="https://example.invalid/v1",
        model="qwen-test",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ReplanExplanationError) as caught:
            await client.explain(_diff())
    finally:
        await client.close()

    assert calls == 1
    assert caught.value.code == "BAILIAN_REPLAN_EXPLANATION_TIMEOUT"
    assert caught.value.retryable is True
    assert str(caught.value) == caught.value.code
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_hard_deadline_cancels_a_slow_custom_transport() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        raise AssertionError("the end-to-end deadline must cancel this handler")

    client = BailianReplanExplanationClient(
        api_key="test-secret-key",
        base_url="https://example.invalid/v1",
        model="qwen-test",
        timeout_seconds=0.01,
        transport=httpx.MockTransport(handler),
    )
    started = monotonic()
    try:
        with pytest.raises(ReplanExplanationError) as caught:
            await client.explain(_diff())
    finally:
        await client.close()

    assert monotonic() - started < 0.15
    assert caught.value.code == "BAILIAN_REPLAN_EXPLANATION_TIMEOUT"
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "code", "retryable"),
    [
        (401, "BAILIAN_REPLAN_EXPLANATION_AUTH_FAILED", False),
        (403, "BAILIAN_REPLAN_EXPLANATION_AUTH_FAILED", False),
        (429, "BAILIAN_REPLAN_EXPLANATION_UNAVAILABLE", True),
        (500, "BAILIAN_REPLAN_EXPLANATION_UNAVAILABLE", True),
        (422, "BAILIAN_REPLAN_EXPLANATION_UNAVAILABLE", False),
    ],
)
async def test_http_failures_map_to_clear_sanitized_errors(
    status_code: int,
    code: str,
    retryable: bool,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"providerSecret": "must-not-escape"},
        )

    client = BailianReplanExplanationClient(
        api_key="test-secret-key",
        base_url="https://example.invalid/v1",
        model="qwen-test",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ReplanExplanationError) as caught:
            await client.explain(_diff())
    finally:
        await client.close()

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert "must-not-escape" not in str(caught.value)
    assert "test-secret-key" not in str(caught.value)


@pytest.mark.parametrize("timeout", [0, -1, 10.01])
def test_timeout_configuration_cannot_exceed_ten_seconds(timeout: float) -> None:
    with pytest.raises(ValueError, match="0..10"):
        BailianReplanExplanationClient(
            api_key="test-secret-key",
            base_url="https://example.invalid/v1",
            model="qwen-test",
            timeout_seconds=timeout,
        )
