# S1-T007 Assistance Constraint Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the deterministic S1-T007 `AssistanceProfile→Constraint` compiler, prove all four profiles and six care-rule categories, fail closed on invalid input, and preserve T003/T008/T009 contracts.

**Architecture:** Add one pure service package under `backend/app/services/assistance_constraints/`. The concrete compiler structurally implements T008's existing Protocol without importing the Agent layer, revalidates mutable Pydantic instances at its own boundary, and returns a freshly allocated canonical tuple. Existing T008 and T009 production files remain unchanged; integration tests prove compatibility.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, JSON snapshots. No HTTP, database, Provider, LLM, LangGraph runtime, clock, randomness, cache, frontend, or planner implementation.

## Global Constraints

- Work only on branch `czy-S1-T007`; `67206f2c55dcb011c61304de94f95b8b83a72ba0` must remain an ancestor.
- Preserve the unrelated untracked Excel lock file `doc/~$行知旅伴_V2.3_Sprint1待办列表_含负责人.xlsx`; never stage, delete, rename, or modify it.
- External JSON remains camelCase; Python attributes remain snake_case.
- T003 Profile fields remain required-nullable. Do not add `returnBy`, omit existing null fields, or update Trip Schema/fixtures/frontend mappings.
- T008 stays `compile(profile: AssistanceProfile) -> Sequence[Constraint]`; do not modify its Protocol, DTOs, adapter, registry, error codes, or recompile guard.
- T009 field names stay exactly `walkLimits.maxContinuousMeters`, `walkLimits.maxDailyMeters`, `maxTransfers`, `restInterval`, and `avoidStairs`.
- Canonical rule order is continuous walk, daily walk, transfers, rest, nap, return, stairs.
- Null numeric/window sources and `avoidStairs=false` omit the whole Constraint; compiled outputs never contain `value: null`.
- `ORDINARY` compiles to an empty tuple; current rules are all `HARD`.
- Parent-child return is a DAY-scoped `ARRIVE_BY` reference to `days[0].endLocationText` and `days[0].timeWindow.end`; do not invent a literal place or time.
- The compiler must have no I/O, network, LLM, system-time, random, cache, or global mutable-state dependency.
- Read and follow `docs/superpowers/specs/2026-08-24-s1-t007-assistance-constraint-compiler-design.md` before editing.

## Preflight

- [ ] **Step 1: Verify branch, baseline ancestry, and workspace state.**

Run:

```powershell
git branch --show-current
git merge-base 67206f2c55dcb011c61304de94f95b8b83a72ba0 HEAD
git status --short --untracked-files=all
```

Expected:

- branch is `czy-S1-T007`;
- merge-base is `67206f2c55dcb011c61304de94f95b8b83a72ba0`;
- the Excel lock file may be untracked;
- no unexplained production/test changes exist before implementation starts.

- [ ] **Step 2: Create an ignored project virtual environment with all test dependencies.**

Run:

```powershell
$bootstrapPython = 'C:\Users\lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $bootstrapPython -m venv .venv
}
$python = (Resolve-Path -LiteralPath '.venv\Scripts\python.exe').Path
& $python -m pip install -e '.[test]'
& $python --version
& $python -m pytest --version
& $python -c "import fastapi, httpx, pydantic, pydantic_settings, uvicorn; print('project-deps-ok')"
```

Expected: Python is at least 3.11, pytest is available, and the import check prints `project-deps-ok`. `.venv/` is already ignored by the repository and must not be staged. The system-default `C:\msys64\ucrt64\bin\python.exe` is not usable here because it has no pytest installation.

---

### Task 1: Build the compiler and field-level error boundary with TDD

**Files:**

- Create: `backend/tests/test_assistance_constraint_compiler.py`
- Create: `backend/app/services/assistance_constraints/compiler.py`
- Create: `backend/app/services/assistance_constraints/__init__.py`

**Interfaces:**

- Consumes: `AssistanceProfile`, `AssistanceType`, `Constraint`, `ValidationIssue`, `issues_from_pydantic`.
- Produces: `DeterministicAssistanceConstraintCompiler.compile(profile: AssistanceProfile) -> tuple[Constraint, ...]`.
- Produces: `AssistanceConstraintCompileError(*, issues, code="ASSISTANCE_PROFILE_INVALID")` with `as_dict() -> dict[str, object]`.
- Produces constants for canonical fields/operators/scopes, exported from the package.

- [ ] **Step 1: Write the failing compiler tests.**

Create `backend/tests/test_assistance_constraint_compiler.py` with:

