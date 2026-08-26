# S1-T017 Clean Slice Acceptance

Date: 2026-08-26
Branch: `czy-S1-T017-final`
Baseline: `12caa055deb12f690c3c0e00c55295e027dbd606`

## Scope

- Added `POST /api/v1/trips/{tripId}/replans/from-events`.
- The event-driven request accepts only `schemaVersion: "1.0"` and `reason: "EXPENSE_CHANGE"`.
- The server derives frozen prefix, actual spend, and suffix facts from CURRENT V1 trusted facts plus T016 execution events.
- The suffix planner receives only unfinished `CandidateTaskFact` rows; the default production planner retains the trusted suffix.
- `/replans` and `/replans/from-events` now use in-memory V2 facts during selection and persist only the selected V2.
- Frontend execution no longer builds browser-side V2 candidates or submits free-text feedback for S1 replanning.

## Backend Evidence

Command:

```powershell
python -m pytest backend/tests/test_s1_t017_event_replan.py -q
```

Result: `9 passed`

Covered:

- Golden path writes EXPENSE + COMPLETE, freezes the first task, and registers one PROPOSED V2.
- Capturing planner receives only tasks 2-4 and the actual spent cents projection.
- Over-budget event returns `REPLAN_NO_FEASIBLE_CANDIDATE` with no PlanVersion V2 and no trusted V2 issuance.
- COMPLETE without explicit EXPENSE returns `REPLAN_EXPENSE_INCOMPLETE` with no V2 residual.
- No events returns `REPLAN_EVENTS_REQUIRED` with no V2 residual.
- No unfinished suffix returns `REPLAN_SUFFIX_EMPTY` with no V2 residual.
- Repeating the same event replan returns the same V2 and keeps only one version-2 row.
- Replaying after V2 rejection returns `REPLAN_S1_VERSION_LIMIT` with no database changes.
- `feedback` and `USER_FEEDBACK` are rejected by schema validation before any V2 side effect.

Command:

```powershell
python -m pytest backend/tests/test_planning_http_boundaries.py::test_replan_uses_actual_expense_and_registers_no_over_budget_v2 backend/tests/test_planning_http_boundaries.py::test_two_candidate_replan_is_selected_issued_diffed_and_accepted -q
```

Result: `2 passed`

Covered:

- Existing `/replans` leaves no trusted V2 row when T018 finds no feasible candidate.
- Existing `/replans` persists and issues only the selected V2; losing candidates leave no `VALIDATED` V2 row.
- Selected V2 remains diffable and acceptable through T019 endpoints.

## Frontend Evidence

Command:

```powershell
pnpm run test
```

Result: `21 passed`

Covered:

- `createExpenseChangeReplanRequest()` emits exactly `schemaVersion` and `reason`.
- Yuan input is rounded to integer cents and rejects empty, negative, and non-finite values.
- `tripApi.replanFromEvents()` posts `/replans/from-events` without candidates, locked IDs, task facts, or feedback.
- `WorkspacePage` calls server event replanning, has no `buildAmapReplanCandidate`, no `tripApi.selectReplan`, and no `USER_FEEDBACK` execution path.

Command:

```powershell
pnpm run lint
pnpm run build
```

Result: both exit `0`. Vite still prints the pre-existing `/runtime-config.js` non-module bundling warning, then completes the build.

## Full Regression

Commands:

```powershell
python -m pytest -q
python -m compileall app backend/app
git diff --check
```

Results:

- `273 passed`
- `compileall` exit `0`
- `git diff --check` exit `0`; Git reports only LF-to-CRLF working-copy warnings.

## Boundary Review

- V1 evidence confirmation remains owned by the existing T011 review flow; no UNKNOWN price/facility/source is auto-marked PASS.
- T018 still owns frozen-prefix validation and candidate selection. T017 supplies a single deterministic suffix candidate from trusted facts.
- T019 Diff/accept/reject compatibility is preserved for selected V2 plans.
- Cross-transaction crash atomicity, replay watermarks, and CAS ledger behavior are intentionally out of this slice.
