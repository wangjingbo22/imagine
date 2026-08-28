from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re
from typing import Protocol

from app.schemas.execution_adjustment import (
    ClarificationQuestion,
    ClarificationQuestionKey,
    ExecutionAdjustmentType,
    ExecutionEventDraft,
    ExecutionEventParseRequest,
    FatigueLevel,
    LlmExecutionEventFields,
)


logger = logging.getLogger(__name__)


class ExecutionEventDraftExtractionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ExecutionEventDraftExtractor(Protocol):
    model: str

    async def extract(
        self,
        *,
        raw_text: str,
        task_id: str,
        task_title: str,
    ) -> LlmExecutionEventFields: ...


@dataclass(frozen=True, slots=True)
class ExecutionEventDraftOutcome:
    draft: ExecutionEventDraft
    recognition_source: str
    recognition_model: str | None = None
    degraded_reason: str | None = None


class ExecutionEventDraftService:
    """Parse a zero-write event draft; this service owns no repository."""

    def __init__(
        self,
        extractor: ExecutionEventDraftExtractor | None = None,
        *,
        deadline_seconds: float = 10.0,
    ) -> None:
        if deadline_seconds <= 0 or deadline_seconds > 10:
            raise ValueError("deadline_seconds must be within (0, 10]")
        self._extractor = extractor
        self._deadline_seconds = deadline_seconds

    async def parse(
        self,
        request: ExecutionEventParseRequest,
    ) -> ExecutionEventDraftOutcome:
        if self._extractor is None:
            return ExecutionEventDraftOutcome(
                draft=_deterministic_draft(request.raw_text, request.task_id),
                recognition_source="DETERMINISTIC_FORM",
            )

        try:
            async with asyncio.timeout(self._deadline_seconds):
                fields = await self._extractor.extract(
                    raw_text=request.raw_text,
                    task_id=request.task_id,
                    task_title=request.current_task.title,
                )
            if fields.task_id != request.task_id or not _fields_are_consistent(fields):
                raise ExecutionEventDraftExtractionError(
                    "BAILIAN_EXECUTION_CONTRACT_MISMATCH"
                )
            return ExecutionEventDraftOutcome(
                draft=_draft_from_fields(fields),
                recognition_source="BAILIAN",
                recognition_model=self._extractor.model,
            )
        except TimeoutError:
            return self._degraded(
                request,
                "BAILIAN_EXECUTION_DEADLINE_EXCEEDED",
            )
        except ExecutionEventDraftExtractionError as error:
            return self._degraded(request, error.code)
        except Exception:
            # asyncio cancellation inherits BaseException and is deliberately
            # not swallowed. Every ordinary adapter/provider failure still
            # degrades to the fixed deterministic confirmation form.
            return self._degraded(request, "BAILIAN_EXECUTION_FAILED")

    @staticmethod
    def _degraded(
        request: ExecutionEventParseRequest,
        code: str,
    ) -> ExecutionEventDraftOutcome:
        # Never log the raw utterance, model response, or credentials.
        logger.warning("执行调整草稿已回退到固定表单: %s", code)
        return ExecutionEventDraftOutcome(
            draft=_deterministic_draft(request.raw_text, request.task_id),
            recognition_source="DEGRADED_FORM",
            degraded_reason=code,
        )


def _fields_are_consistent(fields: LlmExecutionEventFields) -> bool:
    if fields.event_type is None:
        return fields.late_minutes is None and fields.fatigue_level is None
    if fields.event_type is ExecutionAdjustmentType.LATE:
        return fields.fatigue_level is None
    return fields.late_minutes is None


def _draft_from_fields(fields: LlmExecutionEventFields) -> ExecutionEventDraft:
    return _build_draft(
        event_type=fields.event_type,
        task_id=fields.task_id,
        late_minutes=fields.late_minutes,
        fatigue_level=fields.fatigue_level,
    )


