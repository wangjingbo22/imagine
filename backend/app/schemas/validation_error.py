from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ValidationIssue(BaseModel):
    """One stable, field-addressable validation issue."""

    model_config = ConfigDict(extra="forbid", strict=True)

    path: str
    code: str
    message: str
    context: dict[str, str] | None = None
    candidates: list[str] | None = None


def format_error_path(location: Sequence[object]) -> str:
    """Convert a Pydantic location tuple to a JSON field path."""

    parts: list[str] = []
    for item in location:
        if isinstance(item, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{item}]"
            else:
                parts.append(f"[{item}]")
        else:
            parts.append(str(item))
    return ".".join(parts)


def issues_from_pydantic(errors: Sequence[Mapping[str, Any]]) -> list[ValidationIssue]:
    """Map Pydantic error details into the public error contract."""

    return [
        ValidationIssue(
            path=format_error_path(detail.get("loc", ())),
            code=str(detail.get("type", "validation_error")),
            message=str(detail.get("msg", "Validation failed")),
        )
        for detail in errors
    ]


class TripSchemaError(ValueError):
    """Raised when a normalized Trip payload cannot enter the planning flow."""

    def __init__(
        self,
        errors: Sequence[ValidationIssue],
        *,
        code: str = "TRIP_SCHEMA_INVALID",
        schema_version: str = "1.0",
    ) -> None:
        self.code = code
        self.schema_version = schema_version
        self.errors = tuple(errors)
        super().__init__(self._message())

    def _message(self) -> str:
        return "; ".join(
            f"{issue.path or '<root>'}: {issue.message}" for issue in self.errors
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "schemaVersion": self.schema_version,
            "errors": [
                issue.model_dump(exclude_none=True) for issue in self.errors
            ],
        }
