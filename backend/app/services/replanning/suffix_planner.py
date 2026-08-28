from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Protocol, runtime_checkable
from collections.abc import Sequence

from app.schemas.execution_adjustment import (
    EventConstraintSet,
    ExecutionAdjustmentType,
)
from app.services.planning.models import CandidateTaskFact


@dataclass(frozen=True, slots=True)
class SuffixPlanningInput:
    task_facts: tuple[CandidateTaskFact, ...]
    frozen_task_ids: tuple[str, ...]
    actual_spent_cents: int
    event_constraints: EventConstraintSet | None = None
    source_event_task_id: str | None = None
    anchor_end_at: time | None = None


@runtime_checkable
class SuffixPlanner(Protocol):
    """Plan only the not-yet-frozen suffix of a CURRENT V1."""

    def plan_suffix(
        self,
        planning_input: SuffixPlanningInput,
    ) -> Sequence[CandidateTaskFact]: ...


class DeterministicRetainedSuffixPlanner:
    """Legacy fallback kept for explicit fail-closed compatibility checks."""

    def plan_suffix(
        self,
        planning_input: SuffixPlanningInput,
    ) -> tuple[CandidateTaskFact, ...]:
        return planning_input.task_facts


class SuffixPlanningError(ValueError):
    """A deterministic suffix cannot be derived from the trusted input."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


class DeterministicEventAwareSuffixPlanner:
    """Produce a minimal event-aware suffix without inventing Provider facts.

    Place, route, price and facility snapshots are immutable inputs.  LATE may
    only consume already-planned schedule slack; FATIGUE may only tighten the
    derived rest counter.  Walking constraints are deliberately left to the
    server validator so an impossible trusted route fails closed with zero V2
    writes instead of being replaced by a fabricated route.
    """

    _LATE_FIELDS = frozenset({"remaining.timeBudgetMinutes"})
    _FATIGUE_FIELDS = frozenset(
        {
            "remaining.walkBudgetMeters",
            "remaining.maxSegmentWalkMeters",
            "remaining.restIntervalMinutes",
        }
    )

    def plan_suffix(
        self,
        planning_input: SuffixPlanningInput,
    ) -> tuple[CandidateTaskFact, ...]:
        facts = planning_input.task_facts
        constraints = planning_input.event_constraints
        if not facts:
            raise self._invalid("taskFacts", "trusted unfinished task facts are required")
        if constraints is None:
            # S1 EXPENSE_CHANGE replanning predates the T019/T020 event overlay
            # and intentionally retains the trusted suffix.  Only the dedicated
            # S2 adjustment path supplies event constraints and may tighten it.
            return facts
        if (
            planning_input.source_event_task_id is None
            or planning_input.source_event_task_id
            != constraints.source_event.task_id
        ):
            raise self._invalid(
                "sourceEventTaskId",
                "source event must match the compiled transient constraints",
            )
        if planning_input.anchor_end_at is None:
            raise self._invalid(
                "anchorEndAt",
                "the frozen-prefix end time is required for suffix planning",
            )

        limits = self._limits(constraints)
        if constraints.source_event.event_type is ExecutionAdjustmentType.LATE:
            if frozenset(limits) != self._LATE_FIELDS:
                raise self._invalid(
                    "eventConstraints.constraints",
                    "LATE must contain only the remaining time budget",
                )
            return self._tighten_late(
                facts,
                anchor_end=planning_input.anchor_end_at,
                limit_minutes=limits["remaining.timeBudgetMinutes"],
            )

        if frozenset(limits) != self._FATIGUE_FIELDS:
            raise self._invalid(
                "eventConstraints.constraints",
                "FATIGUE must contain walking, segment and rest limits",
            )
        rest_limit = limits["remaining.restIntervalMinutes"]
        return tuple(
            fact.model_copy(
                update={
                    "elapsed_since_rest_minutes": min(
                        fact.elapsed_since_rest_minutes,
                        rest_limit,
                    )
                }
            )
            for fact in facts
        )

    @classmethod
    def _tighten_late(
        cls,
        facts: tuple[CandidateTaskFact, ...],
        *,
        anchor_end: time,
        limit_minutes: int,
    ) -> tuple[CandidateTaskFact, ...]:
        anchor_seconds = cls._seconds(anchor_end)
        span_seconds = cls._seconds(facts[-1].end_at) - anchor_seconds
        limit_seconds = limit_minutes * 60
        if span_seconds <= limit_seconds:
            return facts

        # Only idle slack beyond each immutable Provider route duration may be
        # removed.  Consume later gaps first so the fewest tasks move.
        slack_seconds: list[int] = []
        previous_end = anchor_seconds
        for index, fact in enumerate(facts):
            route_seconds = fact.route.durationSeconds
            gap = cls._seconds(fact.start_at) - previous_end
            if route_seconds > gap:
                raise cls._invalid(
                    f"taskFacts[{index}].route.durationSeconds",
                    "trusted route duration does not fit the restored schedule",
                )
            slack_seconds.append(gap - route_seconds)
            previous_end = cls._seconds(fact.end_at)

        required = span_seconds - limit_seconds
        reductions = [0] * len(facts)
        for index in range(len(facts) - 1, -1, -1):
            reduction = min(required, slack_seconds[index])
            reductions[index] = reduction
            required -= reduction
            if required == 0:
                break

        output: list[CandidateTaskFact] = []
        cumulative_shift = 0
        for index, fact in enumerate(facts):
            cumulative_shift += reductions[index]
            if cumulative_shift == 0:
                output.append(fact)
                continue
            output.append(
                fact.model_copy(
                    update={
                        "start_at": cls._time(
                            cls._seconds(fact.start_at) - cumulative_shift
                        ),
                        "end_at": cls._time(
                            cls._seconds(fact.end_at) - cumulative_shift
                        ),
                    }
                )
            )
        # If route/activity duration alone is above the tightened limit, the
        # earliest trusted schedule is returned and HARD validation rejects it.
        return tuple(output)

    @classmethod
    def _limits(cls, constraints: EventConstraintSet) -> dict[str, int]:
        output: dict[str, int] = {}
        for index, constraint in enumerate(constraints.constraints):
            if (
                constraint.field in output
                or constraint.operator != "LTE"
                or constraint.scope != "REMAINING_ITINERARY"
                or constraint.hardness != "HARD"
                or isinstance(constraint.value, bool)
                or not isinstance(constraint.value, int)
                or constraint.value < 0
            ):
                raise cls._invalid(
                    f"eventConstraints.constraints[{index}]",
                    "transient constraint must be one unique non-negative HARD LTE limit",
                )
            output[constraint.field] = constraint.value
        return output

    @staticmethod
    def _seconds(value: time) -> int:
        return value.hour * 3_600 + value.minute * 60 + value.second

    @staticmethod
    def _time(value: int) -> time:
        if not 0 <= value < 24 * 3_600:
            raise DeterministicEventAwareSuffixPlanner._invalid(
                "taskFacts.time",
                "event-aware schedule must remain within one day",
            )
        hours, remainder = divmod(value, 3_600)
        minutes, seconds = divmod(remainder, 60)
        return time(hour=hours, minute=minutes, second=seconds)

    @staticmethod
    def _invalid(path: str, message: str) -> SuffixPlanningError:
        return SuffixPlanningError(
            "S2_T021_TRUSTED_SUFFIX_UNAVAILABLE",
            path,
            message,
        )


__all__ = [
    "DeterministicEventAwareSuffixPlanner",
    "DeterministicRetainedSuffixPlanner",
    "SuffixPlanner",
    "SuffixPlanningError",
    "SuffixPlanningInput",
]
