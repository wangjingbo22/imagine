"""Deterministic S2 candidate issuer and strict LLM-ranking boundary."""
from __future__ import annotations

from collections.abc import Sequence

from pydantic import ValidationError

from app.domain.recommendation import (
    CandidatePlace,
    CandidateRecommendation,
    FactRef,
    LlmRanking,
    RecommendationBundle,
)


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


__all__ = ["TrustedRecommendationService"]
