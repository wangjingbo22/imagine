from __future__ import annotations

import asyncio
from datetime import date
import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.application.llm_gateway import TripUnderstandingTransportError
from app.domain.trip_draft import (
    LlmTripDraftFields,
    TripDraftExtractionError,
    TripUnderstandingProposal,
    TripUnderstandingRequest,
)


_SYSTEM_PROMPT = """你是行知旅伴的行程字段提取器。只做信息抽取，不生成攻略。
请输出一个 JSON 对象，字段固定为：
cityName, travelDate, startTime, endTime, startLocationText, endLocationText,
budgetCents, interests, mustVisit, avoidPlaces。
规则：
1. 未明确给出的标量填 null，未明确给出的数组填 []，不得猜测或补默认值。
2. travelDate 仅输出 YYYY-MM-DD；模糊日期（例如“周末”“下周”）填 null。
3. startTime/endTime 仅输出 24 小时制 HH:mm；“下午三点”等含明确时段的信息可换算，
   只有“3点”而没有上午/下午语义时填 null。
4. budgetCents 为人民币分的非负整数，例如 350 元输出 35000。
5. cityName 输出常用城市名，不附带省、市后缀；地点名称保留用户原文含义。
6. mustVisit 与 avoidPlaces 不得把同一地点同时放入两个数组。
7. 只输出 JSON，不要 Markdown、解释或额外字段。
8. 输入会按【】分段：cityName、travelDate、startTime、endTime 只能来自
【行程基础】或【用户初始描述】；startLocationText、endLocationText、budgetCents
只能来自【出发地、结束地与共享费用】或【用户初始描述】；interests、mustVisit、avoidPlaces
只能来自【个人偏好】或【最终确认与不可妥协限制】。不要把段落标题、下一段文本或
“偏好/喜欢吃”等文字拼接进地点。没有明确的起点或终点必须填 null。
"""

_TRIP_UNDERSTANDING_SCHEMA = json.dumps(
    TripUnderstandingProposal.model_json_schema(by_alias=True),
    ensure_ascii=False,
    separators=(",", ":"),
)

_TRIP_UNDERSTANDING_SYSTEM_PROMPT = f"""You produce only one JSON object that
validates against the following JSON Schema. Follow it exactly, including all
required nested fields, null values, arrays, camelCase names, and
additionalProperties restrictions.

{_TRIP_UNDERSTANDING_SCHEMA}

Use evidence only from the supplied request. Do not output UUIDs, statuses,
constraints, providers, plans, versions, Markdown, explanations, or JSON
fences. When the request explicitly contains an organizer nickname, personal
budget cap, or a care mode token (ORDINARY, PARENT_CHILD, LOW_STAMINA, or
MOBILITY_ASSISTANCE_BETA), copy it into the first participant's nickname,
budgetCapCents, and careDraft.assistanceTypeHint respectively. A selected care
mode must produce a non-null careDraft with the remaining optional care values
set to null (and walkLimits containing null values).
"""


class BailianTripDraftExtractor:
    """Extract trip candidates through Bailian's OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not 8 <= timeout_seconds <= 45:
            raise ValueError("timeoutSeconds must be between 8 and 45 seconds")
        self.model = model
        self.timeout_seconds = timeout_seconds
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
        text: str,
        reference_date: date,
    ) -> LlmTripDraftFields:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"解析参考日期：{reference_date.isoformat()}。"
                        f"\n用户需求：{text}"
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
            decoded = json.loads(_strip_json_fence(content))
            return LlmTripDraftFields.model_validate(decoded)
        except httpx.TimeoutException as exc:
            raise TripDraftExtractionError("BAILIAN_TIMEOUT") from exc
        except httpx.HTTPStatusError as exc:
            code = (
                "BAILIAN_AUTH_FAILED"
                if exc.response.status_code in {401, 403}
                else "BAILIAN_UNAVAILABLE"
            )
            raise TripDraftExtractionError(code) from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            raise TripDraftExtractionError("BAILIAN_INVALID_RESPONSE") from exc

    async def propose_trip_understanding(
        self,
        request: TripUnderstandingRequest,
    ) -> str:
        return await self._trip_understanding_completion(
            [
                {"role": "system", "content": _TRIP_UNDERSTANDING_SYSTEM_PROMPT},
                {"role": "user", "content": request.model_dump_json(by_alias=True)},
            ]
        )

    async def repair_trip_understanding(
        self,
        request: TripUnderstandingRequest,
        *,
        invalid_response: str,
        validation_errors: str,
    ) -> str:
        repair_prompt = (
            "Your previous JSON did not validate. Return a corrected replacement "
            "only; do not explain it. Validation errors:\n"
            f"{validation_errors}\nPrevious JSON:\n{invalid_response}"
        )
        return await self._trip_understanding_completion(
            [
                {"role": "system", "content": _TRIP_UNDERSTANDING_SYSTEM_PROMPT},
                {"role": "user", "content": request.model_dump_json(by_alias=True)},
                {"role": "user", "content": repair_prompt},
            ]
        )

    async def _trip_understanding_completion(
        self,
        messages: list[dict[str, str]],
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        try:
            async with asyncio.timeout(self.timeout_seconds):
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
            return content
        except (TimeoutError, httpx.TimeoutException) as error:
            raise TripUnderstandingTransportError(
                "LLM_TIMEOUT", retryable=True
            ) from error
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in {401, 403}:
                code, retryable = "LLM_AUTH_FAILED", False
            else:
                code = "LLM_UNAVAILABLE"
                retryable = status == 429 or status >= 500
            raise TripUnderstandingTransportError(
                code,
                retryable=retryable,
            ) from error
        except httpx.TransportError as error:
            raise TripUnderstandingTransportError(
                "LLM_UNAVAILABLE", retryable=True
            ) from error
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise TripUnderstandingTransportError(
                "LLM_INVALID_RESPONSE", retryable=False
            ) from error


def _strip_json_fence(content: str) -> str:
    value = content.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


__all__ = ["BailianTripDraftExtractor"]
