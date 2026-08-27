from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, alias_generators, model_validator
from typing_extensions import TypeAliasType

from app.domain.trip_draft import (
    CanonicalFieldPath,
    ParticipantUnderstanding,
    TripUnderstandingTrip,
    TripDraftRevision,
)


QUESTION_IDS = (
    "trip", "party", "endpoints_budget", "preferences", "assistance", "confirm",
)

JsonValue = TypeAliasType(
    "JsonValue",
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"],
)


class CollaborationModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class CollaborationStatus(StrEnum):
    MIGRATION_REQUIRED = "MIGRATION_REQUIRED"
    DRAFT_CONVERSATION = "DRAFT_CONVERSATION"
    INVITING = "INVITING"
    COLLECTING_MEMBERS = "COLLECTING_MEMBERS"
    CONFLICT_REVIEW = "CONFLICT_REVIEW"
    READY_TO_PLAN = "READY_TO_PLAN"


class ParticipantAccessStatus(StrEnum):
    ORGANIZER_ACTIVE = "ORGANIZER_ACTIVE"
    NOT_INVITED = "NOT_INVITED"
    INVITED = "INVITED"
    SESSION_ACTIVE = "SESSION_ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class TripFlowKind(StrEnum):
    LEGACY_SINGLE = "LEGACY_SINGLE"
    COLLABORATION_V2 = "COLLABORATION_V2"


class ParticipantConfirmationStatus(StrEnum):
    MIGRATION_REQUIRED = "MIGRATION_REQUIRED"
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    NEEDS_RECONFIRMATION = "NEEDS_RECONFIRMATION"


class IssueCode(StrEnum):
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"
    CONFLICT = "CONFLICT"


class ActorScope(StrEnum):
    ORGANIZER = "ORGANIZER"
    PARTICIPANT = "PARTICIPANT"


class RelaxationAction(StrEnum):
    SELECT_CANDIDATE = "SELECT_CANDIDATE"
    SET_SHARED_FIELD = "SET_SHARED_FIELD"
    SET_MEMBER_FIELD = "SET_MEMBER_FIELD"
    REMOVE_MUST_VISIT = "REMOVE_MUST_VISIT"
    REMOVE_AVOID_PLACE = "REMOVE_AVOID_PLACE"
    RAISE_MEMBER_BUDGET_CAP = "RAISE_MEMBER_BUDGET_CAP"
    LOWER_SHARED_BUDGET = "LOWER_SHARED_BUDGET"
    EXTEND_SHARED_TIME = "EXTEND_SHARED_TIME"
    CHANGE_NAP_WINDOW = "CHANGE_NAP_WINDOW"


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


class OrganizerConversationRequest(ConversationSubmission):
    schema_version: Literal["1.0"]
    reference_date: date


class RelaxationOption(CollaborationModel):
    relaxation_id: str = Field(pattern=r"^rx_[a-f0-9]{16}$")
    action: RelaxationAction
    actor_scope: ActorScope
    participant_id: UUID | None
    field_path: CanonicalFieldPath
    proposed_value: JsonValue
    label: str = Field(min_length=1, max_length=160)


class CollaborationIssue(CollaborationModel):
    item_id: str = Field(pattern=r"^ci_[a-f0-9]{16}$")
    field_path: CanonicalFieldPath
    participant_id: UUID | None
    related_participant_ids: list[UUID]
    rule_id: str = Field(pattern=r"^S2T003\.[A-Z0-9_.]+$")
    code: IssueCode
    reason: str = Field(min_length=1, max_length=240)
    candidates: list[str] = Field(default_factory=list, max_length=5)
    relaxations: list[RelaxationOption] = Field(default_factory=list)


class ParticipantProgress(CollaborationModel):
    participant_id: UUID
    member_key: str = Field(pattern=r"^member-[1-3]$")
    role: Literal["ORGANIZER", "MEMBER"]
    access_status: ParticipantAccessStatus
    confirmation_status: ParticipantConfirmationStatus
    confirmed_revision: int | None = Field(default=None, ge=1)


class CollaborationProgress(CollaborationModel):
    expected_count: int = Field(ge=1, le=3)
    confirmed_count: int = Field(ge=0, le=3)
    open_issue_count: int = Field(ge=0)


