# S1-T014 Task 1 Report: Plan Snapshot Contract RED Tests

## Scope

- Worktree: `C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.worktrees\czy-S1-T014`
- Production code changed: none.
- Test file changed: `tests/test_plan_versions.py`.

## Added coverage

- `post_proposal_and_restore_state`, a small async HTTP helper that submits a
  plan proposal and retrieves the corresponding Trip state.
- Parameterized invalid V1 snapshot HTTP cases for:
  1. multiple participants;
  2. multiple Trip days;
  3. start/end-date mismatch;
  4. Trip-day/date mismatch;
  5. nonzero day index;
  6. equal time-window bounds (the `end <= start` boundary); and
  7. daily budget above total budget.
- Every V1 case asserts HTTP 422, `TRIP_SCHEMA_INVALID`, the exact public path
  and error code, then verifies a 404 `TRIP_NOT_FOUND` retrieval so a rejected
  V1 cannot persist Trip state.
- An invalid V2 multi-participant regression which creates and executes a valid
  V1, then requires the rejected V2 to leave V1 as CURRENT, Trip status as
  `EXECUTING`, and `proposedPlans` empty.

## RED verification

Command run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest -q tests/test_plan_versions.py -k 'single_day_snapshot or invalid_v2_snapshot'
```

Result: exit 1; `8 failed, 6 deselected in 1.06s`.

- All seven V1 cases failed at the intended HTTP-contract assertion because the
  current wide `Trip` snapshot model accepted each payload and returned 200,
  rather than a 422 schema error.
- The V2 case established V1 successfully, then received 409 rather than 422:
  it reached the existing persistence/state guard (`TRIP_SNAPSHOT_IMMUTABLE`)
  instead of being rejected at the snapshot schema boundary.

These failures demonstrate the intended T014 defect, not a test syntax or
fixture failure.

## Self-review and focus

- Confirmed the tests only modify `tests/test_plan_versions.py`; no app,
  backend, state-machine, or SQLite production code changed.
- `git diff --check` returned successfully (Git emitted only the repository's
  LF-to-CRLF working-copy warning).
- The virtual environment does not include Ruff (`No module named ruff`), so
  no Ruff result is available. The required focused pytest command above is the
  authoritative RED evidence for this test-locking task.

## Commit

Commit message: `test: expose T014 plan snapshot bypass`.
