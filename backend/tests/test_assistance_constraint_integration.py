from __future__ import annotations

import pytest

from app.agents.tools.assistance_constraints import (
    AssistanceConstraintAgentTool,
    AssistanceConstraintCompiler,
    ConstraintToolContractError,
)
from app.schemas.assistance import create_assistance_profile
from app.schemas.trip import AssistanceType
from app.services.assistance_constraints import (
    DeterministicAssistanceConstraintCompiler,
)
from app.services.route_risk import (
    RouteRiskInput,
    RouteSegmentRiskFacts,
    ValidationStatus,
    WalkType,
    evaluate_route_risk,
)


def risky_route() -> RouteRiskInput:
    return RouteRiskInput(
        segments=(
            RouteSegmentRiskFacts(
                route_segment="seg-all-risks",
                walking_distance_meters=501,
                cumulative_transfers=3,
                elapsed_since_rest_minutes=91,
                walk_types=(WalkType.STAIRS,),
            ),
        )
    )


def test_real_compiler_satisfies_t008_runtime_protocol():
    compiler = DeterministicAssistanceConstraintCompiler()

    assert isinstance(compiler, AssistanceConstraintCompiler)


@pytest.mark.parametrize("profile_type", list(AssistanceType))
def test_t008_agent_preserves_real_compiler_output(profile_type):
    compiler = DeterministicAssistanceConstraintCompiler()
    tool = AssistanceConstraintAgentTool(compiler)
    profile = create_assistance_profile(profile_type)

    output = tool.invoke({"assistanceProfile": profile})

    assert output.constraints == compiler.compile(profile)


def test_invalid_agent_profile_stops_before_a_planning_value_exists():
    compiler = DeterministicAssistanceConstraintCompiler()
    tool = AssistanceConstraintAgentTool(compiler)
    payload = create_assistance_profile(
        AssistanceType.LOW_STAMINA
    ).model_dump(mode="json", by_alias=True)
    payload["maxTransfers"] = "2"
    planner_inputs = []

    with pytest.raises(ConstraintToolContractError) as exc_info:
        output = tool.invoke({"assistanceProfile": payload})
        planner_inputs.append(output)

    assert exc_info.value.code == "CONSTRAINT_TOOL_INPUT_INVALID"
    assert planner_inputs == []
    assert exc_info.value.as_dict()["errors"][0]["path"] == (
        "assistanceProfile.maxTransfers"
    )


def test_t008_rejects_reordered_parent_rules():
    compiler = DeterministicAssistanceConstraintCompiler()
    tool = AssistanceConstraintAgentTool(compiler)
    profile = create_assistance_profile(AssistanceType.PARENT_CHILD)
    payload = tool.invoke(
        {"assistanceProfile": profile}
    ).model_dump(mode="json", by_alias=True)
    payload["constraints"].reverse()

    with pytest.raises(ConstraintToolContractError) as exc_info:
        tool.validate_for_planning(
            {"assistanceProfile": profile},
            payload,
        )

    assert exc_info.value.code == "CONSTRAINT_TOOL_OUTPUT_MISMATCH"


def test_t009_consumes_real_route_constraints_without_field_translation():
    compiler = DeterministicAssistanceConstraintCompiler()
    constraints = (
        *compiler.compile(
            create_assistance_profile(AssistanceType.LOW_STAMINA)
        ),
        *compiler.compile(
            create_assistance_profile(
                AssistanceType.MOBILITY_ASSISTANCE_BETA
            )
        ),
    )

    report = evaluate_route_risk(risky_route(), constraints)

    assert report.status is ValidationStatus.FAIL
    assert [result.rule_id for result in report.results] == [
        "CARE.ROUTE.STAIRS_FORBIDDEN",
        "CARE.ROUTE.WALK_SEGMENT_LIMIT",
        "CARE.ROUTE.TRANSFER_LIMIT",
        "CARE.ROUTE.REST_INTERVAL",
    ]
    assert {result.route_segment for result in report.results} == {
        "seg-all-risks"
    }


def test_t009_ignores_parent_day_rules_instead_of_failing_closed():
    compiler = DeterministicAssistanceConstraintCompiler()
    constraints = compiler.compile(
        create_assistance_profile(AssistanceType.PARENT_CHILD)
    )

    report = evaluate_route_risk(risky_route(), constraints)

    assert report.status is ValidationStatus.PASS
    assert report.results == ()
