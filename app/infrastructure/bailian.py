from __future__ import annotations

import asyncio
from datetime import date
import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.application.llm_gateway import (
    MemberProfileModelProposal,
    OrganizerTripModelProposal,
    TripUnderstandingTransportError,
)
from app.domain.trip_draft import (
    LlmTripDraftFields,
    TripDraftExtractionError,
    TripUnderstandingProposal,
    TripUnderstandingRequest,
)


_SYSTEM_PROMPT = """你是行知旅伴的行程字段提取器。只做信息抽取，不生成攻略。
不要展示思考过程；读取完输入后立即输出最短的合法 JSON。
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

_MEMBER_PROFILE_SCHEMA = json.dumps(
    MemberProfileModelProposal.model_json_schema(by_alias=True),
    ensure_ascii=False,
    separators=(",", ":"),
)

_ORGANIZER_TRIP_SCHEMA = json.dumps(
    OrganizerTripModelProposal.model_json_schema(by_alias=True),
    ensure_ascii=False,
    separators=(",", ":"),
)

_TRIP_UNDERSTANDING_SYSTEM_PROMPT = f"""You produce only one JSON object that
validates against the following JSON Schema. Follow it exactly, including all
required nested fields, null values, arrays, camelCase names, and
additionalProperties restrictions.
Do not generate explanatory reasoning. Return the smallest valid JSON object
immediately after reading the request.

{_TRIP_UNDERSTANDING_SCHEMA}

Use evidence only from the supplied request. Do not output UUIDs, statuses,
constraints, providers, plans, versions, Markdown, explanations, or JSON
fences. When the request explicitly contains an organizer nickname, personal
budget cap, or a care mode token (ORDINARY, PARENT_CHILD, LOW_STAMINA, or
MOBILITY_ASSISTANCE_BETA), copy it into the first participant's nickname,
budgetCapCents, and careDraft.assistanceTypeHint respectively. A selected care
mode must produce a non-null careDraft with the remaining optional care values
set to null (and walkLimits containing null values).

The issue arrays are a closed, internally consistent set:
- Never put a field in missingFields when its proposal value is non-null or its
  referenced list item exists.
- Every missingFields or ambiguities item must have exactly one matching
  confirmationQuestions item with the same fieldPath, memberKey, and
  questionKey. Do not emit any other confirmationQuestions.
- Every non-null scalar and every list item needs exactly one fieldEvidence
  entry, including careDraft.assistanceTypeHint. For a literal care token such
  as ORDINARY, use that exact token as USER_TEXT sourceText.
- An extracted value needs fieldEvidence, not a confirmation question.
- USER_TEXT sourceText must be an exact substring of rawConversation.
"""

_MEMBER_PROFILE_SYSTEM_PROMPT = f"""你是成员个人资料提取器，只返回一个符合以下
JSON Schema 的对象。不要解释、不要输出 Markdown、不要展示思考过程，读取后立即返回
最短的合法 JSON；所有字段都必须出现，字段名使用 camelCase，不得增加字段。

{_MEMBER_PROFILE_SCHEMA}

只读取 rawConversation 中的【用户初始描述】、【个人偏好（兴趣与地点限制）】、
【个人限制（预算、步行、换乘、休息、关怀）】和【最终确认与不可妥协限制】。
其他段落是组织者共享的只读信息，绝对不能提取为成员字段。

提取规则：
- nickname 只有成员明确自称时才填写，否则为 null；不得把组织者或占位名称当成成员昵称。
- budgetCapCents 是个人预算的人民币分整数；“未设置”返回 null。
- interests、mustVisit、avoidPlaces 只保留成员自己的明确表达，空答案返回 []，不要猜测。
- 没有额外关怀限制时，careDraft.assistanceTypeHint 返回 ORDINARY；亲子、低体力、行动辅助
  分别使用 PARENT_CHILD、LOW_STAMINA、MOBILITY_ASSISTANCE_BETA。其余未明确的关怀值为 null，
  walkLimits 的两个字段必须保留；没有任何关怀表述时 careDraft 才返回 null。
