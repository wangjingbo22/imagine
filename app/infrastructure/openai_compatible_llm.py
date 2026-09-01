from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.application.llm_gateway import CandidateSelectionTransportError
from app.schemas.llm import ProviderCandidateSelectionRequest


_CANDIDATE_SELECTION_SYSTEM_PROMPT = """你是行知旅伴的候选地点提议器，不是规划器。
只返回一个 JSON 对象，字段固定为：
schemaVersion, selectedPlaceFactIds, selectionRationale, riskNotes。
规则：
1. selectedPlaceFactIds 只能从 candidateFacts.placeFactId 中选择 2—3 个，保持游览顺序且不得重复。
2. selectionRationale 不超过 240 个中文字符，只能引用输入中的已知标签与属性。
3. riskNotes 只能描述 riskFlags 中未知、未确认或待核实的事实；没有风险时返回 []。
4. 禁止输出或猜测价格、坐标、路线、距离、时长、满意度、评分、Constraint、PASS、planId 或任何版本状态。
5. 不得输出 Markdown、代码块、解释性前后缀或额外字段。
"""


class OpenAiCompatibleCandidateSelectionClient:
    """Short-timeout model client for the S2-T008 proposal boundary."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 10,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not 8 <= timeout_seconds <= 12:
            raise ValueError("candidate selection timeout must be within 8..12 seconds")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            trust_env=False,
        )
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def close(self) -> None:
        await self._client.aclose()

    async def propose_candidate_selection(
        self,
        request: ProviderCandidateSelectionRequest,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _CANDIDATE_SELECTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        _redacted_model_payload(request),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
        }
        try:
            # httpx applies timeouts to individual I/O phases.  The outer
            # deadline makes the complete one-shot model interaction obey the
            # same eight-to-twelve-second budget, including response parsing.
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
        except (httpx.TimeoutException, TimeoutError) as error:
            raise CandidateSelectionTransportError(
                "LLM_TIMEOUT",
                retryable=False,
            ) from error
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in {401, 403}:
                raise CandidateSelectionTransportError(
                    "LLM_AUTH_FAILED",
                    retryable=False,
                ) from error
            raise CandidateSelectionTransportError(
                "LLM_UNAVAILABLE",
                retryable=False,
            ) from error
        except httpx.HTTPError as error:
            raise CandidateSelectionTransportError(
                "LLM_UNAVAILABLE",
                retryable=False,
            ) from error
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise CandidateSelectionTransportError(
                "LLM_SCHEMA_INVALID",
                retryable=False,
            ) from error


def _redacted_model_payload(
    request: ProviderCandidateSelectionRequest,
) -> dict[str, Any]:
    """Remove digests and keep only the allowlisted facts useful to the model."""

    return {
        "schemaVersion": request.schema_version,
        "traceId": str(request.trace_id),
        "confirmedTripSummary": request.confirmed_trip_summary.model_dump(
            mode="json",
            by_alias=True,
        ),
        "candidateFacts": [
            {
                "placeFactId": item.place_fact_id,
                "displayName": item.display_name,
                "categoryTags": list(item.category_tags),
                "knownAttributes": list(item.known_attributes),
                "riskFlags": list(item.risk_flags),
            }
            for item in request.candidate_facts
        ],
        "allowedTaskCount": list(request.allowed_task_count),
    }


__all__ = ["OpenAiCompatibleCandidateSelectionClient"]
