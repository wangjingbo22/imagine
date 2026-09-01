# Task 4 Evidence: Per-Segment Route Controls

## Scope

- Added `frontend/src/components/SegmentRouteModePicker.tsx`.
- Integrated it into `frontend/src/pages/WorkspacePage.tsx` for every Provider route segment.
- Added responsive/focus/error styles in `frontend/src/styles/white-web.css`.
- Added the UI contract and state-safety coverage to `frontend/tests/segmentRoutePreferences.test.ts`.
- Did not modify backend code or V1 issuance / V2 acceptance behavior.

## Behavior Evidence

- The picker exposes text buttons for `DRIVING`, `TRANSIT`, `WALKING`, and `BICYCLING`, with `aria-pressed` on the selected route mode.
- Request state is per segment. A success derives the replacement candidate, display plan, and route evidence before React applies the candidate, plan, evidence, validation/review reset, and restored-plan reset state updates.
- A thrown provider/preview error, or a local schedule preview failure with no candidate, leaves candidate, plan, evidence, review, and restored-plan data unchanged. It records a readable indexed error with the requested mode only.
- Retry is rendered only for an error and uses that indexed explicit requested mode, not the currently rendered route mode.
- A stored `CURRENT` Plan V1 disables the controls and handler, preserving the existing V1/V2 execution boundary for Task 5.
- The picker has visible `:focus-visible` styling and an atomic polite live status for idle, pending, locked, and error states.

## TDD Evidence

1. Added the source-level UI contract before production code. It checks for the picker integration, all four mode choices, retry, atomic-success state targets, indexed error/retry support, and V1 lockout.
2. The required literal `npm --prefix frontend test` command was attempted first but PowerShell blocked `npm.ps1` under the system execution policy before the test runner could start.
3. Re-ran the identical package script through `npm.cmd --prefix frontend test` to avoid changing system policy. RED result: 125 passed, 1 failed. The only failure was `workspace exposes safe per-segment mode controls with retry and V1 lockout`, failing because `WorkspacePage.tsx` had no `SegmentRouteModePicker`.
4. After implementation, `npm.cmd --prefix frontend test` passed: 126 passed, 0 failed.

## Verification Evidence

| Command | Result |
| --- | --- |
| `npm.cmd --prefix frontend test` | Pass: 126 tests, 0 failures |
| `npm.cmd --prefix frontend run lint` | Exit 0; four existing warnings in unrelated pages (`BudgetLedgerPage`, `MemberConversationPage`, and `ConversationPlannerPage`) |
| `npm.cmd --prefix frontend run build` | Exit 0; TypeScript and Vite production build completed |
| `git diff --check` | Exit 0; only Git LF-to-CRLF notices |

## Concerns

- The front-end linter retains four pre-existing warnings outside Task 4. No new lint warning is reported for the Task 4 files.
- This environment requires `npm.cmd` because direct PowerShell invocation of `npm` is prohibited by execution policy.

## Review Fix: Local Schedule Failure State

The Task 4 review found that `replaceAmapPlanSegment` can return a local schedule `FAIL` with an actual route but no rebuilt candidate. The initial Workspace integration incorrectly handled that non-throwing result like a provider request failure, retaining a stale PASS display and persisted-plan eligibility.

- Added `frontend/src/services/segmentRouteReplacementState.ts`, the real pure transition used by Workspace for both successful and local-failure replacement results.
- Local schedule failure now replaces the selected evidence route with `result.evidence.route`, marks the displayed plan `FAIL`, clears persisted-plan and restored-plan state, clears review state, and exposes the exact local failure message.
- The prior valid candidate remains only as a recovery base. It is not displayed as the selected route and cannot pass confirmation while the local `FAIL` planning issue is active.
- No route duration, costs, schedule, or totals are synthesized from the unschedulable route. The prior display facts remain unchanged except for explicit `FAIL` validation; `locationEvidence` carries the actual returned route.
- Provider request errors still leave the currently displayed state intact and produce the retry-only segment error. A local schedule failure instead permits choosing a different mode; a later successful replacement clears the local failure.

### Review-Fix TDD and Verification

1. Added behavior-level test `local schedule failure renders its returned route as FAIL without accepting stale candidate facts` before the transition helper existed.
2. Full RED run: `npm.cmd --prefix frontend test` produced 126 passed and 1 failed. The failure was the expected assertion that the real Workspace state transition did not exist.
3. Full GREEN run: `npm.cmd --prefix frontend test` produced 127 passed and 0 failed. The test uses the actual unschedulable `AmapSegmentReplacementResult`, verifies replacement evidence, `FAIL`/no-persisted eligibility/message/no-fabrication semantics, and verifies recovery by selecting `TRANSIT` from the retained base.
4. `npm.cmd --prefix frontend run lint` exited 0 with the same four unrelated existing warnings; `npm.cmd --prefix frontend run build` exited 0; `git diff --check` exited 0 with only LF-to-CRLF notices.
