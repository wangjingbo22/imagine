# S1-T006 City Cache, Unknown Budget, and Route Risk Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze cityCode-isolated Provider caching, preserve unknown prices as unknown with explicit budget warnings, and bridge normalized routes to T009 without touching the UI or planner.

**Architecture:** Keep the existing SQLite composite key and Provider normalization, strengthen their contracts with acceptance tests, and add one pure domain budget module. Add a separate pure application adapter from the repository's normalized `Route` (the current RouteSnapshot equivalent) to T009 `RouteRiskInput`, preserving `routeId` as `routeSegment` and failing closed on missing transit facts or invalid caller-supplied rest context.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI domain/application modules, SQLite, pytest 8, pytest-asyncio; existing repository virtual environment at `C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv`.

## Global Constraints

- Work only in `C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.worktrees\czy-S1-T006` on branch `czy-S1-T006`.
- Start implementation from baseline `cd9a9d992a2877f718e1577ae331aab2d487406e` plus the committed T006 design/plan documents; do not switch, modify, merge, or reset `main`.
- Do not push or merge. Hand the final local commit SHA and evidence to the parent task; PR creation remains external.
- Owner is 陈梓元; estimate is 2h; Sprint 1 Day 2; dependency is S1-T005.
- A Provider cache lookup is valid only for the exact `provider + operation + cityCode + canonical request parameters`; never fall back across cities.
- Preserve the existing SQLite schema and `SqliteProviderCache` implementation unless a new RED test proves an actual defect. Characterization tests are the intended cache deliverable.
- Unknown price is exactly `amountCents=None + sourceStatus=UNKNOWN`. A known zero is not unknown. Never coerce unknown to zero.
- Budget aggregation exposes only `knownSubtotalCents`; every unknown item creates an `UNKNOWN_PRICE` warning and forces `NEEDS_CONFIRMATION`.
- Treat `app.domain.models.Route` as the current normalized RouteSnapshot source. Preserve `Route.routeId` byte-for-byte as T009 `routeSegment`.
- Require the T010/T011 caller to supply `elapsed_since_rest_minutes`; T006 validates it is an integer at least as large as the current route's rounded-up duration and never guesses a multi-route rest boundary.
- Do not modify `backend/app/services/route_risk`, PlanVersion schemas/state, T007, T010/T011 UI or planner, frontend files, HTTP routes, SQLite schema, or unrelated modules.
- Add no dependencies and perform no network, LLM, clock-dependent business decision, or random behavior.
- Use strict TDD: add the stated test, run the exact RED command and record the expected failure, add only the minimal implementation, then run the GREEN command.
- Baseline evidence is `127 passed in 2.51s` using the repository virtual environment.

---

## File Map

| File | Action | Single responsibility |
|---|---|---|
| `tests/test_place_service.py` | Modify | Two-city same-name cache and cached-unknown acceptance |
| `tests/snapshots/s1_t006_cache_keys.json` | Create | Reviewable composite-key snapshot without payload or secrets |
| `app/domain/models.py` | Modify | Symmetric `PriceFact` amount/source invariant |
| `app/application/amap_service.py` | Modify | Reject non-finite Provider decimals before cents conversion |
| `tests/test_price_fact.py` | Create | Price source normalization model contract |
| `app/domain/budget.py` | Create | Pure known-subtotal and unknown-warning aggregation |
| `tests/test_budget.py` | Create | Known zero, mixed unknown, warning-order budget tests |
| `app/application/route_risk_adapter.py` | Create | Pure `Route -> RouteRiskInput` mapping |
| `tests/test_route_risk_adapter.py` | Create | Mapping, stable ID, T009 integration, and fail-closed tests |

The implementation must not add exports to broad `__init__.py` modules; callers import the two new focused modules directly.

---

### Task 1: Freeze Two-City Cache Isolation and Key Snapshot

**Files:**

- Modify: `tests/test_place_service.py`
- Create: `tests/snapshots/s1_t006_cache_keys.json`
- Verify unchanged: `app/infrastructure/cache.py`

**Interfaces:**

- Consumes: `AmapLocationService.search_places(city, *, keywords, types, page, page_size) -> PlaceCollection`.
- Consumes: SQLite key columns `provider`, `operation`, `city_code`, `request_hash`.
- Produces: acceptance evidence that two cities with identical user query text write and restore distinct cache records.
- Produces: deterministic JSON snapshot sorted by `city_code`; it contains no Provider payload, API key, timestamp, or user secret.

