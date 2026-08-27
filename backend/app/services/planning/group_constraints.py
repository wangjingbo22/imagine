from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.schemas.constraint import Constraint
from app.schemas.trip import AssistanceProfile
from app.services.assistance_constraints.compiler import (
    DeterministicAssistanceConstraintCompiler,
    FIELD_NAP_WINDOW,
)


ConstraintKey = str


@dataclass(frozen=True, slots=True)
class GroupConstraintMergeResult:
    constraints: tuple[Constraint, ...]
    contributors: dict[ConstraintKey, tuple[UUID, ...]]


class GroupConstraintMergeError(ValueError):
    def __init__(self, field: str, participant_ids: tuple[UUID, ...]) -> None:
        self.field = field
        self.participant_ids = tuple(sorted(participant_ids, key=str))
        super().__init__(
            "confirmed participant constraints cannot be merged deterministically "
            f"for {field}"
        )


def _key(constraint: Constraint) -> ConstraintKey:
    return "|".join((constraint.field, constraint.operator, constraint.scope, constraint.hardness))


def merge_group_constraints(
    participants: tuple[tuple[UUID, AssistanceProfile], ...],
    *,
    compiler: DeterministicAssistanceConstraintCompiler | None = None,
) -> GroupConstraintMergeResult:
    resolved = compiler or DeterministicAssistanceConstraintCompiler()
    grouped: dict[ConstraintKey, list[tuple[UUID, Constraint]]] = {}
    for participant_id, profile in participants:
        for constraint in resolved.compile(profile):
            grouped.setdefault(_key(constraint), []).append((participant_id, constraint))

    merged: list[Constraint] = []
    contributors: dict[ConstraintKey, tuple[UUID, ...]] = {}
    for key, entries in grouped.items():
        values = [constraint.value for _, constraint in entries]
        first = entries[0][1]
        participant_ids = tuple(participant_id for participant_id, _ in entries)
        contributors[key] = tuple(sorted(participant_ids, key=str))
        if all(value == values[0] for value in values[1:]):
            merged.append(first)
        elif first.operator == "LTE" and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in values
        ):
            merged.append(first.model_copy(update={"value": min(values)}))
        elif first.field == FIELD_NAP_WINDOW and all(
            isinstance(value, dict)
            and isinstance(value.get("start"), str)
            and isinstance(value.get("end"), str)
            for value in values
        ):
            merged.append(first.model_copy(update={"value": {
                "start": min(value["start"] for value in values),
                "end": max(value["end"] for value in values),
            }}))
        else:
            raise GroupConstraintMergeError(first.field, participant_ids)
    return GroupConstraintMergeResult(tuple(merged), contributors)


__all__ = [
    "ConstraintKey",
    "GroupConstraintMergeError",
    "GroupConstraintMergeResult",
    "merge_group_constraints",
]