```python
from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

import pytest

from app.schemas.assistance import (
    create_assistance_profile,
    low_stamina_profile,
    ordinary_profile,
    parent_child_profile,
)
from app.schemas.trip import AssistanceProfile, AssistanceType
from app.services.assistance_constraints import (
    AssistanceConstraintCompileError,
    DeterministicAssistanceConstraintCompiler,
)


EXPECTED = {
    AssistanceType.ORDINARY: [],
    AssistanceType.PARENT_CHILD: [
        {
            "field": "napWindow",
            "operator": "BLOCK",
            "value": {"start": "13:00:00", "end": "14:00:00"},
            "scope": "DAY",
            "hardness": "HARD",
        },
        {
            "field": "return",
            "operator": "ARRIVE_BY",
            "value": {
                "endLocationPath": "days[0].endLocationText",
                "deadlinePath": "days[0].timeWindow.end",
            },
            "scope": "DAY",
            "hardness": "HARD",
        },
    ],
    AssistanceType.LOW_STAMINA: [
        {
            "field": "walkLimits.maxContinuousMeters",
            "operator": "LTE",
            "value": 500,
            "scope": "ROUTE_SEGMENT",
            "hardness": "HARD",
        },
        {
            "field": "maxTransfers",
            "operator": "LTE",
            "value": 2,
            "scope": "ROUTE",
            "hardness": "HARD",
        },
        {
            "field": "restInterval",
            "operator": "LTE",
            "value": 90,
            "scope": "ROUTE",
            "hardness": "HARD",
        },
    ],
    AssistanceType.MOBILITY_ASSISTANCE_BETA: [
        {
            "field": "avoidStairs",
            "operator": "EQ",
            "value": True,
            "scope": "ROUTE_SEGMENT",
            "hardness": "HARD",
        }
    ],
}


def dumped(compiler, profile: AssistanceProfile) -> list[dict[str, Any]]:
    return [
        item.model_dump(mode="json", by_alias=True)
        for item in compiler.compile(profile)
    ]


@pytest.mark.parametrize("profile_type", list(AssistanceType))
def test_four_profiles_compile_to_exact_repeatable_constraints(profile_type):
    compiler = DeterministicAssistanceConstraintCompiler()
    profile = create_assistance_profile(profile_type)

    first = compiler.compile(profile)
    second = compiler.compile(profile)

    assert dumped(compiler, profile) == EXPECTED[profile_type]
    assert first == second
    assert json.dumps(
        [item.model_dump(mode="json", by_alias=True) for item in first],
        ensure_ascii=False,
        separators=(",", ":"),
    ) == json.dumps(
        [item.model_dump(mode="json", by_alias=True) for item in second],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert all(left is not right for left, right in zip(first, second))


def test_all_optional_rules_follow_one_canonical_order():
    compiler = DeterministicAssistanceConstraintCompiler()
    profile = parent_child_profile()
    profile.walk_limits.max_continuous_meters = 500
    profile.walk_limits.max_daily_meters = 2_000
    profile.max_transfers = 2
    profile.rest_interval = 90
    profile.avoid_stairs = True

    assert [item.field for item in compiler.compile(profile)] == [
        "walkLimits.maxContinuousMeters",
        "walkLimits.maxDailyMeters",
        "maxTransfers",
        "restInterval",
        "napWindow",
        "return",
        "avoidStairs",
    ]


def test_null_and_false_sources_emit_no_constraint_or_null_value():
    compiler = DeterministicAssistanceConstraintCompiler()

    assert compiler.compile(ordinary_profile()) == ()
    for profile_type in AssistanceType:
        payload = json.dumps(
            dumped(compiler, create_assistance_profile(profile_type)),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        assert "null" not in payload


@pytest.mark.parametrize(
    ("mutation", "expected_path", "expected_code"),
    [
        (
            lambda profile: setattr(profile, "max_transfers", "2"),
            "maxTransfers",
            "int_type",
        ),
        (
            lambda profile: setattr(
                profile.walk_limits,
                "max_continuous_meters",
                0,
            ),
            "walkLimits.maxContinuousMeters",
            "greater_than_equal",
        ),
    ],
    ids=["wrong-type", "out-of-range"],
)
def test_mutated_profile_fails_closed_with_field_issue(
    mutation: Callable[[AssistanceProfile], None],
    expected_path: str,
    expected_code: str,
):
    compiler = DeterministicAssistanceConstraintCompiler()
    profile = low_stamina_profile()
    mutation(profile)

    with pytest.raises(AssistanceConstraintCompileError) as exc_info:
        compiler.compile(profile)

    error = exc_info.value.as_dict()
    assert error["code"] == "ASSISTANCE_PROFILE_INVALID"
    assert error["errors"][0]["path"] == expected_path
    assert error["errors"][0]["code"] == expected_code
```

After pasting, remove the unused `Any` workaround only if the test file no longer uses it; in the content above it is used by `dumped()`.

- [ ] **Step 2: Run the focused test and observe RED.**

