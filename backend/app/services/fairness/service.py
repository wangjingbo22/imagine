from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from unicodedata import normalize
from uuid import UUID

from app.schemas.trip import Participant, PreferenceType, Trip
from app.services.planning.models import CandidatePlan
from app.services.route_risk import ValidationStatus

from .models import (
    CandidateFairnessEvaluation,
    CandidateHardRejection,
    FairRecommendationCandidate,
    FairRecommendationDecision,
    ParticipantSatisfaction,
    SatisfactionDeduction,
)


class FairnessInputError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class NoFairCandidateError(ValueError):
    code = "NO_FAIR_CANDIDATE"

    def __init__(self, rejections: Sequence[CandidateHardRejection]) -> None:
        super().__init__("all candidates failed one or more HARD rules")
        self.rejections = tuple(rejections)


@dataclass(frozen=True, slots=True)
class _RankedCandidate:
    source: FairRecommendationCandidate
    evaluation: CandidateFairnessEvaluation

    @property
    def key(self) -> tuple[int, int, int, int, int, str]:
        scores = [item.score for item in self.evaluation.participant_scores]
        total_cost = self.evaluation.total_cost_cents
        return (
            -self.evaluation.minimum_score,
            -sum(scores),
            1 if total_cost is None else 0,
            total_cost if total_cost is not None else 2**63 - 1,
            self.evaluation.detour_meters,
            self.evaluation.stable_id,
        )


