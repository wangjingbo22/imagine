from __future__ import annotations

from typing import Annotated, Literal
from unicodedata import normalize
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.schemas.trip import ContractModel


ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
FactId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[A-Za-z0-9._:-]{1,160}$",
    ),
]
CityCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[A-Za-z0-9._:-]{1,32}$",
    ),
]
FactDigest = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^sha256:[0-9a-f]{64}$",
    ),
]
RiskNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=180),
]

_SENSITIVE_FACT_TERMS = (
    "price",
    "cost",
    "amount",
    "route",
    "score",
    "pass",
    "planid",
    "planversion",
    "validationstatus",
    "coordinate",
    "longitude",
    "latitude",
    "价格",
    "费用",
    "预算",
    "路线",
    "距离",
    "时长",
    "评分",
    "分数",
    "坐标",
    "金额",
)
_PROMPT_INJECTION_TERMS = (
    "ignore previous",
    "ignore all",
    "system prompt",
    "developer message",
    "assistant message",
    "jailbreak",
    "忽略以上",
    "忽略前文",
    "无视以上",
    "系统提示",
    "越狱",
    "改写指令",
    "请输出",
    "必须输出",
)


class ConfirmedTripSummary(ContractModel):
    """A redacted, read-only intent summary supplied by the server."""

    city_code: CityCode
    participant_count: Annotated[int, Field(ge=1, le=3)]
    interest_tags: tuple[ShortText, ...] = Field(max_length=12)
    must_visit_labels: tuple[ShortText, ...] = Field(max_length=8)
    avoid_labels: tuple[ShortText, ...] = Field(max_length=8)
    care_need_labels: tuple[ShortText, ...] = Field(max_length=8)


class ProviderCandidateFact(ContractModel):
    """A safe projection of one opaque, server-issued S2-T006 FactRef.

    Coordinates, prices, routes, scores, constraints and provider payloads are
    deliberately absent.  S2-T009 must restore the authoritative fact by
    placeFactId and verify factDigest before planning.
    """

    place_fact_id: FactId
    fact_digest: FactDigest
    display_name: ShortText
    category_tags: tuple[ShortText, ...] = Field(max_length=8)
    known_attributes: tuple[ShortText, ...] = Field(max_length=8)
    risk_flags: tuple[RiskNote, ...] = Field(max_length=8)


class ProviderCandidateSelectionRequest(ContractModel):
    schema_version: Literal["1.0"]
    trace_id: UUID
    confirmed_trip_summary: ConfirmedTripSummary
    candidate_facts: tuple[ProviderCandidateFact, ...] = Field(
        min_length=6,
        max_length=8,
    )
    allowed_task_count: tuple[Literal[3], Literal[4]]

    @model_validator(mode="after")
    def validate_server_fact_allowlist(self) -> "ProviderCandidateSelectionRequest":
        fact_ids = [item.place_fact_id for item in self.candidate_facts]
        digests = [item.fact_digest for item in self.candidate_facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("candidateFacts must use unique placeFactId values")
        if len(digests) != len(set(digests)):
            raise ValueError("candidateFacts must use unique factDigest values")

        model_visible_text = [
            self.confirmed_trip_summary.city_code,
            *self.confirmed_trip_summary.interest_tags,
            *self.confirmed_trip_summary.must_visit_labels,
            *self.confirmed_trip_summary.avoid_labels,
            *self.confirmed_trip_summary.care_need_labels,
        ]
        for item in self.candidate_facts:
            model_visible_text.extend(
                (
                    item.place_fact_id,
                    item.display_name,
                    *item.category_tags,
                    *item.known_attributes,
                    *item.risk_flags,
                )
            )
        folded = _fold(" ".join(model_visible_text))
        if any(term in folded for term in _SENSITIVE_FACT_TERMS):
            raise ValueError(
                "candidate projection cannot contain price, route, score or plan facts"
            )
        if any(term in folded for term in _PROMPT_INJECTION_TERMS):
            raise ValueError("candidate projection contains prompt-injection text")
        return self


class ProviderCandidateSelectionProposal(ContractModel):
    """The complete model-authored payload admitted at the S2-T008 boundary."""

    schema_version: Literal["1.0"]
    selected_place_fact_ids: tuple[FactId, ...] = Field(
        min_length=2,
        max_length=3,
    )
    selection_rationale: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
    ]
    risk_notes: tuple[RiskNote, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def validate_explanation_boundary(self) -> "ProviderCandidateSelectionProposal":
        if len(self.selected_place_fact_ids) != len(
            set(self.selected_place_fact_ids)
        ):
            raise ValueError("selectedPlaceFactIds must be unique")

        text = _fold(" ".join((self.selection_rationale, *self.risk_notes)))
        forbidden_terms = (
            "pass",
            "hard",
            "score",
            "评分",
            "分数",
            "价格",
            "费用",
            "预算",
            "路线",
            "planid",
            "planversion",
            "current",
            "constraint",
            "satisfaction",
            "distance",
            "duration",
            "coordinate",
            "保证",
            "确保",
            "必然",
            "约束",
            "通过",
            "合格",
            "满意度",
            "距离",
            "时长",
            "坐标",
            "¥",
            "￥",
        )
        if any(term in text for term in forbidden_terms):
            raise ValueError(
                "model explanation cannot assert price, route, score, PASS or plan state"
            )
        if any(
            not any(
                marker in note
                for marker in ("未知", "待确认", "未确认", "待核实", "缺少")
            )
            for note in self.risk_notes
        ):
            raise ValueError("riskNotes may only describe unknown or unconfirmed facts")
        return self


def _fold(value: str) -> str:
    return normalize("NFKC", value).casefold()


CandidateSelectionFailureCode = Literal[
    "LLM_NOT_CONFIGURED",
    "LLM_TIMEOUT",
    "LLM_AUTH_FAILED",
    "LLM_UNAVAILABLE",
    "LLM_INVALID_JSON",
    "LLM_SCHEMA_INVALID",
    "LLM_OUT_OF_ALLOWLIST",
]


class CandidateSelectionGatewayResult(ContractModel):
    trace_id: UUID
    request_digest: Annotated[
        str,
        StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
    ]
    decision: Literal["MODEL_PROPOSAL", "DETERMINISTIC_ENUMERATION"]
    proposal: ProviderCandidateSelectionProposal | None
    failure_code: CandidateSelectionFailureCode | None
    call_count: Annotated[int, Field(ge=0, le=2)]
    model: ShortText | None = None

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "CandidateSelectionGatewayResult":
        if self.decision == "MODEL_PROPOSAL":
            if self.proposal is None or self.failure_code is not None:
                raise ValueError("MODEL_PROPOSAL requires proposal without failureCode")
            if self.call_count < 1:
                raise ValueError("MODEL_PROPOSAL requires at least one model call")
        else:
            if self.proposal is not None or self.failure_code is None:
                raise ValueError(
                    "DETERMINISTIC_ENUMERATION requires failureCode without proposal"
                )
        return self


__all__ = [
    "CandidateSelectionFailureCode",
    "CandidateSelectionGatewayResult",
    "ConfirmedTripSummary",
    "ProviderCandidateFact",
    "ProviderCandidateSelectionProposal",
    "ProviderCandidateSelectionRequest",
]
