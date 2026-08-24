from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.constraint import Constraint
from app.schemas.assistance import ordinary_profile
from app.services.route_risk import (
    FIELD_AVOID_STAIRS,
    FIELD_MAX_TRANSFERS,
    FIELD_REST_INTERVAL,
    FIELD_WALK_SEGMENT,
    RouteRiskContractError,
    RouteRiskInput,
    RouteSegmentRiskFacts,
    ValidationStatus,
    WalkType,
    evaluate_route_risk,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "routes"


def load_route(name: str) -> RouteRiskInput:
    return RouteRiskInput.model_validate_json(
        (FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"),
        strict=True,
    )


def hard_constraint(
    field: str,
    operator: str,
    value: int | bool,
    *,
    scope: str = "ROUTE_SEGMENT",
) -> Constraint:
    return Constraint(
        field=field,
        operator=operator,
        value=value,
        scope=scope,
        hardness="HARD",
    )


@pytest.mark.parametrize(
    ("fixture", "constraint", "expected_segment", "expected_rule"),
    [
        (
            "stairs",
            hard_constraint(FIELD_AVOID_STAIRS, "EQ", True),
            "seg-stairs",
            "CARE.ROUTE.STAIRS_FORBIDDEN",
        ),
        (
            "excessive_walk",
            hard_constraint(FIELD_WALK_SEGMENT, "LTE", 500),
            "seg-walk-501",
            "CARE.ROUTE.WALK_SEGMENT_LIMIT",
        ),
        (
            "too_many_transfers",
            hard_constraint(FIELD_MAX_TRANSFERS, "LTE", 2, scope="ROUTE"),
            "seg-transfer-3",
            "CARE.ROUTE.TRANSFER_LIMIT",
        ),
        (
            "missed_rest",
            hard_constraint(FIELD_REST_INTERVAL, "LTE", 90, scope="ROUTE"),
            "seg-rest-91",
            "CARE.ROUTE.REST_INTERVAL",
        ),
    ],
    ids=["stairs", "walking", "transfers", "rest"],
)
def test_four_route_risks_fail_with_traceable_segment_and_rule(
    fixture: str,
    constraint: Constraint,
    expected_segment: str,
    expected_rule: str,
):
    report = evaluate_route_risk(load_route(fixture), [constraint])

    assert report.status is ValidationStatus.FAIL
    assert len(report.results) == 1
    assert report.results[0].status is ValidationStatus.FAIL
    assert report.results[0].route_segment == expected_segment
    assert report.results[0].rule_id == expected_rule
    assert report.model_dump(by_alias=True)["results"][0]["routeSegment"] == (
        expected_segment
    )


def test_exact_walk_transfer_and_rest_boundaries_pass():
    route = RouteRiskInput(
        segments=(
            RouteSegmentRiskFacts(
                route_segment="seg-boundary",
                walking_distance_meters=500,
                cumulative_transfers=2,
                elapsed_since_rest_minutes=90,
                walk_types=(WalkType.LEVEL,),
            ),
        )
    )
    constraints = (
        hard_constraint(FIELD_WALK_SEGMENT, "LTE", 500),
        hard_constraint(FIELD_MAX_TRANSFERS, "LTE", 2, scope="ROUTE"),
        hard_constraint(FIELD_REST_INTERVAL, "LTE", 90, scope="ROUTE"),
    )

    report = evaluate_route_risk(route, constraints)

    assert report.status is ValidationStatus.PASS
    assert {result.status for result in report.results} == {
        ValidationStatus.PASS
    }


def test_ordinary_profile_has_no_demographic_false_positive():
    profile = ordinary_profile()
    report = evaluate_route_risk(
        load_route("stairs"),
        [
            hard_constraint(
                FIELD_AVOID_STAIRS,
                "EQ",
                profile.avoid_stairs,
            )
        ],
    )

    assert report.status is ValidationStatus.PASS
    assert len(report.results) == 1
    assert report.results[0].status is ValidationStatus.PASS
    assert report.results[0].route_segment is None


def test_unknown_stair_evidence_requires_confirmation_not_pass():
    route = RouteRiskInput(
        segments=(
            RouteSegmentRiskFacts(
                route_segment="seg-unknown",
                walking_distance_meters=100,
                cumulative_transfers=0,
                elapsed_since_rest_minutes=15,
                walk_types=(WalkType.UNKNOWN,),
            ),
        )
    )

    report = evaluate_route_risk(
        route,
        [hard_constraint(FIELD_AVOID_STAIRS, "EQ", True)],
    )

    assert report.status is ValidationStatus.NEEDS_CONFIRMATION
    assert report.results[0].route_segment == "seg-unknown"


def test_unknown_hard_route_constraint_fails_closed():
    unknown = hard_constraint(
        "wheelchairRampEvidence",
        "EQ",
        True,
        scope="ROUTE_SEGMENT",
    )

    with pytest.raises(RouteRiskContractError) as exc_info:
        evaluate_route_risk(load_route("stairs"), [unknown])

    assert exc_info.value.code == "UNSUPPORTED_HARD_ROUTE_CONSTRAINT"
    assert exc_info.value.field == "wheelchairRampEvidence"


def test_non_route_constraint_is_outside_this_evaluator():
    budget = hard_constraint(
        "totalBudgetCents",
        "LTE",
        35_000,
        scope="TRIP",
    )

    report = evaluate_route_risk(load_route("stairs"), [budget])

    assert report.status is ValidationStatus.PASS
    assert report.results == ()


def test_combined_results_have_stable_rule_order_and_bytes():
    route = load_route("stairs")
    segment = route.segments[0].model_copy(
        update={
            "walking_distance_meters": 501,
            "cumulative_transfers": 3,
            "elapsed_since_rest_minutes": 91,
        }
    )
    combined = RouteRiskInput(segments=(segment,))
    constraints = (
        hard_constraint(FIELD_REST_INTERVAL, "LTE", 90, scope="ROUTE"),
        hard_constraint(FIELD_MAX_TRANSFERS, "LTE", 2, scope="ROUTE"),
        hard_constraint(FIELD_WALK_SEGMENT, "LTE", 500),
        hard_constraint(FIELD_AVOID_STAIRS, "EQ", True),
    )

    first = evaluate_route_risk(combined, constraints)
    second = evaluate_route_risk(combined, tuple(reversed(constraints)))

    assert [result.rule_id for result in first.results] == [
        "CARE.ROUTE.STAIRS_FORBIDDEN",
        "CARE.ROUTE.WALK_SEGMENT_LIMIT",
        "CARE.ROUTE.TRANSFER_LIMIT",
        "CARE.ROUTE.REST_INTERVAL",
    ]
    assert first.model_dump_json(by_alias=True) == second.model_dump_json(
        by_alias=True
    )


def test_invalid_operator_does_not_silently_pass():
    malformed = hard_constraint(FIELD_WALK_SEGMENT, "LT", 500)

    with pytest.raises(RouteRiskContractError) as exc_info:
        evaluate_route_risk(load_route("excessive_walk"), [malformed])

    assert exc_info.value.code == "INVALID_ROUTE_CONSTRAINT"


def test_route_fixture_missing_risk_fact_is_structurally_rejected():
    with pytest.raises(ValidationError):
        RouteRiskInput.model_validate(
            {
                "segments": [
                    {
                        "routeSegment": "seg-incomplete",
                        "walkingDistanceMeters": 10,
                        "cumulativeTransfers": 0,
                        "walkTypes": ["LEVEL"],
                    }
                ]
            },
            strict=True,
        )


def test_empty_walk_type_evidence_is_rejected_instead_of_treated_as_pass():
    with pytest.raises(ValidationError):
        RouteRiskInput.model_validate_json(
            """
            {
              "segments": [
                {
                  "routeSegment": "seg-no-walk-evidence",
                  "walkingDistanceMeters": 10,
                  "cumulativeTransfers": 0,
                  "elapsedSinceRestMinutes": 5,
                  "walkTypes": []
                }
              ]
            }
            """,
            strict=True,
        )
