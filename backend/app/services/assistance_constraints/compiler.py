from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from app.schemas.constraint import Constraint
from app.schemas.trip import AssistanceProfile, AssistanceType
from app.schemas.validation_error import ValidationIssue, issues_from_pydantic


FIELD_WALK_CONTINUOUS: Final = "walkLimits.maxContinuousMeters"
FIELD_WALK_DAILY: Final = "walkLimits.maxDailyMeters"
FIELD_MAX_TRANSFERS: Final = "maxTransfers"
FIELD_REST_INTERVAL: Final = "restInterval"
FIELD_NAP_WINDOW: Final = "napWindow"
FIELD_RETURN: Final = "return"
FIELD_AVOID_STAIRS: Final = "avoidStairs"

OP_LTE: Final = "LTE"
OP_EQ: Final = "EQ"
OP_BLOCK: Final = "BLOCK"
OP_ARRIVE_BY: Final = "ARRIVE_BY"

SCOPE_ROUTE_SEGMENT: Final = "ROUTE_SEGMENT"
SCOPE_ROUTE: Final = "ROUTE"
SCOPE_DAY: Final = "DAY"
HARD: Final = "HARD"

RETURN_END_LOCATION_PATH: Final = "days[0].endLocationText"
RETURN_DEADLINE_PATH: Final = "days[0].timeWindow.end"


class AssistanceConstraintCompileError(ValueError):
    """Field-addressable failure that cannot yield planning constraints."""

    def __init__(
        self,
        *,
        issues: Sequence[ValidationIssue],
        code: str = "ASSISTANCE_PROFILE_INVALID",
    ) -> None:
        self.code = code
        self.issues = tuple(issues)
        message = "; ".join(
            f"{issue.path or '<root>'}: {issue.message}"
            for issue in self.issues
        )
        super().__init__(message)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "errors": [
                issue.model_dump(exclude_none=True) for issue in self.issues
            ],
        }


def _validated_profile(profile: AssistanceProfile) -> AssistanceProfile:
    if not isinstance(profile, AssistanceProfile):
        raise AssistanceConstraintCompileError(
            issues=(
                ValidationIssue(
                    path="",
                    code="model_type",
                    message="Input must be an AssistanceProfile",
                ),
            )
        )

    try:
        raw = profile.model_dump_json(by_alias=True, warnings="none")
        return AssistanceProfile.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        raise AssistanceConstraintCompileError(
            issues=issues_from_pydantic(exc.errors())
        ) from exc
    except (PydanticSerializationError, TypeError, ValueError) as exc:
        raise AssistanceConstraintCompileError(
            issues=(
                ValidationIssue(
                    path="",
                    code="invalid_json_value",
                    message=str(exc),
                ),
            )
        ) from exc


class DeterministicAssistanceConstraintCompiler:
    """Compile a confirmed profile without I/O, inference, or mutation."""

    def compile(
        self,
        profile: AssistanceProfile,
    ) -> tuple[Constraint, ...]:
        valid = _validated_profile(profile)
        constraints: list[Constraint] = []

        if valid.walk_limits.max_continuous_meters is not None:
            constraints.append(
                Constraint(
                    field=FIELD_WALK_CONTINUOUS,
                    operator=OP_LTE,
                    value=valid.walk_limits.max_continuous_meters,
                    scope=SCOPE_ROUTE_SEGMENT,
                    hardness=HARD,
                )
            )
        if valid.walk_limits.max_daily_meters is not None:
            constraints.append(
                Constraint(
                    field=FIELD_WALK_DAILY,
                    operator=OP_LTE,
                    value=valid.walk_limits.max_daily_meters,
                    scope=SCOPE_DAY,
                    hardness=HARD,
                )
            )
        if valid.max_transfers is not None:
            constraints.append(
                Constraint(
                    field=FIELD_MAX_TRANSFERS,
                    operator=OP_LTE,
                    value=valid.max_transfers,
                    scope=SCOPE_ROUTE,
                    hardness=HARD,
                )
            )
        if valid.rest_interval is not None:
            constraints.append(
                Constraint(
                    field=FIELD_REST_INTERVAL,
                    operator=OP_LTE,
                    value=valid.rest_interval,
                    scope=SCOPE_ROUTE,
                    hardness=HARD,
                )
            )
        if valid.nap_window is not None:
            constraints.append(
                Constraint(
                    field=FIELD_NAP_WINDOW,
                    operator=OP_BLOCK,
                    value=valid.nap_window.model_dump(
                        mode="json",
                        by_alias=True,
                    ),
                    scope=SCOPE_DAY,
                    hardness=HARD,
                )
            )
        if valid.type is AssistanceType.PARENT_CHILD:
            constraints.append(
                Constraint(
                    field=FIELD_RETURN,
                    operator=OP_ARRIVE_BY,
                    value={
                        "endLocationPath": RETURN_END_LOCATION_PATH,
                        "deadlinePath": RETURN_DEADLINE_PATH,
                    },
                    scope=SCOPE_DAY,
                    hardness=HARD,
                )
            )
        if valid.avoid_stairs:
            constraints.append(
                Constraint(
                    field=FIELD_AVOID_STAIRS,
                    operator=OP_EQ,
                    value=True,
                    scope=SCOPE_ROUTE_SEGMENT,
                    hardness=HARD,
                )
            )

        return tuple(constraints)


__all__ = [
    "AssistanceConstraintCompileError",
    "DeterministicAssistanceConstraintCompiler",
    "FIELD_AVOID_STAIRS",
    "FIELD_MAX_TRANSFERS",
    "FIELD_NAP_WINDOW",
    "FIELD_REST_INTERVAL",
    "FIELD_RETURN",
    "FIELD_WALK_CONTINUOUS",
    "FIELD_WALK_DAILY",
    "RETURN_DEADLINE_PATH",
    "RETURN_END_LOCATION_PATH",
]
