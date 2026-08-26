"""Deterministic S2 candidate issuer and strict LLM-ranking boundary."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from itertools import combinations
from typing import Literal, Protocol
from uuid import UUID

from pydantic import ValidationError

from app.domain.recommendation import (
    CandidatePlace,
    CandidateRecommendation,
    FactRef,
    LlmRanking,
    MemberScore,
    RecommendationBundle,
    TrustedPlan,
)
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
    ProviderFactBundle,
    RecommendationOrchestrationRequest,
    RecommendationOrchestrationResult,
)


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


class RecommendationOrchestrationService:
    """T009 orchestration; it owns no FactRef registry or model transport."""

    _MAX_ENUMERATED_ORDERS = 12

    def __init__(
        self,
        *,
        fact_registry: ProviderFactRegistryPort,
        proposal_gateway: CandidateProposalGatewayPort,
        route_builder: RouteCandidateBuilderPort,
        planner: DeterministicCandidatePlanner | None = None,
        fairness: DeterministicFairRecommendationService | None = None,
    ) -> None:
        self._fact_registry = fact_registry
        self._proposal_gateway = proposal_gateway
        self._route_builder = route_builder
        self._planner = planner or DeterministicCandidatePlanner()
        self._fairness = fairness or DeterministicFairRecommendationService()

    async def recommend(
        self,
        *,
        trip_id: UUID,
        request: RecommendationOrchestrationRequest,
    ) -> RecommendationOrchestrationResult:
        facts = self._restore_facts(trip_id, request)
        trace_id = _trace_id(trip_id, facts)
        llm_request = ProviderCandidateSelectionRequest(
            trace_id=trace_id,
            provider_fact_digest=facts.provider_fact_digest,
            confirmed_trip_summary=facts.confirmed_trip_summary,
            candidate_facts=facts.candidate_facts,
        )

        proposal: ProviderCandidateSelectionProposal | None = None
        fallback_reason: FallbackReason | None = None
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
                    trace_id=trace_id,
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
            trace_id=trace_id,
            built=built,
            decision=decision,
            strategy="DETERMINISTIC_FALLBACK",
            fallback_reason=fallback_reason,
            rationale="AI 辅助不可用，已按服务端白名单、真实路线与公平规则确定唯一方案。",
            risk_notes=(
                "已使用确定性枚举；地点、路线、费用和来源均从服务端事实恢复。",
            ),
        )

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


def _trace_id(trip_id: UUID, facts: ProviderFactBundle) -> str:
    seed = f"{trip_id}:{facts.fact_set_id}:{facts.provider_fact_digest}"
    return f"recommend-{sha256(seed.encode('utf-8')).hexdigest()[:24]}"


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
    "MemberPreference",
    "ProviderFactRegistryPort",
    "ProviderFactRestoreError",
    "RawCandidateProposal",
    "RecommendationOrchestrationError",
    "RecommendationOrchestrationService",
    "RouteCandidateBuildError",
    "RouteCandidateBuilderPort",
    "TrustedRecommendationService",
]