Run:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'backend')
& $python -m pytest -p no:cacheprovider backend/tests/test_assistance_constraint_compiler.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.services.assistance_constraints'`. This proves the tests are exercising the missing T007 implementation.

- [ ] **Step 3: Implement the minimal compiler and error contract.**

Create `backend/app/services/assistance_constraints/compiler.py` with:

```python
from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from app.schemas.constraint import Constraint
from app.schemas.trip import AssistanceProfile, AssistanceType
from app.schemas.validation_error import ValidationIssue, issues_from_pydantic


FIELD_WALK_CONTINUOUS: Final = "walkLimits.maxContinuousMeters"
FIELD_WALK_DAILY: Final = "walkLimits.maxDailyMeters"
FIELD_MAX_TRANSFERS: Final = "maxTransfers"
FIELD_REST_INTERVAL: Final = "restInterval"
FIELD_NAP_WINDOW: Final = "napWindow"
FIELD_RETURN: Final = "return"
FIELD_AVOID_STAIRS: Final = "avoidStairs"

OP_LTE: Final = "LTE"
OP_EQ: Final = "EQ"
OP_BLOCK: Final = "BLOCK"
OP_ARRIVE_BY: Final = "ARRIVE_BY"

SCOPE_ROUTE_SEGMENT: Final = "ROUTE_SEGMENT"
SCOPE_ROUTE: Final = "ROUTE"
SCOPE_DAY: Final = "DAY"
HARD: Final = "HARD"

RETURN_END_LOCATION_PATH: Final = "days[0].endLocationText"
RETURN_DEADLINE_PATH: Final = "days[0].timeWindow.end"


class AssistanceConstraintCompileError(ValueError):
    """Field-addressable failure that cannot yield planning constraints."""

    def __init__(
        self,
        *,
        issues: Sequence[ValidationIssue],
        code: str = "ASSISTANCE_PROFILE_INVALID",
    ) -> None:
        self.code = code
        self.issues = tuple(issues)
        message = "; ".join(
            f"{issue.path or '<root>'}: {issue.message}"
            for issue in self.issues
        )
        super().__init__(message)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "errors": [
                issue.model_dump(exclude_none=True) for issue in self.issues
            ],
        }


def _validated_profile(profile: AssistanceProfile) -> AssistanceProfile:
    if not isinstance(profile, AssistanceProfile):
        raise AssistanceConstraintCompileError(
            issues=(
                ValidationIssue(
                    path="",
                    code="model_type",
                    message="Input must be an AssistanceProfile",
                ),
            )
        )

    try:
        raw = profile.model_dump_json(by_alias=True, warnings="none")
        return AssistanceProfile.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        raise AssistanceConstraintCompileError(
            issues=issues_from_pydantic(exc.errors())
        ) from exc
    except (PydanticSerializationError, TypeError, ValueError) as exc:
        raise AssistanceConstraintCompileError(
            issues=(
                ValidationIssue(
                    path="",
                    code="invalid_json_value",
                    message=str(exc),
                ),
            )
        ) from exc


class DeterministicAssistanceConstraintCompiler:
    """Compile a confirmed profile without I/O, inference, or mutation."""

    def compile(
        self,
        profile: AssistanceProfile,
    ) -> tuple[Constraint, ...]:
        valid = _validated_profile(profile)
        constraints: list[Constraint] = []

        if valid.walk_limits.max_continuous_meters is not None:
            constraints.append(
                Constraint(
                    field=FIELD_WALK_CONTINUOUS,
                    operator=OP_LTE,
                    value=valid.walk_limits.max_continuous_meters,
                    scope=SCOPE_ROUTE_SEGMENT,
                    hardness=HARD,
                )
            )
        if valid.walk_limits.max_daily_meters is not None:
            constraints.append(
                Constraint(
                    field=FIELD_WALK_DAILY,
                    operator=OP_LTE,
                    value=valid.walk_limits.max_daily_meters,
                    scope=SCOPE_DAY,
                    hardness=HARD,
                )
            )
        if valid.max_transfers is not None:
            constraints.append(
                Constraint(
                    field=FIELD_MAX_TRANSFERS,
                    operator=OP_LTE,
                    value=valid.max_transfers,
                    scope=SCOPE_ROUTE,
                    hardness=HARD,
                )
            )
        if valid.rest_interval is not None:
            constraints.append(
                Constraint(
                    field=FIELD_REST_INTERVAL,
                    operator=OP_LTE,
                    value=valid.rest_interval,
                    scope=SCOPE_ROUTE,
                    hardness=HARD,
                )
            )
        if valid.nap_window is not None:
            constraints.append(
                Constraint(
                    field=FIELD_NAP_WINDOW,
                    operator=OP_BLOCK,
                    value=valid.nap_window.model_dump(
                        mode="json",
                        by_alias=True,
                    ),
                    scope=SCOPE_DAY,
                    hardness=HARD,
                )
            )
        if valid.type is AssistanceType.PARENT_CHILD:
            constraints.append(
                Constraint(
                    field=FIELD_RETURN,
                    operator=OP_ARRIVE_BY,
                    value={
                        "endLocationPath": RETURN_END_LOCATION_PATH,
                        "deadlinePath": RETURN_DEADLINE_PATH,
                    },
                    scope=SCOPE_DAY,
                    hardness=HARD,
                )
            )
        if valid.avoid_stairs:
            constraints.append(
                Constraint(
                    field=FIELD_AVOID_STAIRS,
                    operator=OP_EQ,
                    value=True,
                    scope=SCOPE_ROUTE_SEGMENT,
                    hardness=HARD,
                )
            )

        return tuple(constraints)


__all__ = [
    "AssistanceConstraintCompileError",
    "DeterministicAssistanceConstraintCompiler",
    "FIELD_AVOID_STAIRS",
    "FIELD_MAX_TRANSFERS",
    "FIELD_NAP_WINDOW",
    "FIELD_REST_INTERVAL",
    "FIELD_RETURN",
    "FIELD_WALK_CONTINUOUS",
    "FIELD_WALK_DAILY",
    "RETURN_DEADLINE_PATH",
    "RETURN_END_LOCATION_PATH",
]
```

