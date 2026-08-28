from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.application.execution_event_draft_service import (
    ExecutionEventDraftService,
)
from app.infrastructure.bailian_execution_event import (
    BailianExecutionEventExtractor,
)
from app.schemas.execution_adjustment import (
    CurrentTaskContext,
    ExecutionEventDraft,
    ExecutionEventParseRequest,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "execution_adjustments"
    / "s2_t019_colloquial_cases.json"
)


def _request(raw_text: str) -> ExecutionEventParseRequest:
    return ExecutionEventParseRequest(
        raw_text=raw_text,
        task_id="task-2",
        current_task=CurrentTaskContext(task_id="task-2", title="参观博物馆"),
    )


@pytest.mark.asyncio
async def test_fixed_colloquial_fixtures_are_stable() -> None:
    service = ExecutionEventDraftService()
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))

    for case in cases:
        outcome = await service.parse(_request(case["rawText"]))
        expected = case["expected"]
        draft = outcome.draft
        assert draft.event_type == expected["eventType"], case["name"]
        assert draft.late_minutes == expected["lateMinutes"], case["name"]
        assert draft.fatigue_level == expected["fatigueLevel"], case["name"]
        actual_key = (
            draft.clarification_questions[0].question_key
            if draft.clarification_questions
            else None
        )
        assert actual_key == expected["questionKey"], case["name"]
        assert outcome.recognition_source == "DETERMINISTIC_FORM"


@pytest.mark.asyncio
async def test_bailian_adapter_accepts_only_strict_exact_json() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        assert "Constraint" in payload["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "eventType": "LATE",
                                    "taskId": "task-2",
                                    "lateMinutes": 20,
                                    "fatigueLevel": None,
                                }
                            )
                        }
                    }
                ]
            },
        )

    extractor = BailianExecutionEventExtractor(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="qwen-test",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    try:
        outcome = await ExecutionEventDraftService(extractor).parse(
            _request("晚了二十分钟")
        )
    finally:
        await extractor.close()

    assert calls == 1
    assert outcome.recognition_source == "BAILIAN"
    assert outcome.recognition_model == "qwen-test"
    assert outcome.draft.late_minutes == 20


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"eventType":"LATE","taskId":"task-2",'
        '"lateMinutes":20,"fatigueLevel":null}\n```',
        '{"eventType":"LATE","taskId":"task-2","lateMinutes":20,'
        '"fatigueLevel":null,"constraint":{"field":"budget"}}',
        '{"eventType":"LATE","taskId":"other-task","lateMinutes":20,'
        '"fatigueLevel":null}',
    ],
)
async def test_invalid_or_tampered_model_output_falls_back_once(
    content: str,
) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    extractor = BailianExecutionEventExtractor(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="qwen-test",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    try:
        outcome = await ExecutionEventDraftService(extractor).parse(
            _request("晚了二十分钟")
        )
    finally:
        await extractor.close()

    assert calls == 1
    assert outcome.recognition_source == "DEGRADED_FORM"
    assert outcome.draft.late_minutes == 20


@pytest.mark.asyncio
async def test_timeout_calls_provider_once_and_returns_fixed_form(caplog) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    extractor = BailianExecutionEventExtractor(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="qwen-test",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    try:
        outcome = await ExecutionEventDraftService(extractor).parse(
            _request("我迟到了")
        )
    finally:
        await extractor.close()

    assert calls == 1
    assert outcome.degraded_reason == "BAILIAN_EXECUTION_TIMEOUT"
    assert outcome.draft.clarification_questions[0].question_key == (
        "LATE_MINUTES_REQUIRED"
    )
    assert "BAILIAN_EXECUTION_TIMEOUT" in caplog.text
    assert "我迟到了" not in caplog.text
    assert "test-key" not in caplog.text


@pytest.mark.asyncio
async def test_end_to_end_deadline_stops_a_slow_streaming_extractor() -> None:
    class SlowExtractor:
        model = "slow-test-model"
        calls = 0

        async def extract(self, **_: str):
            self.calls += 1
            await asyncio.sleep(0.2)
            raise AssertionError("the hard deadline should cancel this call")

    extractor = SlowExtractor()
    started = asyncio.get_running_loop().time()
    outcome = await ExecutionEventDraftService(
        extractor,
        deadline_seconds=0.01,
    ).parse(_request("我迟到了"))
    elapsed = asyncio.get_running_loop().time() - started

    assert extractor.calls == 1
    assert elapsed < 0.15
    assert outcome.degraded_reason == "BAILIAN_EXECUTION_DEADLINE_EXCEEDED"
    assert outcome.draft.clarification_questions[0].question_key == (
        "LATE_MINUTES_REQUIRED"
    )


@pytest.mark.asyncio
async def test_unexpected_non_cancellation_failure_degrades_to_fixed_form() -> None:
    class FailingExtractor:
        model = "failing-test-model"
        calls = 0

        async def extract(self, **_: str):
            self.calls += 1
            raise RuntimeError("unexpected provider failure")

    extractor = FailingExtractor()
    outcome = await ExecutionEventDraftService(extractor).parse(
        _request("我迟到了")
    )

    assert extractor.calls == 1
    assert outcome.recognition_source == "DEGRADED_FORM"
    assert outcome.degraded_reason == "BAILIAN_EXECUTION_FAILED"
    assert outcome.draft.event_type == "LATE"
    assert outcome.draft.clarification_questions[0].question_key == (
        "LATE_MINUTES_REQUIRED"
    )


@pytest.mark.asyncio
async def test_cancellation_is_not_converted_into_a_form_response() -> None:
    class CancelledExtractor:
        model = "cancelled-test-model"

        async def extract(self, **_: str):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await ExecutionEventDraftService(CancelledExtractor()).parse(
            _request("我迟到了")
        )


def test_request_task_mismatch_and_draft_schema_fail_closed() -> None:
    with pytest.raises(ValueError, match="currentTask.taskId"):
        ExecutionEventParseRequest(
            raw_text="晚了20分钟",
            task_id="task-2",
            current_task={"taskId": "task-3", "title": "另一个任务"},
        )

    schema = ExecutionEventDraft.model_json_schema(by_alias=True)
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "schemaVersion",
        "eventType",
        "taskId",
        "lateMinutes",
        "fatigueLevel",
        "clarificationQuestions",
    }

    published = json.loads(
        (Path(__file__).parents[1] / "schemas" / "execution_event_draft.schema.json")
        .read_text(encoding="utf-8")
    )
    assert published == schema


@pytest.mark.parametrize("minutes", [1, 240])
def test_late_minute_boundaries_are_accepted(minutes: int) -> None:
    draft = ExecutionEventDraft.model_validate_json(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "eventType": "LATE",
                "taskId": "task-2",
                "lateMinutes": minutes,
                "fatigueLevel": None,
                "clarificationQuestions": [],
            }
        ),
        strict=True,
    )
    assert draft.late_minutes == minutes


@pytest.mark.parametrize("minutes", [0, 241])
def test_late_minute_out_of_range_is_rejected(minutes: int) -> None:
    with pytest.raises(ValueError):
        ExecutionEventDraft.model_validate_json(
            json.dumps(
                {
                    "schemaVersion": "1.0",
                    "eventType": "LATE",
                    "taskId": "task-2",
                    "lateMinutes": minutes,
                    "fatigueLevel": None,
                    "clarificationQuestions": [],
                }
            ),
            strict=True,
        )
