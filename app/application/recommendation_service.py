"""Deterministic S2 candidate issuer and strict LLM-ranking boundary."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

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


__all__ = ["MemberPreference", "TrustedRecommendationService"]