Create `backend/app/services/assistance_constraints/__init__.py` with:

```python
from .compiler import (
    AssistanceConstraintCompileError,
    DeterministicAssistanceConstraintCompiler,
    FIELD_AVOID_STAIRS,
    FIELD_MAX_TRANSFERS,
    FIELD_NAP_WINDOW,
    FIELD_REST_INTERVAL,
    FIELD_RETURN,
    FIELD_WALK_CONTINUOUS,
    FIELD_WALK_DAILY,
    RETURN_DEADLINE_PATH,
    RETURN_END_LOCATION_PATH,
)

__all__ = [
    "AssistanceConstraintCompileError",
    "DeterministicAssistanceConstraintCompiler",
    "FIELD_AVOID_STAIRS",
    "FIELD_MAX_TRANSFERS",
    "FIELD_NAP_WINDOW",
    "FIELD_REST_INTERVAL",
    "FIELD_RETURN",
    "FIELD_WALK_CONTINUOUS",
    "FIELD_WALK_DAILY",
    "RETURN_DEADLINE_PATH",
    "RETURN_END_LOCATION_PATH",
]
```

- [ ] **Step 4: Run the focused test and observe GREEN.**

Run:

```powershell
& $python -m pytest -p no:cacheprovider backend/tests/test_assistance_constraint_compiler.py -q
```

Expected: `8 passed`. The four parameterized profile cases, canonical-order case, null/false case, and two invalid-mutation cases all pass.

- [ ] **Step 5: Review scope and commit the vertical slice.**

Run:

```powershell
git diff --check
git diff --name-only
git add -- backend/app/services/assistance_constraints backend/tests/test_assistance_constraint_compiler.py
git commit -m "feat: compile deterministic assistance constraints"
```

Expected: only the new compiler package and focused test are committed; the Excel lock file is not staged.

---

### Task 2: Lock four-profile canonical JSON snapshots

**Files:**

- Modify: `backend/tests/test_assistance_constraint_compiler.py`
- Create: `backend/tests/snapshots/assistance_constraints.json`

**Interfaces:**

- Consumes: the compiler from Task 1 and T003 profile factories.
- Produces: one reviewed JSON snapshot keyed by the four public `AssistanceType` values.

- [ ] **Step 1: Add a snapshot test before creating the snapshot.**

Append to `backend/tests/test_assistance_constraint_compiler.py`:

```python
from pathlib import Path


SNAPSHOT_PATH = (
    Path(__file__).parent / "snapshots" / "assistance_constraints.json"
)


@pytest.mark.parametrize("profile_type", list(AssistanceType))
def test_profile_output_matches_reviewed_snapshot(profile_type):
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    compiler = DeterministicAssistanceConstraintCompiler()

    assert dumped(
        compiler,
        create_assistance_profile(profile_type),
    ) == expected[profile_type.value]
```

Move the `from pathlib import Path` import to the top import block when applying this change; do not leave a mid-file import.

- [ ] **Step 2: Run the snapshot test and observe RED.**

Run:

```powershell
& $python -m pytest -p no:cacheprovider backend/tests/test_assistance_constraint_compiler.py::test_profile_output_matches_reviewed_snapshot -q
```

Expected: four failures with `FileNotFoundError` for `backend/tests/snapshots/assistance_constraints.json`.

