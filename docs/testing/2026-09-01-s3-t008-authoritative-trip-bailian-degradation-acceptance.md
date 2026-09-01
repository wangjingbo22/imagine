# S3-T008 Independent Acceptance Record

Date: 2026-09-01

## Environment

- Worktree: `C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.worktrees\czy-S3-T008`
- Branch and baseline: `czy-S3-T008 @ 402ac8a00b623d347812046de6ffc84c1a73c37d`
- Test role: independent product test and acceptance only
- Runtime: Python and the repository frontend Node toolchain
- Test isolation: a worktree-local pytest base temporary directory only; no main-worktree `.pytest-tmp-s3-t002-*` path is used.

## Scope Audit

The uncommitted implementation changes are limited to the organizer conversation API projection, TripDraft recognition DTO and repository read path, a repository invariant check, frontend collaboration types and notice, the frontend API contract note, one frontend collaboration-flow assertion, and one new backend acceptance test. No Bailian transport or retry implementation, planning state machine, S3-T002 media, S3-T007, or S3-T009 file is modified.

The response reads recognition metadata from the persisted `trip_draft_revisions` record after a successful initial revision. `MODEL_PROPOSAL` rejects a non-null degradation reason; `REVIEWED_FIXED_QUESTIONS` requires one. The existing collaboration readiness guard still requires all participants confirmed, no issues, and the current revision before `READY_TO_PLAN` / `canPlan` is possible.

## Required Invariants

- An unreviewed no-key or timeout result remains the existing `FIXED_QUESTIONS` fallback and creates neither a TripDraft revision nor a collaboration session / authoritative plan.
- A six-answer reviewed fallback produces `REVIEWED_FIXED_QUESTIONS`, retains the actual failure code, and reports the persisted call count (zero when no key is configured).
- A model result is `MODEL_PROPOSAL` and has no degradation reason.
- Replaying one idempotency key creates no additional revision and makes no additional model call.
- A reviewed fallback remains a rule revision until the existing confirmation and `READY_TO_PLAN` path completes.
- Existing CURRENT data is not overwritten by either fallback path.
- The page shows the reviewed-fallback notice and failure code and contains no false Bailian-success copy.

## Commands And Results


- `..\..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q --tb=short --basetemp .pytest-tmp-s3-t008-independent backend/tests/test_s3_t008_bailian_authoritative_degradation.py backend/tests/test_s2_t002_revision_service.py backend/tests/test_s2_t002_revision_store.py backend/tests/test_s2_t003_collaboration_service.py backend/tests/test_s2_t003_http_boundaries.py backend/tests/test_collaboration_trip_projection.py`
  - Result: `61 passed in 10.96s`.
  - Covered the four S3-T008 scenarios: no-key reviewed fallback (`LLM_NOT_CONFIGURED`, `callCount=0`), timeout direct fallback with no revision/session, model success with `degradedReason=null`, and idempotent replay with no extra revision or gateway call.

- `..\..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q --tb=short --basetemp .pytest-tmp-s3-t008-independent backend/tests/test_s2_t004_conversation_fallback.py backend/tests/test_s2_t004_fixed_question_fallback.py backend/tests/test_s2_t004_trip_understanding_gateway.py`
  - Result: `39 passed in 2.91s`.
  - Confirms the pre-existing fixed-question and gateway fallback contracts remain compatible.

- `npm.cmd test` in `frontend`
  - Result: `84 passed, 0 failed`; this includes `reviewed fallback revision renders authoritative degradation without model success copy`.

- `npm.cmd run build` in `frontend`
  - Result: TypeScript and Vite production build passed. Vite emitted its existing informational warning that `/runtime-config.js` is an external runtime script without `type="module"`; output was generated successfully.

- Dedicated black-box SQLite scenario
  - Created and confirmed a real CURRENT V1 through the existing planning HTTP flow, then posted both unreviewed and six-answer reviewed no-key failures to `/api/v2/trips/conversations`.
  - Result: the existing CURRENT row was byte-for-byte unchanged; unreviewed returned `FIXED_QUESTIONS`; reviewed returned `REVIEWED_FIXED_QUESTIONS/LLM_NOT_CONFIGURED/callCount=0`; the reviewed Trip had zero `plan_versions` rows. Its persisted collaboration session remained `DRAFT_CONVERSATION`; the derived aggregate was `COLLECTING_MEMBERS`, `canPlan=false`, and `readinessDigest=null`, so it cannot enter authoritative planning before the existing confirmation path.

- Browser black-box flow using a no-key local API
  - Completed the six supplied answers, observed the first response as `FIXED_QUESTIONS` with `LLM_NOT_CONFIGURED` and no Trip, checked all six answers, then retried.
  - Result: the rendered page showed `已核对六项回答草稿` and `本次百炼未成功，草稿来自已核对的六项回答（LLM_NOT_CONFIGURED）。仍可继续确认资料。`; visible page text contained no `百炼成功`.
  - Harness note: the first Vite run returned 502 because its default proxy targets port 8000 while the isolated API used port 8018. Re-running Vite with `VITE_DEV_PROXY_TARGET=http://127.0.0.1:8018` passed; this was test wiring only, not a product defect.

## Risk And Decision

Residual risk: live external Bailian transport behavior is intentionally not exercised with a real credential. Its timeout and model-success contracts are covered by the repository's deterministic gateway test double, while the no-key and user-visible degradation paths were exercised end to end.

Final decision: **PASS**. The implementation stays within S3-T008, projects persisted recognition metadata without granting authority, preserves the fixed-question failure path and CURRENT PlanVersion, and accurately presents the reviewed degradation state.