- [ ] **Step 1: Extend the place payload helper without changing existing callers**

Add these imports at the top of `tests/test_place_service.py`:

```python
import json
import sqlite3
from pathlib import Path
```

Replace only the `place_payload` signature and the `id/name` assignments with:

```python
def place_payload(
    *,
    provider_city_code: str,
    ad_code: str,
    cost: str | list[Any] = "",
    place_id: str | None = None,
    name: str = "测试景点",
) -> dict[str, Any]:
    return {
        "status": "1",
        "count": "1",
        "pois": [
            {
                "id": place_id or f"poi-{ad_code}",
                "name": name,
                "address": "测试路 1 号",
                "location": "116.397499,39.908722",
                "citycode": provider_city_code,
                "adcode": ad_code,
                "type": "风景名胜",
                "tel": [],
                "biz_ext": {"rating": "4.8", "cost": cost},
            }
        ],
    }
```

Add the snapshot constant after imports:

```python
CACHE_KEY_SNAPSHOT = (
    Path(__file__).parent / "snapshots" / "s1_t006_cache_keys.json"
)
```

- [ ] **Step 2: Add the two-city offline restore test before creating the snapshot**

Append this test to `tests/test_place_service.py`:

```python
@pytest.mark.asyncio
async def test_same_named_poi_cache_is_isolated_by_city_code_and_matches_key_snapshot(
    tmp_path,
    beijing: CityContext,
    shanghai: CityContext,
) -> None:
    query = {
        "keywords": "城市博物馆",
        "types": [],
        "page": 1,
        "page_size": 20,
    }
    await build_service(
        tmp_path,
        SearchClient(
            place_payload(
                provider_city_code="010",
                ad_code="110101",
                place_id="same-name-beijing",
                name="城市博物馆",
            )
        ),
    ).search_places(beijing, **query)
    await build_service(
        tmp_path,
        SearchClient(
            place_payload(
                provider_city_code="021",
                ad_code="310101",
                place_id="same-name-shanghai",
                name="城市博物馆",
            )
        ),
    ).search_places(shanghai, **query)

    offline = build_service(
        tmp_path,
        SearchClient(error=AppError("PROVIDER_TIMEOUT", "timeout", 503, True)),
    )
    cached_beijing = await offline.search_places(beijing, **query)
    cached_shanghai = await offline.search_places(shanghai, **query)

    assert cached_beijing.provenance.sourceStatus is SourceStatus.VERIFIED_CACHE
    assert cached_beijing.cityCode == "110000"
    assert cached_beijing.places[0].placeId == "same-name-beijing"
    assert cached_beijing.places[0].adCode == "110101"
    assert cached_shanghai.provenance.sourceStatus is SourceStatus.VERIFIED_CACHE
    assert cached_shanghai.cityCode == "310000"
    assert cached_shanghai.places[0].placeId == "same-name-shanghai"
    assert cached_shanghai.places[0].adCode == "310101"

    with sqlite3.connect(tmp_path / "cache.sqlite3") as connection:
        rows = connection.execute(
            """
            SELECT provider, operation, city_code, request_hash
            FROM provider_cache
            WHERE operation = 'place_search'
            ORDER BY city_code
            """
        ).fetchall()
    actual_snapshot = [
        {
            "provider": row[0],
            "operation": row[1],
            "cityCode": row[2],
            "requestHash": row[3],
        }
        for row in rows
    ]
    expected_snapshot = json.loads(CACHE_KEY_SNAPSHOT.read_text(encoding="utf-8"))
    assert actual_snapshot == expected_snapshot
```