class CollaborationAggregate(CollaborationModel):
    schema_version: Literal["1.0"] = "1.0"
    trip_id: UUID
    draft_id: UUID
    current_revision: int = Field(ge=1)
    organizer_participant_id: UUID
    status: CollaborationStatus
    collaboration_version: int = Field(ge=1)
    policy_version: Literal["S2-T003.1"] = "S2-T003.1"
    readiness_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    can_plan: bool
    progress: CollaborationProgress
    participants: list[ParticipantProgress]
    confirmation_items: list[CollaborationIssue]


class InvitationCreateRequest(CollaborationModel):
    schema_version: Literal["1.0"]
    expected_version: int = Field(ge=1)
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class InvitationRedeemRequest(CollaborationModel):
    schema_version: Literal["1.0"]
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")


class InvitationCreated(CollaborationModel):
    invitation_id: UUID
    trip_id: UUID
    participant_id: UUID
    invitation_url: str | None
    expires_at: datetime
    link_available: bool
    collaboration_version: int = Field(ge=1)


class OrganizerBootstrapResult(CollaborationModel):
    trip_id: UUID
    organizer_participant_id: UUID
    organizer_token: str | None
    organizer_token_available: bool
    collaboration_version: int = Field(ge=1)


class OrganizerConversationCreated(CollaborationModel):
    revision: TripDraftRevision
    organizer_access: OrganizerBootstrapResult


class InvitationRedeemed(CollaborationModel):
    session_id: UUID
    participant_session_token: str | None
    trip_id: UUID
    participant_id: UUID
    expires_at: datetime
    session_token_available: bool


class ParticipantMutationRequest(CollaborationModel):
    schema_version: Literal["1.0"]
    base_revision: int = Field(ge=1)
    expected_version: int = Field(ge=1)


class ParticipantConversationRequest(ParticipantMutationRequest):
    natural_language_request: str = Field(min_length=1, max_length=1000)
    answers: list[ConversationAnswer] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def require_fixed_questions(self) -> "ParticipantConversationRequest":
        ConversationSubmission(
            naturalLanguageRequest=self.natural_language_request,
            answers=self.answers,
        )
        return self

    def submission(self) -> ConversationSubmission:
        return ConversationSubmission(
            naturalLanguageRequest=self.natural_language_request,
            answers=self.answers,
        )


class ResolveConfirmationItemRequest(ParticipantMutationRequest):
    relaxation_id: str = Field(pattern=r"^rx_[a-f0-9]{16}$")


class MemberSessionView(CollaborationModel):
    schema_version: Literal["1.0"] = "1.0"
    trip_id: UUID
    participant_id: UUID
    current_revision: int = Field(ge=1)
    shared_trip: TripUnderstandingTrip
    participant: ParticipantUnderstanding
    access_status: ParticipantAccessStatus
    confirmation_status: ParticipantConfirmationStatus
    confirmation_items: list[CollaborationIssue]


COLLABORATION_SCHEMA_MODELS = (
    CollaborationAggregate,
    CollaborationProgress,
    CollaborationIssue,
    ParticipantProgress,
    InvitationCreateRequest,
    InvitationCreated,
    OrganizerBootstrapResult,
    InvitationRedeemRequest,
    InvitationRedeemed,
    ParticipantMutationRequest,
    ParticipantConversationRequest,
    ResolveConfirmationItemRequest,
    MemberSessionView,
)


def published_collaboration_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "S2-T003 Collaboration Contracts",
        "schemaVersion": "1.0",
        "$defs": {
            model.__name__: model.model_json_schema(
                by_alias=True,
                mode="validation",
            )
            for model in COLLABORATION_SCHEMA_MODELS
        },
    }


__all__ = [
    "ActorScope",
    "CollaborationAggregate",
    "CollaborationIssue",
    "CollaborationModel",
    "CollaborationProgress",
    "COLLABORATION_SCHEMA_MODELS",
    "CollaborationStatus",
    "ConversationAnswer",
    "ConversationSubmission",
    "InvitationCreateRequest",
    "InvitationCreated",
    "InvitationRedeemRequest",
    "InvitationRedeemed",
    "IssueCode",
    "JsonValue",
    "MemberSessionView",
    "OrganizerBootstrapResult",
    "OrganizerConversationCreated",
    "OrganizerConversationRequest",
    "ParticipantAccessStatus",
    "ParticipantConfirmationStatus",
    "ParticipantConversationRequest",
    "ParticipantMutationRequest",
    "ParticipantProgress",
    "published_collaboration_schema",
    "QUESTION_IDS",
    "RelaxationAction",
    "RelaxationOption",
    "ResolveConfirmationItemRequest",
    "TripFlowKind",
]