- [ ] **Step 3: Add the reviewed canonical snapshot.**

Create `backend/tests/snapshots/assistance_constraints.json` with:

```json
{
  "ORDINARY": [],
  "PARENT_CHILD": [
    {
      "field": "napWindow",
      "operator": "BLOCK",
      "value": {
        "start": "13:00:00",
        "end": "14:00:00"
      },
      "scope": "DAY",
      "hardness": "HARD"
    },
    {
      "field": "return",
      "operator": "ARRIVE_BY",
      "value": {
        "endLocationPath": "days[0].endLocationText",
        "deadlinePath": "days[0].timeWindow.end"
      },
      "scope": "DAY",
      "hardness": "HARD"
    }
  ],
  "LOW_STAMINA": [
    {
      "field": "walkLimits.maxContinuousMeters",
      "operator": "LTE",
      "value": 500,
      "scope": "ROUTE_SEGMENT",
      "hardness": "HARD"
    },
    {
      "field": "maxTransfers",
      "operator": "LTE",
      "value": 2,
      "scope": "ROUTE",
      "hardness": "HARD"
    },
    {
      "field": "restInterval",
      "operator": "LTE",
      "value": 90,
      "scope": "ROUTE",
      "hardness": "HARD"
    }
  ],
  "MOBILITY_ASSISTANCE_BETA": [
    {
      "field": "avoidStairs",
      "operator": "EQ",
      "value": true,
      "scope": "ROUTE_SEGMENT",
      "hardness": "HARD"
    }
  ]
}
```

- [ ] **Step 4: Run snapshot and focused tests and observe GREEN.**

Run:

```powershell
& $python -m pytest -p no:cacheprovider backend/tests/test_assistance_constraint_compiler.py -q
```

Expected: `12 passed`.

- [ ] **Step 5: Parse, inspect, and commit the snapshot evidence.**

Run:

```powershell
& $python -c "import json, pathlib; p=pathlib.Path('backend/tests/snapshots/assistance_constraints.json'); data=json.loads(p.read_text(encoding='utf-8')); assert list(data) == ['ORDINARY','PARENT_CHILD','LOW_STAMINA','MOBILITY_ASSISTANCE_BETA']; print({k: len(v) for k, v in data.items()})"
git diff --check
git add -- backend/tests/test_assistance_constraint_compiler.py backend/tests/snapshots/assistance_constraints.json
git commit -m "test: lock assistance constraint snapshots"
```

Expected parse output: `{'ORDINARY': 0, 'PARENT_CHILD': 2, 'LOW_STAMINA': 3, 'MOBILITY_ASSISTANCE_BETA': 1}`.

---

### Task 3: Prove T008 injection and T009 consumption compatibility

**Files:**

- Create: `backend/tests/test_assistance_constraint_integration.py`
- Do not modify: `backend/app/agents/tools/assistance_constraints.py`
- Do not modify: `backend/app/services/route_risk/evaluator.py`

**Interfaces:**

- Consumes: T008 `AssistanceConstraintCompiler`, `AssistanceConstraintAgentTool`, and `ConstraintToolContractError`.
- Consumes: T009 `RouteRiskInput`, `RouteSegmentRiskFacts`, `WalkType`, and `evaluate_route_risk`.
- Proves: the real compiler is structurally accepted, canonical output survives the Agent boundary, tampering still fails, route fields remain consumable, and DAY rules remain outside T009.

- [ ] **Step 1: Add the complete integration regression file.**

Create `backend/tests/test_assistance_constraint_integration.py` with:

```python
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
```

- [ ] **Step 2: Run the new integration file.**

Run:

```powershell
& $python -m pytest -p no:cacheprovider backend/tests/test_assistance_constraint_integration.py -q
```

Expected: `9 passed`. These are compatibility/characterization tests and should pass without changing T008 or T009 production code. If any fail, fix only the new compiler or test assumptions after re-reading the frozen contract; do not weaken T008/T009 guards.

- [ ] **Step 3: Run the existing T003/T008/T009 regression set.**

Run:

```powershell
& $python -m pytest -p no:cacheprovider backend/tests/test_assistance_profile_schema.py backend/tests/test_assistance_constraint_tool.py backend/tests/test_route_risk.py -q
```

Expected at the audited baseline: `38 passed`. A count change caused by concurrent branch updates is acceptable only if all collected tests pass and the diff is understood.

- [ ] **Step 4: Prove frozen production contracts were not edited.**

Run:

```powershell
git diff --exit-code 67206f2c55dcb011c61304de94f95b8b83a72ba0 -- backend/app/schemas/trip.py backend/app/schemas/assistance.py backend/app/schemas/constraint.py backend/app/agents/tools/assistance_constraints.py backend/app/services/route_risk/evaluator.py
```