- [ ] **Step 3: Run the cache acceptance test and observe RED**

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_place_service.py::test_same_named_poi_cache_is_isolated_by_city_code_and_matches_key_snapshot
```

Expected: FAIL with `FileNotFoundError` for
`tests/snapshots/s1_t006_cache_keys.json`. The two online writes and two offline reads must have completed before that failure; any earlier assertion failure means the existing cache contract is defective and must be investigated before changing production code.

- [ ] **Step 4: Create the reviewed key snapshot**

Create `tests/snapshots/s1_t006_cache_keys.json` with exactly:

```json
[
  {
    "provider": "AMAP",
    "operation": "place_search",
    "cityCode": "110000",
    "requestHash": "2e0661f0a04ac1e591a39979ea61f5ce3f0c0a5ec9ab7536492d0710b2eec9c5"
  },
  {
    "provider": "AMAP",
    "operation": "place_search",
    "cityCode": "310000",
    "requestHash": "49e5ec5dfe9a06e4ebaeaf58c872d64bc95f564a8b547f1e2bacb82e4e127e2d"
  }
]
```

- [ ] **Step 5: Run GREEN for all place/cache behavior**

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_place_service.py
```

Expected: all tests PASS, including the pre-existing one-city cache miss test. Do not modify `cache.py` when this is green.

- [ ] **Step 6: Commit the isolated cache evidence**

```powershell
git add -- tests/test_place_service.py tests/snapshots/s1_t006_cache_keys.json
git commit -m "test(cache): lock city-code isolation evidence"
```

---

### Task 2: Enforce Symmetric Unknown Price Normalization

**Files:**

- Create: `tests/test_price_fact.py`
- Modify: `app/domain/models.py` (`PriceFact.validate_unknown_price` only)
- Modify: `app/application/amap_service.py` (`_yuan_to_cents` finite-value guard only)
- Modify: `tests/test_place_service.py` (Provider/cached unknown regressions)

**Interfaces:**

- Consumes/produces: existing `PriceFact(amountCents, kind, provenance)`.
- Invariant: `(amountCents is None) == (provenance.sourceStatus is UNKNOWN)`.
- Error: inconsistent facts fail Pydantic validation at construction; no coercion is performed.

- [ ] **Step 1: Write the model-level failing tests**

Create `tests/test_price_fact.py`:

```python
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
```

- [ ] **Step 2: Run the model test and observe RED**

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_price_fact.py::test_price_amount_and_unknown_status_must_agree
```

Expected: FAIL for the `(0, UNKNOWN)` parameter because the current one-way validator accepts it.

- [ ] **Step 3: Make the smallest symmetric validator change**

Replace `PriceFact.validate_unknown_price` in `app/domain/models.py` with:

```python
    @model_validator(mode="after")
    def validate_unknown_price(self) -> "PriceFact":
        amount_is_unknown = self.amountCents is None
        status_is_unknown = self.provenance.sourceStatus is SourceStatus.UNKNOWN
        if amount_is_unknown != status_is_unknown:
            raise ValueError(
                "UNKNOWN price must use amountCents=None and known price must not use UNKNOWN"
            )
        return self
```

- [ ] **Step 4: Add Provider invalid-value and cached-unknown regressions**

Append to `tests/test_place_service.py`:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cost",
    ["", [], "not-a-price", "-1", "NaN", "Infinity", "-Infinity"],
)
async def test_missing_or_invalid_provider_price_stays_unknown(
    tmp_path,
    beijing: CityContext,
    cost: str | list[Any],
) -> None:
    service = build_service(
        tmp_path,
        SearchClient(place_payload(provider_city_code="010", ad_code="110101", cost=cost)),
    )

    result = await service.search_places(
        beijing,
        keywords="城市博物馆",
        types=[],
        page=1,
        page_size=20,
    )

    price = result.places[0].priceReference
    assert price.amountCents is None
    assert price.provenance.sourceStatus is SourceStatus.UNKNOWN


@pytest.mark.asyncio
async def test_cached_unknown_price_keeps_unknown_price_provenance(
    tmp_path,
    beijing: CityContext,
) -> None:
    query = {
        "keywords": "无票价景点",
        "types": [],
        "page": 1,
        "page_size": 20,
    }
    await build_service(
        tmp_path,
        SearchClient(place_payload(provider_city_code="010", ad_code="110101", cost="")),
    ).search_places(beijing, **query)
    offline = build_service(
        tmp_path,
        SearchClient(error=AppError("PROVIDER_TIMEOUT", "timeout", 503, True)),
    )

    cached = await offline.search_places(beijing, **query)

    assert cached.provenance.sourceStatus is SourceStatus.VERIFIED_CACHE
    assert cached.places[0].priceReference.amountCents is None
    assert (
        cached.places[0].priceReference.provenance.sourceStatus
        is SourceStatus.UNKNOWN
    )
    assert (
        cached.places[0].priceReference.provenance.fetchedAt
        == cached.provenance.fetchedAt
    )
```

