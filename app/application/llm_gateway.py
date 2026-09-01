from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import json
import logging
import re
from typing import Annotated, Literal, Protocol
from unicodedata import normalize

from pydantic import BaseModel, ConfigDict, Field, ValidationError, alias_generators

from app.domain.trip_draft import (
    CareDraft,
    ParticipantUnderstanding,
    TripUnderstandingFailureCode,
    TripUnderstandingGatewayResult,
    TripUnderstandingProposal,
    TripUnderstandingRequest,
    TripUnderstandingTrip,
    validate_trip_understanding,
)
from app.schemas.validation_error import TripSchemaError, ValidationIssue
from app.schemas.llm import (
    CandidateSelectionFailureCode,
    CandidateSelectionGatewayResult,
    ProviderCandidateSelectionProposal,
    ProviderCandidateSelectionRequest,
)


logger = logging.getLogger(__name__)


class CandidateSelectionContractError(RuntimeError):
    """Raised for a caller-side contract violation before any model call."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CandidateSelectionTransportError(RuntimeError):
    """Sanitized infrastructure failure; provider details never cross layers."""

    def __init__(self, code: CandidateSelectionFailureCode, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class CandidateSelectionModelClient(Protocol):
    model: str

    async def propose_candidate_selection(
        self,
        request: ProviderCandidateSelectionRequest,
    ) -> str: ...


class CandidateSelectionGateway(Protocol):
    async def select(
        self,
        request: ProviderCandidateSelectionRequest,
    ) -> CandidateSelectionGatewayResult: ...


class StrictCandidateSelectionGateway:
    """Validate exactly one model proposal or request deterministic fallback.

    S2 deliberately has no model repair or transport-retry loop at this
    boundary.  A timeout, provider error, invalid JSON, schema violation or
    allowlist violation therefore consumes at most one model call before the
    deterministic enumerator takes over.
    """

    def __init__(
        self,
        client: CandidateSelectionModelClient,
        *,
        max_transport_attempts: int = 1,
    ) -> None:
        # Keep the keyword for source compatibility with callers that already
        # construct the gateway explicitly, but fail closed instead of silently
        # re-enabling the retired retry behavior.
        if max_transport_attempts != 1:
            raise ValueError("maxTransportAttempts is fixed to 1")
        self._client = client

    async def select(
        self,
        request: ProviderCandidateSelectionRequest,
    ) -> CandidateSelectionGatewayResult:
        trusted_request = _strict_request(request)
        digest = _request_digest(trusted_request)
        call_count = 1
        try:
            raw = await self._client.propose_candidate_selection(trusted_request)
        except CandidateSelectionTransportError as error:
            return _fallback(
                request=trusted_request,
                request_digest=digest,
                failure_code=error.code,
                call_count=call_count,
                model=self._client.model,
            )
        except Exception as error:
            logger.warning(
                "candidate selection client failed with %s",
                type(error).__name__,
            )
            return _fallback(
                request=trusted_request,
                request_digest=digest,
                failure_code="LLM_UNAVAILABLE",
                call_count=call_count,
                model=self._client.model,
            )

        try:
            proposal = ProviderCandidateSelectionProposal.model_validate_json(
                raw,
                strict=True,
            )
        except ValidationError as error:
            failure_code: CandidateSelectionFailureCode = (
                "LLM_INVALID_JSON"
                if any(item["type"] == "json_invalid" for item in error.errors())
                else "LLM_SCHEMA_INVALID"
            )
            return _fallback(
                request=trusted_request,
                request_digest=digest,
                failure_code=failure_code,
                call_count=call_count,
                model=self._client.model,
            )

        allowed_ids = {
            item.place_fact_id for item in trusted_request.candidate_facts
        }
        if not set(proposal.selected_place_fact_ids) <= allowed_ids:
            return _fallback(
                request=trusted_request,
                request_digest=digest,
                failure_code="LLM_OUT_OF_ALLOWLIST",
                call_count=call_count,
                model=self._client.model,
            )

        if not _proposal_is_grounded(trusted_request, proposal):
            return _fallback(
                request=trusted_request,
                request_digest=digest,
                failure_code="LLM_SCHEMA_INVALID",
                call_count=call_count,
                model=self._client.model,
            )

        return CandidateSelectionGatewayResult(
            trace_id=trusted_request.trace_id,
            request_digest=digest,
            decision="MODEL_PROPOSAL",
            proposal=proposal,
            failure_code=None,
            call_count=call_count,
            model=self._client.model,
        )


class TripUnderstandingTransportError(RuntimeError):
    """Sanitized infrastructure failure for trip understanding transport."""

    def __init__(
        self,
        code: TripUnderstandingFailureCode,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


_MemberText40 = Annotated[str, Field(min_length=1, max_length=40)]
_MemberText120 = Annotated[str, Field(min_length=1, max_length=120)]
_MemberText240 = Annotated[str, Field(min_length=1, max_length=240)]
_MEMBER_PROFILE_FIELD_PATTERN = (
    r"^(?:nickname|budgetCapCents|interests\[\d+\]|mustVisit\[\d+\]|"
    r"avoidPlaces\[\d+\]|careDraft\.(?:assistanceTypeHint|childAge|"
    r"walkLimits\.(?:maxContinuousMeters|maxDailyMeters)|maxTransfers|"
    r"restIntervalMinutes|napWindow\.(?:start|end)|avoidStairs))$"
)


class _MemberProfileContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        loc_by_alias=True,
    )


class MemberProfileEvidence(_MemberProfileContractModel):
    field_path: str = Field(pattern=_MEMBER_PROFILE_FIELD_PATTERN)
    source_text: _MemberText240


class MemberProfileModelProposal(_MemberProfileContractModel):
    """Compact model contract for one member's editable profile only."""

    schema_version: Literal["1.0"]
    nickname: _MemberText40 | None
    budget_cap_cents: int | None = Field(ge=0)
    interests: list[_MemberText120] = Field(min_length=0, max_length=20)
    must_visit: list[_MemberText120] = Field(min_length=0, max_length=20)
    avoid_places: list[_MemberText120] = Field(min_length=0, max_length=20)
    care_draft: CareDraft | None
    field_evidence: list[MemberProfileEvidence] = Field(min_length=0, max_length=100)