- 每个非 null 标量、每个数组元素和 careDraft 中每个非 null 值，都必须有且只有一个
  fieldEvidence。fieldPath 使用精简路径，例如 interests[0]、budgetCapCents、
  careDraft.walkLimits.maxContinuousMeters；sourceText 必须逐字出现在 rawConversation 中。
- null 字段和空数组不要创建证据。数组值去重，避免条件不得同时放入 mustVisit。
"""

_ORGANIZER_TRIP_SYSTEM_PROMPT = f"""你是行程固定问卷提取器，只返回一个符合以下
JSON Schema 的对象。不要解释、不要输出 Markdown、不要展示思考过程，读取后立即返回
最短的合法 JSON；所有字段都必须出现，字段名使用 camelCase，不得增加字段。

{_ORGANIZER_TRIP_SCHEMA}

这是已经填写完整的六问表单，只做信息抽取，不生成攻略，也不要生成缺失项、歧义或追问。
提取规则：
- trip 的城市、日期、起止时间只来自【行程基础】；起点、终点、共享预算只来自
  【出发地、结束地与共享费用】。预算转换为人民币分整数，例如 900 元返回 90000。
- participants 数量严格等于【同行信息】的人数，memberKey 必须按 member-1、member-2、
  member-3 排列。第一位是组织者；尚未填写个人资料的受邀成员保留 null、[] 和 null careDraft，
  不得编造昵称、预算、偏好或关怀需求。
- 组织者昵称来自【同行信息】；组织者个人预算、关怀模式和限制来自【个人限制】。
- interests、mustVisit、avoidPlaces 只来自【个人偏好】、【用户初始描述】和【最终确认】；
  数组值去重，避开地点不得同时出现在 mustVisit。
- 关怀类型使用 ORDINARY、PARENT_CHILD、LOW_STAMINA、MOBILITY_ASSISTANCE_BETA；
  其余未明确的关怀值为 null，walkLimits 的两个字段必须保留。
- 不要输出 fieldEvidence；服务端会从固定问卷原文生成证据并校验。
"""


class BailianTripDraftExtractor:
    """Extract trip candidates through Bailian's OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        organizer_model: str | None = None,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not 8 <= timeout_seconds <= 45:
            raise ValueError("timeoutSeconds must be between 8 and 45 seconds")
        self.model = model
        self.organizer_model = organizer_model or model
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

    async def extract(
        self,
        *,
        text: str,
        reference_date: date,
    ) -> LlmTripDraftFields:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "enable_thinking": False,
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

    async def propose_organizer_trip(
        self,
        request: TripUnderstandingRequest,
    ) -> str:
        compact_request = json.dumps(
            {
                "schemaVersion": "1.0",
                "referenceDate": request.reference_date.isoformat(),
                "rawConversation": request.raw_conversation,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return await self._trip_understanding_completion(
            [
                {"role": "system", "content": _ORGANIZER_TRIP_SYSTEM_PROMPT},
                {"role": "user", "content": compact_request},
            ],
            max_tokens=1400,
            deadline_seconds=30,
            model=self.organizer_model,
        )

    async def propose_member_profile(
        self,
        request: TripUnderstandingRequest,
    ) -> str:
        compact_request = json.dumps(
            {
                "schemaVersion": "1.0",
                "rawConversation": request.raw_conversation,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return await self._trip_understanding_completion(
            [
                {"role": "system", "content": _MEMBER_PROFILE_SYSTEM_PROMPT},
                {"role": "user", "content": compact_request},
            ],
            max_tokens=1600,
            deadline_seconds=20,
        )

    async def _trip_understanding_completion(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        deadline_seconds: float | None = None,
        model: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "temperature": 0,
            "enable_thinking": False,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        effective_deadline = (
            self.timeout_seconds
            if deadline_seconds is None
            else min(self.timeout_seconds, deadline_seconds)
        )
        try:
            async with asyncio.timeout(effective_deadline):
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
