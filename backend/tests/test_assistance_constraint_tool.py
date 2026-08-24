from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.agents.tools.assistance_constraints import (
    AssistanceConstraintAgentTool,
    CompileAssistanceConstraintsOutput,
    ConstraintToolContractError,
    register_assistance_constraint_tool,
)
from app.schemas.assistance import low_stamina_profile
from app.schemas.constraint import Constraint
from app.schemas.trip import AssistanceProfile


class FakeCompiler:
    def __init__(self) -> None:
        self.calls = 0

    def compile(
        self,
        profile: AssistanceProfile,
    ) -> Sequence[Constraint]:
        self.calls += 1
        return (
            Constraint(
                field="walkLimits.maxContinuousMeters",
                operator="LTE",
                value=profile.walk_limits.max_continuous_meters,
                scope="ROUTE_SEGMENT",
                hardness="HARD",
            ),
            Constraint(
                field="maxTransfers",
                operator="LTE",
                value=profile.max_transfers,
                scope="ROUTE",
                hardness="HARD",
            ),
        )


class FakeRegistry:
    def __init__(self) -> None:
        self.tools: list[AssistanceConstraintAgentTool] = []

    def register_tool(self, tool: AssistanceConstraintAgentTool) -> None:
        self.tools.append(tool)


def test_registers_framework_neutral_agent_tool():
    registry = FakeRegistry()
    compiler = FakeCompiler()

    tool = register_assistance_constraint_tool(registry, compiler)

    assert registry.tools == [tool]
    assert tool.name == "compile_assistance_constraints"
    assert tool.input_model.model_json_schema()["type"] == "object"


def test_tool_only_accepts_structured_profile_and_preserves_compiler_output():
    compiler = FakeCompiler()
    tool = AssistanceConstraintAgentTool(compiler)
    profile = low_stamina_profile()

    output = tool.invoke({"assistanceProfile": profile})

    assert compiler.calls == 1
    assert output.constraints[0].scope == "ROUTE_SEGMENT"
    assert output.constraints[0].hardness == "HARD"
    assert output.constraints[0].value == (
        profile.walk_limits.max_continuous_meters
    )
    assert output.constraints[1].field == "maxTransfers"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["constraints"][0].update(
            {"scope": "TRIP"}
        ),
        lambda payload: payload["constraints"][0].update(
            {"hardness": "SOFT"}
        ),
        lambda payload: payload["constraints"][0].update({"value": 9_999}),
        lambda payload: payload["constraints"].pop(),
    ],
    ids=["scope", "hardness", "value", "omission"],
)
def test_model_rewrite_is_rejected_before_planning(mutation):
    compiler = FakeCompiler()
    tool = AssistanceConstraintAgentTool(compiler)
    profile = low_stamina_profile()
    canonical = tool.invoke({"assistanceProfile": profile})
    payload = canonical.model_dump(mode="json", by_alias=True)
    mutation(payload)
    planner_calls: list[CompileAssistanceConstraintsOutput] = []

    with pytest.raises(ConstraintToolContractError) as exc_info:
        verified = tool.validate_for_planning(
            {"assistanceProfile": profile},
            payload,
        )
        planner_calls.append(verified)

    assert exc_info.value.code == "CONSTRAINT_TOOL_OUTPUT_MISMATCH"
    assert planner_calls == []


def test_structurally_incomplete_constraint_is_rejected_before_recompile():
    compiler = FakeCompiler()
    tool = AssistanceConstraintAgentTool(compiler)
    profile = low_stamina_profile()
    canonical = tool.invoke({"assistanceProfile": profile})
    payload = canonical.model_dump(mode="json", by_alias=True)
    del payload["constraints"][0]["scope"]
    calls_before_validation = compiler.calls

    with pytest.raises(ConstraintToolContractError) as exc_info:
        tool.validate_for_planning({"assistanceProfile": profile}, payload)

    assert exc_info.value.code == "CONSTRAINT_TOOL_OUTPUT_INVALID"
    assert compiler.calls == calls_before_validation


@pytest.mark.parametrize(
    "invalid_field",
    [
        {"maxTransfers": "1"},
        {"modelAuthoredConstraints": []},
    ],
    ids=["wrong-type", "extra-agent-field"],
)
def test_bad_agent_input_never_calls_compiler(invalid_field: dict[str, Any]):
    compiler = FakeCompiler()
    tool = AssistanceConstraintAgentTool(compiler)
    profile_payload = low_stamina_profile().model_dump(mode="json", by_alias=True)
    if "maxTransfers" in invalid_field:
        profile_payload.update(invalid_field)
        raw_input: dict[str, Any] = {"assistanceProfile": profile_payload}
    else:
        raw_input = {
            "assistanceProfile": profile_payload,
            **invalid_field,
        }

    with pytest.raises(ConstraintToolContractError) as exc_info:
        tool.invoke(raw_input)

    assert exc_info.value.code == "CONSTRAINT_TOOL_INPUT_INVALID"
    assert compiler.calls == 0


def test_exact_canonical_output_is_admitted_to_planning():
    compiler = FakeCompiler()
    tool = AssistanceConstraintAgentTool(compiler)
    profile = low_stamina_profile()
    canonical = tool.invoke({"assistanceProfile": profile})

    verified = tool.validate_for_planning(
        {"assistanceProfile": profile},
        canonical.model_dump(mode="json", by_alias=True),
    )

    assert verified == canonical
    assert compiler.calls == 2


def test_mutated_compiler_constraint_is_revalidated_and_rejected():
    compiler = FakeCompiler()
    profile = low_stamina_profile()
    mutated = compiler.compile(profile)[0]
    mutated.hardness = "BROKEN"  # type: ignore[assignment]

    class MutatedCompiler:
        def compile(self, _profile: AssistanceProfile) -> Sequence[Constraint]:
            return (mutated,)

    with pytest.raises(ConstraintToolContractError) as exc_info:
        AssistanceConstraintAgentTool(MutatedCompiler()).invoke(
            {"assistanceProfile": profile}
        )

    assert exc_info.value.code == "CONSTRAINT_COMPILER_OUTPUT_INVALID"


def test_mutated_output_model_is_revalidated_and_rejected():
    compiler = FakeCompiler()
    tool = AssistanceConstraintAgentTool(compiler)
    profile = low_stamina_profile()
    output = tool.invoke({"assistanceProfile": profile})
    output.constraints[0].scope = "BROKEN"

    with pytest.raises(ConstraintToolContractError) as exc_info:
        tool.validate_for_planning({"assistanceProfile": profile}, output)

    assert exc_info.value.code == "CONSTRAINT_TOOL_OUTPUT_MISMATCH"


def test_non_finite_json_number_is_rejected_at_tool_boundary():
    compiler = FakeCompiler()
    tool = AssistanceConstraintAgentTool(compiler)
    profile = low_stamina_profile()
    output = tool.invoke({"assistanceProfile": profile})
    payload = output.model_dump(mode="json", by_alias=True)
    payload["constraints"][0]["value"] = float("nan")

    with pytest.raises(ConstraintToolContractError) as exc_info:
        tool.validate_for_planning({"assistanceProfile": profile}, payload)

    assert exc_info.value.code == "CONSTRAINT_TOOL_OUTPUT_INVALID"
