from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
import re
from typing import Annotated, Literal
from unicodedata import normalize
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    alias_generators,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.schemas.trip import CreateSingleDayTrip
from app.schemas.validation_error import (
    TripSchemaError,
    ValidationIssue,
    issues_from_pydantic,
)


class DraftContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class DraftAssistanceInput(DraftContractModel):
    max_segment_walk_meters: int = Field(default=500, ge=100)
    max_transfers: int = Field(default=2, ge=0)
    rest_interval_minutes: int = Field(default=90, ge=1)


class TripDraftParseRequest(DraftContractModel):
    schema_version: Literal["1.0"] = "1.0"
    trip_id: UUID | None = None
    natural_language_request: str = Field(min_length=1, max_length=1000)
    reference_date: date | None = None
    reference_time: time | None = None
    city_name: str | None = None
    travel_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    start_location_text: str | None = None
    end_location_text: str | None = None
    budget_cents: int | None = Field(default=None, ge=0)
    interests: list[str] = Field(default_factory=list)
    must_visit: list[str] = Field(default_factory=list)
    avoid_places: list[str] = Field(default_factory=list)
    assistance_mode: Literal[
        "standard", "family", "low-mobility", "assisted"
    ] = "standard"
    assistance_profile: DraftAssistanceInput = Field(
        default_factory=DraftAssistanceInput
    )


class ConfirmationItem(DraftContractModel):
    item_id: str
    path: str
    code: Literal["missing", "ambiguous", "conflict", "invalid"]
    message: str
    candidates: list[str] = Field(default_factory=list)


class ParsedTripFields(DraftContractModel):
    city_name: str | None = None
    travel_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    start_location_text: str | None = None
    end_location_text: str | None = None
    budget_cents: int | None = None
    interests: list[str] = Field(default_factory=list)
    must_visit: list[str] = Field(default_factory=list)
    avoid_places: list[str] = Field(default_factory=list)


class LlmTripDraftFields(DraftContractModel):
    """Untrusted candidate fields extracted by an LLM before rule validation."""

    city_name: str | None = None
    travel_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    start_location_text: str | None = None
    end_location_text: str | None = None
    budget_cents: int | None = Field(default=None, ge=0)
    interests: list[str] = Field(default_factory=list)
    must_visit: list[str] = Field(default_factory=list)
    avoid_places: list[str] = Field(default_factory=list)


