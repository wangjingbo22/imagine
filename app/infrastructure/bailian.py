from __future__ import annotations

from datetime import date
import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.domain.trip_draft import LlmTripDraftFields, TripDraftExtractionError


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
