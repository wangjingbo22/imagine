from collections.abc import Iterable
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models import NonBlankText, PriceFact


class BudgetStatus(StrEnum):
    COMPLETE = "COMPLETE"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"


class BudgetLine(BaseModel):
    referenceId: NonBlankText
    priceFact: PriceFact


class BudgetWarning(BaseModel):
    code: Literal["UNKNOWN_PRICE"] = "UNKNOWN_PRICE"
    referenceId: NonBlankText
    kind: NonBlankText
    message: Literal["价格未知，未计入已知金额小计"] = (
        "价格未知，未计入已知金额小计"
    )


class BudgetSummary(BaseModel):
    knownSubtotalCents: int = Field(ge=0)
    unknownAmountCount: int = Field(ge=0)
    status: BudgetStatus
    warnings: list[BudgetWarning]


def summarize_budget(lines: Iterable[BudgetLine]) -> BudgetSummary:
    known_subtotal_cents = 0
    warnings: list[BudgetWarning] = []

    for line in lines:
        amount_cents = line.priceFact.amountCents
        if amount_cents is None:
            warnings.append(
                BudgetWarning(
                    referenceId=line.referenceId,
                    kind=line.priceFact.kind,
                )
            )
            continue
        known_subtotal_cents += amount_cents

    return BudgetSummary(
        knownSubtotalCents=known_subtotal_cents,
        unknownAmountCount=len(warnings),
        status=(
            BudgetStatus.NEEDS_CONFIRMATION
            if warnings
            else BudgetStatus.COMPLETE
        ),
        warnings=warnings,
    )


__all__ = [
    "BudgetLine",
    "BudgetStatus",
    "BudgetSummary",
    "BudgetWarning",
    "summarize_budget",
]
