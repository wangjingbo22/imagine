from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictFloat, StrictStr, UUID4, model_validator

from .arrival_evidence import LocationEvidenceSource
from .trip import ContractModel


class LocationAttemptOutcome(str, Enum):
    EVIDENCE = "EVIDENCE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TIMEOUT = "TIMEOUT"


class ArrivalDecisionResult(str, Enum):
    ARRIVED = "ARRIVED"
    TOO_FAR = "TOO_FAR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TIMEOUT = "TIMEOUT"
    LOW_ACCURACY = "LOW_ACCURACY"


class TargetTaskLocation(ContractModel):
    model_config = ConfigDict(
        alias_generator=ContractModel.model_config["alias_generator"],
        populate_by_name=True,
        extra="forbid",
        strict=False,
        loc_by_alias=True,
        allow_inf_nan=False,
    )

    longitude: Annotated[StrictFloat, Field(ge=-180, le=180)]
    latitude: Annotated[StrictFloat, Field(ge=-90, le=90)]


class ArrivalDecisionRequest(ContractModel):
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
    target_location: TargetTaskLocation
    attempt_outcome: LocationAttemptOutcome
    source: LocationEvidenceSource
    arrival_evidence_id: UUID4 | None = None

    @model_validator(mode="after")
    def evidence_id_matches_attempt_outcome(self) -> "ArrivalDecisionRequest":
        if self.attempt_outcome is LocationAttemptOutcome.EVIDENCE:
            if self.arrival_evidence_id is None:
                raise ValueError(
                    "arrivalEvidenceId is required when attemptOutcome is EVIDENCE"
                )
        elif self.arrival_evidence_id is not None:
            raise ValueError(
                "arrivalEvidenceId is only allowed when attemptOutcome is EVIDENCE"
            )
        return self


class ArrivalDecision(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    trip_id: UUID4
    task_id: str
    arrival_evidence_id: UUID4 | None = None
    result: ArrivalDecisionResult
    reason_code: str
    message: str
    source: LocationEvidenceSource
    distance_meters: float | None = None
    accuracy: float | None = None
    allowed_distance_meters: float | None = None
    auto_confirmed: bool
    manual_confirmation_allowed: bool


__all__ = [
    "ArrivalDecision",
    "ArrivalDecisionRequest",
    "ArrivalDecisionResult",
    "LocationAttemptOutcome",
    "TargetTaskLocation",
]
