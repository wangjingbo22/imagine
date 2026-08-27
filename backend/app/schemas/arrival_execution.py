from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictStr, UUID4, model_validator

from .arrival_decision import TargetTaskLocation
from .arrival_evidence import LocationEvidenceSource
from .trip import ContractModel


class CreateArrivalExecutionEventRequest(ContractModel):
    model_config = ConfigDict(
        alias_generator=ContractModel.model_config["alias_generator"],
        populate_by_name=True,
        extra="forbid",
        strict=False,
        str_strip_whitespace=True,
        loc_by_alias=True,
    )

    schema_version: Literal["1.0"] = "1.0"
    task_id: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    plan_version_id: UUID4
    arrival_evidence_id: UUID4
    target_location: TargetTaskLocation
    source: LocationEvidenceSource
    idempotency_key: Annotated[StrictStr, Field(min_length=1, max_length=160)]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def occurred_at_must_include_timezone(
        self,
    ) -> "CreateArrivalExecutionEventRequest":
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurredAt must include a timezone")
        return self


__all__ = ["CreateArrivalExecutionEventRequest"]
