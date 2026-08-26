from __future__ import annotations

from datetime import date, time
from enum import Enum
import re
from typing import Annotated, Literal
from unicodedata import normalize

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    UUID4,
    ValidationError,
    ValidationInfo,
    alias_generators,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from .validation_error import (
    TripSchemaError,
    ValidationIssue,
    issues_from_pydantic,
)


_SECOND_PRECISION_TIME = re.compile(r"^\d{2}:\d{2}:\d{2}$")


def _validate_second_precision_time(value: object) -> object:
    """Reject fractional-second and timezone-bearing time values."""

    if isinstance(value, str):
        if not _SECOND_PRECISION_TIME.fullmatch(value):
            raise PydanticCustomError(
                "time_format",
                "Time must use HH:mm:ss without fractional seconds or timezone offsets",
            )
        try:
            return time.fromisoformat(value)
        except ValueError as exc:
            raise PydanticCustomError(
                "time_parsing",
                "Input should be a valid time in HH:mm:ss format",
            ) from exc

    if isinstance(value, time):
        if value.microsecond or value.tzinfo is not None:
            raise PydanticCustomError(
                "time_format",
                "Time must use HH:mm:ss without fractional seconds or timezone offsets",
            )
        return value

    return value


SecondPrecisionTime = Annotated[
    time,
    BeforeValidator(_validate_second_precision_time),
]


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        loc_by_alias=True,
    )


class TripMode(str, Enum):
    SINGLE = "SINGLE"
    GROUP = "GROUP"


class TripStatus(str, Enum):
    DRAFT = "DRAFT"
    CONSTRAINT_CONFIRMED = "CONSTRAINT_CONFIRMED"
    PLANNING = "PLANNING"
    PLAN_REVIEW = "PLAN_REVIEW"
    CONFIRMED = "CONFIRMED"
    EXECUTING = "EXECUTING"
    REPLAN_REVIEW = "REPLAN_REVIEW"
    COMPLETED = "COMPLETED"


class PreferenceType(str, Enum):
    INTEREST = "INTEREST"
    MUST_VISIT = "MUST_VISIT"
    AVOID_PLACE = "AVOID_PLACE"


class AssistanceType(str, Enum):
    ORDINARY = "ORDINARY"
    PARENT_CHILD = "PARENT_CHILD"
    LOW_STAMINA = "LOW_STAMINA"
    MOBILITY_ASSISTANCE_BETA = "MOBILITY_ASSISTANCE_BETA"


class GeoPoint(ContractModel):
    longitude: Annotated[float, Field(ge=-180, le=180)]
    latitude: Annotated[float, Field(ge=-90, le=90)]


class ProviderConfig(ContractModel):
    provider: Literal["AMAP"]
    coordinate_system: Literal["GCJ02"]


class CityContext(ContractModel):
    country_code: Literal["CN"]
    city_code: Annotated[str, Field(min_length=1, max_length=64)]
    city_name: Annotated[str, Field(min_length=1, max_length=80)]
    center: GeoPoint
    provider_config: ProviderConfig


class Preference(ContractModel):
    type: PreferenceType
    value: Annotated[str, Field(min_length=1, max_length=120)]
    weight: Annotated[int, Field(ge=1, le=5)]
    is_hard: bool


class WalkLimits(ContractModel):
    """Walking thresholds in metres for one segment and the whole day."""

    max_continuous_meters: Annotated[int | None, Field(ge=1)]
    max_daily_meters: Annotated[int | None, Field(ge=1)]


class NapWindow(ContractModel):
    start: SecondPrecisionTime
    end: SecondPrecisionTime

    @field_validator("end")
    @classmethod
    def end_must_follow_start(cls, value: time, info: ValidationInfo) -> time:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise PydanticCustomError(
                "invalid_nap_window",
                "napWindow.end must be later than napWindow.start",
            )
        return value


class AssistanceProfile(ContractModel):
    """One serializable source for downstream care-constraint compilation."""

    type: AssistanceType
    child_age: Annotated[int | None, Field(ge=0, le=17)]
    walk_limits: WalkLimits
    max_transfers: Annotated[int | None, Field(ge=0)]
    rest_interval: Annotated[int | None, Field(ge=1)]
    nap_window: NapWindow | None
    avoid_stairs: bool


class Participant(ContractModel):
    participant_id: UUID4
    nickname: Annotated[str, Field(min_length=1, max_length=40)]
    budget_cap_cents: Annotated[int, Field(ge=0)]
    preferences: list[Preference] = Field(default_factory=list)
    assistance_profile: AssistanceProfile | None = None


class TimeWindow(ContractModel):
    start: SecondPrecisionTime
    end: SecondPrecisionTime


class TripDayInput(ContractModel):
    day_index: Annotated[int, Field(ge=0)]
    date: date
    daily_budget_cents: Annotated[int, Field(ge=0)]
    start_location_text: Annotated[str, Field(min_length=1, max_length=120)]
    end_location_text: Annotated[str, Field(min_length=1, max_length=120)]
    time_window: TimeWindow


class Trip(ContractModel):
    schema_version: Literal["1.0"]
    trip_id: UUID4
    mode: TripMode
    status: TripStatus
    city_context: CityContext
    start_date: date
    end_date: date
    currency: Literal["CNY"]
    total_budget_cents: Annotated[int, Field(ge=0)]
    participants: list[Participant] = Field(min_length=1, max_length=3)
    days: list[TripDayInput] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_participant_count_by_mode(self) -> "Trip":
        participant_count = len(self.participants)
        if self.mode is TripMode.SINGLE and participant_count != 1:
            raise PydanticCustomError(
                "mode_participant_mismatch",
                "SINGLE trips must contain exactly one participant",
                {"public_path": "participants"},
            )
        if self.mode is TripMode.GROUP and not 2 <= participant_count <= 3:
            raise PydanticCustomError(
                "mode_participant_mismatch",
                "GROUP trips must contain two or three participants",
                {"public_path": "participants"},
            )
        return self


