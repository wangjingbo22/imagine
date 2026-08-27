from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, alias_generators, model_validator

from app.domain.trip_draft import ParsedTripFields, TripDraftParseResult


QUESTION_IDS = (
    "trip", "party", "endpoints_budget", "preferences", "assistance", "confirm",
)


class CollaborationModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class CollaborationStatus(StrEnum):
    DRAFT_CONVERSATION = "DRAFT_CONVERSATION"
    INVITING = "INVITING"
    COLLECTING_MEMBERS = "COLLECTING_MEMBERS"
    CONFLICT_REVIEW = "CONFLICT_REVIEW"
    READY_TO_PLAN = "READY_TO_PLAN"


class ParticipantConfirmationStatus(StrEnum):
    INVITED = "INVITED"
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ConversationAnswer(CollaborationModel):
    question_id: str = Field(min_length=1, max_length=40)
    answer: str = Field(min_length=1, max_length=1000)


class ConversationSubmission(CollaborationModel):
    natural_language_request: str = Field(min_length=1, max_length=1000)
    answers: list[ConversationAnswer] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def require_fixed_question_order(self) -> "ConversationSubmission":
        if tuple(item.question_id for item in self.answers) != QUESTION_IDS:
            raise ValueError("answers must contain the six fixed questions in order")
        return self

    @property
    def transcript(self) -> str:
        headings = (
            "行程基础（目标、城市、日期、可用时间）",
            "同行信息（人数、组织者）",
            "出发地、结束地与共享费用",
            "个人偏好（兴趣与地点限制）",
            "个人限制（预算、步行、换乘、休息、关怀）",
            "最终确认与不可妥协限制",
        )
        sections = [
            f"【{heading}】\n{answer.answer}"
            for heading, answer in zip(headings, self.answers, strict=True)
        ]
        return "\n\n".join((f"【用户初始描述】\n{self.natural_language_request}", *sections))

    @property
    def participant_count(self) -> int:
        text = self.answers[1].answer
        for value in ("3", "三", "2", "二", "两", "1", "一"):
            if value in text:
                return {"3": 3, "三": 3, "2": 2, "二": 2, "两": 2, "1": 1, "一": 1}[value]
        return 1


class CollaborationParticipant(CollaborationModel):
    participant_id: UUID
    display_name: str | None = Field(default=None, max_length=40)
    status: ParticipantConfirmationStatus
    is_organizer: bool
    parsed: ParsedTripFields | None = None


class CollaborationConflict(CollaborationModel):
    conflict_id: str
    participant_ids: list[UUID]
    rule_id: str
    message: str
    suggestion: str
    allowed_relaxations: list[str] = Field(default_factory=list)


class CollaborationState(CollaborationModel):
    trip_id: UUID
    organizer_participant_id: UUID
    status: CollaborationStatus
    expected_participants: int = Field(ge=1, le=3)
    participants: list[CollaborationParticipant]
    conflicts: list[CollaborationConflict] = Field(default_factory=list)


class OrganizerConversationResult(CollaborationModel):
    state: CollaborationState | None
    parse: TripDraftParseResult
    # This is an opaque capability for the browser session that created the
    # collaboration.  The database only keeps its digest.
    organizer_access_token: str | None = None


class MemberConversationResult(CollaborationModel):
    state: CollaborationState
    parse: TripDraftParseResult


class InvitationCreated(CollaborationModel):
    participant_id: UUID
    invitation_url: str
    expires_at: datetime


class InvitationConversation(CollaborationModel):
    trip_id: UUID
    participant_id: UUID
    expires_at: datetime
    status: ParticipantConfirmationStatus
    shared_trip: ParsedTripFields


class ConflictResolution(CollaborationModel):
    relaxation: str = Field(min_length=1, max_length=80)


__all__ = [
    "CollaborationConflict", "CollaborationParticipant", "CollaborationState",
    "CollaborationStatus", "ConversationSubmission", "InvitationConversation",
    "InvitationCreated", "OrganizerConversationResult", "ParticipantConfirmationStatus",
    "ConflictResolution", "MemberConversationResult", "QUESTION_IDS",
]
