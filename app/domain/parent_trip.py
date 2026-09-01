from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, UUID4, model_validator

from app.domain.collaboration import CollaborationModel


class ParentTripCreateRequest(CollaborationModel):
    schema_version: Literal["1.0"]
    parent_trip_id: UUID4
    title: str = Field(min_length=1, max_length=80)
    city_name: str = Field(min_length=1, max_length=80)
    start_date: date
    day_budget_cents: list[Annotated[int, Field(ge=0, le=100_000_000)]] = Field(
        min_length=2, max_length=3
    )


class ParentTripDay(CollaborationModel):
    day_index: int = Field(ge=0, le=2)
    date: date
    budget_cents: int = Field(ge=0)
    child_trip_id: UUID4 | None = None
    child_budget_cents: int | None = Field(default=None, ge=0)
    planned_cost_cents: int | None = Field(default=None, ge=0)
    actual_spent_cents: int | None = Field(default=None, ge=0)
    remaining_budget_cents: int | None = None
    child_status: str = "NOT_CREATED"
    cost_status: Literal["NOT_AVAILABLE", "PLANNED", "ACTUAL_RECORDED"] = "NOT_AVAILABLE"


class ParentTripPlaceMemoryItem(CollaborationModel):
    day_index: int = Field(ge=0, le=2)
    date: date
    child_trip_id: UUID4
    plan_id: UUID4
    plan_status: Literal["PROPOSED", "CURRENT"]
    place_id: str = Field(min_length=1, max_length=160)
    place_name: str = Field(min_length=1, max_length=120)


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
    days: list[ParentTripDay] = Field(min_length=2, max_length=3)
    place_memory: list[ParentTripPlaceMemoryItem] = Field(
        default_factory=list,
        max_length=9,
    )


class ParentTripDayLinkRequest(CollaborationModel):
    schema_version: Literal["1.0"]
    child_trip_id: UUID4


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
    visible_profiles: list[ParentTripMemberProfile] = Field(min_length=1, max_length=3)
    poll_after_seconds: Literal[5] = 5
    changed_at: datetime


__all__ = [
    "ParentTrip",
    "ParentTripCreateRequest",
    "ParentTripDay",
    "ParentTripDayLinkRequest",
    "ParentTripInvitationCreateRequest",
    "ParentTripInvitationCreated",
    "ParentTripInvitationRedeemRequest",
    "ParentTripInvitationRedeemed",
    "ParentTripMemberProfile",
    "ParentTripMemberProfileUpdate",
    "ParentTripPlaceMemoryItem",
    "ParentTripSyncView",
]