class OrganizerTripModelProposal(_MemberProfileContractModel):
    """Compact model contract for a complete fixed-question organizer form."""

    schema_version: Literal["1.0"]
    trip: TripUnderstandingTrip
    participants: list[ParticipantUnderstanding] = Field(min_length=1, max_length=20)


class TripUnderstandingModelClient(Protocol):
    model: str

    async def propose_trip_understanding(
        self,
        request: TripUnderstandingRequest,
    ) -> str: ...

    async def repair_trip_understanding(
        self,
        request: TripUnderstandingRequest,
        *,
        invalid_response: str,
        validation_errors: str,
    ) -> str: ...

    async def propose_member_profile(
        self,
        request: TripUnderstandingRequest,
    ) -> str: ...

    async def propose_organizer_trip(
        self,
        request: TripUnderstandingRequest,
    ) -> str: ...


class TripUnderstandingGateway(Protocol):
    async def understand(
        self,
        request: TripUnderstandingRequest,
    ) -> TripUnderstandingGatewayResult: ...


class StrictTripUnderstandingGateway:
    """Validate one model understanding proposal or return fixed-question fallback."""

    def __init__(
        self,
        client: TripUnderstandingModelClient,
        *,
        max_transport_attempts: int = 2,
    ) -> None:
        if max_transport_attempts not in {1, 2}:
            raise ValueError("maxTransportAttempts must be 1 or 2")
        self._client = client
        self._max_transport_attempts = max_transport_attempts

    async def understand(
        self,
        request: TripUnderstandingRequest,
    ) -> TripUnderstandingGatewayResult:
        trusted_request = _strict_understanding_request(request)
        if trusted_request.scope == "MEMBER_PROFILE":
            return await self._understand_member_profile(trusted_request)
        if callable(getattr(self._client, "propose_organizer_trip", None)):
            return await self._understand_organizer_trip(trusted_request)

        call_count = 0
        repair: tuple[str, str] | None = None

        while call_count < self._max_transport_attempts:
            call_count += 1
            try:
                if repair is None:
                    raw = await self._client.propose_trip_understanding(
                        trusted_request
                    )
                else:
                    raw = await self._client.repair_trip_understanding(
                        trusted_request,
                        invalid_response=repair[0],
                        validation_errors=repair[1],
                    )
            except TripUnderstandingTransportError as error:
                if error.retryable and call_count < self._max_transport_attempts:
                    continue
                return _understanding_fallback(
                    error.code,
                    call_count,
                    self._client.model,
                )
            except Exception as error:
                logger.warning(
                    "trip understanding client failed with %s",
                    type(error).__name__,
                )
                return _understanding_fallback(
                    "LLM_UNAVAILABLE",
                    call_count,
                    self._client.model,
                )

            try:
                proposal = TripUnderstandingProposal.model_validate_json(
                    raw,
                    strict=True,
                )
            except ValidationError as error:
                failure_code: TripUnderstandingFailureCode = (
                    "LLM_INVALID_JSON"
                    if any(item["type"] == "json_invalid" for item in error.errors())
                    else "LLM_SCHEMA_INVALID"
                )
                if call_count < self._max_transport_attempts:
                    repair = (raw, _validation_error_summary(error))
                    continue
                return _understanding_fallback(
                    failure_code,
                    call_count,
                    self._client.model,
                )

            try:
                proposal = validate_trip_understanding(trusted_request, proposal)
            except TripSchemaError as error:
                if call_count < self._max_transport_attempts:
                    repair = (raw, str(error))
                    continue
                return _understanding_fallback(
                    "LLM_CONTENT_INVALID",
                    call_count,
                    self._client.model,
                )
            return TripUnderstandingGatewayResult(
                decision="MODEL_PROPOSAL",
                proposal=proposal,
                failure_code=None,
                call_count=call_count,
                model=self._client.model,
            )

        raise AssertionError("trip understanding loop must return")

    async def _understand_member_profile(
        self,
        request: TripUnderstandingRequest,
    ) -> TripUnderstandingGatewayResult:
        # Member forms have a deterministic reviewed fallback, so this boundary
        # deliberately spends at most one model call before returning control.
        call_count = 1
        try:
            raw = await self._client.propose_member_profile(request)
        except TripUnderstandingTransportError as error:
            return _understanding_fallback(
                error.code,
                call_count,
                self._client.model,
            )
        except Exception as error:
            logger.warning(
                "member profile client failed with %s",
                type(error).__name__,
            )
            return _understanding_fallback(
                "LLM_UNAVAILABLE",
                call_count,
                self._client.model,
            )

        try:
            compact = MemberProfileModelProposal.model_validate_json(raw, strict=True)
            proposal = _member_profile_understanding_proposal(compact)
        except ValidationError as error:
            failure_code: TripUnderstandingFailureCode = (
                "LLM_INVALID_JSON"
                if any(item["type"] == "json_invalid" for item in error.errors())
                else "LLM_SCHEMA_INVALID"
            )
            return _understanding_fallback(
                failure_code,
                call_count,
                self._client.model,
            )
        except TripSchemaError:
            return _understanding_fallback(
                "LLM_CONTENT_INVALID",
                call_count,
                self._client.model,
            )

        try:
            proposal = validate_trip_understanding(request, proposal)
        except TripSchemaError:
            return _understanding_fallback(
                "LLM_CONTENT_INVALID",
                call_count,
                self._client.model,
            )
        return TripUnderstandingGatewayResult(
            decision="MODEL_PROPOSAL",
            proposal=proposal,
            failure_code=None,
            call_count=call_count,
            model=self._client.model,
        )

    async def _understand_organizer_trip(
        self,
        request: TripUnderstandingRequest,
    ) -> TripUnderstandingGatewayResult:
        call_count = 1
        model = getattr(self._client, "organizer_model", self._client.model)
        if not isinstance(model, str) or not model:
            model = self._client.model
        try:
            raw = await self._client.propose_organizer_trip(request)
        except TripUnderstandingTransportError as error:
            return _understanding_fallback(
                error.code,
                call_count,
                model,
            )
        except Exception as error:
            logger.warning(
                "organizer trip client failed with %s",
                type(error).__name__,
            )
            return _understanding_fallback(
                "LLM_UNAVAILABLE",
                call_count,
                model,
            )

        try:
            compact = OrganizerTripModelProposal.model_validate_json(raw, strict=True)
            proposal = _organizer_trip_understanding_proposal(compact, request)
        except ValidationError as error:
            failure_code: TripUnderstandingFailureCode = (
                "LLM_INVALID_JSON"
                if any(item["type"] == "json_invalid" for item in error.errors())
                else "LLM_SCHEMA_INVALID"
            )
            return _understanding_fallback(
                failure_code,
                call_count,
                model,
            )
        except TripSchemaError:
            return _understanding_fallback(
                "LLM_CONTENT_INVALID",
                call_count,
                model,
            )

        try:
            proposal = validate_trip_understanding(request, proposal)
        except TripSchemaError:
            return _understanding_fallback(
                "LLM_CONTENT_INVALID",
                call_count,
                model,
            )
        return TripUnderstandingGatewayResult(
            decision="MODEL_PROPOSAL",
            proposal=proposal,
            failure_code=None,
            call_count=call_count,
            model=model,
        )