- [ ] **Step 5: Run the non-finite Provider cases and observe their RED**

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_place_service.py::test_missing_or_invalid_provider_price_stays_unknown
```

Expected: at least the `NaN`/infinity cases ERROR or FAIL because the current
`_yuan_to_cents` reaches Decimal comparison/quantization instead of returning unknown.

- [ ] **Step 6: Reject non-finite Decimal values before conversion**

In `app/application/amap_service.py`, replace `_yuan_to_cents` with:

```python
def _yuan_to_cents(value: Any) -> int | None:
    text = _text(value)
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
```

- [ ] **Step 7: Run GREEN for price and place contracts**

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_price_fact.py tests/test_place_service.py
```

Expected: all tests PASS. In particular, free `0 + ONLINE` remains valid and cached unknown remains `None + UNKNOWN` even though the enclosing collection is `VERIFIED_CACHE`.

- [ ] **Step 8: Commit the source-normalization invariant**

```powershell
git add -- app/domain/models.py app/application/amap_service.py tests/test_price_fact.py tests/test_place_service.py
git commit -m "fix(price): enforce unknown source invariant"
```

---

### Task 3: Add Known-Subtotal Budget Aggregation and Explicit Warnings

**Files:**

- Create: `app/domain/budget.py`
- Create: `tests/test_budget.py`

**Interfaces:**

- Consumes: `Iterable[BudgetLine]`, where `BudgetLine.referenceId` locates the source and `BudgetLine.priceFact` already satisfies the Task 2 invariant.
- Produces: `BudgetSummary(knownSubtotalCents, unknownAmountCount, status, warnings)`.
- Status: `COMPLETE` only when there are no unknown lines; otherwise `NEEDS_CONFIRMATION`.
- Warning order: exactly input order; one `UNKNOWN_PRICE` per unknown line.

- [ ] **Step 1: Write all budget behavior tests before the module exists**

Create `tests/test_budget.py`:

```python
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
```

- [ ] **Step 2: Run the budget test and observe RED**

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_budget.py
```

Expected: collection ERROR with `ModuleNotFoundError: No module named 'app.domain.budget'`.

- [ ] **Step 3: Implement the complete pure budget module**

Create `app/domain/budget.py`:

```python
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
```

- [ ] **Step 4: Run GREEN and the price invariant regression**

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_budget.py tests/test_price_fact.py
```

Expected: all tests PASS. Review the implementation and confirm no expression uses `amount_cents or 0`, `sum(... or 0)`, or a field named `totalCostCents`.

- [ ] **Step 5: Commit the independently testable budget slice**

```powershell
git add -- app/domain/budget.py tests/test_budget.py
git commit -m "feat(budget): warn without summing unknown prices"
```

---

### Task 4: Adapt the Normalized Route Snapshot to T009

**Files:**

- Create: `app/application/route_risk_adapter.py`
- Create: `tests/test_route_risk_adapter.py`
- Verify unchanged: `backend/app/services/route_risk/models.py`
- Verify unchanged: `backend/app/services/route_risk/evaluator.py`

**Interfaces:**

- Consumes: `route_snapshot: app.domain.models.Route` and keyword-only
  `elapsed_since_rest_minutes: int` supplied by the downstream schedule context.
- Produces: `app.services.route_risk.models.RouteRiskInput` containing exactly one `RouteSegmentRiskFacts`.
- Stable mapping: `Route.routeId -> RouteSegmentRiskFacts.route_segment` without renaming, indexing, or hashing.
- Error: `RouteRiskAdapterError(code="ROUTE_RISK_INPUT_INVALID", route_segment=<routeId>, field=<field>)`.

- [ ] **Step 1: Write adapter and downstream integration tests before the module exists**

Create `tests/test_route_risk_adapter.py`:

```python
from datetime import UTC, datetime

import pytest

from app.application.route_risk_adapter import (
    RouteRiskAdapterError,
    route_snapshot_to_risk_input,
)
from app.domain.models import (
    PriceFact,
    Provenance,
    Route,
    SourceStatus,
    TravelMode,
)
from app.schemas.constraint import Constraint
from app.schemas.trip import GeoPoint
from app.services.route_risk import ValidationStatus, evaluate_route_risk
from app.services.route_risk.models import WalkType


NOW = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
ORIGIN = GeoPoint(longitude=116.397499, latitude=39.908722)
DESTINATION = GeoPoint(longitude=116.481028, latitude=39.989643)


def route_snapshot(
    *,
    route_id: str = "route-stable-001",
    mode: TravelMode = TravelMode.TRANSIT,
    distance_meters: int = 8_000,
    duration_seconds: int = 2_400,
    walking_distance_meters: int | None = 600,
    transfer_count: int | None = 2,
) -> Route:
    provenance = Provenance(sourceStatus=SourceStatus.ONLINE, fetchedAt=NOW)
    return Route(
        routeId=route_id,
        mode=mode,
        origin=ORIGIN,
        destination=DESTINATION,
        distanceMeters=distance_meters,
        durationSeconds=duration_seconds,
        walkingDistanceMeters=walking_distance_meters,
        transferCount=transfer_count,
        steps=[],
        priceReference=PriceFact(
            amountCents=500,
            kind="TRANSIT_FARE",
            provenance=provenance,
        ),
        provenance=provenance,
    )


def test_transit_route_maps_exact_facts_and_stable_route_segment() -> None:
    source = route_snapshot()

    first = route_snapshot_to_risk_input(source, elapsed_since_rest_minutes=40)
    second = route_snapshot_to_risk_input(source, elapsed_since_rest_minutes=40)

    assert len(first.segments) == 1
    segment = first.segments[0]
    assert segment.route_segment == "route-stable-001"
    assert segment.walking_distance_meters == 600
    assert segment.cumulative_transfers == 2
    assert segment.elapsed_since_rest_minutes == 40
    assert segment.walk_types == (WalkType.UNKNOWN,)
    assert first.model_dump_json(by_alias=True) == second.model_dump_json(
        by_alias=True
    )


def test_unknown_stair_evidence_reaches_t009_with_same_route_segment() -> None:
    risk_input = route_snapshot_to_risk_input(
        route_snapshot(),
        elapsed_since_rest_minutes=40,
    )
    constraint = Constraint(
        field="avoidStairs",
        operator="EQ",
        value=True,
        scope="ROUTE_SEGMENT",
        hardness="HARD",
    )

    report = evaluate_route_risk(risk_input, [constraint])

    assert report.status is ValidationStatus.NEEDS_CONFIRMATION
    assert report.results[0].route_segment == "route-stable-001"


@pytest.mark.parametrize(
    ("mode", "expected_walk", "expected_walk_type"),
    [
        (TravelMode.WALKING, 850, WalkType.UNKNOWN),
        (TravelMode.DRIVING, 0, WalkType.LEVEL),
        (TravelMode.BICYCLING, 0, WalkType.LEVEL),
    ],
)
def test_non_transit_mode_boundaries(
    mode: TravelMode,
    expected_walk: int,
    expected_walk_type: WalkType,
) -> None:
    result = route_snapshot_to_risk_input(
        route_snapshot(
            mode=mode,
            distance_meters=850,
            duration_seconds=61,
            walking_distance_meters=None,
            transfer_count=None,
        ),
        elapsed_since_rest_minutes=2,
    )

    segment = result.segments[0]
    assert segment.walking_distance_meters == expected_walk
    assert segment.cumulative_transfers == 0
    assert segment.elapsed_since_rest_minutes == 2
    assert segment.walk_types == (expected_walk_type,)


@pytest.mark.parametrize(
    ("source", "elapsed_since_rest_minutes", "expected_field"),
    [
        (route_snapshot(walking_distance_meters=None), 40, "walkingDistanceMeters"),
        (route_snapshot(transfer_count=None), 40, "transferCount"),
        (route_snapshot(route_id="r" * 121), 40, "routeId"),
        (route_snapshot(), 39, "elapsedSinceRestMinutes"),
        (route_snapshot(), True, "elapsedSinceRestMinutes"),
    ],
)
def test_invalid_required_route_fact_fails_closed(
    source: Route,
    elapsed_since_rest_minutes: int,
    expected_field: str,
) -> None:
    with pytest.raises(RouteRiskAdapterError) as captured:
        route_snapshot_to_risk_input(
            source,
            elapsed_since_rest_minutes=elapsed_since_rest_minutes,
        )

    assert captured.value.code == "ROUTE_RISK_INPUT_INVALID"
    assert captured.value.route_segment == source.routeId
    assert captured.value.field == expected_field
```