Expected: no output and exit code 0.

- [ ] **Step 5: Commit integration evidence.**

Run:

```powershell
git add -- backend/tests/test_assistance_constraint_integration.py
git commit -m "test: prove assistance compiler integrations"
```

Expected: one test-only commit; no frozen production contract is staged.

---

### Task 4: Add owner-specific S1-T007 traceability with a RED/GREEN check

**Files:**

- Create: `backend/tests/test_s1_t007_traceability.py`
- Create: `docs/traceability/sprint1/chen_ziyuan_s1_t007.json`
- Create: `docs/traceability/sprint1/chen_ziyuan_s1_t007.md`
- Do not modify: `docs/traceability/sprint1/lin_canhan_day1.json`
- Do not modify: `backend/tests/test_day1_traceability.py`

**Interfaces:**

- Consumes: files created in Tasks 1–3 and frozen T003/T008/T009 contract paths.
- Produces: machine-readable and human-readable evidence for `S1-T007 / PBI-03-A / AC-03-A`.

- [ ] **Step 1: Write the traceability test first.**

Create `backend/tests/test_s1_t007_traceability.py` with:

```python
from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACE_JSON = (
    REPO_ROOT
    / "docs"
    / "traceability"
    / "sprint1"
    / "chen_ziyuan_s1_t007.json"
)
TRACE_MD = TRACE_JSON.with_suffix(".md")


def test_s1_t007_traceability_identifies_contract_and_real_files():
    trace = json.loads(TRACE_JSON.read_text(encoding="utf-8"))

    assert trace["taskId"] == "S1-T007"
    assert trace["pbiId"] == "PBI-03-A"
    assert trace["acId"] == "AC-03-A"
    assert trace["owner"] == "陈梓元"
    assert trace["baseline"] == (
        "67206f2c55dcb011c61304de94f95b8b83a72ba0"
    )
    assert trace["dependsOn"] == ["S1-T003"]
    assert trace["consumedBy"] == ["S1-T008", "S1-T009", "S1-T011"]

    for group in (
        "codeFiles",
        "contractFiles",
        "testFiles",
        "snapshots",
    ):
        assert trace[group]
        for relative_path in trace[group]:
            assert (REPO_ROOT / relative_path).is_file(), relative_path


def test_s1_t007_traceability_lists_acceptance_proofs_and_handoff():
    trace = json.loads(TRACE_JSON.read_text(encoding="utf-8"))

    assert TRACE_MD.is_file()
    assert trace["proves"] == [
        "four-profile-canonical-snapshot",
        "repeatable-order-and-json-bytes",
        "null-source-constraint-omission",
        "walking-transfer-rest-nap-return-stairs-covered",
        "field-level-invalid-profile-fails-closed",
        "t008-protocol-and-rewrite-guard-compatible",
        "t009-route-fields-and-day-scope-compatible",
    ]
    assert trace["nonGoals"] == [
        "profile-schema-change",
        "agent-adapter-change",
        "route-risk-algorithm-change",
        "planner-or-return-reference-resolution",
    ]
```

- [ ] **Step 2: Run the traceability test and observe RED.**

Run:

```powershell
& $python -m pytest -p no:cacheprovider backend/tests/test_s1_t007_traceability.py -q
```

Expected: two failures because `chen_ziyuan_s1_t007.json` does not exist.

- [ ] **Step 3: Create the machine-readable trace.**

Create `docs/traceability/sprint1/chen_ziyuan_s1_t007.json` with:

```json
{
  "schemaVersion": "1.0",
  "taskId": "S1-T007",
  "pbiId": "PBI-03-A",
  "acId": "AC-03-A",
  "owner": "陈梓元",
  "status": "IMPLEMENTED",
  "baseline": "67206f2c55dcb011c61304de94f95b8b83a72ba0",
  "dependsOn": ["S1-T003"],
  "consumedBy": ["S1-T008", "S1-T009", "S1-T011"],
  "codeFiles": [
    "backend/app/services/assistance_constraints/__init__.py",
    "backend/app/services/assistance_constraints/compiler.py"
  ],
  "contractFiles": [
    "backend/app/schemas/trip.py",
    "backend/app/schemas/assistance.py",
    "backend/app/schemas/constraint.py",
    "backend/app/agents/tools/assistance_constraints.py",
    "backend/app/services/route_risk/evaluator.py"
  ],
  "testFiles": [
    "backend/tests/test_assistance_constraint_compiler.py",
    "backend/tests/test_assistance_constraint_integration.py",
    "backend/tests/test_s1_t007_traceability.py"
  ],
  "snapshots": [
    "backend/tests/snapshots/assistance_constraints.json"
  ],
  "proves": [
    "four-profile-canonical-snapshot",
    "repeatable-order-and-json-bytes",
    "null-source-constraint-omission",
    "walking-transfer-rest-nap-return-stairs-covered",
    "field-level-invalid-profile-fails-closed",
    "t008-protocol-and-rewrite-guard-compatible",
    "t009-route-fields-and-day-scope-compatible"
  ],
  "nonGoals": [
    "profile-schema-change",
    "agent-adapter-change",
    "route-risk-algorithm-change",
    "planner-or-return-reference-resolution"
  ]
}
```