class UnavailableTripUnderstandingGateway:
    """Stable no-Key boundary for trip understanding."""

    async def understand(
        self,
        request: TripUnderstandingRequest,
    ) -> TripUnderstandingGatewayResult:
        trusted_request = _strict_understanding_request(request)
        del trusted_request
        return _understanding_fallback(
            "LLM_NOT_CONFIGURED",
            0,
            None,
        )


def _strict_understanding_request(
    request: TripUnderstandingRequest,
) -> TripUnderstandingRequest:
    return TripUnderstandingRequest.model_validate_json(
        request.model_dump_json(by_alias=True),
        strict=True,
    )


def _member_profile_understanding_proposal(
    compact: MemberProfileModelProposal,
) -> TripUnderstandingProposal:
    return TripUnderstandingProposal.model_validate(
        {
            "schemaVersion": "1.0",
            "trip": {
                "cityName": None,
                "travelDate": None,
                "startTime": None,
                "endTime": None,
                "startLocationText": None,
                "endLocationText": None,
                "budgetCents": None,
            },
            "participants": [
                {
                    "memberKey": "member-1",
                    "nickname": compact.nickname,
                    "budgetCapCents": compact.budget_cap_cents,
                    "interests": list(compact.interests),
                    "mustVisit": list(compact.must_visit),
                    "avoidPlaces": list(compact.avoid_places),
                    "careDraft": (
                        compact.care_draft.model_dump(mode="python", by_alias=True)
                        if compact.care_draft is not None
                        else None
                    ),
                }
            ],
            "fieldEvidence": [
                {
                    "fieldPath": f"participants[0].{item.field_path}",
                    "memberKey": "member-1",
                    "sourceType": "USER_TEXT",
                    "sourceText": item.source_text,
                }
                for item in compact.field_evidence
            ],
            "missingFields": [],
            "ambiguities": [],
            "confirmationQuestions": [],
        }
    )


