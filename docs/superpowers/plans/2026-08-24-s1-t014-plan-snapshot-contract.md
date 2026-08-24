# S1-T014 Plan Snapshot Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Plan V1/V2 registration from bypassing the Sprint 1 single-person, single-day Trip contract while preserving all valid T014 state flows.

**Architecture:** Introduce a lifecycle-specific `PlanReviewTripSnapshot` schema that reuses the T001 cross-field policy, make `ProposedPlanVersion` depend on it, and map its custom policy paths through the existing HTTP validation envelope. Repository transitions and persistence remain unchanged.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, SQLite, pytest, httpx ASGI transport, TypeScript/Vite regression build.

## Global Constraints

- Work only on isolated branch `czy-S1-T014`; do not modify or merge `main`.
- Sprint 1 Plan snapshots are exactly one participant and exactly one Trip day.
- Reuse `validate_single_day_policy`; do not duplicate its date, day-index,
  time-window, budget, or preference rules.
- Reject invalid payloads before any service/repository write with HTTP 422,
  `code = TRIP_SCHEMA_INVALID`, and an exact field-addressable error path.
- A rejected V1 must create no Trip state. A rejected V2 must preserve the
  CURRENT V1, `EXECUTING` state, and an empty proposed-candidate list.
- Preserve valid V1/V2 behavior and do not change the Plan state-transition
  matrix, SQLite schema, or transaction logic.
- Do not implement T011, T015–T018, T021–T024, or server-side recomputation of
  caller-declared constraint PASS values.
- Use test-driven development: observe the targeted tests fail before changing
  production code, then make the smallest implementation that passes.
- Record automated evidence and obtain an independent code review before push.

---

## Task 1: Lock the Defect with HTTP Contract Tests

**Files:**
- Modify: `tests/test_plan_versions.py`

- [ ] Add a small async helper that posts a proposal and restores the Trip state.
- [ ] Add parameterized invalid V1 cases for participant count, Trip-day count,
  end-date mismatch, day-date mismatch, nonzero day index, reversed/equal time
  window, and daily budget above total budget.
- [ ] Assert HTTP 422, `TRIP_SCHEMA_INVALID`, exact error path/code, and a
  subsequent `TRIP_NOT_FOUND` response for every case.
- [ ] Add an invalid V2 regression: establish a valid V1 as CURRENT/EXECUTING,
  submit a multi-participant V2, then assert CURRENT V1 and state are unchanged.
- [ ] Run only the new tests and capture a RED result caused by the current wide
  `Trip` contract accepting or imprecisely reporting the payloads.

**Verification:**

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_plan_versions.py -k 'single_day_snapshot or invalid_v2_snapshot'
```

## Task 2: Enforce the Plan-review Snapshot Contract

**Files:**
- Modify: `backend/app/schemas/trip.py`
- Modify: `backend/app/schemas/plan.py`
- Modify: `backend/app/schemas/validation_error.py`
- Modify: `backend/app/schemas/__init__.py`

- [ ] Generalize only the type annotation of `validate_single_day_policy` from
  `CreateSingleDayTrip` to `Trip`; preserve its behavior and issue ordering.
- [ ] Add `PlanReviewTripSnapshot(Trip)` with literal `SINGLE` mode,
  literal `PLAN_REVIEW` status, and one-item participant/day bounds.
- [ ] Run the shared policy in an after-model validator. Raise the first issue as
  `PydanticCustomError(issue.code, issue.message, {"public_path": ...})`,
  prefixing the T001 path with `tripSnapshot.`.
- [ ] Change `ProposedPlanVersion.trip_snapshot` to the new subtype and remove
  redundant generic status checking.
- [ ] Teach `issues_from_pydantic` to prefer a string `ctx.public_path`; retain
  normal location formatting for every other Pydantic error.
- [ ] Export the new snapshot type through the schema modules.
- [ ] Run the targeted tests until GREEN, then run all Plan tests.

**Verification:**

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_plan_versions.py tests/test_plan_v2_diff.py
```

## Task 3: Register Contract and Traceability Evidence

**Files:**
- Modify: `.agent/api_contracts.md`
- Create: `docs/traceability/sprint1/chen_ziyuan_s1_t014.md`
- Create: `docs/traceability/sprint1/chen_ziyuan_s1_t014.json`
- Create: `tests/test_s1_t014_traceability.py`

- [ ] Document that `tripSnapshot` must be the single-person/single-day
  `PLAN_REVIEW` snapshot and list the stable rejection behavior.
- [ ] Add Markdown and JSON traceability mapping PBI-04-B → AC-04-B → S1-T014
  → code/tests/evidence, including dependency T013 and explicit non-goals.
- [ ] Add a traceability test that loads the JSON and checks required IDs,
  evidence paths, owner, dependency, and acceptance cases.
- [ ] Run the traceability test RED before adding the artifacts, then GREEN after
  the artifacts are complete.

**Verification:**

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_s1_t014_traceability.py
```

## Task 4: Full Verification and Independent Review

**Files:**
- Review all branch changes against `origin/main`

- [ ] Run the complete Python test suite.
- [ ] Run frontend lint and production build.
- [ ] Run `git diff --check` and inspect branch status for accidental files.
- [ ] Generate a whole-branch review package from merge base to HEAD.
- [ ] Have an independent reviewer check specification compliance and code
  quality; fix every Critical or Important finding and repeat its covering tests.
- [ ] Re-run the full verification after review fixes.
- [ ] Push only `czy-S1-T014`; do not merge it into `main`.

**Verification:**

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q
pnpm --dir frontend run lint
pnpm --dir frontend run build
git diff --check origin/main...HEAD
git status --short --branch
```