- [ ] **Step 4: Create the human-readable handoff trace.**

Create `docs/traceability/sprint1/chen_ziyuan_s1_t007.md` with:

```markdown
# 陈梓元 S1-T007 关怀约束编译追溯

## 任务

`S1-T007 / PBI-03-A / AC-03-A` 在基线
`67206f2c55dcb011c61304de94f95b8b83a72ba0` 上实现确定性的
`AssistanceProfile→Constraint` 编译器。上游是 T003；T008、T009 和
T011 消费本任务结果。

## 固定规则

Canonical 顺序为连续步行、全天步行、换乘、休息、午休、返程、
避阶梯。Null 来源和 `avoidStairs=false` 不产生规则；四个正式 Profile
输出数量依次为 0、2、3、1。当前规则均为 HARD。

亲子午休表示为 `napWindow/BLOCK/DAY`。返程表示为
`return/ARRIVE_BY/DAY`，value 引用 `days[0].endLocationText` 与
`days[0].timeWindow.end`，不猜测地点或时间。

## 兼容边界

T003 Profile Schema、T008 Protocol/Agent adapter 和 T009 路线风险器
均未修改。真实编译器通过 T008 注入与防篡改测试；T009 直接消费五个
冻结路线字段，并忽略 DAY-scoped 午休/返程规则。返程引用的解析和
候选计划总校验属于 T011。

## 自动化证据

- `test_assistance_constraint_compiler.py`：四 Profile 快照、重复编译、
  Null 省略、固定顺序和字段级非法输入。
- `test_assistance_constraint_integration.py`：T008/T009 真实集成与篡改
  拒绝。
- `snapshots/assistance_constraints.json`：四 Profile canonical JSON。
- `test_s1_t007_traceability.py`：任务、依赖、消费者及证据文件完整性。
```

- [ ] **Step 5: Run traceability and existing owner-ledger tests and observe GREEN.**

Run:

```powershell
& $python -m pytest -p no:cacheprovider backend/tests/test_s1_t007_traceability.py backend/tests/test_day1_traceability.py -q
```

Expected: `4 passed`. The new owner-specific trace passes without changing 林粲涵's three-task Day 1 ledger.

- [ ] **Step 6: Commit traceability.**

Run:

```powershell
git add -- backend/tests/test_s1_t007_traceability.py docs/traceability/sprint1/chen_ziyuan_s1_t007.json docs/traceability/sprint1/chen_ziyuan_s1_t007.md
git commit -m "docs: trace S1-T007 acceptance evidence"
```

Expected: only the new trace test and two trace documents are committed.

---

### Task 5: Final verification and completion gate

**Files:**

- Verify all files from Tasks 1–4.
- Do not create or edit production/test files during this task unless a verification failure identifies a concrete defect; if it does, return to the responsible TDD task and repeat its RED/GREEN cycle.

**Interfaces:**

- Proves the complete compiler, snapshot, T008/T009 compatibility, traceability, scope boundary, and clean Git handoff.

- [ ] **Step 1: Run the complete S1 care regression set.**

