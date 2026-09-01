# Task 6 Verification Report

## Scope

- Added browser coverage for per-segment route preferences.
- Added the dedicated `test:segment-route-preferences` package script and CI gate after `test:t024`.
- Corrected the mobile route-mode and retry targets from 36px to 44px after the new browser test demonstrated the accessibility failure.

## TDD Evidence

The first E2E run was red because the test navigation fixture wrote React Router state at the history root instead of `history.state.usr`; the workspace correctly rendered its no-plan state. The fixture was corrected without changing product behavior.

The subsequent route success fixture was red because its manually chosen task times did not leave time for the preceding routes. The test data was corrected to be a valid confirmed candidate.

The new 375px computed-height assertion then failed as intended: the route mode target height was below 44px. `frontend/src/styles/white-web.css` now sets both the base and mobile override to `min-height: 44px`.

## Verification

| Command | Result |
| --- | --- |
| `npm.cmd --prefix frontend run test:segment-route-preferences` | PASS: 8/8 Playwright checks across 375, 768, 1366, and 1440 viewports. It verifies one selected-mode route request with organizer header, exactly one following preview, visible route/timeline/summary update, and failure retention with explicit same-mode retry. |
| `npm.cmd --prefix frontend test` | PASS: 136/136. |
| `npm.cmd --prefix frontend run lint` | Exit 0; 4 existing warnings in `BudgetLedgerPage`, `MemberConversationPage`, and `ConversationPlannerPage`; none in Task 6 files. |
| `npm.cmd --prefix frontend run build` | PASS. |
| `& .\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q backend/tests/test_segment_route_preferences.py backend/tests/test_amap_transport_retry.py backend/tests/test_route_risk.py backend/tests/test_candidate_planner.py backend/tests/test_planning_http_boundaries.py` | 60 passed, 17 failed. All failures are the known pre-existing planning-boundary contract mismatch: unauthenticated requests return `401 ACCOUNT_SESSION_REQUIRED` while tests expect `409`. |
| `git diff --check` | PASS before staging. |

The first sandboxed backend attempt could not create pytest temporary directories under the user Temp folder (23 setup errors). Re-running the exact command with Temp access produced the result above.

## Residual Risk

The backend planning-boundary suite remains red until its authentication expectation or test setup is reconciled. No implementation was changed to conceal that discrepancy. CI will install Chromium once and execute the existing responsive gate followed by the new dedicated E2E gate.
