from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from .plan import PlanDiffCategory, PlanDiffChangeType, PlanVersionDiff
from .trip import ContractModel


class _FrozenContractModel(ContractModel):
    """Strict, immutable value object used only at the LLM boundary."""

    model_config = ConfigDict(frozen=True)


class ReplanExplanationChange(_FrozenContractModel):
    """Allowlisted, identifier-free projection of one server-computed change."""

    category: PlanDiffCategory
    change_type: PlanDiffChangeType
    label: Annotated[str, Field(min_length=1, max_length=120)]
    before: str | int | None
    after: str | int | None


class ReplanExplanationMetricsDelta(_FrozenContractModel):
    """Server-computed aggregate deltas; the model cannot change their values."""

    cost_cents: int
    walk_meters: int
    transfer_count: int


class ReplanExplanationProjection(_FrozenContractModel):
    """Immutable, redacted PlanVersionDiff view sent to the explanation model.

    Trip/plan/task identifiers and all version/status fields are intentionally
    absent.  The projection is derived exclusively from a validated server-side
    ``PlanVersionDiff`` and is never accepted from an API caller.
    """

    changes: tuple[ReplanExplanationChange, ...]
    metrics_delta: ReplanExplanationMetricsDelta

    @classmethod
    def from_plan_version_diff(
        cls,
        diff: PlanVersionDiff,
    ) -> "ReplanExplanationProjection":
        return cls(
            changes=tuple(
                ReplanExplanationChange(
                    category=item.category,
                    change_type=item.change_type,
                    label=item.label,
                    before=item.before,
                    after=item.after,
                )
                for item in diff.items
            ),
            metrics_delta=ReplanExplanationMetricsDelta(
                cost_cents=diff.metrics_delta.total_cost_cents,
                walk_meters=diff.metrics_delta.total_walk_meters,
                transfer_count=diff.metrics_delta.transfer_count,
            ),
        )


class LlmReplanExplanationPayload(ContractModel):
    """The complete allowlist for untrusted model output."""

    summary: Annotated[str, Field(min_length=1, max_length=240)]

    @field_validator("summary")
    @classmethod
    def summary_must_be_one_paragraph(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("summary must be one paragraph")
        return value


class ReplanDifferenceExplanation(ContractModel):
    """Display-only explanation; it has no plan mutation authority."""

    summary: Annotated[str, Field(min_length=1, max_length=240)]
    model: Annotated[str, Field(min_length=1, max_length=120)] | None = None

    @field_validator("summary")
    @classmethod
    def summary_must_be_one_paragraph(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("summary must be one paragraph")
        return value


__all__ = [
    "LlmReplanExplanationPayload",
    "ReplanDifferenceExplanation",
    "ReplanExplanationChange",
    "ReplanExplanationMetricsDelta",
    "ReplanExplanationProjection",
]