Run:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'backend')
& $python -m pytest -p no:cacheprovider backend/tests/test_assistance_profile_schema.py backend/tests/test_assistance_constraint_compiler.py backend/tests/test_assistance_constraint_integration.py backend/tests/test_assistance_constraint_tool.py backend/tests/test_route_risk.py backend/tests/test_s1_t007_traceability.py backend/tests/test_day1_traceability.py -q
```

Expected at plan time: `63 passed`. If the repository gains tests concurrently, all collected tests must pass and the new total must be reported.

- [ ] **Step 2: Run the complete repository test suite.**

Run:

```powershell
& $python -m pytest -p no:cacheprovider -q
```

Expected at plan time: `101 passed` (audited baseline 78 plus 23 new cases), zero failures. A different count is acceptable only when collection output explains concurrent additions/removals; never accept deselection or skipped T007 tests as completion.

- [ ] **Step 3: Verify JSON, whitespace, and forbidden dependencies.**

Run:

```powershell
& $python -c "import json, pathlib; files=['backend/tests/snapshots/assistance_constraints.json','docs/traceability/sprint1/chen_ziyuan_s1_t007.json']; [json.loads(pathlib.Path(p).read_text(encoding='utf-8')) for p in files]; print('json-ok')"
git diff --check 67206f2c55dcb011c61304de94f95b8b83a72ba0..HEAD
rg -n "requests|httpx|openai|langgraph|datetime\.now|date\.today|random|uuid|sleep|cache" backend/app/services/assistance_constraints
```

Expected: `json-ok`; `git diff --check` has no output; the dependency scan has no output.

- [ ] **Step 4: Verify frozen contract files are byte-unchanged from the baseline.**

Run:

```powershell
git diff --exit-code 67206f2c55dcb011c61304de94f95b8b83a72ba0 -- backend/app/schemas/trip.py backend/app/schemas/assistance.py backend/app/schemas/constraint.py backend/app/agents/tools/assistance_constraints.py backend/app/services/route_risk/evaluator.py
```

Expected: no output and exit code 0.

- [ ] **Step 5: Verify exactly the intended implementation scope.**

Run:

```powershell
git diff --name-only 67206f2c55dcb011c61304de94f95b8b83a72ba0..HEAD
git status --short --untracked-files=all
```

Expected implementation paths in addition to the two analysis documents already on the branch:

```text
backend/app/services/assistance_constraints/__init__.py
backend/app/services/assistance_constraints/compiler.py
backend/tests/snapshots/assistance_constraints.json
backend/tests/test_assistance_constraint_compiler.py
backend/tests/test_assistance_constraint_integration.py
backend/tests/test_s1_t007_traceability.py
docs/traceability/sprint1/chen_ziyuan_s1_t007.json
docs/traceability/sprint1/chen_ziyuan_s1_t007.md
```

The only permitted unrelated status entry is the pre-existing untracked Excel lock file. No production/test change may remain unstaged or uncommitted.

- [ ] **Step 6: Record completion evidence without changing external systems.**

Report:

- final commit hashes from Tasks 1–4;
- exact focused and full pytest counts;
- snapshot profile counts `0/2/3/1`;
- confirmation that frozen T003/T008/T009 files have no diff;
- remaining untracked Excel lock file;
- the return-reference handoff to T011.

Do not push, open a PR, or claim CI/QA/PO approval unless the code-writing window was separately authorized for those external actions.

## Test Matrix Summary

| Requirement | Primary test | Expected proof |
| --- | --- | --- |
| Four public Profile classes | `test_four_profiles_compile_to_exact_repeatable_constraints` | exact 0/2/3/1 outputs |
| Determinism | same test + compact JSON comparison | equal values, order, bytes, fresh instances |
| Walking | low-stamina + all-optional tests | fixed T009 field, LTE, scope, hard value |
| Transfers | low-stamina test | `maxTransfers/LTE/ROUTE/HARD` |
| Rest | low-stamina test | `restInterval/LTE/ROUTE/HARD` |
| Nap | parent-child test | atomic `napWindow/BLOCK/DAY/HARD` |
| Return | parent-child test | atomic `return/ARRIVE_BY/DAY/HARD` with two Trip paths |
| Avoid stairs | mobility test | only `avoidStairs/EQ true/ROUTE_SEGMENT/HARD` |
| Null omission | `test_null_and_false_sources_emit_no_constraint_or_null_value` | no null-valued output or ordinary false-positive |
| Rule order | `test_all_optional_rules_follow_one_canonical_order` | all seven positions fixed |
| Invalid field | mutated Profile + invalid Agent mapping | field-level issue and no planning value |
| T008 compatibility | integration Protocol/adapter/reorder tests | injection works; rewrite rejected |
| T009 compatibility | real risky route + parent DAY isolation | four route failures; DAY rules ignored |
| Traceability | `test_s1_t007_traceability.py` | task/AC/dependencies/files/proofs complete |

## Explicit Non-Goals

- No `AssistanceProfile` or Trip Schema version change.
- No explicit user-configurable `returnBy` field in this task.
- No frontend types, UI, API routes, status transitions, or persistence.
- No T008 Protocol/adapter/registry behavior change.
- No T009 evaluator/field alias/risk-status behavior change.
- No T006 Provider or RouteSnapshot adapter.
- No T011 candidate planner, DAY rule evaluation, or return-reference resolution.
- No soft preference inference, demographic thresholds, or facility guarantees.
- No multi-participant merge/conflict rules, Sprint 2 event conversion, or Plan V2.
- No network, database, cache, LLM, clock, randomness, or global singleton.

## Definition of Done

Implementation is complete only when all Task 5 gates pass, the expected snapshot and trace files are committed, frozen contract files have no diff from `67206f2`, and the only unrelated workspace entry remains the untouched Excel lock file. A partial compiler, a passing focused test with failing full suite, an unreviewed snapshot change, or a planner that has not yet resolved the DAY return reference must not be described as full end-to-end planning completion.
