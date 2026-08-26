from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from app.application.execution_event_draft_service import (
    ExecutionEventDraftExtractionError,
)
from app.schemas.execution_adjustment import LlmExecutionEventFields


_SYSTEM_PROMPT = """你是行知旅伴的执行异常字段提取器，只做字段抽取。
仅输出严格 JSON 对象，字段必须且只能是：
eventType, taskId, lateMinutes, fatigueLevel。
规则：
1. eventType 只能是 LATE、FATIGUE 或 null。
2. LATE 时 lateMinutes 为 1..240 的整数；不明确填 null；fatigueLevel 必须为 null。
3. FATIGUE 时 fatigueLevel 只能是 MILD、MODERATE、SEVERE；不明确填 null；lateMinutes 必须为 null。
4. 无法判断或同时提到两类事件时 eventType 填 null，其余值均填 null。
5. taskId 必须原样回显。不得输出 Constraint、Profile、PlanVersion、状态或解释。
6. 不要 Markdown 代码块，不要补字段，不要猜测不明确的数值或等级。
"""


class BailianExecutionEventExtractor:
    """Strict one-shot Bailian adapter for the S2-T019 zero-write draft."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def close(self) -> None:
        await self._client.aclose()

    async def extract(
        self,
        *,
        raw_text: str,
        task_id: str,
        task_title: str,
    ) -> LlmExecutionEventFields:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"当前任务 taskId={task_id}，标题={task_title}。\n"
                        f"用户原话：{raw_text}"
                    ),
                },
            ],
        }
        try:
            response = await self._client.post(
                "/chat/completions",
                headers=self._headers,
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message content is not text")
            # Deliberately no fence stripping or JSON repair: fail closed.
            return LlmExecutionEventFields.model_validate_json(
                content,
                strict=True,
            )
        except httpx.TimeoutException as exc:
            raise ExecutionEventDraftExtractionError(
                "BAILIAN_EXECUTION_TIMEOUT"
            ) from exc
        except httpx.HTTPStatusError as exc:
            code = (
                "BAILIAN_EXECUTION_AUTH_FAILED"
                if exc.response.status_code in {401, 403}
                else "BAILIAN_EXECUTION_UNAVAILABLE"
            )
            raise ExecutionEventDraftExtractionError(code) from exc
        except (
            httpx.HTTPError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            raise ExecutionEventDraftExtractionError(
                "BAILIAN_EXECUTION_INVALID_RESPONSE"
            ) from exc


__all__ = ["BailianExecutionEventExtractor"]
