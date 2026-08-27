from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictFloat, UUID4, model_validator

from .trip import ContractModel


class LocationEvidenceSource(str, Enum):
    WEB_GEOLOCATION = "WEB_GEOLOCATION"
    NATIVE_GEOLOCATION = "NATIVE_GEOLOCATION"


class LocationEvidence(ContractModel):
    """A single, immutable location reading supplied by a client."""

    model_config = ConfigDict(
        alias_generator=ContractModel.model_config["alias_generator"],
        populate_by_name=True,
        extra="forbid",
        strict=False,
        str_strip_whitespace=True,
        loc_by_alias=True,
        allow_inf_nan=False,
    )

    longitude: Annotated[StrictFloat, Field(ge=-180, le=180)]
    latitude: Annotated[StrictFloat, Field(ge=-90, le=90)]
    accuracy: Annotated[StrictFloat, Field(gt=0)]
    captured_at: datetime
    source: LocationEvidenceSource

    @model_validator(mode="after")
    def captured_at_must_include_timezone(self) -> "LocationEvidence":
        if self.captured_at.tzinfo is None:
            raise ValueError("capturedAt must include a timezone")
        return self


class CreateArrivalEvidence(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    task_id: Annotated[str, Field(min_length=1, max_length=64)]
    location_evidence: LocationEvidence
    idempotency_key: Annotated[str, Field(min_length=1, max_length=160)]


class ArrivalEvidence(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    evidence_id: UUID4
    trip_id: UUID4
    task_id: str
    location_evidence: LocationEvidence
    idempotency_key: str
    recorded_at: datetime


__all__ = [
    "ArrivalEvidence",
    "CreateArrivalEvidence",
    "LocationEvidence",
    "LocationEvidenceSource",
]
