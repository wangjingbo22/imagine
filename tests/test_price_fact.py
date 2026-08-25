from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.models import PriceFact, Provenance, SourceStatus


NOW = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)


def provenance(status: SourceStatus) -> Provenance:
    return Provenance(sourceStatus=status, fetchedAt=NOW)


@pytest.mark.parametrize(
    ("amount_cents", "status"),
    [
        (None, SourceStatus.ONLINE),
        (0, SourceStatus.UNKNOWN),
    ],
)
def test_price_amount_and_unknown_status_must_agree(
    amount_cents: int | None,
    status: SourceStatus,
) -> None:
    with pytest.raises(ValidationError):
        PriceFact(
            amountCents=amount_cents,
            kind="ADMISSION",
            provenance=provenance(status),
        )


def test_known_zero_and_unknown_none_are_distinct_valid_facts() -> None:
    free = PriceFact(
        amountCents=0,
        kind="FREE",
        provenance=provenance(SourceStatus.ONLINE),
    )
    unknown = PriceFact(
        amountCents=None,
        kind="ADMISSION",
        provenance=provenance(SourceStatus.UNKNOWN),
    )

    assert free.amountCents == 0
    assert free.provenance.sourceStatus is SourceStatus.ONLINE
    assert unknown.amountCents is None
    assert unknown.provenance.sourceStatus is SourceStatus.UNKNOWN
