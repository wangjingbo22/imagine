from datetime import UTC, datetime

from app.domain.budget import (
    BudgetLine,
    BudgetStatus,
    summarize_budget,
)
from app.domain.models import PriceFact, Provenance, SourceStatus


NOW = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)


def line(
    reference_id: str,
    *,
    amount_cents: int | None,
    status: SourceStatus,
    kind: str,
) -> BudgetLine:
    return BudgetLine(
        referenceId=reference_id,
        priceFact=PriceFact(
            amountCents=amount_cents,
            kind=kind,
            provenance=Provenance(sourceStatus=status, fetchedAt=NOW),
        ),
    )


def test_all_known_prices_include_real_zero_without_warning() -> None:
    summary = summarize_budget(
        [
            line(
                "museum",
                amount_cents=1_250,
                status=SourceStatus.ONLINE,
                kind="ADMISSION",
            ),
            line(
                "walk",
                amount_cents=0,
                status=SourceStatus.ONLINE,
                kind="FREE",
            ),
        ]
    )

    assert summary.knownSubtotalCents == 1_250
    assert summary.unknownAmountCount == 0
    assert summary.status is BudgetStatus.COMPLETE
    assert summary.warnings == []


def test_unknown_price_is_not_summed_as_zero_and_emits_located_warning() -> None:
    summary = summarize_budget(
        [
            line(
                "museum",
                amount_cents=1_250,
                status=SourceStatus.ONLINE,
                kind="ADMISSION",
            ),
            line(
                "restaurant",
                amount_cents=None,
                status=SourceStatus.UNKNOWN,
                kind="PER_CAPITA_REFERENCE",
            ),
        ]
    )

    assert summary.knownSubtotalCents == 1_250
    assert summary.unknownAmountCount == 1
    assert summary.status is BudgetStatus.NEEDS_CONFIRMATION
    assert [warning.model_dump() for warning in summary.warnings] == [
        {
            "code": "UNKNOWN_PRICE",
            "referenceId": "restaurant",
            "kind": "PER_CAPITA_REFERENCE",
            "message": "价格未知，未计入已知金额小计",
        }
    ]


def test_multiple_unknown_warnings_preserve_input_order() -> None:
    summary = summarize_budget(
        [
            line(
                "route-b",
                amount_cents=None,
                status=SourceStatus.UNKNOWN,
                kind="TRANSIT_FARE",
            ),
            line(
                "place-a",
                amount_cents=None,
                status=SourceStatus.UNKNOWN,
                kind="ADMISSION",
            ),
        ]
    )

    assert summary.knownSubtotalCents == 0
    assert summary.unknownAmountCount == 2
    assert summary.status is BudgetStatus.NEEDS_CONFIRMATION
    assert [warning.referenceId for warning in summary.warnings] == [
        "route-b",
        "place-a",
    ]
