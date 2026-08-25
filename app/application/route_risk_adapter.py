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
