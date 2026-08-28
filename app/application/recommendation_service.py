"""Deterministic S2 candidate issuer and strict LLM-ranking boundary."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from itertools import combinations
from typing import Literal, Protocol
from unicodedata import normalize
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from app.application.collaboration_ports import (
    CollaborationReadinessGuard,
    PlanningAccess,
    PlanningOperation,
    TripDraftRevisionView,
)
from app.application.llm_gateway import CandidateSelectionGateway
from app.core.errors import AppError
from app.domain.recommendation import (
    CandidatePlace,
    CandidateRecommendation,
    FactRef,
    LlmRanking,
    MemberScore,
    RecommendationBundle,
    TrustedPlan,
)
from app.domain.models import Place, SourceStatus
from app.domain.hard_conflicts import assistance_profile_from_care
from app.services.fairness import (
    DeterministicFairRecommendationService,
    FairRecommendationCandidate,
    NoFairCandidateError,
)
from app.services.planning import (
    CandidatePlanInputError,
    CandidatePlanRejected,
    DeterministicCandidatePlanner,
)
from app.services.recommendation import (
    BuiltRouteCandidate,
    FallbackReason,
    ProviderCandidateSelectionProposal,
    ProviderCandidateSelectionRequest,
    ProviderCandidateFactView,
    ProviderFactBundle,
    ProviderFactIssueDraft,
    ProviderFactSetSummary,
    RecommendationOrchestrationRequest,
    RecommendationOrchestrationResult,
)
from app.schemas.llm import (
    ConfirmedTripSummary,
    ProviderCandidateFact,
)
from app.schemas.constraint import Constraint
from app.schemas.trip import (
    CityContext,
    Participant,
    Preference,
    PreferenceType,
    Trip,
    TripDayInput,
    TripMode,
    TripStatus,
)
from app.services.planning.models import CandidateEndpointFact


class RecommendationOrchestrationError(ValueError):
    def __init__(self, code: str, message: str, *, http_status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class ProviderFactRestoreError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


GatewayFailureCode = Literal["LLM_UNAVAILABLE", "LLM_TIMEOUT"]


class CandidateProposalGatewayError(RuntimeError):
    def __init__(self, code: GatewayFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class RouteCandidateBuildError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RawCandidateProposal:
    payload: bytes
    provider_fact_digest: str


class ProviderFactRegistryPort(Protocol):
    """T006 seam: restore and verify an already issued server fact set."""

    def restore(
        self,
        trip_id: UUID,
        fact_set_id: str,
    ) -> ProviderFactBundle: ...

    def issue(self, draft: ProviderFactIssueDraft) -> ProviderFactSetSummary: ...


class CandidateProposalGatewayPort(Protocol):
    """T008 seam: one Qwen call returning an untrusted strict-JSON payload."""

    async def propose(
        self,
        request: ProviderCandidateSelectionRequest,
    ) -> RawCandidateProposal: ...


class RouteCandidateBuilderPort(Protocol):
    """Provider seam that resolves true routes for an allowlisted ID order."""

    async def build(
        self,
        facts: ProviderFactBundle,
        selected_place_fact_ids: tuple[str, ...],
    ) -> BuiltRouteCandidate: ...


@dataclass(frozen=True, slots=True)
class _BuiltCandidates:
    candidates: tuple[FairRecommendationCandidate, ...]
    selected_ids_by_candidate: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class IssuedProviderCandidates:
    summary: ProviderFactSetSummary
    facts: tuple[FactRef, ...]


class RecommendationOrchestrationService:
    """T009 orchestration; it owns no FactRef registry or model transport."""

    _MAX_ENUMERATED_ORDERS = 12

    def __init__(
        self,
        *,
        fact_registry: ProviderFactRegistryPort,
        route_builder: RouteCandidateBuilderPort | None,
        readiness_guard: CollaborationReadinessGuard,
        proposal_gateway: CandidateProposalGatewayPort | None = None,
        candidate_selection_gateway: CandidateSelectionGateway | None = None,
        planner: DeterministicCandidatePlanner | None = None,
        fairness: DeterministicFairRecommendationService | None = None,
    ) -> None:
        if proposal_gateway is None and candidate_selection_gateway is None:
            raise ValueError("a candidate selection gateway is required")
        self._readiness_guard = readiness_guard
        self._fact_registry = fact_registry
        self._proposal_gateway = proposal_gateway
        self._candidate_selection_gateway = candidate_selection_gateway
        self._route_builder = route_builder
        self._planner = planner or DeterministicCandidatePlanner()
        self._fairness = fairness or DeterministicFairRecommendationService()

    @property
    def readiness_guard(self) -> CollaborationReadinessGuard:
        return self._readiness_guard

    @property
    def candidate_selection_gateway(self) -> CandidateSelectionGateway | None:
        """Expose the canonical T008 seam for runtime composition checks."""

        return self._candidate_selection_gateway

    async def recommend(
        self,
        *,
        trip_id: UUID,
        request: RecommendationOrchestrationRequest,
        access: PlanningAccess,
    ) -> RecommendationOrchestrationResult:
        if (
            access.trip_id != trip_id
            or access.operation is not PlanningOperation.RECOMMENDATION
        ):
            raise AppError(
                "PLANNING_ACCESS_INVALID",
                "推荐访问上下文不匹配",
                409,
                False,
            )
        with self._readiness_guard.operation(access):
            return await self._recommend_ready(trip_id=trip_id, request=request)

    async def _recommend_ready(
        self,
        *,
        trip_id: UUID,
        request: RecommendationOrchestrationRequest,
    ) -> RecommendationOrchestrationResult:
        if self._route_builder is None:
            # The conversation preview can use the strict T008 gateway without
            # a route builder.  The signed T006 -> T009 endpoint must instead
            # fail before any model call until the Provider-owned builder is
            # explicitly composed.
            raise RecommendationOrchestrationError(
                "ROUTE_CANDIDATE_BUILDER_UNAVAILABLE",
                "可信路线候选构建器尚未配置",
                http_status=503,
            )
        facts = self._restore_facts(trip_id, request)
        trace_id = _trace_id(trip_id, facts)

        proposal: ProviderCandidateSelectionProposal | None = None
        fallback_reason: FallbackReason | None = None
        try:
            llm_request = _strict_candidate_request(trace_id, facts)
        except (ValidationError, ValueError, TypeError):
            # User/provider text that cannot be safely projected must never be
            # sent to a model.  Deterministic enumeration remains available.
            llm_request = None
            fallback_reason = "LLM_SCHEMA_INVALID"

        if llm_request is not None and self._candidate_selection_gateway is not None:
            gateway_result = await self._candidate_selection_gateway.select(llm_request)
            if gateway_result.decision == "MODEL_PROPOSAL":
                proposal = gateway_result.proposal
            else:
                fallback_reason = gateway_result.failure_code or "LLM_UNAVAILABLE"
        elif llm_request is not None and self._proposal_gateway is not None:
            # Compatibility bridge for the earlier T009 raw-payload port.  It
            # now receives the same redacted T008 request and its response is
            # parsed by the one canonical strict proposal schema.
            try:
                raw = await self._proposal_gateway.propose(llm_request)
                if raw.provider_fact_digest != facts.provider_fact_digest:
                    fallback_reason = "LLM_DIGEST_MISMATCH"
                else:
                    try:
                        proposal = ProviderCandidateSelectionProposal.model_validate_json(
                            raw.payload,
                            strict=True,
                        )
                    except (ValidationError, ValueError, TypeError):
                        fallback_reason = "LLM_FORMAT_INVALID"
                    if proposal is not None and not self._inside_allowlist(
                        proposal,
                        facts,
                    ):
                        proposal = None
                        fallback_reason = "LLM_ALLOWLIST_VIOLATION"
            except CandidateProposalGatewayError as error:
                fallback_reason = error.code

        if proposal is not None:
            built = await self._build_candidates(
                facts,
                _proposal_orders(proposal.selected_place_fact_ids),
            )
            decision = self._select(facts, built)
            if decision is not None:
                return self._result(
                    facts=facts,
                    trace_id=str(trace_id),
                    built=built,
                    decision=decision,
                    strategy="LLM_PROPOSAL",
                    fallback_reason=None,
                    rationale=proposal.selection_rationale,
                    risk_notes=proposal.risk_notes,
                )
            fallback_reason = "LLM_PROPOSAL_UNUSABLE"

        fallback_reason = fallback_reason or "LLM_UNAVAILABLE"
        built = await self._build_candidates(
            facts,
            _deterministic_orders(
                tuple(item.place_fact_id for item in facts.candidate_facts),
                limit=self._MAX_ENUMERATED_ORDERS,
            ),
        )
        decision = self._select(facts, built)
        if decision is None:
            raise RecommendationOrchestrationError(
                "NO_RECOMMENDATION",
                "服务端白名单中没有通过真实路线和 HARD 约束的候选方案",
            )
        return self._result(
            facts=facts,
            trace_id=str(trace_id),
            built=built,
            decision=decision,
            strategy="DETERMINISTIC_FALLBACK",
            fallback_reason=fallback_reason,
            rationale="AI 辅助不可用，已按服务端白名单、真实路线与公平规则确定唯一方案。",
            risk_notes=(
                "已使用确定性枚举；地点、路线、费用和来源均从服务端事实恢复。",
            ),
        )

    async def recommend_preview_from_provider_facts(
        self,
        *,
        trip_id: UUID,
        facts: Sequence[FactRef],
        city_code: str,
        interests: Sequence[str],
        must_visit: Sequence[str],
        avoid_places: Sequence[str],
        care_need_labels: Sequence[str],
        members: Sequence["MemberPreference"],
    ) -> RecommendationBundle:
        """Serve the collaboration UI through the same T008 gateway.

        The v2 conversation flow does not yet own a planning ``Trip`` at this
        screen, so it cannot invoke the route-backed v1 decision method.  It
        nevertheless reuses this orchestration object and the identical strict
        model boundary for its provider-backed preview; final routing and HARD
        validation remain in the v1 flow.
        """

        trusted = TrustedRecommendationService()
        candidates = trusted.issue_candidates(
            facts,
            interests=interests,
            must_visit=must_visit,
            avoid_places=avoid_places,
        )
        if not candidates:
            raise RecommendationOrchestrationError(
                "NO_RECOMMENDATION",
                "服务端没有可用于推荐的可信地点事实",
            )

        ranking: LlmRanking | None = None
        gateway = self._candidate_selection_gateway
        if gateway is not None and 6 <= len(candidates) <= 8:
            facts_by_ref = {item.fact_ref_id: item for item in facts}
            try:
                request = ProviderCandidateSelectionRequest(
                    schema_version="1.0",
                    trace_id=uuid5(
                        NAMESPACE_URL,
                        "xingzhi:recommendation-preview:"
                        + str(trip_id)
                        + ":"
                        + ",".join(item.fact_ref_id for item in candidates),
                    ),
                    confirmed_trip_summary=ConfirmedTripSummary(
                        city_code=city_code,
                        participant_count=len(members),
                        interest_tags=_stable_unique_text(interests, limit=12),
                        must_visit_labels=_stable_unique_text(must_visit, limit=8),
                        avoid_labels=_stable_unique_text(avoid_places, limit=8),
                        care_need_labels=_stable_unique_text(
                            care_need_labels,
                            limit=8,
                        ),
                    ),
                    candidate_facts=tuple(
                        _safe_preview_candidate_fact(
                            facts_by_ref[item.fact_ref_id]
                        )
                        for item in candidates
                    ),
                    allowed_task_count=(3, 4),
                )
                gateway_result = await gateway.select(request)
                if (
                    gateway_result.decision == "MODEL_PROPOSAL"
                    and gateway_result.proposal is not None
                ):
                    by_ref = {item.fact_ref_id: item for item in candidates}
                    proposal = gateway_result.proposal
                    ranking = LlmRanking(
                        recommendations=[
                            CandidateRecommendation(
                                place_id=by_ref[fact_id].place_id,
                                reason=proposal.selection_rationale[:80],
                            )
                            for fact_id in proposal.selected_place_fact_ids
                        ]
                    )
            except (ValidationError, ValueError, TypeError, KeyError):
                # Unsafe projection or an unusable model result must not make
                # the preview unavailable; deterministic ranking is canonical.
                ranking = None

        bundle = trusted.rank(candidates, ranking)
        return trusted.choose_single_plan(bundle, facts, members)

    def issue_provider_candidate_facts(
        self,
        *,
        trip: Trip,
        start_location: CandidateEndpointFact,
        end_location: CandidateEndpointFact,
        confirmed_constraints: tuple[Constraint, ...],
        confirmed_trip_summary: dict[str, object],
        provider_places: Sequence[Place],
    ) -> IssuedProviderCandidates:
        """Filter and sign the T030 allowlist before any LLM sees it."""

        places = TrustedRecommendationService.pre_filter_provider_places(
            provider_places,
            trip=trip,
        )
        draft = ProviderFactIssueDraft(
            trip=trip,
            start_location=start_location,
            end_location=end_location,
            confirmed_constraints=confirmed_constraints,
            confirmed_trip_summary=confirmed_trip_summary,
            places=tuple(places),
            routes=(),
        )
        summary = self._fact_registry.issue(draft)
        places_by_id = {item.placeId: item for item in places}
        facts = tuple(
            FactRef(
                fact_ref_id=reference.fact_ref_id,
                place=places_by_id[reference.provider_object_id],
            )
            for reference in summary.references
            if reference.kind == "PLACE"
        )
        if not 6 <= len(facts) <= 8:
            raise RecommendationOrchestrationError(
                "PROVIDER_FACT_ISSUANCE_INVALID",
                "服务端 FactRef 签发结果必须包含 6–8 个地点候选",
                http_status=500,
            )
        return IssuedProviderCandidates(summary=summary, facts=facts)

    def _restore_facts(
        self,
        trip_id: UUID,
        request: RecommendationOrchestrationRequest,
    ) -> ProviderFactBundle:
        try:
            facts = self._fact_registry.restore(trip_id, request.fact_set_id)
        except ProviderFactRestoreError as error:
            raise RecommendationOrchestrationError(
                error.code,
                error.message,
                http_status=409,
            ) from error
        if facts.trip.trip_id != trip_id:
            raise RecommendationOrchestrationError(
                "PROVIDER_FACT_TRIP_MISMATCH",
                "恢复的 FactRef 不属于当前 Trip",
                http_status=409,
            )
        if facts.fact_set_id != request.fact_set_id:
            raise RecommendationOrchestrationError(
                "PROVIDER_FACT_SET_MISMATCH",
                "恢复的 FactRef 集合 ID 与请求不一致",
                http_status=409,
            )
        if facts.provider_fact_digest != request.provider_fact_digest:
            raise RecommendationOrchestrationError(
                "PROVIDER_FACT_DIGEST_MISMATCH",
                "请求摘要与服务端签发的 FactRef 摘要不一致",
                http_status=409,
            )
        return facts

    @staticmethod
    def _inside_allowlist(
        proposal: ProviderCandidateSelectionProposal,
        facts: ProviderFactBundle,
    ) -> bool:
        allowed = {item.place_fact_id for item in facts.candidate_facts}
        return set(proposal.selected_place_fact_ids) <= allowed

    async def _build_candidates(
        self,
        facts: ProviderFactBundle,
        orders: Sequence[tuple[str, ...]],
    ) -> _BuiltCandidates:
        if self._route_builder is None:
            raise RecommendationOrchestrationError(
                "ROUTE_CANDIDATE_BUILDER_UNAVAILABLE",
                "可信路线候选构建器尚未配置",
                http_status=503,
            )
        candidates: list[FairRecommendationCandidate] = []
        selected_ids_by_candidate: dict[str, tuple[str, ...]] = {}
        for order in orders:
            try:
                built = await self._route_builder.build(facts, order)
                self._validate_built_candidate(facts, order, built)
                plan = self._planner.generate(built.request)
            except (
                RouteCandidateBuildError,
                CandidatePlanInputError,
                CandidatePlanRejected,
                ValidationError,
                ValueError,
            ):
                continue
            if plan.candidate_id in selected_ids_by_candidate:
                continue
            candidates.append(
                FairRecommendationCandidate(
                    plan=plan,
                    provider_fact_digest=facts.provider_fact_digest,
                    detour_meters=built.detour_meters,
                )
            )
            selected_ids_by_candidate[plan.candidate_id] = order
        return _BuiltCandidates(tuple(candidates), selected_ids_by_candidate)

    @staticmethod
    def _validate_built_candidate(
        facts: ProviderFactBundle,
        requested_order: tuple[str, ...],
        built: BuiltRouteCandidate,
    ) -> None:
        if built.selected_place_fact_ids != requested_order:
            raise RouteCandidateBuildError("route builder changed selected FactRef order")
        if built.request.trip != facts.trip:
            raise RouteCandidateBuildError("route candidate changed the confirmed Trip")
        if built.request.start_location != facts.start_location:
            raise RouteCandidateBuildError("route candidate changed the trusted start")
        if built.request.end_location != facts.end_location:
            raise RouteCandidateBuildError("route candidate changed the trusted end")
        if built.request.confirmed_constraints != facts.confirmed_constraints:
            raise RouteCandidateBuildError("route candidate changed confirmed constraints")

        by_fact_id = {
            item.place_fact_id: item.provider_place_id
            for item in facts.candidate_facts
        }
        allowed_provider_ids = set(by_fact_id.values())
        task_provider_ids = [
            item.place.placeId for item in built.request.task_facts
        ]
        if not set(task_provider_ids) <= allowed_provider_ids:
            raise RouteCandidateBuildError("route candidate contains a non-allowlisted place")
        required_provider_ids = {by_fact_id[item] for item in requested_order}
        if not required_provider_ids <= set(task_provider_ids):
            raise RouteCandidateBuildError("route candidate omitted a selected FactRef")

    def _select(
        self,
        facts: ProviderFactBundle,
        built: _BuiltCandidates,
    ):
        if not built.candidates:
            return None
        try:
            return self._fairness.select_unique(
                trip=facts.trip,
                candidates=built.candidates,
            )
        except NoFairCandidateError:
            return None

    @staticmethod
    def _result(
        *,
        facts: ProviderFactBundle,
        trace_id: str,
        built: _BuiltCandidates,
        decision,
        strategy: Literal["LLM_PROPOSAL", "DETERMINISTIC_FALLBACK"],
        fallback_reason: FallbackReason | None,
        rationale: str,
        risk_notes: tuple[str, ...],
    ) -> RecommendationOrchestrationResult:
        selected_ids = built.selected_ids_by_candidate[
            decision.selected_plan.candidate_id
        ]
        return RecommendationOrchestrationResult(
            trip_id=facts.trip.trip_id,
            trace_id=trace_id,
            provider_fact_digest=facts.provider_fact_digest,
            strategy=strategy,
            fallback_reason=fallback_reason,
            selected_place_fact_ids=selected_ids,
            selection_rationale=rationale,
            risk_notes=risk_notes,
            decision=decision,
        )


def _trace_id(trip_id: UUID, facts: ProviderFactBundle) -> UUID:
    seed = f"{trip_id}:{facts.fact_set_id}:{facts.provider_fact_digest}"
    return uuid5(NAMESPACE_URL, f"xingzhi:recommendation:{seed}")


def _strict_candidate_request(
    trace_id: UUID,
    facts: ProviderFactBundle,
) -> ProviderCandidateSelectionRequest:
    """Project a restored T006 bundle into T008's model-safe contract.

    The source view intentionally retains Provider facts needed by deterministic
    routing and pricing.  Only a fixed, non-authoritative subset crosses this
    adapter: opaque FactRef identity, display/category labels, source class and
    an optional stale-cache risk marker.  Arbitrary ``knownAttributes`` values,
    coordinates, prices, routes, scores and workflow state never cross it.
    """

    trip = facts.trip
    interests: list[str] = []
    must_visit: list[str] = []
    avoid: list[str] = []
    care: list[str] = []
    for participant in trip.participants:
        for preference in participant.preferences:
            target = (
                interests
                if preference.type is PreferenceType.INTEREST
                else must_visit
                if preference.type is PreferenceType.MUST_VISIT
                else avoid
            )
            target.append(preference.value)
        profile = participant.assistance_profile
        if profile is not None:
            care.append(profile.type.value)
            if profile.avoid_stairs:
                care.append("避开楼梯")

    summary = ConfirmedTripSummary(
        city_code=trip.city_context.city_code,
        participant_count=len(trip.participants),
        interest_tags=_stable_unique_text(interests, limit=12),
        must_visit_labels=_stable_unique_text(must_visit, limit=8),
        avoid_labels=_stable_unique_text(avoid, limit=8),
        care_need_labels=_stable_unique_text(care, limit=8),
    )
    candidate_facts = tuple(
        _safe_candidate_fact(item, facts.provider_fact_digest)
        for item in facts.candidate_facts
    )
    return ProviderCandidateSelectionRequest(
        schema_version="1.0",
        trace_id=trace_id,
        confirmed_trip_summary=summary,
        candidate_facts=candidate_facts,
        allowed_task_count=(3, 4),
    )


def _safe_candidate_fact(
    fact: ProviderCandidateFactView,
    provider_fact_digest: str,
) -> ProviderCandidateFact:
    digest = fact.fact_digest or sha256(
        (
            f"{provider_fact_digest}:{fact.place_fact_id}:"
            f"{fact.provider_place_id}:{fact.name}:{fact.category}:"
            f"{fact.source_status.value}"
        ).encode("utf-8")
    ).hexdigest()
    source_label = {
        "ONLINE": "在线来源已核验",
        "VERIFIED_CACHE": "缓存来源已核验",
        "USER_CONFIRMED": "用户来源已确认",
    }.get(fact.source_status.value, "来源待确认")
    risk_flags = (
        ("缓存时效待确认",)
        if fact.known_attributes.get("isStale") is True
        else ()
    )
    return ProviderCandidateFact(
        place_fact_id=fact.place_fact_id,
        fact_digest=f"sha256:{digest}",
        display_name=fact.name,
        category_tags=(fact.category,),
        known_attributes=(source_label,),
        risk_flags=risk_flags,
    )


def _safe_preview_candidate_fact(fact: FactRef) -> ProviderCandidateFact:
    place = fact.place
    digest = sha256(place.model_dump_json().encode("utf-8")).hexdigest()
    source_label = {
        "ONLINE": "在线来源已核验",
        "VERIFIED_CACHE": "缓存来源已核验",
        "USER_CONFIRMED": "用户来源已确认",
    }.get(place.provenance.sourceStatus.value, "来源待确认")
    return ProviderCandidateFact(
        place_fact_id=fact.fact_ref_id,
        fact_digest=f"sha256:{digest}",
        display_name=place.name,
        category_tags=((place.category,) if place.category else ()),
        known_attributes=(source_label,),
        risk_flags=(
            ("缓存时效待确认",)
            if place.provenance.isStale
            else ()
        ),
    )


def _stable_unique_text(values: Sequence[str], *, limit: int) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip().casefold()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value.strip())
        if len(result) == limit:
            break
    return tuple(result)


def _normalized_text(value: str) -> str:
    return " ".join(normalize("NFKC", value).strip().casefold().split())


def _place_matches_label(place: Place, label: str) -> bool:
    expected = _normalized_text(label)
    if not expected:
        return False
    name = _normalized_text(place.name)
    provider_id = _normalized_text(place.placeId)
    return (
        expected == provider_id
        or expected in name
        or name in expected
    )


def project_collaboration_recommendation_trip(
    revision: TripDraftRevisionView,
    city_context: CityContext,
) -> Trip:
    """Project a READY 1–3 member revision without writing planning state."""

    shared = revision.understanding.trip
    required_shared = {
        "trip.cityName": shared.city_name,
        "trip.travelDate": shared.travel_date,
        "trip.startTime": shared.start_time,
        "trip.endTime": shared.end_time,
        "trip.startLocationText": shared.start_location_text,
        "trip.endLocationText": shared.end_location_text,
        "trip.budgetCents": shared.budget_cents,
    }
    missing = [path for path, value in required_shared.items() if value is None]
    projected_participants: list[Participant] = []
    for index, item in enumerate(revision.understanding.participants):
        participant_id = revision.member_bindings.get(item.member_key)
        fields = {
            f"participants[{index}].participantId": participant_id,
            f"participants[{index}].nickname": item.nickname,
            f"participants[{index}].budgetCapCents": item.budget_cap_cents,
            f"participants[{index}].careDraft": item.care_draft,
        }
        missing.extend(path for path, value in fields.items() if value is None)
        if any(value is None for value in fields.values()):
            continue
        assert isinstance(participant_id, UUID)
        assert item.nickname is not None
        assert item.budget_cap_cents is not None
        assert item.care_draft is not None
        preferences = [
            Preference(
                type=PreferenceType.INTEREST,
                value=value,
                weight=4,
                is_hard=False,
            )
            for value in item.interests
        ]
        preferences.extend(
            Preference(
                type=PreferenceType.MUST_VISIT,
                value=value,
                weight=5,
                is_hard=True,
            )
            for value in item.must_visit
        )
        preferences.extend(
            Preference(
                type=PreferenceType.AVOID_PLACE,
                value=value,
                weight=5,
                is_hard=True,
            )
            for value in item.avoid_places
        )
        projected_participants.append(
            Participant(
                participant_id=participant_id,
                nickname=item.nickname,
                budget_cap_cents=item.budget_cap_cents,
                preferences=preferences,
                assistance_profile=assistance_profile_from_care(item.care_draft),
            )
        )
    if missing:
        raise AppError(
            "COLLABORATION_CANONICAL_TRIP_INCOMPLETE",
            "READY 协作版本缺少签发 Provider FactRef 所需字段",
            409,
            False,
            errors=[{"path": path, "message": "required"} for path in missing],
        )

    assert shared.travel_date is not None
    assert shared.start_time is not None and shared.end_time is not None
    assert shared.start_location_text is not None
    assert shared.end_location_text is not None
    assert shared.budget_cents is not None
    return Trip(
        schema_version="1.0",
        trip_id=revision.trip_id,
        mode=(
            TripMode.SINGLE
            if len(projected_participants) == 1
            else TripMode.GROUP
        ),
        status=TripStatus.CONSTRAINT_CONFIRMED,
        city_context=city_context,
        start_date=shared.travel_date,
        end_date=shared.travel_date,
        currency="CNY",
        total_budget_cents=shared.budget_cents,
        participants=projected_participants,
        days=[
            TripDayInput(
                day_index=0,
                date=shared.travel_date,
                daily_budget_cents=shared.budget_cents,
                start_location_text=shared.start_location_text,
                end_location_text=shared.end_location_text,
                time_window={
                    "start": f"{shared.start_time}:00",
                    "end": f"{shared.end_time}:00",
                },
            )
        ],
    )


def _proposal_orders(selected: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    candidates: list[tuple[str, ...]] = [selected, tuple(reversed(selected))]
    if len(selected) == 3:
        candidates.extend(
            (
                selected[1:] + selected[:1],
                selected[2:] + selected[:2],
            )
        )
    candidates.append(tuple(sorted(selected)))
    return _unique_orders(candidates)


def _deterministic_orders(
    fact_ids: tuple[str, ...],
    *,
    limit: int,
) -> tuple[tuple[str, ...], ...]:
    ordered = tuple(sorted(fact_ids))
    candidates: list[tuple[str, ...]] = []
    for size in (2, 3):
        for offset in range(1, len(ordered)):
            for start in range(len(ordered)):
                order = tuple(
                    ordered[(start + step * offset) % len(ordered)]
                    for step in range(size)
                )
                if len(set(order)) != size:
                    continue
                if order in candidates:
                    continue
                candidates.append(order)
                if len(candidates) >= limit:
                    return tuple(candidates)
    return tuple(candidates)


def _unique_orders(
    orders: Sequence[tuple[str, ...]],
) -> tuple[tuple[str, ...], ...]:
    seen: set[tuple[str, ...]] = set()
    result: list[tuple[str, ...]] = []
    for order in orders:
        if order in seen:
            continue
        seen.add(order)
        result.append(order)
    return tuple(result)


@dataclass(frozen=True)
class MemberPreference:
    participant_id: str
    interests: tuple[str, ...]
    must_visit: tuple[str, ...]


class TrustedRecommendationService:
    """Issues only provider-backed FactRefs and accepts only an ID whitelist."""

    @staticmethod
    def pre_filter_provider_places(
        places: Sequence[Place],
        *,
        trip: Trip,
    ) -> list[Place]:
        """Apply only deterministic, Provider-observable HARD constraints.

        Route-only care limits remain for the route planner.  At the place
        issuance boundary we can already fail closed on city/source, hard
        avoid labels, duplicate Provider IDs, missing must-visits and a known
        single-place price that exceeds any confirmed trip/member budget cap.
        """

        must_visit: list[str] = []
        avoid_places: list[str] = []
        interests: list[str] = []
        for participant in trip.participants:
            for preference in participant.preferences:
                target = (
                    interests
                    if preference.type is PreferenceType.INTEREST
                    else must_visit
                    if preference.type is PreferenceType.MUST_VISIT
                    else avoid_places
                )
                target.append(preference.value)

        required = _stable_unique_text(must_visit, limit=9)
        if len(required) > 8:
            raise RecommendationOrchestrationError(
                "TOO_MANY_HARD_MUST_VISIT_PLACES",
                "硬性必去地点超过 8 个，无法签发 6–8 个可信候选",
            )
        avoided = _stable_unique_text(avoid_places, limit=24)
        interest_words = tuple(_normalized_text(item) for item in interests)
        budget_limit = min(
            trip.total_budget_cents,
            *(participant.budget_cap_cents for participant in trip.participants),
        )
        trusted_statuses = {SourceStatus.ONLINE, SourceStatus.VERIFIED_CACHE}
        unique: dict[str, Place] = {}
        for place in places:
            if place.placeId in unique:
                continue
            if place.cityCode != trip.city_context.city_code:
                continue
            if place.provenance.sourceStatus not in trusted_statuses:
                continue
            if any(_place_matches_label(place, label) for label in avoided):
                continue
            amount = place.priceReference.amountCents
            if amount is not None and amount > budget_limit:
                continue
            unique[place.placeId] = place

        filtered = list(unique.values())
        missing_required = [
            label
            for label in required
            if not any(_place_matches_label(place, label) for place in filtered)
        ]
        if missing_required:
            raise RecommendationOrchestrationError(
                "HARD_MUST_VISIT_FACT_MISSING",
                "高德/缓存事实未覆盖全部硬性必去地点："
                + "、".join(missing_required),
            )

        def sort_key(place: Place) -> tuple[int, int, int, int, str]:
            is_required = any(
                _place_matches_label(place, label) for label in required
            )
            haystack = _normalized_text(f"{place.name} {place.category or ''}")
            interest_matches = sum(word in haystack for word in interest_words)
            amount = place.priceReference.amountCents
            return (
                0 if is_required else 1,
                -interest_matches,
                0 if place.provenance.sourceStatus is SourceStatus.ONLINE else 1,
                amount if amount is not None else 10**12,
                place.placeId,
            )

        selected = sorted(filtered, key=sort_key)[:8]
        if len(selected) < 6:
            raise RecommendationOrchestrationError(
                "INSUFFICIENT_TRUSTED_PROVIDER_CANDIDATES",
                "硬约束预过滤后不足 6 个高德/缓存地点，禁止签发 FactRef",
            )
        return selected

    @staticmethod
    def issue_candidates(
        facts: Sequence[FactRef],
        *,
        interests: Sequence[str],
        must_visit: Sequence[str],
        avoid_places: Sequence[str],
    ) -> list[CandidatePlace]:
        avoided = {item.casefold() for item in avoid_places}
        required = {item.casefold() for item in must_visit}
        interest_words = tuple(item.casefold() for item in interests)

        def sort_key(fact: FactRef) -> tuple[int, int, str]:
            place = fact.place
            haystack = f"{place.name} {place.category or ''}".casefold()
            is_required = place.name.casefold() in required
            interest_matches = sum(word in haystack for word in interest_words)
            price = place.priceReference.amountCents
            return (0 if is_required else 1, -interest_matches, price if price is not None else 10**12, place.placeId)

        selected: list[CandidatePlace] = []
        seen: set[str] = set()
        for fact in sorted(facts, key=sort_key):
            place = fact.place
            if place.placeId in seen or place.name.casefold() in avoided:
                continue
            seen.add(place.placeId)
            selected.append(CandidatePlace(
                fact_ref_id=fact.fact_ref_id,
                place_id=place.placeId,
                name=place.name,
                category=place.category,
            ))
            if len(selected) == 8:
                break
        # The UI contract permits 6–8, while sparse provider results must
        # remain usable and must not invent places.
        return selected

    @staticmethod
    def rank(
        candidates: Sequence[CandidatePlace],
        llm_ranking: LlmRanking | None,
    ) -> RecommendationBundle:
        allowed = {item.place_id for item in candidates}
        if llm_ranking is not None:
            ids = [item.place_id for item in llm_ranking.recommendations]
            if len(ids) == len(set(ids)) and set(ids).issubset(allowed):
                return RecommendationBundle(
                    candidates=list(candidates),
                    recommendations=list(llm_ranking.recommendations),
                    used_deterministic_fallback=False,
                )
        return RecommendationBundle(
            candidates=list(candidates),
            recommendations=[
                CandidateRecommendation(place_id=item.place_id, reason="基于已核验地点事实的稳定排序")
                for item in candidates
            ],
            used_deterministic_fallback=True,
        )

    def rank_from_llm_json(
        self,
        candidates: Sequence[CandidatePlace],
        raw: str | None,
    ) -> RecommendationBundle:
        """One-shot parse: invalid/non-JSON/extra fields fall back, never retry."""
        try:
            ranking = LlmRanking.model_validate_json(raw) if raw is not None else None
        except (ValidationError, ValueError, TypeError):
            ranking = None
        return self.rank(candidates, ranking)

    @staticmethod
    def choose_single_plan(
        bundle: RecommendationBundle,
        facts: Sequence[FactRef],
        members: Sequence[MemberPreference],
    ) -> RecommendationBundle:
        """Turn a bounded ranking into exactly one explainable 1–4 task plan.

        The choice is deliberately deterministic.  It favours required places,
        then the existing stable ranking, and scores the *resulting* task set
        for every confirmed member.  No provider fact is invented here.
        """
        candidates_by_id = {item.place_id: item for item in bundle.candidates}
        facts_by_id = {item.place.placeId: item for item in facts}
        ordered = [candidates_by_id[item.place_id] for item in bundle.recommendations if item.place_id in candidates_by_id]
        if not ordered:
            return bundle

        # Exhaustively evaluate at most 126 possible three/four-task selections.
        # The comparison implements the published fairness key exactly:
        # minimum member score desc, average score desc, known price asc, then
        # a stable candidate-id tie break.
        sizes = range(3, min(4, len(ordered)) + 1) if len(ordered) >= 3 else (len(ordered),)
        possible_sets = (tasks for size in sizes for tasks in combinations(ordered, size))
        scored_sets = [(list(tasks), TrustedRecommendationService._score_members(tasks, members), facts_by_id) for tasks in possible_sets]
        tasks, scores, _ = min(
            scored_sets,
            key=lambda entry: TrustedRecommendationService._fairness_sort_key(entry[0], entry[1], facts_by_id),
        )
        # Restore the approved bounded ranking order as the task sequence.  The
        # order is display-only; the task membership came from fairness ranking.
        selected_ids = {task.place_id for task in tasks}
        tasks = [task for task in ordered if task.place_id in selected_ids]

        unknown_facts = [
            f"{task.name} 的价格尚未由高德提供，需要在生成路线时核验"
            for task in tasks
            if (fact := facts_by_id.get(task.place_id)) is not None and fact.place.priceReference.amountCents is None
        ]
        interest_groups = sum(bool(member.interests) for member in members)
        compromises = (["任务组合按最低成员分优先确定，优先避免只满足单一成员的安排"] if len(members) > 1 else [])
        care_points = ["已在进入推荐前完成成员确认与硬冲突筛除"]
        if interest_groups > 1:
            care_points.append("已将不同成员的已确认兴趣共同纳入评分")
        plan = TrustedPlan(
            tasks=tasks,
            member_scores=scores,
            lowest_member_score=min(score.score for score in scores),
            care_points=care_points,
            compromises=compromises,
            unknown_facts=unknown_facts,
            confirmation_message="这是当前约束下唯一的稳定推荐。确认后再核验路线、费用和可达性。",
        )
        return bundle.model_copy(update={"trusted_plan": plan})

    @staticmethod
    def _score_members(
        tasks: Sequence[CandidatePlace], members: Sequence[MemberPreference],
    ) -> list[MemberScore]:
        selected_text = " ".join(
            f"{item.name} {item.category or ''}".casefold() for item in tasks
        )
        scores: list[MemberScore] = []
        for member in members:
            interests = tuple(item.casefold() for item in member.interests if item.strip())
            must_visit = tuple(item.casefold() for item in member.must_visit if item.strip())
            interest_hits = sum(word in selected_text for word in interests)
            missing_must = [place for place in must_visit if place not in selected_text]
            score = min(100, 70 + min(20, interest_hits * 10) + (10 if must_visit and not missing_must else 0))
            penalties: list[str] = []
            reasons: list[str] = []
            if interest_hits:
                reasons.append(f"覆盖 {interest_hits} 项已确认兴趣")
            if must_visit and not missing_must:
                reasons.append("已纳入必去地点")
            if missing_must:
                score = max(0, score - 45)
                penalties.append("MUST_VISIT_NOT_SELECTED")
                reasons.append("部分必去地点未进入本轮任务")
            if not reasons:
                reasons.append("按已确认约束保留可行候选")
            scores.append(MemberScore(
                participant_id=member.participant_id, score=score,
                penalty_rule_ids=penalties, reasons=reasons,
            ))
        return scores

    @staticmethod
    def _fairness_sort_key(
        tasks: Sequence[CandidatePlace], scores: Sequence[MemberScore], facts_by_id: dict[str, FactRef],
    ) -> tuple[float, float, int, str]:
        known_cost = sum(
            fact.place.priceReference.amountCents or 0
            for task in tasks if (fact := facts_by_id.get(task.place_id)) is not None
        )
        return (
            -min(item.score for item in scores),
            -(sum(item.score for item in scores) / len(scores)),
            known_cost,
            ",".join(sorted(item.place_id for item in tasks)),
        )


__all__ = [
    "CandidateProposalGatewayError",
    "CandidateProposalGatewayPort",
    "IssuedProviderCandidates",
    "MemberPreference",
    "ProviderFactRegistryPort",
    "ProviderFactRestoreError",
    "RawCandidateProposal",
    "RecommendationOrchestrationError",
    "RecommendationOrchestrationService",
    "RouteCandidateBuildError",
    "RouteCandidateBuilderPort",
    "TrustedRecommendationService",
    "project_collaboration_recommendation_trip",
]