def _organizer_trip_understanding_proposal(
    compact: OrganizerTripModelProposal,
    request: TripUnderstandingRequest,
) -> TripUnderstandingProposal:
    trip = compact.trip.model_dump(mode="python", by_alias=True)
    participants = [
        item.model_dump(mode="python", by_alias=True)
        for item in compact.participants
    ]
    trip_budget = _fixed_question_budget_cents(
        request.raw_conversation,
        r"(?:共享预算|本次行程总预算|同行行程总预算)\s*[:：]\s*(\d+(?:\.\d{1,2})?)",
    )
    if trip_budget is not None:
        trip["budgetCents"] = trip_budget
    organizer_budget = _fixed_question_budget_cents(
        request.raw_conversation,
        r"(?:组织者)?个人预算上限\s*[:：]\s*(\d+(?:\.\d{1,2})?)",
    )
    if organizer_budget is not None and participants:
        participants[0]["budgetCapCents"] = organizer_budget

    evidence = _organizer_evidence(
        raw_conversation=request.raw_conversation,
        trip=trip,
        participants=participants,
    )
    return TripUnderstandingProposal.model_validate(
        {
            "schemaVersion": "1.0",
            "trip": trip,
            "participants": participants,
            "fieldEvidence": evidence,
            "missingFields": [],
            "ambiguities": [],
            "confirmationQuestions": [],
        }
    )