def _deterministic_draft(raw_text: str, task_id: str) -> ExecutionEventDraft:
    text = raw_text.strip()
    late_signal = any(word in text for word in ("迟到", "晚了", "来晚", "延误"))
    fatigue_signal = any(
        word in text
        for word in ("走不动", "累了", "有点累", "很累", "太累", "疲劳")
    )
    if late_signal and fatigue_signal:
        return _build_draft(event_type=None, task_id=task_id)
    if late_signal:
        return _build_draft(
            event_type=ExecutionAdjustmentType.LATE,
            task_id=task_id,
            late_minutes=_extract_late_minutes(text),
        )
    if fatigue_signal:
        return _build_draft(
            event_type=ExecutionAdjustmentType.FATIGUE,
            task_id=task_id,
            fatigue_level=_extract_fatigue_level(text),
        )
    return _build_draft(event_type=None, task_id=task_id)


def _build_draft(
    *,
    event_type: ExecutionAdjustmentType | None,
    task_id: str,
    late_minutes: int | None = None,
    fatigue_level: FatigueLevel | None = None,
) -> ExecutionEventDraft:
    questions: list[ClarificationQuestion]
    if event_type is None:
        questions = [
            ClarificationQuestion(
                question_key=ClarificationQuestionKey.EVENT_TYPE_REQUIRED,
                prompt="这次调整是因为迟到，还是因为体力不适？",
                options=["LATE", "FATIGUE"],
            )
        ]
    elif event_type is ExecutionAdjustmentType.LATE and late_minutes is None:
        questions = [
            ClarificationQuestion(
                question_key=ClarificationQuestionKey.LATE_MINUTES_REQUIRED,
                prompt="请确认迟到了多少分钟（1–240）。",
                options=[],
            )
        ]
    elif event_type is ExecutionAdjustmentType.FATIGUE and fatigue_level is None:
        questions = [
            ClarificationQuestion(
                question_key=ClarificationQuestionKey.FATIGUE_LEVEL_REQUIRED,
                prompt="请确认当前疲劳程度。",
                options=["MILD", "MODERATE", "SEVERE"],
            )
        ]
    else:
        questions = []

    return ExecutionEventDraft(
        event_type=event_type,
        task_id=task_id,
        late_minutes=late_minutes,
        fatigue_level=fatigue_level,
        clarification_questions=questions,
    )


def _extract_late_minutes(text: str) -> int | None:
    half_hour = re.search(r"(?:晚了|迟到|延误|来晚)\s*半(?:个)?小时", text)
    if half_hour:
        return 30

    hour = re.search(
        r"(?:晚了|迟到|延误|来晚)\s*([一二两三四])(?:个)?小时",
        text,
    )
    if hour:
        value = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4}[hour.group(1)] * 60
        return value if value <= 240 else None

    arabic = re.search(
        r"(?:晚了|迟到|延误|来晚)\s*(\d{1,3})\s*(?:分钟|分(?:钟)?)",
        text,
    )
    if arabic:
        value = int(arabic.group(1))
        return value if 1 <= value <= 240 else None

    chinese = re.search(
        r"(?:晚了|迟到|延误|来晚)\s*([零〇一二两三四五六七八九十百]+)\s*(?:分钟|分(?:钟)?)",
        text,
    )
    if chinese:
        value = _chinese_integer(chinese.group(1))
        return value if value is not None and 1 <= value <= 240 else None
    return None


def _chinese_integer(value: str) -> int | None:
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
              "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if not value:
        return None
    total = 0
    section = 0
    number = 0
    for character in value:
        if character in digits:
            number = digits[character]
        elif character == "十":
            section += (number or 1) * 10
            number = 0
        elif character == "百":
            section += (number or 1) * 100
            number = 0
        else:
            return None
    total += section + number
    return total


def _extract_fatigue_level(text: str) -> FatigueLevel | None:
    if any(word in text for word in ("走不动", "太累", "非常累", "严重疲劳")):
        return FatigueLevel.SEVERE
    if any(word in text for word in ("很累", "比较累", "中度疲劳")):
        return FatigueLevel.MODERATE
    if any(word in text for word in ("有点累", "稍微累", "轻度疲劳")):
        return FatigueLevel.MILD
    return None


__all__ = [
    "ExecutionEventDraftExtractionError",
    "ExecutionEventDraftExtractor",
    "ExecutionEventDraftOutcome",
    "ExecutionEventDraftService",
]
