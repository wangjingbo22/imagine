from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from app.schemas.constraint import Constraint
from app.schemas.trip import AssistanceProfile, ContractModel
from app.schemas.validation_error import ValidationIssue, issues_from_pydantic


class CompileAssistanceConstraintsInput(ContractModel):
    """Structured input accepted by the Agent tool.

    Constraints are deliberately absent: an LLM may select this tool but may
    not author or rewrite the deterministic constraint set.
    """

    assistance_profile: AssistanceProfile


class CompileAssistanceConstraintsOutput(ContractModel):
    constraints: tuple[Constraint, ...]


@runtime_checkable
class AssistanceConstraintCompiler(Protocol):
    """T007-owned compiler boundary injected into the T008 adapter."""

    def compile(
        self,
        profile: AssistanceProfile,
    ) -> Sequence[Constraint]: ...


class ConstraintToolContractError(ValueError):
    """Fail-closed error raised before constraints may enter planning."""

    def __init__(
        self,
        *,
        code: str,
        issues: Sequence[ValidationIssue],
    ) -> None:
        self.code = code
        self.issues = tuple(issues)
        message = "; ".join(
            f"{issue.path or '<root>'}: {issue.message}" for issue in self.issues
        )
        super().__init__(message)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "errors": [
                issue.model_dump(exclude_none=True) for issue in self.issues
            ],
        }


class AssistanceConstraintAgentTool:
    """Thin Agent adapter around the injected deterministic T007 compiler."""

    name = "compile_assistance_constraints"
    description = (
        "Compile a confirmed AssistanceProfile into deterministic constraints. "
        "The returned scope, hardness and values must not be rewritten."
    )
    input_model = CompileAssistanceConstraintsInput
    output_model = CompileAssistanceConstraintsOutput

    def __init__(self, compiler: AssistanceConstraintCompiler) -> None:
        self._compiler = compiler

    def invoke(
        self,
        raw_input: CompileAssistanceConstraintsInput | Mapping[str, object],
    ) -> CompileAssistanceConstraintsOutput:
        request = self._validate_input(raw_input)
        try:
            compiled = tuple(self._compiler.compile(request.assistance_profile))
            return self._validate_output({"constraints": compiled})
        except ConstraintToolContractError as exc:
            raise ConstraintToolContractError(
                code="CONSTRAINT_COMPILER_OUTPUT_INVALID",
                issues=exc.issues,
            ) from exc

    def validate_for_planning(
        self,
        raw_input: CompileAssistanceConstraintsInput | Mapping[str, object],
        untrusted_output: (
            CompileAssistanceConstraintsOutput | Mapping[str, object]
        ),
    ) -> CompileAssistanceConstraintsOutput:
        """Recompile and reject any model-side rewrite or omission.

        Recompilation intentionally makes T007 determinism part of the
        boundary: only the exact canonical output receives a planning-capable
        return value.
        """

        request = self._validate_input(raw_input)
        candidate = self._validate_output(untrusted_output)
        expected = self.invoke(request)
        if candidate != expected:
            raise ConstraintToolContractError(
                code="CONSTRAINT_TOOL_OUTPUT_MISMATCH",
                issues=(
                    ValidationIssue(
                        path="constraints",
                        code="canonical_mismatch",
                        message=(
                            "Agent tool output differs from the deterministic "
                            "compiler result"
                        ),
                    ),
                ),
            )
        return candidate

    @staticmethod
    def _validate_input(
        raw_input: CompileAssistanceConstraintsInput | Mapping[str, object],
    ) -> CompileAssistanceConstraintsInput:
        try:
            return CompileAssistanceConstraintsInput.model_validate_json(
                _payload_as_json(raw_input),
                strict=True,
            )
        except (TypeError, ValueError) as exc:
            issues = (
                issues_from_pydantic(exc.errors())
                if isinstance(exc, ValidationError)
                else [
                    ValidationIssue(
                        path="",
                        code="invalid_json_value",
                        message=str(exc),
                    )
                ]
            )
            raise ConstraintToolContractError(
                code="CONSTRAINT_TOOL_INPUT_INVALID",
                issues=issues,
            ) from exc

    @staticmethod
    def _validate_output(
        raw_output: CompileAssistanceConstraintsOutput | Mapping[str, object],
    ) -> CompileAssistanceConstraintsOutput:
        try:
            return CompileAssistanceConstraintsOutput.model_validate_json(
                _payload_as_json(raw_output),
                strict=True,
            )
        except (TypeError, ValueError) as exc:
            issues = (
                issues_from_pydantic(exc.errors())
                if isinstance(exc, ValidationError)
                else [
                    ValidationIssue(
                        path="",
                        code="invalid_json_value",
                        message=str(exc),
                    )
                ]
            )
            raise ConstraintToolContractError(
                code="CONSTRAINT_TOOL_OUTPUT_INVALID",
                issues=issues,
            ) from exc


def _payload_as_json(value: ContractModel | Mapping[str, object]) -> str:
    """Force every boundary value through strict, finite JSON.

    ``model_validate(..., strict=True)`` intentionally rejects a Python list
    for a tuple field, although the same array is valid JSON for that field.
    Conversely, accepting an already-built Pydantic model without reparsing
    would trust nested instances that may have been mutated after creation.
    Both mappings and model instances therefore take the same JSON round trip.
    """

    def contract_default(item: object) -> object:
        if isinstance(item, ContractModel):
            return item.model_dump(mode="json", by_alias=True)
        raise TypeError(
            f"Object of type {type(item).__name__} is not JSON serializable"
        )

    serializable = (
        value.model_dump(mode="json", by_alias=True)
        if isinstance(value, ContractModel)
        else value
    )
    return json.dumps(
        serializable,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
        default=contract_default,
    )


@runtime_checkable
class AgentToolRegistry(Protocol):
    def register_tool(self, tool: AssistanceConstraintAgentTool) -> None: ...


def register_assistance_constraint_tool(
    registry: AgentToolRegistry,
    compiler: AssistanceConstraintCompiler,
) -> AssistanceConstraintAgentTool:
    """Register the adapter without taking a dependency on LangGraph itself."""

    tool = AssistanceConstraintAgentTool(compiler)
    registry.register_tool(tool)
    return tool


__all__ = [
    "AgentToolRegistry",
    "AssistanceConstraintAgentTool",
    "AssistanceConstraintCompiler",
    "CompileAssistanceConstraintsInput",
    "CompileAssistanceConstraintsOutput",
    "ConstraintToolContractError",
    "register_assistance_constraint_tool",
]
