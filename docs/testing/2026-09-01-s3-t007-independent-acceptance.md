# S3-T007 Independent Acceptance Record

**Task:** isolated two-day `Trip.days[]` serialization, validation, and SQLite snapshot persistence

**Date:** 2026-09-01 (Asia/Shanghai)

**Assessed worktree:** `C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.worktrees\czy-S3-T007`

**Branch and baseline:** `czy-S3-T007`, HEAD `315fab7`; assessment includes the uncommitted S3-T007 implementation only.

**Role and write boundary:** independent product QA. This record is the only QA-authored persistent file. No production source, dependency, configuration, existing test, parent-trip, S3-T008/S3-T009, or collaboration-token file may be changed.

## Pre-execution Scope Review

Reviewed before execution:

- S3-T007 implementation diff in `backend/app/schemas/trip.py` and `app/infrastructure/workflow_store.py`.
- The submitted fixture, generated schema, schema snapshot, and `backend/tests/test_s3_t007_two_day_trip.py`.
- Existing single-day schema and planner contracts, workflow-store confirmation tables, parent-trip tests, and the S3-T008/S3-T009 independent acceptance records.

The submitted change introduces only `CreateTwoDayTrip`, `validate_two_day_trip_json`, and the isolated `two_day_trip_snapshots` repository path. The single-day confirmation and planning entry points remain typed as one-day contracts.

## Acceptance Checklist And Reproducible Commands

| Check | Required independent assertion | Status before execution |
| --- | --- | --- |
| Strict two-day shape | Exactly two days; ordered `dayIndex` is `0, 1`; `status` is only `DRAFT`; schema artifact equals generated Pydantic schema. | PASS |
| Cross-day validation | `endDate == startDate + 1 day`; each day date maps to its position; both time windows are increasing; each daily budget is within the total budget. | PASS |
| Serialization | Parse -> JSON alias serialization -> parse preserves both day records and distinct per-day locations, windows, and budgets; unknown fields are forbidden. | PASS |
| SQLite persistence | Fresh database save/read after repository re-open returns the complete two-day value; the database contains one dedicated snapshot row. | PASS |
| Idempotency/conflict | Re-saving byte/semantic-equivalent data creates no second row; a changed value with the same `tripId` rejects with `TWO_DAY_TRIP_CONFLICT`. | PASS |
| Isolation | No write to `confirmed_trip_inputs` or `trip_flow_registry`; `CreateDayTrip`, confirmation input, `PlanReviewTripSnapshot`, and `CandidatePlanRequest` still reject two days. | PASS |
| Adjacent scope | No production changes outside T007; parent trips, S3-T008/S3-T009, and collaboration token behavior are not modified. | PASS |
| Regression | Run the submitted focused suite and the repository backend regression suite using an isolated in-worktree pytest base directory. | PASS |

Planned commands (all from this worktree):

```powershell
..\..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q --tb=short --basetemp .qa-tmp-s3-t007-targeted backend/tests/test_s3_t007_two_day_trip.py
..\..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q --tb=short --basetemp .qa-tmp-s3-t007-regression
git diff --name-only
git diff --check
```

An additional temporary black-box probe will use a separate SQLite file and payload mutations not imported from the submitted test module. Temporary files and pytest base directories will be removed before handoff.

## Execution Results

| Command or check | Actual result |
| --- | --- |
| `..\\..\\.venv\\Scripts\\python.exe -B -m pytest -p no:cacheprovider -q --tb=short --basetemp .qa-tmp-s3-t007-targeted backend/tests/test_s3_t007_two_day_trip.py` | Exit 0: `18 passed in 0.52s`. Covers submitted schema, serialization, invalid-shape, repository, conflict, and single-day boundary cases. |
| Worktree-local independent black-box probe | Exit 0: `two-day independent probe: PASS`. Used a separate UUID, `2026-12-30` / `2026-12-31`, distinct per-day locations, windows, and budgets. It checked alias round-trip, generated schema equality, unknown nested field rejection, wrong indexes, date continuity/mapping, time/budget failures, dedicated SQLite row, save timestamp stability on semantic replay, process re-open read, same-ID conflict, confirmation/review rejection, and planner-request rejection. |
| `..\\..\\.venv\\Scripts\\python.exe -B -m pytest -p no:cacheprovider -q --tb=short --basetemp .qa-tmp-s3-t007-regression` | Exit 0: `814 passed, 2 skipped in 86.24s`. This includes existing parent-trip, collaboration, confirmation, planner, and S3-T008/S3-T009 regression coverage. |
| `git diff --check` | Exit 0. No whitespace errors reported. |
| Scope audit: `git diff --name-only`, `git diff --stat`, and untracked-file listing | The only modified tracked production files are `app/infrastructure/workflow_store.py` and `backend/app/schemas/trip.py`; the submitted untracked implementation artifacts are the T007 schema, fixture, snapshot, and focused test. No parent-trip, S3-T008, S3-T009, or collaboration-token file is in the change set. |

The black-box probe is deliberately separate from the submitted pytest module. It asserted that its snapshot database has zero `confirmed_trip_inputs` rows and zero `trip_flow_registry` rows for the two-day `tripId`; the repository has no call path to the single-day confirmation flow.

### Test Environment Note

The first direct invocation of the temporary probe stopped before product assertions because Python put the probe directory ahead of the worktree and then resolved `app.schemas.trip` through an unrelated S3-T009 worktree path present in the virtual-environment search path. Diagnostic commands confirmed that importing from this worktree resolves `backend/app/schemas/trip.py` under `czy-S3-T007`. The identical probe was therefore executed through `runpy` from the assessed worktree and passed. This is an environment import-path condition, not a product failure; no result from the incorrect import was used for acceptance.

## Decision And Residual Risk

**Decision: PASS / accepted for the stated S3-T007 scope.**

`CreateTwoDayTrip` is a separate DRAFT-only contract with strict two-day ordering and cross-day policy validation. Its values survive canonical serialization and isolated SQLite restart/read without day mixing. Duplicate semantic saves retain one immutable row, while a same-`tripId` content change is rejected. The new persistence path does not create confirmation or flow-registry state, and the existing one-day creation, review, and planning boundaries continue to reject a two-day value.

Residual risk is intentionally limited to future work: this scope does not publish an HTTP creation endpoint, authorize a two-day confirmation, or make the one-day planner multi-day aware. Any such integration must be a separate contract and must preserve the demonstrated one-day rejection behavior until deliberately changed.

## QA Hygiene

No production source, dependency, configuration, existing test, parent-trip, S3-T008/S3-T009, or collaboration-token file was modified by QA. The temporary black-box probe, SQLite database, and both pytest base directories are removed before handoff; this report is the only QA-authored persistent file.