- [ ] **Step 2: Run the adapter test and observe RED**

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_route_risk_adapter.py
```

Expected: collection ERROR with
`ModuleNotFoundError: No module named 'app.application.route_risk_adapter'`.

- [ ] **Step 3: Implement the complete pure adapter**

Create `app/application/route_risk_adapter.py`:

```python
from app.domain.models import Route, TravelMode
from app.services.route_risk.models import (
    RouteRiskInput,
    RouteSegmentRiskFacts,
    WalkType,
)


class RouteRiskAdapterError(ValueError):
    def __init__(
        self,
        *,
        route_segment: str,
        field: str,
        message: str,
    ) -> None:
        self.code = "ROUTE_RISK_INPUT_INVALID"
        self.route_segment = route_segment
        self.field = field
        super().__init__(message)


def route_snapshot_to_risk_input(
    route_snapshot: Route,
    *,
    elapsed_since_rest_minutes: int,
) -> RouteRiskInput:
    route_segment = route_snapshot.routeId
    if len(route_segment) > 120:
        raise RouteRiskAdapterError(
            route_segment=route_segment,
            field="routeId",
            message="routeId exceeds the T009 routeSegment limit",
        )

    if route_snapshot.mode is TravelMode.TRANSIT:
        if route_snapshot.walkingDistanceMeters is None:
            raise RouteRiskAdapterError(
                route_segment=route_segment,
                field="walkingDistanceMeters",
                message="transit route requires walkingDistanceMeters",
            )
        if route_snapshot.transferCount is None:
            raise RouteRiskAdapterError(
                route_segment=route_segment,
                field="transferCount",
                message="transit route requires transferCount",
            )
        walking_distance_meters = route_snapshot.walkingDistanceMeters
        cumulative_transfers = route_snapshot.transferCount
    elif route_snapshot.mode is TravelMode.WALKING:
        walking_distance_meters = route_snapshot.distanceMeters
        cumulative_transfers = 0
    else:
        walking_distance_meters = 0
        cumulative_transfers = 0

    minimum_elapsed_minutes = (route_snapshot.durationSeconds + 59) // 60
    if (
        type(elapsed_since_rest_minutes) is not int
        or elapsed_since_rest_minutes < minimum_elapsed_minutes
    ):
        raise RouteRiskAdapterError(
            route_segment=route_segment,
            field="elapsedSinceRestMinutes",
            message=(
                "elapsedSinceRestMinutes must be an integer covering the route duration"
            ),
        )

    walk_types = (
        (WalkType.UNKNOWN,)
        if route_snapshot.mode in {TravelMode.WALKING, TravelMode.TRANSIT}
        else (WalkType.LEVEL,)
    )
    return RouteRiskInput(
        segments=(
            RouteSegmentRiskFacts(
                route_segment=route_segment,
                walking_distance_meters=walking_distance_meters,
                cumulative_transfers=cumulative_transfers,
                elapsed_since_rest_minutes=elapsed_since_rest_minutes,
                walk_types=walk_types,
            ),
        )
    )


__all__ = ["RouteRiskAdapterError", "route_snapshot_to_risk_input"]
```

- [ ] **Step 4: Run GREEN for adapter and T009 integration**

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_route_risk_adapter.py backend/tests/test_route_risk.py
```

Expected: all tests PASS. Inspect that `routeSegment` is still
`route-stable-001`, stair evidence is `UNKNOWN`, and no code was added to the T009 model/evaluator.

- [ ] **Step 5: Commit the route integration slice**

```powershell
git add -- app/application/route_risk_adapter.py tests/test_route_risk_adapter.py
git commit -m "feat(route): adapt normalized route to risk input"
```

---

### Task 5: Run Full Acceptance, Scope Audit, and Prepare Delivery Evidence

**Files:**

- Review: every change from baseline `cd9a9d992a2877f718e1577ae331aab2d487406e` to `HEAD`
- Do not create or modify production files in this task.

**Interfaces:**

