from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from collections.abc import Sequence

from app.services.planning.models import CandidateTaskFact

if TYPE_CHECKING:
    from app.schemas.execution_adjustment import EventConstraintSet


@dataclass(frozen=True, slots=True)
class SuffixPlanningInput:
    task_facts: tuple[CandidateTaskFact, ...]
    frozen_task_ids: tuple[str, ...]
    actual_spent_cents: int
    event_constraints: "EventConstraintSet | None" = None
    source_event_task_id: str | None = None


@runtime_checkable
class SuffixPlanner(Protocol):
    """Plan only the not-yet-frozen suffix of a CURRENT V1."""

    def plan_suffix(
        self,
        planning_input: SuffixPlanningInput,
    ) -> Sequence[CandidateTaskFact]: ...


class DeterministicRetainedSuffixPlanner:
    """Production default: keep the already trusted suffix facts unchanged."""

    def plan_suffix(
        self,
        planning_input: SuffixPlanningInput,
    ) -> tuple[CandidateTaskFact, ...]:
        return planning_input.task_facts


__all__ = [
    "DeterministicRetainedSuffixPlanner",
    "SuffixPlanner",
    "SuffixPlanningInput",
]