class CreateDayTrip(Trip):
    """The unified one-day DRAFT entry for one to three participants."""

    status: Literal["DRAFT"]
    participants: list[Participant] = Field(min_length=1, max_length=3)
    days: list[TripDayInput] = Field(min_length=1, max_length=1)


class CreateSingleDayTrip(CreateDayTrip):
    mode: Literal["SINGLE"]
    status: Literal["DRAFT"]
    participants: list[Participant] = Field(min_length=1, max_length=1)
    days: list[TripDayInput] = Field(min_length=1, max_length=1)


def _normalized_preference(value: str) -> str:
    return normalize("NFKC", value).strip().casefold()


def validate_single_day_policy(
    trip: CreateDayTrip | PlanReviewTripSnapshot,
) -> list[ValidationIssue]:
    """Validate cross-field rules that JSON Schema cannot express alone."""

    issues: list[ValidationIssue] = []
    day = trip.days[0]

    if trip.start_date != trip.end_date:
        issues.append(
            ValidationIssue(
                path="endDate",
                code="date_mismatch",
                message="startDate and endDate must match for a single-day trip",
            )
        )

    if day.date != trip.start_date:
        issues.append(
            ValidationIssue(
                path="days[0].date",
                code="date_mismatch",
                message="days[0].date must match startDate",
            )
        )

    if day.day_index != 0:
        issues.append(
            ValidationIssue(
                path="days[0].dayIndex",
                code="invalid_day_index",
                message="dayIndex must be 0 for the S1 single-day contract",
            )
        )

    if day.time_window.end <= day.time_window.start:
        issues.append(
            ValidationIssue(
                path="days[0].timeWindow.end",
                code="invalid_time_window",
                message="timeWindow.end must be later than timeWindow.start",
            )
        )

    if day.daily_budget_cents > trip.total_budget_cents:
        issues.append(
            ValidationIssue(
                path="days[0].dailyBudgetCents",
                code="budget_exceeded",
                message="daily budget cannot exceed total budget",
            )
        )

    for participant_index, participant in enumerate(trip.participants):
        must_visit: dict[str, int] = {}
        avoid_place: dict[str, int] = {}
        for preference_index, preference in enumerate(participant.preferences):
            preference_path = (
                f"participants[{participant_index}].preferences[{preference_index}]"
            )
            expected_hard = preference.type is not PreferenceType.INTEREST
            if preference.is_hard is not expected_hard:
                issues.append(
                    ValidationIssue(
                        path=f"{preference_path}.isHard",
                        code="invalid_preference_hardness",
                        message="Preference hardness does not match its type",
                    )
                )

            normalized_value = _normalized_preference(preference.value)
            if preference.type is PreferenceType.MUST_VISIT:
                must_visit[normalized_value] = preference_index
            elif preference.type is PreferenceType.AVOID_PLACE:
                avoid_place[normalized_value] = preference_index

        for value in sorted(must_visit.keys() & avoid_place.keys()):
            conflict_index = max(must_visit[value], avoid_place[value])
            issues.append(
                ValidationIssue(
                    path=(
                        f"participants[{participant_index}].preferences"
                        f"[{conflict_index}].value"
                    ),
                    code="preference_conflict",
                    message="A place cannot be both must-visit and avoid",
                )
            )

    return issues


class PlanReviewTripSnapshot(Trip):
    """A single-day Trip snapshot admitted to Plan review."""

    mode: Literal[TripMode.SINGLE]
    status: Literal[TripStatus.PLAN_REVIEW]
    participants: list[Participant] = Field(min_length=1, max_length=1)
    days: list[TripDayInput] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def validate_single_day_snapshot_policy(self) -> "PlanReviewTripSnapshot":
        policy_issues = validate_single_day_policy(self)
        if policy_issues:
            issue = policy_issues[0]
            raise PydanticCustomError(
                issue.code,
                issue.message,
                {"public_path": f"tripSnapshot.{issue.path}"},
            )
        return self


def validate_trip_json(raw: str | bytes) -> CreateSingleDayTrip:
    """Parse and validate one complete normalized Trip JSON payload."""

    try:
        trip = CreateSingleDayTrip.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        raise TripSchemaError(issues_from_pydantic(exc.errors())) from exc

    policy_issues = validate_single_day_policy(trip)
    if policy_issues:
        raise TripSchemaError(policy_issues)
    return trip


def validate_create_day_trip_json(raw: str | bytes) -> CreateDayTrip:
    """Parse and validate the unified one-day DRAFT Trip contract."""

    try:
        trip = CreateDayTrip.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        raise TripSchemaError(issues_from_pydantic(exc.errors())) from exc

    policy_issues = validate_single_day_policy(trip)
    if policy_issues:
        raise TripSchemaError(policy_issues)
    return trip


__all__ = [
    "AssistanceProfile",
    "AssistanceType",
    "CityContext",
    "CreateDayTrip",
    "CreateSingleDayTrip",
    "GeoPoint",
    "NapWindow",
    "Participant",
    "PlanReviewTripSnapshot",
    "Preference",
    "PreferenceType",
    "ProviderConfig",
    "TimeWindow",
    "Trip",
    "TripDayInput",
    "TripMode",
    "TripStatus",
    "WalkLimits",
    "validate_single_day_policy",
    "validate_create_day_trip_json",
    "validate_trip_json",
]