- Produces: targeted test transcript, full pytest transcript, cache-key snapshot, commit list, clean-tree evidence, and a PR-ready handoff.
- External dependency: actual PR URL/number can only be filled by the parent/user after push; do not invent it and do not push from this worktree.

- [ ] **Step 1: Run the exact T006 acceptance set**

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_place_service.py tests/test_price_fact.py tests/test_budget.py tests/test_route_risk_adapter.py backend/tests/test_route_risk.py
```

Expected: all selected tests PASS with no collection errors or warnings from changed code.

- [ ] **Step 2: Run the complete Python regression suite**

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q
```

Expected: at least the 127 baseline tests plus all new T006 tests PASS. Record the actual count and duration; do not copy the baseline count as if it were the final result.

- [ ] **Step 3: Verify formatting, branch, scope, and no secret leakage**

```powershell
$t006Base = 'cd9a9d992a2877f718e1577ae331aab2d487406e'
git branch --show-current
git diff --check "$t006Base...HEAD"
git diff --name-only "$t006Base...HEAD"
git diff "$t006Base...HEAD" -- . ':!docs/superpowers/**' | Select-String -Pattern 'AMAP_WEB_SERVICE_KEY\s*=|api[_-]?key\s*=' -CaseSensitive:$false
git status --short
```

Expected:

- branch output is exactly `czy-S1-T006`;
- `git diff --check` produces no output;
- changed production files are only `app/domain/models.py`,
  `app/application/amap_service.py`, `app/domain/budget.py`, and
  `app/application/route_risk_adapter.py`;
- test/evidence files are only those listed in the File Map;
- secret scan produces no matches;
- status is clean after the four small commits.

- [ ] **Step 4: Perform the independent QA matrix**

An independent reviewer must execute, not merely read, these cases:

| QA ID | Given / When | Expected |
|---|---|---|
| QA-C01 | 北京与上海写入同名“城市博物馆”，两次在线调用随后失败 | 两城各自恢复自身 `placeId/adCode/cityCode`；均为 `VERIFIED_CACHE` |
| QA-C02 | 读取 key snapshot | 两个 key 都含显式 cityCode；hash 不同；无 payload、Key、时间戳 |
| QA-C03 | 仅北京有缓存，上海在线失败 | 上海抛原 `PROVIDER_TIMEOUT`，不返回北京数据 |
| QA-P01 | 缺失、列表、非法字符串、负数、NaN、正负 Infinity | 全部为 `None + UNKNOWN`，不泄漏 Decimal 异常 |
| QA-P02 | `0 + ONLINE` 与 `None + UNKNOWN` | 两者均合法且语义不同；`0 + UNKNOWN` 被拒绝 |
| QA-P03 | unknown 经缓存恢复 | 集合是 `VERIFIED_CACHE`，价格事实仍是 `UNKNOWN` |
| QA-B01 | 1250 分已知 + 0 分免费 | 已知小计 1250，`COMPLETE`，无预警 |
| QA-B02 | 1250 分已知 + unknown | 已知小计仍为 1250，状态 `NEEDS_CONFIRMATION`，有定位预警 |
| QA-B03 | 两个 unknown | 小计 0，两个预警按输入顺序排列 |
| QA-R01 | 完整公交 Route + 40 分钟累计休息间隔 | routeId 原样成为 routeSegment；600m、2 次、40min 精确映射 |
| QA-R02 | 同一 Route 映射两次 | camelCase JSON 字节一致 |
| QA-R03 | 将公交映射结果交给避楼梯硬规则 | `NEEDS_CONFIRMATION`，结果保留源 routeSegment |
| QA-R04 | 公交步行/换乘事实缺失、累计休息间隔小于本段时长或 routeId 超长 | `ROUTE_RISK_INPUT_INVALID`，具体 field 可定位，不填 0 |
| QA-S01 | 审查 diff | 无前端、规划器、PlanVersion、T009 evaluator、SQLite schema 改动 |

- [ ] **Step 5: Capture local delivery metadata without push/merge**

```powershell
$t006Base = 'cd9a9d992a2877f718e1577ae331aab2d487406e'
git log --oneline "$t006Base..HEAD"
git rev-parse HEAD
git status --short --branch
```

Handoff must include:

