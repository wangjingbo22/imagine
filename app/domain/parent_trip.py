from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, UUID4, model_validator

from app.domain.collaboration import CollaborationModel


# 这些上限是产品容量边界，不是界面默认值。集中定义可以确保请求模型、
# 返回模型与存储层使用同一约束，避免只放开前端导致服务端校验失败。
MAX_PARENT_TRIP_DAYS = 30
MAX_PARENT_TRIP_PARTICIPANTS = 20


class ParentTripCreateRequest(CollaborationModel):
    schema_version: Literal["1.0"]
    parent_trip_id: UUID4
    title: str = Field(min_length=1, max_length=80)
    city_name: str = Field(min_length=1, max_length=80)
    start_date: date
    day_budget_cents: list[Annotated[int, Field(ge=0, le=100_000_000)]] = Field(
        min_length=2, max_length=MAX_PARENT_TRIP_DAYS
    )


class ParentTripDay(CollaborationModel):
    day_index: int = Field(ge=0, lt=MAX_PARENT_TRIP_DAYS)
    date: date
    budget_cents: int = Field(ge=0)
    child_trip_id: UUID4 | None = None
    child_budget_cents: int | None = Field(default=None, ge=0)
    planned_cost_cents: int | None = Field(default=None, ge=0)
    actual_spent_cents: int | None = Field(default=None, ge=0)
    remaining_budget_cents: int | None = None
    child_status: str = "NOT_CREATED"
    cost_status: Literal["NOT_AVAILABLE", "PLANNED", "ACTUAL_RECORDED"] = "NOT_AVAILABLE"


class ParentTrip(CollaborationModel):
    schema_version: Literal["1.0"] = "1.0"
    parent_trip_id: UUID4
    title: str
    city_name: str
    start_date: date
    end_date: date
    total_budget_cents: int = Field(ge=0)
    planned_cost_cents: int | None = Field(default=None, ge=0)
    actual_spent_cents: int | None = Field(default=None, ge=0)
    days: list[ParentTripDay] = Field(min_length=2, max_length=MAX_PARENT_TRIP_DAYS)


class ParentTripDayLinkRequest(CollaborationModel):
    schema_version: Literal["1.0"]
    child_trip_id: UUID4


class ParentTripDayBudgetUpdate(CollaborationModel):
    """组织者修改某一天预算时的最小写入合约。

    金额继续使用整数分，杜绝人民币小数在浏览器与服务端之间往返时产生精度误差。
    """
    schema_version: Literal["1.0"]
    budget_cents: int = Field(ge=0, le=100_000_000)


class ParentTripInvitationCreateRequest(CollaborationModel):
    schema_version: Literal["1.0"]
    expected_sync_version: int = Field(ge=1)
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class ParentTripInvitationRedeemRequest(CollaborationModel):
    schema_version: Literal["1.0"]
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")


class ParentTripMemberProfileUpdate(CollaborationModel):
    schema_version: Literal["1.0"]
    expected_sync_version: int = Field(ge=1)
    nickname: str = Field(min_length=1, max_length=80)
    interests: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=8
    )
    budget_cap_cents: int | None = Field(default=None, ge=0, le=100_000_000)

    @model_validator(mode="after")
    def require_unique_interests(self) -> "ParentTripMemberProfileUpdate":
        normalized = [item.casefold() for item in self.interests]
        if len(normalized) != len(set(normalized)):
            raise ValueError("interests must not contain duplicates")
        return self


class ParentTripMemberProfile(CollaborationModel):
    participant_id: UUID4
    role: Literal["ORGANIZER", "MEMBER"]
    access_status: Literal["ORGANIZER_ACTIVE", "INVITED", "MEMBER_ACTIVE"]
    nickname: str
    interests: list[str]
    budget_cap_cents: int | None = None
    profile_version: int = Field(ge=1)
    updated_at: datetime


class ParentTripInvitationCreated(CollaborationModel):
    invitation_id: UUID4
    parent_trip_id: UUID4
    participant_id: UUID4
    invitation_url: str | None
    expires_at: datetime
    link_available: bool
    sync_version: int = Field(ge=1)


class ParentTripInvitationRedeemed(CollaborationModel):
    session_id: UUID4
    parent_trip_id: UUID4
    participant_id: UUID4
    member_session_token: str | None
    expires_at: datetime
    session_token_available: bool
    sync_version: int = Field(ge=1)


class ParentTripSyncView(CollaborationModel):
    schema_version: Literal["1.0"] = "1.0"
    parent_trip: ParentTrip
    sync_version: int = Field(ge=1)
    viewer_role: Literal["ORGANIZER", "MEMBER"]
    viewer_participant_id: UUID4
    visible_profiles: list[ParentTripMemberProfile] = Field(
        min_length=1,
        max_length=MAX_PARENT_TRIP_PARTICIPANTS,
    )
    poll_after_seconds: Literal[5] = 5
    changed_at: datetime


__all__ = [
    "ParentTrip",
    "ParentTripCreateRequest",
    "ParentTripDay",
    "ParentTripDayLinkRequest",
    "ParentTripDayBudgetUpdate",
    "ParentTripInvitationCreateRequest",
    "ParentTripInvitationCreated",
    "ParentTripInvitationRedeemRequest",
    "ParentTripInvitationRedeemed",
    "ParentTripMemberProfile",
    "ParentTripMemberProfileUpdate",
    "ParentTripSyncView",
]