class TripDraftExtractionError(RuntimeError):
    """Raised when an optional LLM extractor cannot provide trusted JSON."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class TripDraftParseResult(DraftContractModel):
    trip_id: str
    status: Literal["DRAFT"] = "DRAFT"
    recognition_source: Literal[
        "BAILIAN", "DETERMINISTIC_RULES", "DEGRADED_RULES"
    ]
    recognition_model: str | None = None
    degraded_reason: str | None = None
    parsed: ParsedTripFields
    confirmation_items: list[ConfirmationItem]
    can_plan: bool
    trip: CreateSingleDayTrip | None = None


class UnderstandingContractModel(BaseModel):
    """Strict, non-authoritative JSON contract for model understanding output."""

    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        loc_by_alias=True,
    )


MemberKey = Annotated[str, Field(pattern=r"^member-[1-3]$")]
_TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
TimeText = Annotated[str, Field(pattern=_TIME_PATTERN)]
Text40 = Annotated[str, Field(min_length=1, max_length=40)]
Text80 = Annotated[str, Field(min_length=1, max_length=80)]
Text120 = Annotated[str, Field(min_length=1, max_length=120)]
Text240 = Annotated[str, Field(min_length=1, max_length=240)]
Text1000 = Annotated[str, Field(min_length=1, max_length=1000)]
Text160 = Annotated[str, Field(min_length=1, max_length=160)]

_CANONICAL_TRIP_PATHS = {
    "trip.cityName",
    "trip.travelDate",
    "trip.startTime",
    "trip.endTime",
    "trip.startLocationText",
    "trip.endLocationText",
    "trip.budgetCents",
}
_CANONICAL_DIRECT_MEMBER_PATHS = {
    "nickname",
    "budgetCapCents",
    "interests",
    "mustVisit",
    "avoidPlaces",
}
_CANONICAL_CARE_PATHS = {
    "careDraft.assistanceTypeHint",
    "careDraft.childAge",
    "careDraft.walkLimits.maxContinuousMeters",
    "careDraft.walkLimits.maxDailyMeters",
    "careDraft.maxTransfers",
    "careDraft.restIntervalMinutes",
    "careDraft.napWindow.start",
    "careDraft.napWindow.end",
    "careDraft.avoidStairs",
}
_CANONICAL_FIELD_PATTERN = (
    r"(?:"
    r"trip\.(?:cityName|travelDate|startTime|endTime|startLocationText|"
    r"endLocationText|budgetCents)|participants|"
    r"participants\[\d+\]\.(?:nickname|budgetCapCents|"
    r"interests\[\d+\]|mustVisit\[\d+\]|avoidPlaces\[\d+\]|"
    r"careDraft\.(?:assistanceTypeHint|childAge|"
    r"walkLimits\.(?:maxContinuousMeters|maxDailyMeters)|maxTransfers|"
    r"restIntervalMinutes|napWindow\.(?:start|end)|avoidStairs)))"
)
CanonicalFieldPath = Annotated[str, Field(pattern=_CANONICAL_FIELD_PATTERN)]
QuestionKey = Literal[
    "CITY_NAME",
    "TRAVEL_DATE",
    "START_TIME",
    "END_TIME",
    "START_LOCATION",
    "END_LOCATION",
    "TRIP_BUDGET",
    "PARTY_SIZE",
    "MEMBER_NICKNAME",
    "MEMBER_BUDGET",
    "MEMBER_INTERESTS",
    "MEMBER_MUST_VISIT",
    "MEMBER_AVOID_PLACES",
    "MEMBER_CARE_PRESET",
    "MEMBER_CARE_DETAILS",
]
AssistanceHint = Literal[
    "ORDINARY",
    "PARENT_CHILD",
    "LOW_STAMINA",
    "MOBILITY_ASSISTANCE_BETA",
]


class ExplicitParticipantHint(UnderstandingContractModel):
    member_key: MemberKey
    nickname: Text40 | None
    budget_cap_cents: int | None = Field(ge=0)
    interests: list[Text120] = Field(min_length=0, max_length=20)
    must_visit: list[Text120] = Field(min_length=0, max_length=20)
    avoid_places: list[Text120] = Field(min_length=0, max_length=20)
    care_text: Text1000 | None


class TripUnderstandingExplicitFields(UnderstandingContractModel):
    city_name: Text80 | None
    travel_date: date | None
    start_time: TimeText | None
    end_time: TimeText | None
    start_location_text: Text120 | None
    end_location_text: Text120 | None
    budget_cents: int | None = Field(ge=0)
    participants: list[ExplicitParticipantHint] = Field(min_length=0, max_length=3)

    @model_validator(mode="after")
    def validate_member_key_sequence(self) -> "TripUnderstandingExplicitFields":
        expected = [f"member-{index}" for index in range(1, len(self.participants) + 1)]
        actual = [participant.member_key for participant in self.participants]
        if actual != expected:
            _raise_understanding_error(
                "member_key_sequence",
                "participants",
                "explicit participants must use sequential member-1..member-N keys",
            )
        return self


class TripUnderstandingRequest(UnderstandingContractModel):
    schema_version: Literal["1.0"]
    scope: Literal["FULL_TRIP", "MEMBER_PROFILE"] = "FULL_TRIP"
    reference_date: date
    raw_conversation: str = Field(max_length=8000)
    explicit_fields: TripUnderstandingExplicitFields


class CareWalkLimits(UnderstandingContractModel):
    max_continuous_meters: int | None = Field(ge=1)
    max_daily_meters: int | None = Field(ge=1)


class CareNapWindow(UnderstandingContractModel):
    start: TimeText | None
    end: TimeText | None


class CareDraft(UnderstandingContractModel):
    assistance_type_hint: AssistanceHint | None
    child_age: int | None = Field(ge=0, le=17)
    walk_limits: CareWalkLimits
    max_transfers: int | None = Field(ge=0)
    rest_interval_minutes: int | None = Field(ge=1)
    nap_window: CareNapWindow | None
    avoid_stairs: bool | None


class TripUnderstandingTrip(UnderstandingContractModel):
    city_name: Text80 | None
    travel_date: date | None
    start_time: TimeText | None
    end_time: TimeText | None
    start_location_text: Text120 | None
    end_location_text: Text120 | None
    budget_cents: int | None = Field(ge=0)


class ParticipantUnderstanding(UnderstandingContractModel):
    member_key: MemberKey
    nickname: Text40 | None
    budget_cap_cents: int | None = Field(ge=0)
    interests: list[Text120] = Field(min_length=0, max_length=20)
    must_visit: list[Text120] = Field(min_length=0, max_length=20)
    avoid_places: list[Text120] = Field(min_length=0, max_length=20)
    care_draft: CareDraft | None


class FieldEvidence(UnderstandingContractModel):
    field_path: CanonicalFieldPath
    member_key: MemberKey | None
    source_type: Literal["USER_TEXT", "EXPLICIT_FIELD"]
    source_text: Text240


class MissingField(UnderstandingContractModel):
    field_path: CanonicalFieldPath
    member_key: MemberKey | None
    code: Literal["MISSING"]
    question_key: QuestionKey


class Ambiguity(UnderstandingContractModel):
    field_path: CanonicalFieldPath
    member_key: MemberKey | None
    code: Literal["AMBIGUOUS"]
    reason: Text240
    candidates: list[Text120] = Field(min_length=2, max_length=5)
    question_key: QuestionKey


class ConfirmationQuestion(UnderstandingContractModel):
    field_path: CanonicalFieldPath
    member_key: MemberKey | None
    question_key: QuestionKey
    prompt: Text160
    choices: list[Text120] = Field(min_length=0, max_length=5)


_MEMBER_PATH_RE = re.compile(r"^participants\[(\d+)\]\.(.+)$")
_LIST_ITEM_PATH_RE = re.compile(r"^(interests|mustVisit|avoidPlaces)\[(\d+)\]$")


def _raise_understanding_error(code: str, path: str, message: str) -> None:
    raise PydanticCustomError(code, message, {"public_path": path})


def _parsed_member_path(path: str) -> tuple[int, str, int | None] | None:
    match = _MEMBER_PATH_RE.fullmatch(path)
    if match is None:
        return None
    index = int(match.group(1))
    tail = match.group(2)
    list_match = _LIST_ITEM_PATH_RE.fullmatch(tail)
    if list_match is not None:
        return index, list_match.group(1), int(list_match.group(2))
    return index, tail, None


def _care_values(care: CareDraft) -> list[object]:
    return [
        care.assistance_type_hint,
        care.child_age,
        care.walk_limits.max_continuous_meters,
        care.walk_limits.max_daily_meters,
        care.max_transfers,
        care.rest_interval_minutes,
        care.nap_window.start if care.nap_window is not None else None,
        care.nap_window.end if care.nap_window is not None else None,
        care.avoid_stairs,
    ]


def _evidence_value_paths(
    proposal: "TripUnderstandingProposal",
) -> dict[tuple[str, str | None], object]:
    values: dict[tuple[str, str | None], object] = {}
    trip_fields = {
        "cityName": proposal.trip.city_name,
        "travelDate": proposal.trip.travel_date,
        "startTime": proposal.trip.start_time,
        "endTime": proposal.trip.end_time,
        "startLocationText": proposal.trip.start_location_text,
        "endLocationText": proposal.trip.end_location_text,
        "budgetCents": proposal.trip.budget_cents,
    }
    for field, value in trip_fields.items():
        if value is not None:
            values[(f"trip.{field}", None)] = value

    for index, participant in enumerate(proposal.participants):
        member_key = participant.member_key
        participant_fields = {
            "nickname": participant.nickname,
            "budgetCapCents": participant.budget_cap_cents,
        }
        for field, value in participant_fields.items():
            if value is not None:
                values[(f"participants[{index}].{field}", member_key)] = value
        for field, items in (
            ("interests", participant.interests),
            ("mustVisit", participant.must_visit),
            ("avoidPlaces", participant.avoid_places),
        ):
            for item_index, value in enumerate(items):
                values[(f"participants[{index}].{field}[{item_index}]", member_key)] = value
        if participant.care_draft is not None:
            care = participant.care_draft
            care_values = {
                "careDraft.assistanceTypeHint": care.assistance_type_hint,
                "careDraft.childAge": care.child_age,
                "careDraft.walkLimits.maxContinuousMeters": (
                    care.walk_limits.max_continuous_meters
                ),
                "careDraft.walkLimits.maxDailyMeters": care.walk_limits.max_daily_meters,
                "careDraft.maxTransfers": care.max_transfers,
                "careDraft.restIntervalMinutes": care.rest_interval_minutes,
                "careDraft.napWindow.start": (
                    care.nap_window.start if care.nap_window is not None else None
                ),
                "careDraft.napWindow.end": (
                    care.nap_window.end if care.nap_window is not None else None
                ),
                "careDraft.avoidStairs": care.avoid_stairs,
            }
            for field, value in care_values.items():
                if value is not None:
                    values[(f"participants[{index}].{field}", member_key)] = value
    return values


def _normalized_values_are_unique(values: Sequence[str]) -> bool:
    normalized = {normalize("NFKC", value).strip().casefold() for value in values}
    return len(normalized) == len(values)


class TripUnderstandingProposal(UnderstandingContractModel):
    schema_version: Literal["1.0"]
    trip: TripUnderstandingTrip
    participants: list[ParticipantUnderstanding] = Field(min_length=1, max_length=3)
    field_evidence: list[FieldEvidence] = Field(min_length=0, max_length=100)
    missing_fields: list[MissingField] = Field(min_length=0, max_length=50)
    ambiguities: list[Ambiguity] = Field(min_length=0, max_length=50)
    confirmation_questions: list[ConfirmationQuestion] = Field(
        min_length=0,
        max_length=50,
    )

    @model_validator(mode="after")
    def validate_semantics(self) -> "TripUnderstandingProposal":
        expected_member_keys = [
            f"member-{index}" for index in range(1, len(self.participants) + 1)
        ]
        actual_member_keys = [participant.member_key for participant in self.participants]
        if actual_member_keys != expected_member_keys:
            _raise_understanding_error(
                "member_key_sequence",
                "participants",
                "participants must use sequential member-1..member-N keys",
            )

        for index, participant in enumerate(self.participants):
            for field_name, values in (
                ("interests", participant.interests),
                ("mustVisit", participant.must_visit),
                ("avoidPlaces", participant.avoid_places),
            ):
                if not _normalized_values_are_unique(values):
                    _raise_understanding_error(
                        "duplicate_preference_value",
                        f"participants[{index}].{field_name}",
                        "Preference values must be unique after Unicode normalization",
                    )
            if participant.care_draft is not None and not any(
                value is not None for value in _care_values(participant.care_draft)
            ):
                _raise_understanding_error(
                    "empty_care_draft",
                    f"participants[{index}].careDraft",
                    "careDraft must be null when it contains no care signal",
                )

        evidence_values = _evidence_value_paths(self)
        evidence_keys: set[tuple[str, str | None]] = set()
        for index, evidence in enumerate(self.field_evidence):
            key = (evidence.field_path, evidence.member_key)
            self._validate_path(
                evidence.field_path,
                evidence.member_key,
                f"fieldEvidence[{index}]",
                True,
            )
            if evidence.field_path != "participants" and key not in evidence_values:
                _raise_understanding_error(
                    "evidence_without_value",
                    f"fieldEvidence[{index}].fieldPath",
                    "Evidence must point to a non-null proposal value",
                )
            evidence_keys.add(key)
        for key in evidence_values:
            if key not in evidence_keys:
                _raise_understanding_error(
                    "missing_field_evidence",
                    "fieldEvidence",
                    "Every non-null modeled value must have field evidence",
                )

        missing_keys: set[tuple[str, str | None]] = set()
        for index, missing in enumerate(self.missing_fields):
            self._validate_path(
                missing.field_path,
                missing.member_key,
                f"missingFields[{index}]",
                False,
            )
            key = (missing.field_path, missing.member_key)
            if key in missing_keys:
                _raise_understanding_error(
                    "duplicate_missing_field",
                    f"missingFields[{index}].fieldPath",
                    "missingFields must not contain duplicate field paths",
                )
            missing_keys.add(key)

        ambiguity_keys: set[tuple[str, str | None]] = set()
        for index, ambiguity in enumerate(self.ambiguities):
            self._validate_path(
                ambiguity.field_path,
                ambiguity.member_key,
                f"ambiguities[{index}]",
                False,
            )
            key = (ambiguity.field_path, ambiguity.member_key)
            if key in ambiguity_keys:
                _raise_understanding_error(
                    "duplicate_ambiguity",
                    f"ambiguities[{index}].fieldPath",
                    "ambiguities must not contain duplicate field paths",
                )
            if key in missing_keys:
                _raise_understanding_error(
                    "conflicting_field_status",
                    f"ambiguities[{index}].fieldPath",
                    "A field cannot be both missing and ambiguous",
                )
            ambiguity_keys.add(key)

        question_keys: dict[tuple[str, str | None, str], ConfirmationQuestion] = {}
        for index, question in enumerate(self.confirmation_questions):
            self._validate_path(
                question.field_path,
                question.member_key,
                f"confirmationQuestions[{index}]",
                False,
            )
            key = (question.field_path, question.member_key, question.question_key)
            if key in question_keys:
                _raise_understanding_error(
                    "duplicate_confirmation_question",
                    f"confirmationQuestions[{index}].questionKey",
                    "confirmationQuestions must not contain duplicate keys",
                )
            question_keys[key] = question

        issue_keys: set[tuple[str, str | None, str]] = set()
        for missing in self.missing_fields:
            key = (missing.field_path, missing.member_key, missing.question_key)
            if key not in question_keys:
                _raise_understanding_error(
                    "missing_question",
                    "confirmationQuestions",
                    "Every missing field must have one matching confirmation question",
                )
            issue_keys.add(key)
        for ambiguity in self.ambiguities:
            key = (ambiguity.field_path, ambiguity.member_key, ambiguity.question_key)
            if key not in question_keys:
                _raise_understanding_error(
                    "missing_question",
                    "confirmationQuestions",
                    "Every ambiguity must have one matching confirmation question",
                )
            question = question_keys[key]
            if question.choices != ambiguity.candidates:
                _raise_understanding_error(
                    "question_choices_mismatch",
                    "confirmationQuestions",
                    "Ambiguity question choices must equal candidates",
                )
            issue_keys.add(key)
        if set(question_keys) != issue_keys:
            _raise_understanding_error(
                "orphan_confirmation_question",
                "confirmationQuestions",
                "Every confirmation question must explain a missing or ambiguous field",
            )
        return self


    def _validate_path(
        self,
        field_path: str,
        member_key: str | None,
        location: str,
        requires_value: bool,
    ) -> None:
        if field_path in _CANONICAL_TRIP_PATHS or field_path == "participants":
            if member_key is not None:
                _raise_understanding_error(
                    "trip_field_member_key",
                    f"{location}.memberKey",
                    "Trip-level field paths must have a null memberKey",
                )
            return

        parsed = _parsed_member_path(field_path)
        if parsed is None:
            _raise_understanding_error(
                "invalid_field_path",
                f"{location}.fieldPath",
                "fieldPath is not in the canonical field path allowlist",
            )
        participant_index, tail, list_index = parsed
        if participant_index >= len(self.participants):
            _raise_understanding_error(
                "participant_index_out_of_range",
                f"{location}.fieldPath",
                "participant index must address an existing participant",
            )
        expected_member_key = self.participants[participant_index].member_key
        if member_key != expected_member_key:
            _raise_understanding_error(
                "member_key_path_mismatch",
                f"{location}.memberKey",
                "memberKey must match the participant addressed by fieldPath",
            )
        participant = self.participants[participant_index]
        if list_index is not None:
            values = getattr(participant, _camel_to_snake(tail.split("[")[0]))
            if list_index >= len(values):
                _raise_understanding_error(
                    "list_index_out_of_range",
                    f"{location}.fieldPath",
                    "List item index must address an existing item",
                )
        elif tail in _CANONICAL_DIRECT_MEMBER_PATHS:
            return
        elif tail in _CANONICAL_CARE_PATHS:
            if requires_value and participant.care_draft is None:
                _raise_understanding_error(
                    "care_evidence_without_draft",
                    f"{location}.fieldPath",
                    "Care evidence requires a non-null careDraft",
                )
            return
        else:
            _raise_understanding_error(
                "invalid_field_path",
                f"{location}.fieldPath",
                "fieldPath is not in the canonical field path allowlist",
            )


class TripDraftRevision(UnderstandingContractModel):
    schema_version: Literal["1.0"] = "1.0"
    draft_id: UUID
    revision: int = Field(ge=1)
    trip_id: UUID
    understanding: TripUnderstandingProposal
    member_bindings: dict[str, UUID]
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime

    @model_validator(mode="after")
    def validate_member_bindings(self) -> "TripDraftRevision":
        member_keys = [member.member_key for member in self.understanding.participants]
        if set(self.member_bindings) != set(member_keys):
            raise ValueError("memberBindings must exactly match proposal member keys")
        if len(set(self.member_bindings.values())) != len(self.member_bindings):
            raise ValueError("participant bindings must be unique")
        return self


class TripUnderstandingExtraction(UnderstandingContractModel):
    proposal: TripUnderstandingProposal
    recognition_source: str = Field(min_length=1, max_length=40)
    recognition_model: str | None = Field(default=None, max_length=120)
    degraded_reason: str | None = Field(default=None, max_length=240)
    llm_call_count: Literal[0, 1, 2]


TripUnderstandingFailureCode = Literal[
    "LLM_NOT_CONFIGURED",
    "LLM_TIMEOUT",
    "LLM_AUTH_FAILED",
    "LLM_UNAVAILABLE",
    "LLM_INVALID_RESPONSE",
    "LLM_INVALID_JSON",
    "LLM_SCHEMA_INVALID",
    "LLM_CONTENT_INVALID",
]


class TripDraftRevisionRecognition(UnderstandingContractModel):
    source: Literal["MODEL_PROPOSAL", "REVIEWED_FIXED_QUESTIONS"]
    model: str | None = Field(default=None, max_length=120)
    degraded_reason: TripUnderstandingFailureCode | None = None
    call_count: Literal[0, 1, 2]

    @model_validator(mode="after")
    def validate_source_metadata(self) -> "TripDraftRevisionRecognition":
        if self.source == "MODEL_PROPOSAL" and self.degraded_reason is not None:
            raise ValueError("model proposals cannot carry a degraded reason")
        if self.source == "REVIEWED_FIXED_QUESTIONS" and self.degraded_reason is None:
            raise ValueError("reviewed fixed questions must preserve a failure code")
        return self


class TripUnderstandingGatewayResult(UnderstandingContractModel):
    decision: Literal["MODEL_PROPOSAL", "FIXED_QUESTIONS"]
    proposal: TripUnderstandingProposal | None
    failure_code: TripUnderstandingFailureCode | None
    call_count: int = Field(ge=0, le=2)
    model: str | None

    @model_validator(mode="after")
    def validate_result_shape(self) -> "TripUnderstandingGatewayResult":
        if self.decision == "MODEL_PROPOSAL":
            valid = (
                self.proposal is not None
                and self.failure_code is None
                and 1 <= self.call_count <= 2
            )
        else:
            valid = self.proposal is None and self.failure_code is not None
        if not valid:
            raise ValueError("trip understanding gateway result is inconsistent")
        return self


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _display_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _explicit_field_display_value(
    request: TripUnderstandingRequest,
    proposal: TripUnderstandingProposal,
    evidence: FieldEvidence,
) -> str | None:
    path = evidence.field_path
    trip_fields = {
        "trip.cityName": request.explicit_fields.city_name,
        "trip.travelDate": request.explicit_fields.travel_date,
        "trip.startTime": request.explicit_fields.start_time,
        "trip.endTime": request.explicit_fields.end_time,
        "trip.startLocationText": request.explicit_fields.start_location_text,
        "trip.endLocationText": request.explicit_fields.end_location_text,
        "trip.budgetCents": request.explicit_fields.budget_cents,
    }
    if path in trip_fields:
        return _display_value(trip_fields[path])
    if path == "participants":
        return str(len(request.explicit_fields.participants))

    parsed = _parsed_member_path(path)
    if parsed is None:
        return None
    participant_index, tail, list_index = parsed
    if participant_index >= len(proposal.participants):
        return None
    participant_hint = next(
        (
            hint
            for hint in request.explicit_fields.participants
            if hint.member_key == evidence.member_key
        ),
        None,
    )
    if participant_hint is None:
        return None
    if list_index is not None:
        values = getattr(participant_hint, _camel_to_snake(tail.split("[")[0]))
        if list_index >= len(values):
            return None
        return _display_value(values[list_index])
    if tail in {"nickname", "budgetCapCents"}:
        return _display_value(getattr(participant_hint, _camel_to_snake(tail)))
    if tail in _CANONICAL_CARE_PATHS:
        return _display_value(participant_hint.care_text)
    return None


def _proposal_field_display_value(
    proposal: TripUnderstandingProposal,
    evidence: FieldEvidence,
) -> str | None:
    if evidence.field_path == "participants":
        return str(len(proposal.participants))
    value = _evidence_value_paths(proposal).get(
        (evidence.field_path, evidence.member_key)
    )
    return _display_value(value)


def _is_care_field_path(field_path: str) -> bool:
    parsed = _parsed_member_path(field_path)
    return parsed is not None and parsed[1] in _CANONICAL_CARE_PATHS


def validate_trip_understanding(
    request: TripUnderstandingRequest,
    proposal: TripUnderstandingProposal,
) -> TripUnderstandingProposal:
    """Validate a proposal while binding evidence to one request context."""

    errors: list[ValidationIssue] = []
    for index, evidence in enumerate(proposal.field_evidence):
        if evidence.source_type == "USER_TEXT":
            if evidence.source_text not in request.raw_conversation:
                errors.append(
                    ValidationIssue(
                        path=f"fieldEvidence[{index}].sourceText",
                        code="evidence_source_mismatch",
                        message="USER_TEXT evidence must be an exact sourceText substring of rawConversation",
                    )
                )
        else:
            expected = _explicit_field_display_value(request, proposal, evidence)
            proposal_value = _proposal_field_display_value(proposal, evidence)
            proposal_matches_source = (
                _is_care_field_path(evidence.field_path)
                or proposal_value == evidence.source_text
            )
            if (
                expected is None
                or evidence.source_text != expected
                or not proposal_matches_source
            ):
                errors.append(
                    ValidationIssue(
                        path=f"fieldEvidence[{index}].sourceText",
                        code="explicit_field_source_mismatch",
                        message="EXPLICIT_FIELD evidence must equal the canonical explicit field display value",
                    )
                )
    if errors:
        raise TripSchemaError(errors)
    return proposal


def validate_trip_understanding_json(
    request_raw: str | bytes,
    proposal_raw: str | bytes,
) -> TripUnderstandingProposal:
    """Strictly parse and context-validate a request/proposal JSON pair."""

    try:
        request = TripUnderstandingRequest.model_validate_json(request_raw, strict=True)
        proposal = TripUnderstandingProposal.model_validate_json(
            proposal_raw,
            strict=True,
        )
    except ValidationError as exc:
        raise TripSchemaError(issues_from_pydantic(exc.errors())) from exc
    return validate_trip_understanding(request, proposal)


validate_trip_understanding_proposal = validate_trip_understanding


__all__ = [
    "Ambiguity",
    "CareDraft",
    "CareNapWindow",
    "CareWalkLimits",
    "ConfirmationItem",
    "ConfirmationQuestion",
    "DraftAssistanceInput",
    "ExplicitParticipantHint",
    "FieldEvidence",
    "LlmTripDraftFields",
    "MissingField",
    "ParticipantUnderstanding",
    "ParsedTripFields",
    "TripUnderstandingExplicitFields",
    "TripUnderstandingFailureCode",
    "TripDraftRevisionRecognition",
    "TripUnderstandingGatewayResult",
    "TripUnderstandingProposal",
    "TripUnderstandingRequest",
    "TripUnderstandingTrip",
    "TripDraftRevision",
    "TripUnderstandingExtraction",
    "TripDraftParseRequest",
    "TripDraftParseResult",
    "TripDraftExtractionError",
    "validate_trip_understanding",
    "validate_trip_understanding_json",
    "validate_trip_understanding_proposal",
]