- final local commit SHA and the four implementation commit SHAs;
- exact targeted/full pytest counts and durations;
- cache snapshot path;
- the RED failure observed for each task and the corresponding GREEN command;
- explicit statement that `Route` is the current RouteSnapshot equivalent and `routeId` is preserved as `routeSegment`;
- explicit statement that no UI/planner/T009 evaluator/PlanVersion/cache schema was changed;
- `PR: pending external push/creation` until a real PR exists.

If Task 5 uncovers a defect, return to the owning task, add a reproducing RED test, make the smallest fix, rerun its GREEN command and the full suite, then create a focused fix commit. Do not amend unrelated commits and do not weaken assertions.

---

## TDD Command Index

| Slice | RED command | Expected RED | GREEN command |
|---|---|---|---|
| Cache | `pytest ...::test_same_named_poi_cache_is_isolated_by_city_code_and_matches_key_snapshot` | snapshot `FileNotFoundError` | `pytest -q tests/test_place_service.py` |
| Price model | `pytest ...::test_price_amount_and_unknown_status_must_agree` | `0 + UNKNOWN` not rejected | `pytest -q tests/test_price_fact.py` |
| Provider price | `pytest ...::test_missing_or_invalid_provider_price_stays_unknown` | non-finite Decimal error | `pytest -q tests/test_price_fact.py tests/test_place_service.py` |
| Budget | `pytest -q tests/test_budget.py` | missing `app.domain.budget` | `pytest -q tests/test_budget.py tests/test_price_fact.py` |
| Route | `pytest -q tests/test_route_risk_adapter.py` | missing adapter module | `pytest -q tests/test_route_risk_adapter.py backend/tests/test_route_risk.py` |

Every abbreviated command above uses:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m
```

as its executable prefix.

## Boundary and Error Semantics Summary

| Boundary | Invalid state | Required behavior |
|---|---|---|
| Cache lookup | exact city/parameters absent | rethrow original online `AppError`; no cross-city search |
| `PriceFact` | amount missing without UNKNOWN, or known amount with UNKNOWN | Pydantic validation error; no coercion |
| Budget summary | one or more unknown prices | skip unknown from arithmetic, emit one warning each, return `NEEDS_CONFIRMATION` |
| Route adapter | transit walking/transfer fact missing | `RouteRiskAdapterError`, field-addressable, no zero fill |
| Route adapter | caller rest context is non-integer or below route duration | `RouteRiskAdapterError(field="elapsedSinceRestMinutes")`; no inferred reset |
| Route adapter | routeId longer than 120 | `RouteRiskAdapterError(field="routeId")` |
| Stair evidence | Provider has no structured evidence on walking/transit | map `WalkType.UNKNOWN`; T009 decides `NEEDS_CONFIRMATION` |

## Small-Step Commit Sequence

1. `test(cache): lock city-code isolation evidence`
2. `fix(price): enforce unknown source invariant`
3. `feat(budget): warn without summing unknown prices`
4. `feat(route): adapt normalized route to risk input`
5. Optional focused `fix(...)` only if Task 5 finds a new test-proven defect.

Do not squash these locally; the parent can choose PR merge policy after review.

## Plan Self-Review Result

- **Spec coverage:** C-01/C-02/C-03 map to Task 1; P-01/P-02/P-03 to Task 2;
  B-01/B-02/B-03 to Task 3; R-01 through R-05 to Task 4; delivery and scope
  evidence to Task 5.
- **Completeness:** every created module, model, function, error field, snapshot value,
  test body, command, expected RED/GREEN result, and commit message is specified.
- **Type consistency:** `BudgetLine.priceFact`, `BudgetSummary.knownSubtotalCents`,
  `RouteRiskAdapterError.route_segment`, and T009 snake_case constructor fields are
  used consistently across production and test snippets.
- **Scope:** the plan changes only four focused production files plus tests/evidence;
  it does not modify T010/T011, PlanVersion, T009, HTTP, frontend, or SQLite schema.

## Execution Handoff

Recommended execution is **subagent-driven development**: use a fresh implementer for
each of Tasks 1–4 and review specification compliance plus code quality before moving to
the next task; then use an independent QA worker for Task 5. Inline execution is also
valid when using `superpowers:executing-plans`, but it must keep the same RED/GREEN and
commit checkpoints. Neither execution mode may push or merge from this worktree.
