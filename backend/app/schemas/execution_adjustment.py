from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BeforeValidator, ConfigDict, Field, UUID4, model_validator

from .constraint import Constraint
from .trip import ContractModel


class ExecutionAdjustmentType(str, Enum):
    LATE = "LATE"
    FATIGUE = "FATIGUE"


class FatigueLevel(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class ClarificationQuestionKey(str, Enum):
    EVENT_TYPE_REQUIRED = "EVENT_TYPE_REQUIRED"
    LATE_MINUTES_REQUIRED = "LATE_MINUTES_REQUIRED"
    FATIGUE_LEVEL_REQUIRED = "FATIGUE_LEVEL_REQUIRED"


def _execution_type(value: object) -> object:
    return ExecutionAdjustmentType(value) if isinstance(value, str) else value


def _fatigue_level(value: object) -> object:
    return FatigueLevel(value) if isinstance(value, str) else value


def _question_key(value: object) -> object:
    return ClarificationQuestionKey(value) if isinstance(value, str) else value


ExecutionAdjustmentValue = Annotated[
    ExecutionAdjustmentType,
    BeforeValidator(_execution_type),
]
FatigueLevelValue = Annotated[FatigueLevel, BeforeValidator(_fatigue_level)]
ClarificationQuestionKeyValue = Annotated[
    ClarificationQuestionKey,
    BeforeValidator(_question_key),
]


class CurrentTaskContext(ContractModel):
    task_id: Annotated[str, Field(min_length=1, max_length=64)]
    title: Annotated[str, Field(min_length=1, max_length=120)]


class ExecutionEventParseRequest(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    raw_text: Annotated[str, Field(min_length=1, max_length=500)]
    task_id: Annotated[str, Field(min_length=1, max_length=64)]
    current_task: CurrentTaskContext

    @model_validator(mode="after")
    def current_task_must_match(self) -> "ExecutionEventParseRequest":
        if self.current_task.task_id != self.task_id:
            raise ValueError("currentTask.taskId must equal taskId")
        return self


class LlmExecutionEventFields(ContractModel):
    """Untrusted model output before deterministic policy validation."""

    event_type: ExecutionAdjustmentValue | None
    task_id: Annotated[str, Field(min_length=1, max_length=64)]
    late_minutes: Annotated[int | None, Field(ge=1, le=240)]
    fatigue_level: FatigueLevelValue | None


class ClarificationQuestion(ContractModel):
    question_key: ClarificationQuestionKeyValue
    prompt: Annotated[str, Field(min_length=1, max_length=120)]
    options: list[Annotated[str, Field(min_length=1, max_length=40)]]


class ExecutionEventDraft(ContractModel):
    """A zero-write draft. Only a user-confirmed copy may enter T020."""

    schema_version: Literal["1.0"] = "1.0"
    event_type: ExecutionAdjustmentValue | None
    task_id: Annotated[str, Field(min_length=1, max_length=64)]
    late_minutes: Annotated[int | None, Field(ge=1, le=240)]
    fatigue_level: FatigueLevelValue | None
    clarification_questions: list[ClarificationQuestion]

    @model_validator(mode="after")
    def validate_draft_shape(self) -> "ExecutionEventDraft":
        keys = [question.question_key for question in self.clarification_questions]
        if len(keys) != len(set(keys)):
            raise ValueError("clarificationQuestions must not repeat questionKey")

        if self.event_type is None:
            if self.late_minutes is not None or self.fatigue_level is not None:
                raise ValueError("unknown eventType cannot carry event values")
            if keys != [ClarificationQuestionKey.EVENT_TYPE_REQUIRED]:
                raise ValueError("unknown eventType requires EVENT_TYPE_REQUIRED")
            return self

        if self.event_type is ExecutionAdjustmentType.LATE:
            if self.fatigue_level is not None:
                raise ValueError("LATE cannot carry fatigueLevel")
            expected = (
                []
                if self.late_minutes is not None
                else [ClarificationQuestionKey.LATE_MINUTES_REQUIRED]
            )
            if keys != expected:
                raise ValueError("LATE clarification state is inconsistent")
            return self

        if self.late_minutes is not None:
            raise ValueError("FATIGUE cannot carry lateMinutes")
        expected = (
            []
            if self.fatigue_level is not None
            else [ClarificationQuestionKey.FATIGUE_LEVEL_REQUIRED]
        )
        if keys != expected:
            raise ValueError("FATIGUE clarification state is inconsistent")
        return self


class ConfirmedExecutionAdjustment(ContractModel):
    """The explicit user-confirmed input accepted by deterministic T020."""

    schema_version: Literal["1.0"] = "1.0"
    confirmation_status: Literal["CONFIRMED"] = "CONFIRMED"
    event_type: ExecutionAdjustmentValue
    task_id: Annotated[str, Field(min_length=1, max_length=64)]
    late_minutes: Annotated[int | None, Field(ge=1, le=240)]
    fatigue_level: FatigueLevelValue | None

    @model_validator(mode="after")
    def validate_confirmed_shape(self) -> "ConfirmedExecutionAdjustment":
        if self.event_type is ExecutionAdjustmentType.LATE:
            if self.late_minutes is None or self.fatigue_level is not None:
                raise ValueError("confirmed LATE requires only lateMinutes")
        elif self.fatigue_level is None or self.late_minutes is not None:
            raise ValueError("confirmed FATIGUE requires only fatigueLevel")
        return self


class CreateConfirmedExecutionAdjustmentEvent(ConfirmedExecutionAdjustment):
    """One user-confirmed adjustment ready for idempotent persistence."""

    # This DTO is accepted directly from JSON.  The shared ContractModel is
    # strict for internal contracts, so opt this HTTP input into normal JSON
    # coercion just like CreateExecutionEvent does (UUID/datetime arrive as
    # strings on the wire).
    model_config = ConfigDict(
        alias_generator=ContractModel.model_config["alias_generator"],
        populate_by_name=True,
        extra="forbid",
        strict=False,
        str_strip_whitespace=True,
        loc_by_alias=True,
    )

    plan_version_id: UUID4
    idempotency_key: Annotated[str, Field(min_length=1, max_length=160)]
    occurred_at: datetime

    @model_validator(mode="after")
    def occurred_at_must_be_aware(self) -> "CreateConfirmedExecutionAdjustmentEvent":
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurredAt must include a timezone")
        return self


class ConfirmedExecutionAdjustmentEvent(CreateConfirmedExecutionAdjustmentEvent):
    """Server-issued LATE/FATIGUE event created only after confirmation."""

    event_id: UUID4
    trip_id: UUID4


class RemainingConstraintContext(ContractModel):
    remaining_time_minutes: Annotated[int | None, Field(ge=0)] = None
    remaining_walk_budget_meters: Annotated[int | None, Field(ge=0)] = None
    max_segment_walk_meters: Annotated[int | None, Field(ge=1)] = None
    rest_interval_minutes: Annotated[int | None, Field(ge=1)] = None


class ExecutionConstraintCompileRequest(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    event: ConfirmedExecutionAdjustment
    current_constraints: RemainingConstraintContext

    @model_validator(mode="after")
    def require_only_relevant_baselines(self) -> "ExecutionConstraintCompileRequest":
        current = self.current_constraints
        if self.event.event_type is ExecutionAdjustmentType.LATE:
            if current.remaining_time_minutes is None:
                raise ValueError("LATE requires remainingTimeMinutes")
            if any(
                value is not None
                for value in (
                    current.remaining_walk_budget_meters,
                    current.max_segment_walk_meters,
                    current.rest_interval_minutes,
                )
            ):
                raise ValueError("LATE cannot carry walking or rest baselines")
        else:
            if current.remaining_time_minutes is not None:
                raise ValueError("FATIGUE cannot carry remainingTimeMinutes")
            if any(
                value is None
                for value in (
                    current.remaining_walk_budget_meters,
                    current.max_segment_walk_meters,
                    current.rest_interval_minutes,
                )
            ):
                raise ValueError("FATIGUE requires walking and rest baselines")
        return self


class ExecutionAdjustmentReason(ContractModel):
    reason_code: Annotated[str, Field(min_length=1, max_length=80)]
    message: Annotated[str, Field(min_length=1, max_length=240)]


class EventConstraintSet(ContractModel):
    """Transient constraints for S2-T021; never merged into T007 constraints."""

    schema_version: Literal["1.0"] = "1.0"
    policy_version: Literal["S2-T020-1.0"] = "S2-T020-1.0"
    source_event: ConfirmedExecutionAdjustment
    constraints: tuple[Constraint, ...]
    reasons: tuple[ExecutionAdjustmentReason, ...]
    input_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


__all__ = [
    "ClarificationQuestion",
    "ClarificationQuestionKey",
    "ConfirmedExecutionAdjustment",
    "ConfirmedExecutionAdjustmentEvent",
    "CreateConfirmedExecutionAdjustmentEvent",
    "CurrentTaskContext",
    "EventConstraintSet",
    "ExecutionAdjustmentReason",
    "ExecutionAdjustmentType",
    "ExecutionConstraintCompileRequest",
    "ExecutionEventDraft",
    "ExecutionEventParseRequest",
    "FatigueLevel",
    "LlmExecutionEventFields",
    "RemainingConstraintContext",
]
