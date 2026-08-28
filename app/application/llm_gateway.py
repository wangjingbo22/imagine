from __future__ import annotations

from hashlib import sha256
import json
import logging
from typing import Protocol
from unicodedata import normalize

from pydantic import ValidationError

from app.domain.trip_draft import (
    TripUnderstandingFailureCode,
    TripUnderstandingGatewayResult,
    TripUnderstandingProposal,
    TripUnderstandingRequest,
    validate_trip_understanding,
)
from app.schemas.validation_error import TripSchemaError
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


class TripUnderstandingModelClient(Protocol):
    model: str

    async def propose_trip_understanding(
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
        call_count = 0

        while call_count < self._max_transport_attempts:
            call_count += 1
            try:
                raw = await self._client.propose_trip_understanding(
                    trusted_request
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
                return _understanding_fallback(
                    failure_code,
                    call_count,
                    self._client.model,
                )

            try:
                proposal = validate_trip_understanding(trusted_request, proposal)
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

        raise AssertionError("trip understanding loop must return")


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
    "StrictTripUnderstandingGateway",
    "StrictCandidateSelectionGateway",
    "TripUnderstandingGateway",
    "TripUnderstandingModelClient",
    "TripUnderstandingTransportError",
    "UnavailableLlmGateway",
    "UnavailableTripUnderstandingGateway",
]
