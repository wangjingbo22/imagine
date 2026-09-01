# Task 5 Report

## Scope

- Initial planning now sends one non-persistent candidate preview and returns no V1.
- Final acceptance issues V1 only after a PASS or NEEDS_CONFIRMATION preview.
- An issuance response requiring fact confirmation opens the existing review path without confirming or starting execution.
- Preview FAIL and local unschedulable segment failures remain blocked.

## TDD Evidence

- Added tests before the implementation.
- RED command: `npm.cmd --prefix frontend test`
- RED result: initial planning attempted `/plan-versions/generate`; Workspace had no final issuance call.
- GREEN command: `npm.cmd --prefix frontend test`
- GREEN result: 132 passed, 0 failed.

## Final Verification

- `npm.cmd --prefix frontend run lint`: passed with four pre-existing warnings outside Task 5 files.
- `npm.cmd --prefix frontend run build`: passed.
- `git diff --check`: passed.

## Review Fixes

- Added a V1 issuance checkpoint before confirm/start so retries reuse the issued ID.
- Added shared acceptance and segment-replacement race predicates for pending route updates and V1 confirmation.
- Preserved server preview FAIL explanations for initial plans and rebuilt route candidates; the Workspace renders non-review issues with `aria-live`.
- Kept local unschedulable segment behavior unchanged.

## Review-Fix Verification

- RED command: `npm.cmd --prefix frontend test`
- RED result: 4 failures covering missing preview issues, issuance checkpoint, race predicates, and retained rebuilt candidate state.
- GREEN command: `npm.cmd --prefix frontend test`
- GREEN result: 135 passed, 0 failed.
- `npm.cmd --prefix frontend run lint`: passed with the same four pre-existing warnings outside Task 5 files.
- `npm.cmd --prefix frontend run build`: passed.
- `git diff --check`: passed.

## P2 Preview Confirmation UX/State Fix

- Preserved the complete server `CandidatePlanPreview` through initial planning and successful segment replacements, and cleared it for regeneration, local schedule failures, and restored issued plans.
- Added a pure `NEEDS_CONFIRMATION` notice formatter that presents server warning messages plus matching constraint suggestions without creating a review or blocking V1 issuance.
- Workspace now announces the concrete confirmation facts before acceptance and labels the enabled action `继续核对计划事实`.
- RED command: `npm.cmd --prefix frontend test`; result: 133 passed, 3 expected failures for missing preview retention, notice formatter, and replacement state.
- GREEN command: `npm.cmd --prefix frontend test`; result: 136 passed, 0 failed.
- `npm.cmd --prefix frontend run lint`: passed with four pre-existing warnings outside Task 5 files.
- `npm.cmd --prefix frontend run build`: passed with the existing `runtime-config.js` bundling advisory.
- `git diff --check`: passed.
