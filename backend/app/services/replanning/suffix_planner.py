from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Protocol, runtime_checkable
from collections.abc import Sequence

from app.domain.models import TravelMode
from app.schemas.execution_adjustment import (
    EventConstraintSet,
    ExecutionAdjustmentType,
)
from app.services.planning.models import CandidateTaskFact, PlannedRest


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
    only consume already-planned schedule slack; FATIGUE schedules explicit
    breaks and shorter activities. Walking constraints are deliberately left to the
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
                delay_minutes=constraints.source_event.late_minutes or 0,
            )

        if frozenset(limits) != self._FATIGUE_FIELDS:
            raise self._invalid(
                "eventConstraints.constraints",
                "FATIGUE must contain walking, segment and rest limits",
            )
        return self._schedule_fatigue(
            facts,
            anchor_end=planning_input.anchor_end_at,
            rest_limit=limits["remaining.restIntervalMinutes"],
        )

    @classmethod
    def _schedule_fatigue(cls, facts, *, anchor_end: time, rest_limit: int):
        # A break occupies real clock time at the previous stop. Do not invent
        # en-route stops, seating, shorter Provider routes or lower walking facts.
        cursor = cls._seconds(anchor_end)
        output = []
        for index, fact in enumerate(facts):
            route_seconds = fact.route.durationSeconds
            original_duration = cls._seconds(fact.end_at) - cls._seconds(fact.start_at)
            available_activity = rest_limit * 60 - route_seconds
            minimum_activity = min(original_duration, 15 * 60)
            exerting_route = fact.route.mode in {TravelMode.WALKING, TravelMode.BICYCLING}
            if (route_seconds > rest_limit * 60 and exerting_route) or rest_limit * 60 < minimum_activity:
                raise SuffixPlanningError(
                    "REPLAN_FATIGUE_ROUTE_TOO_LONG",
                    f"taskFacts[{index}].route.durationSeconds",
                    "现有交通路段加必要停留时间超过疲劳休息间隔；需要核实更省力的路线，不能仅修改计数。",
                )
            # A longer (but still within-limit) route needs a second real
            # break on arrival, before the visit. Never invent an en-route stop.
            arrival_rest_seconds = 30 * 60 if (
                available_activity < minimum_activity or route_seconds >= rest_limit * 60
            ) else 0
            activity_seconds = min(
                original_duration,
                rest_limit * 60 if arrival_rest_seconds else available_activity,
            )
            start = max(cls._seconds(fact.start_at), cursor + 30 * 60 + route_seconds + arrival_rest_seconds)
            rest_end = start - route_seconds - arrival_rest_seconds
            end = start + activity_seconds
            if end >= 24 * 3600:
                raise SuffixPlanningError(
                    "REPLAN_FATIGUE_TIME_INSUFFICIENT", f"taskFacts[{index}].endAt",
                    "加入真实休息后无法在当天完成，请调整出行安排。",
                )
            note = fact.note
            if activity_seconds < original_duration:
                note = f"疲劳减负：本项停留由 {original_duration // 60} 分钟缩短为 {activity_seconds // 60} 分钟。{note}"
            output.append(fact.model_copy(update={
                "start_at": cls._time(start),
                "end_at": cls._time(end),
                "rest_before": PlannedRest(start_at=cls._time(cursor), end_at=cls._time(rest_end)),
                "rest_on_arrival": (
                    PlannedRest(start_at=cls._time(start - arrival_rest_seconds), end_at=cls._time(start))
                    if arrival_rest_seconds else None
                ),
                # Legacy T010 field describes the preceding route, not the
                # post-arrival break; retain at least its real travel duration.
                "elapsed_since_rest_minutes": (route_seconds + 59) // 60,
                "note": note[:500],
            }))
            cursor = end
        return tuple(output)

    @classmethod
    def _tighten_late(
        cls,
        facts: tuple[CandidateTaskFact, ...],
        *,
        anchor_end: time,
        limit_minutes: int,
        delay_minutes: int,
    ) -> tuple[CandidateTaskFact, ...]:
        anchor_seconds = cls._seconds(anchor_end)
        span_seconds = cls._seconds(facts[-1].end_at) - anchor_seconds
        limit_seconds = limit_minutes * 60
        if span_seconds <= limit_seconds:
            # Even when existing slack absorbs the delay, make the V2 an
            # actionable execution update rather than returning a byte-for-byte
            # copy. Prefer a small visit reduction; otherwise retain the clock
            # and record exactly which buffer absorbed the delay.
            first = facts[0]
            duration = cls._seconds(first.end_at) - cls._seconds(first.start_at)
            reduction = min(delay_minutes * 60, max(0, duration - 15 * 60))
            note = (
                f"迟到调整：已确认迟到 {delay_minutes} 分钟；"
                + (f"本项停留缩短 {reduction // 60} 分钟。" if reduction else "由原有时间缓冲吸收，后续按更新后的执行说明进行。")
                + first.note
            )[:500]
            return (
                first.model_copy(update={
                    "end_at": cls._time(cls._seconds(first.end_at) - reduction),
                    "note": note,
                }),
                *facts[1:],
            )

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
                        "note": (
                            f"迟到调整：已确认迟到 {delay_minutes} 分钟，已压缩后续空档。"
                            f"{fact.note}"
                        )[:500],
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
