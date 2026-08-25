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