class DeterministicFairRecommendationService:
    """Compute scores from trusted facts and select exactly one stable winner."""

    def select_unique(
        self,
        *,
        trip: Trip,
        candidates: Sequence[FairRecommendationCandidate],
    ) -> FairRecommendationDecision:
        self._validate_inputs(trip, candidates)
        accepted: list[_RankedCandidate] = []
        rejections: list[CandidateHardRejection] = []

        for candidate in candidates:
            candidate_rejections = self._hard_rejections(trip, candidate.plan)
            if candidate_rejections:
                rejections.extend(candidate_rejections)
                continue
            participant_scores = tuple(
                self._score_participant(participant, candidate.plan)
                for participant in trip.participants
            )
            scores = [item.score for item in participant_scores]
            evaluation = CandidateFairnessEvaluation(
                candidate_id=candidate.plan.candidate_id,
                participant_scores=participant_scores,
                minimum_score=min(scores),
                average_score=round(sum(scores) / len(scores), 4),
                total_cost_cents=candidate.plan.metrics.total_cost_cents,
                known_total_cost_cents=candidate.plan.metrics.known_total_cost_cents,
                detour_meters=candidate.detour_meters,
                stable_id=candidate.plan.candidate_id,
            )
            accepted.append(_RankedCandidate(candidate, evaluation))

        if not accepted:
            raise NoFairCandidateError(rejections)

        winner = min(accepted, key=lambda item: item.key)
        return FairRecommendationDecision(
            selected_plan=winner.source.plan,
            selected_evaluation=winner.evaluation,
            evaluated_candidate_ids=tuple(
                sorted(item.source.plan.candidate_id for item in accepted)
            ),
            hard_rejections=tuple(
                sorted(
                    rejections,
                    key=lambda item: (
                        item.candidate_id,
                        str(item.participant_id or ""),
                        item.rule_id,
                    ),
                )
            ),
        )

    @staticmethod
    def _validate_inputs(
        trip: Trip,
        candidates: Sequence[FairRecommendationCandidate],
    ) -> None:
        if not candidates:
            raise FairnessInputError(
                "FAIRNESS_CANDIDATES_REQUIRED",
                "at least one server-owned candidate is required",
            )
        candidate_ids = [item.plan.candidate_id for item in candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise FairnessInputError(
                "FAIRNESS_CANDIDATE_DUPLICATE",
                "candidateId values must be unique",
            )
        digests = {item.provider_fact_digest for item in candidates}
        if len(digests) != 1:
            raise FairnessInputError(
                "PROVIDER_FACT_DIGEST_MISMATCH",
                "all candidates must derive from the same Provider fact digest",
            )
        for item in candidates:
            if item.plan.trip_id != str(trip.trip_id):
                raise FairnessInputError(
                    "FAIRNESS_TRIP_MISMATCH",
                    "candidate tripId does not match the confirmed Trip",
                )
            if item.plan.city_code != trip.city_context.city_code:
                raise FairnessInputError(
                    "FAIRNESS_CITY_MISMATCH",
                    "candidate cityCode does not match the confirmed Trip",
                )

    @staticmethod
    def _hard_rejections(
        trip: Trip,
        plan: CandidatePlan,
    ) -> list[CandidateHardRejection]:
        rejections: list[CandidateHardRejection] = []
        if any(
            result.hardness == "HARD" and result.status is not ValidationStatus.PASS
            for result in plan.constraint_results
        ):
            rejections.append(
                CandidateHardRejection(
                    candidate_id=plan.candidate_id,
                    rule_id="FAIR.HARD.CONSTRAINT_NOT_PASS",
                    reason="候选存在未通过的 HARD 约束，不参与公平排序。",
                )
            )
            return rejections

        plan_text = _plan_text(plan)
        for participant in trip.participants:
            if (
                plan.metrics.total_cost_cents is not None
                and plan.metrics.total_cost_cents > participant.budget_cap_cents
            ):
                rejections.append(
                    CandidateHardRejection(
                        candidate_id=plan.candidate_id,
                        participant_id=participant.participant_id,
                        rule_id="FAIR.HARD.BUDGET_CAP_EXCEEDED",
                        reason=f"候选已知总费用超过成员 {participant.nickname} 的预算上限。",
                    )
                )
            for preference in participant.preferences:
                matched = _key(preference.value) in plan_text
                if preference.type is PreferenceType.MUST_VISIT and not matched:
                    rejections.append(
                        CandidateHardRejection(
                            candidate_id=plan.candidate_id,
                            participant_id=participant.participant_id,
                            rule_id="FAIR.HARD.MUST_VISIT_MISSING",
                            reason=f"候选缺少成员 {participant.nickname} 的必去地点：{preference.value}。",
                        )
                    )
                if preference.type is PreferenceType.AVOID_PLACE and matched:
                    rejections.append(
                        CandidateHardRejection(
                            candidate_id=plan.candidate_id,
                            participant_id=participant.participant_id,
                            rule_id="FAIR.HARD.AVOID_PLACE_PRESENT",
                            reason=f"候选包含成员 {participant.nickname} 明确避开的地点：{preference.value}。",
                        )
                    )
        return rejections

    @staticmethod
    def _score_participant(
        participant: Participant,
        plan: CandidatePlan,
    ) -> ParticipantSatisfaction:
        plan_text = _plan_text(plan)
        deductions: list[SatisfactionDeduction] = []
        for preference in participant.preferences:
            if preference.type is not PreferenceType.INTEREST:
                continue
            if _key(preference.value) in plan_text:
                continue
            deductions.append(
                SatisfactionDeduction(
                    rule_id="FAIR.INTEREST.UNMET",
                    points=preference.weight * 4,
                    preference_value=preference.value,
                    reason=f"方案未覆盖已确认兴趣“{preference.value}”。",
                )
            )
        return ParticipantSatisfaction(
            participant_id=participant.participant_id,
            nickname=participant.nickname,
            score=max(0, 100 - sum(item.points for item in deductions)),
            deductions=tuple(deductions),
        )


def _key(value: str) -> str:
    return normalize("NFKC", value).strip().casefold()


def _plan_text(plan: CandidatePlan) -> str:
    return _key(
        " ".join(
            " ".join(
                (
                    task.title,
                    task.category,
                    task.end_location_text,
                    task.place_id,
                    task.note,
                )
            )
            for task in plan.tasks
        )
    )


__all__ = [
    "DeterministicFairRecommendationService",
    "FairnessInputError",
    "NoFairCandidateError",
]
