from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue

from .trip import ContractModel


class Constraint(ContractModel):
    """One compiled, deterministic constraint shared by planning validators.

    T007 owns the AssistanceProfile-to-Constraint compilation rules.  This
    module only freezes the transport contract consumed by T008 and T009.
    """

    field: Annotated[str, Field(min_length=1, max_length=120)]
    operator: Annotated[str, Field(min_length=1, max_length=40)]
    value: JsonValue
    scope: Annotated[str, Field(min_length=1, max_length=40)]
    hardness: Literal["HARD", "SOFT"]


__all__ = ["Constraint"]