def _fixed_question_budget_cents(raw_conversation: str, pattern: str) -> int | None:
    match = re.search(pattern, raw_conversation)
    if match is None:
        return None
    try:
        amount = Decimal(match.group(1))
    except InvalidOperation:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _organizer_evidence(
    *,
    raw_conversation: str,
    trip: dict[str, object],
    participants: list[dict[str, object]],
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []

    def add(field_path: str, member_key: str | None, value: object) -> None:
        if value is None:
            return
        source_text = _organizer_source_text(
            raw_conversation,
            field_path=field_path,
            value=value,
        )
        evidence.append(
            {
                "fieldPath": field_path,
                "memberKey": member_key,
                "sourceType": "USER_TEXT",
                "sourceText": source_text,
            }
        )

    for field_name, value in trip.items():
        add(f"trip.{field_name}", None, value)

    for participant_index, participant in enumerate(participants):
        member_key = participant["memberKey"]
        assert isinstance(member_key, str)
        prefix = f"participants[{participant_index}]."
        add(f"{prefix}nickname", member_key, participant.get("nickname"))
        add(f"{prefix}budgetCapCents", member_key, participant.get("budgetCapCents"))
        for field_name in ("interests", "mustVisit", "avoidPlaces"):
            values = participant.get(field_name)
            assert isinstance(values, list)
            for item_index, value in enumerate(values):
                add(f"{prefix}{field_name}[{item_index}]", member_key, value)
        care = participant.get("careDraft")
        if not isinstance(care, dict):
            continue
        add(
            f"{prefix}careDraft.assistanceTypeHint",
            member_key,
            care.get("assistanceTypeHint"),
        )
        add(f"{prefix}careDraft.childAge", member_key, care.get("childAge"))
        walk_limits = care.get("walkLimits")
        if isinstance(walk_limits, dict):
            add(
                f"{prefix}careDraft.walkLimits.maxContinuousMeters",
                member_key,
                walk_limits.get("maxContinuousMeters"),
            )
            add(
                f"{prefix}careDraft.walkLimits.maxDailyMeters",
                member_key,
                walk_limits.get("maxDailyMeters"),
            )
        add(f"{prefix}careDraft.maxTransfers", member_key, care.get("maxTransfers"))
        add(
            f"{prefix}careDraft.restIntervalMinutes",
            member_key,
            care.get("restIntervalMinutes"),
        )
        nap_window = care.get("napWindow")
        if isinstance(nap_window, dict):
            add(f"{prefix}careDraft.napWindow.start", member_key, nap_window.get("start"))
            add(f"{prefix}careDraft.napWindow.end", member_key, nap_window.get("end"))
        add(f"{prefix}careDraft.avoidStairs", member_key, care.get("avoidStairs"))
    return evidence


def _organizer_source_text(
    raw_conversation: str,
    *,
    field_path: str,
    value: object,
) -> str:
    if field_path == "trip.budgetCents":
        pattern = r"(?:共享预算|本次行程总预算|同行行程总预算)\s*[:：]\s*(\d+(?:\.\d{1,2})?)"
    elif field_path.endswith(".budgetCapCents"):
        pattern = r"(?:组织者)?个人预算上限\s*[:：]\s*(\d+(?:\.\d{1,2})?)"
    else:
        pattern = ""
    if pattern:
        match = re.search(pattern, raw_conversation)
        if match is not None:
            return match.group(1)

    if isinstance(value, date):
        candidate = value.isoformat()
    elif isinstance(value, bool):
        candidates = (
            ("避开楼梯", "需要避开楼梯", "不走楼梯")
            if value
            else ("无需避开楼梯", "不需要避开楼梯")
        )
        candidate = next((item for item in candidates if item in raw_conversation), "")
    else:
        candidate = str(value)
    if candidate and candidate in raw_conversation:
        return candidate
    raise TripSchemaError(
        [
            ValidationIssue(
                path=field_path,
                code="evidence_source_mismatch",
                message="Extracted organizer value is not grounded in the fixed questionnaire",
            )
        ]
    )


def _understanding_fallback(
    failure_code: TripUnderstandingFailureCode,
    call_count: int,
    model: str | None,
) -> TripUnderstandingGatewayResult:
    return TripUnderstandingGatewayResult(
        decision="FIXED_QUESTIONS",
        proposal=None,
        failure_code=failure_code,
        call_count=call_count,
        model=model,
    )


def _validation_error_summary(error: ValidationError) -> str:
    return json.dumps(error.errors(), ensure_ascii=False, separators=(",", ":"))


class UnavailableLlmGateway:
    """Stable no-Key boundary used by S2-T009 to choose deterministic enumeration."""

    async def select(
        self,
        request: ProviderCandidateSelectionRequest,
    ) -> CandidateSelectionGatewayResult:
        trusted_request = _strict_request(request)
        return _fallback(
            request=trusted_request,
            request_digest=_request_digest(trusted_request),
            failure_code="LLM_NOT_CONFIGURED",
            call_count=0,
            model=None,
        )


def _strict_request(
    request: ProviderCandidateSelectionRequest,
) -> ProviderCandidateSelectionRequest:
    try:
        return ProviderCandidateSelectionRequest.model_validate_json(
            request.model_dump_json(by_alias=True),
            strict=True,
        )
    except ValidationError as error:
        raise CandidateSelectionContractError(
            "CANDIDATE_SELECTION_REQUEST_INVALID"
        ) from error


def _request_digest(request: ProviderCandidateSelectionRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{sha256(canonical).hexdigest()}"


def _proposal_is_grounded(
    request: ProviderCandidateSelectionRequest,
    proposal: ProviderCandidateSelectionProposal,
) -> bool:
    facts_by_id = {
        item.place_fact_id: item for item in request.candidate_facts
    }
    selected = [facts_by_id[item] for item in proposal.selected_place_fact_ids]
    rationale = _fold(proposal.selection_rationale)

    for fact in selected:
        grounding_terms = (
            fact.display_name,
            *fact.category_tags,
            *fact.known_attributes,
        )
        if not any(_fold(term) in rationale for term in grounding_terms):
            return False

    risk_flags = [
        _fold(flag)
        for fact in selected
        for flag in fact.risk_flags
    ]
    return all(
        any(
            flag in _fold(note) or _fold(note) in flag
            for flag in risk_flags
        )
        for note in proposal.risk_notes
    )


def _fold(value: str) -> str:
    return normalize("NFKC", value).casefold()


def _fallback(
    *,
    request: ProviderCandidateSelectionRequest,
    request_digest: str,
    failure_code: CandidateSelectionFailureCode,
    call_count: int,
    model: str | None,
) -> CandidateSelectionGatewayResult:
    return CandidateSelectionGatewayResult(
        trace_id=request.trace_id,
        request_digest=request_digest,
        decision="DETERMINISTIC_ENUMERATION",
        proposal=None,
        failure_code=failure_code,
        call_count=call_count,
        model=model,
    )


__all__ = [
    "CandidateSelectionContractError",
    "CandidateSelectionGateway",
    "CandidateSelectionModelClient",
    "CandidateSelectionTransportError",
    "MemberProfileEvidence",
    "MemberProfileModelProposal",
    "OrganizerTripModelProposal",
    "StrictTripUnderstandingGateway",
    "StrictCandidateSelectionGateway",
    "TripUnderstandingGateway",
    "TripUnderstandingModelClient",
    "TripUnderstandingTransportError",
    "UnavailableLlmGateway",
    "UnavailableTripUnderstandingGateway",
]
