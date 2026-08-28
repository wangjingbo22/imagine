# S2-T002 Draft Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended in the current session) or `executing-plans` (in a separate session) to implement this plan task by task. Use `test-driven-development` for every production change and `verification-before-completion` before the final commit.

**Goal:** Persist an immutable `draftId/revision` result for each fixed-question answer command, guarantee at most one model parse per answer command, reuse saved revisions during confirmation, and make corrected answers advance the revision so T003 invalidates stale confirmations.

**Architecture:** Add one SQLite-backed application service behind T003's frozen `TripDraftRevisionPort`. The service owns immutable draft revisions and durable command claims; T003 remains the sole owner of collaboration state, confirmations, conflicts, and readiness. The existing `/api/v2/trips/conversations` stub creates revision 1 and then bootstraps T003. Model extraction occurs only through a T004-shaped gateway and never inside a SQLite transaction.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, built-in `sqlite3`, pytest, existing T001 `TripUnderstandingProposal`, existing T003 collaboration service/store/routes.

## Global constraints

- For implementation, use a version-manager-created `czy-S2-T002-code` worktree. Its concrete baseline is the `czy-S2-T002` feature HEAD that already contains this plan. The `czy-S2-T002-analysis` worktree and branch are only for producing and committing the present design documents.
- Do not modify `frontend/**` or the legacy `/api/v1/trips/drafts/*` behavior.
- Do not introduce a second confirmation, conflict, participant, or READY state model.
- The gateway may return only a strict T001 proposal plus recognition metadata. It must not write `Trip`, `Constraint`, `PlanVersion`, confirmation, or readiness state.
- Every write path must fail closed on a pending, failed, stale, or corrupt revision. Do not retry the same claimed answer command by calling the gateway again.
- Use the repository interpreter `C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe`. Do not search for or install another runtime.

---

## Task 1: Freeze the T002 domain contract

**Files:**

- Modify: `app/domain/trip_draft.py`
- Modify: `app/domain/collaboration.py`
- Create: `backend/tests/test_s2_t002_contract.py`

### Step 1: Write the failing contract tests

Add these tests:

```python
def test_revision_envelope_rejects_binding_drift_and_extra_fields() -> None:
    proposal = valid_group_proposal(member_keys=("member-1", "member-2"))
    with pytest.raises(ValidationError):
        TripDraftRevision(
            schemaVersion="1.0",
            draftId=uuid4(),
            revision=1,
            tripId=uuid4(),
            understanding=proposal,
            memberBindings={"member-1": uuid4()},
            sourceDigest="a" * 64,
            createdAt=datetime.now(UTC),
            canPlan=True,
        )


def test_organizer_conversation_reuses_fixed_question_contract() -> None:
    request = OrganizerConversationRequest(
        schemaVersion="1.0",
        referenceDate=date(2026, 8, 27),
        naturalLanguageRequest="两人去上海一日游",
        answers=valid_six_answers(),
    )
    assert [answer.question_id for answer in request.answers] == list(QUESTION_IDS)
```

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest backend/tests/test_s2_t002_contract.py -q
```

Expected: FAIL because the T002 envelope and organizer request/response models do not exist.

### Step 2: Implement only the strict models

Extend its datetime import to `from datetime import date, datetime`, then add to `app/domain/trip_draft.py`:

```python
class TripDraftRevision(UnderstandingContractModel):
    schema_version: Literal["1.0"] = "1.0"
    draft_id: UUID
    revision: int = Field(ge=1)
    trip_id: UUID
    understanding: TripUnderstandingProposal
    member_bindings: dict[str, UUID]
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime

    @model_validator(mode="after")
    def validate_member_bindings(self) -> "TripDraftRevision":
        member_keys = [member.member_key for member in self.understanding.participants]
        if set(self.member_bindings) != set(member_keys):
            raise ValueError("memberBindings must exactly match proposal member keys")
        if len(set(self.member_bindings.values())) != len(self.member_bindings):
            raise ValueError("participant bindings must be unique")
        return self


class TripUnderstandingExtraction(UnderstandingContractModel):
    proposal: TripUnderstandingProposal
    recognition_source: str = Field(min_length=1, max_length=40)
    recognition_model: str | None = Field(default=None, max_length=120)
    degraded_reason: str | None = Field(default=None, max_length=240)
    llm_call_count: Literal[0, 1]
```

Import `date` alongside `datetime`, then add `OrganizerConversationRequest` and `OrganizerConversationCreated` to `app/domain/collaboration.py`. Compose existing models rather than copying their fields:

```python
class OrganizerConversationRequest(ConversationSubmission):
    schema_version: Literal["1.0"]
    reference_date: date


class OrganizerConversationCreated(CollaborationModel):
    revision: TripDraftRevision
    organizer_access: OrganizerBootstrapResult
```

Keep the existing `QUESTION_IDS` validator as the single fixed-question definition.

### Step 3: Run the tests and commit

Run the same test command. Expected: PASS.

```powershell
git add app/domain/trip_draft.py app/domain/collaboration.py backend/tests/test_s2_t002_contract.py
git commit -m "feat(s2-t002): freeze draft revision contract"
```

---

## Task 2: Persist immutable revisions and durable command claims

**Files:**

- Create: `app/infrastructure/trip_draft_revision_store.py`
- Create: `backend/tests/test_s2_t002_revision_store.py`

### Step 1: Write failing persistence and concurrency tests

Add these exact tests:

- `test_completed_revision_survives_restart_and_rows_are_immutable`
- `test_same_command_replays_saved_revision_and_digest_conflict_is_rejected`
- `test_concurrent_same_answer_command_claims_once`
- `test_stale_base_revision_is_rejected_before_claim`
- `test_pending_command_hides_old_current_revision`

The concurrency test must synchronize two threads at the claim boundary and assert exactly one `ClaimedCommand`; the other result must be `CommandInProgress` or `CompletedCommand`, never a second claim. The restart test must construct a second repository over the same SQLite file and compare the full serialized revision and `sourceDigest` byte for byte. The immutability assertion must attempt a second insert for the same `(draft_id, revision)` and expect `DRAFT_REVISION_IMMUTABLE`.

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest backend/tests/test_s2_t002_revision_store.py -q
```

Expected: FAIL because the repository does not exist.

### Step 2: Implement schema, claims, and CAS

Create `SqliteTripDraftRevisionRepository` with these public operations:

```python
class SqliteTripDraftRevisionRepository:
    def claim_initial(self, command: AnswerCommand, *, draft_id: UUID, trip_id: UUID) -> CommandClaim: ...
    def claim_next(self, command: AnswerCommand, *, draft_id: UUID, trip_id: UUID, base_revision: int) -> CommandClaim: ...
    def complete(self, claim: ClaimedCommand, revision: TripDraftRevision, extraction: TripUnderstandingExtraction) -> None: ...
    def fail(self, claim: ClaimedCommand, *, code: str) -> None: ...
    def get_current(self, trip_id: UUID) -> TripDraftRevision: ...
```

Define the repository boundary types in the same module so Task 2 has no dependency on the Task 3 service:

```python
@dataclass(frozen=True, slots=True)
class AnswerCommand:
    actor_scope: str
    actor_id: str
    operation: str
    idempotency_key: str
    request_digest: str


@dataclass(frozen=True, slots=True)
class ClaimedCommand:
    command: AnswerCommand
    draft_id: UUID
    trip_id: UUID
    target_revision: int


@dataclass(frozen=True, slots=True)
class CompletedCommand:
    revision: TripDraftRevision


@dataclass(frozen=True, slots=True)
class CommandInProgress:
    target_revision: int


@dataclass(frozen=True, slots=True)
class FailedCommand:
    code: str


CommandClaim = ClaimedCommand | CompletedCommand | CommandInProgress | FailedCommand


class TripDraftRevisionStoreError(RuntimeError):
    pass
```

Create the three tables and constraints from the design document: `trip_draft_heads`, `trip_draft_revisions`, and `trip_draft_commands`. Use the same connection settings as `collaboration_store.py`: WAL, foreign keys, `busy_timeout`, and `BEGIN IMMEDIATE` for claims and completion.

Claim behavior must be decided inside one short transaction:

```python
with self._immediate_transaction() as connection:
    prior = self._find_command(connection, command.identity)
    if prior is not None:
        return self._replay_or_conflict(prior, command.request_digest)
    self._assert_no_active_planning_lease(connection, trip_id)
    head = self._load_head_for_update(connection, draft_id)
    self._require_current_and_idle(head, base_revision)
    target_revision = base_revision + 1
    self._insert_claim(connection, command, target_revision)
    self._mark_pending(connection, head, target_revision)
    return ClaimedCommand(command=command, target_revision=target_revision)
```

`_assert_no_active_planning_lease()` must read T003's existing `collaboration_operation_leases` table inside the same `BEGIN IMMEDIATE` transaction as the command claim. This reuses the T003 lease instead of duplicating it and prevents lease acquisition from racing between a read-only preflight and the claim. `complete()` must validate `target_revision`, insert the immutable row, CAS `pending_revision` and `current_revision`, clear pending, and mark the command completed in one transaction. `fail()` must retain the failed command and pending marker so `get_current()` returns `TRIP_DRAFT_REVISION_UNAVAILABLE`; it must never delete the claim to enable a second gateway call.

Persist JSON using canonical serialization (`sort_keys=True`, compact separators, UTF-8) and revalidate it through `TripDraftRevision` when reading. Do not expose SQL rows to the application layer.

### Step 3: Run the tests and commit

Run the same test command. Expected: PASS, including the concurrent single-claim assertion.

```powershell
git add app/infrastructure/trip_draft_revision_store.py backend/tests/test_s2_t002_revision_store.py
git commit -m "feat(s2-t002): persist immutable draft revisions"
```

---

## Task 3: Implement the single-parse revision service

**Files:**

- Create: `app/application/trip_draft_revision_service.py`
- Create: `backend/tests/test_s2_t002_revision_service.py`

### Step 1: Write the failing application tests

Add a `CountingTripUnderstandingGateway` test double and these tests:

- `test_initial_answer_revision_calls_gateway_once_and_persists_exact_proposal`
- `test_initial_replay_does_not_call_gateway_again`
- `test_concurrent_initial_same_answer_calls_gateway_once`
- `test_member_correction_preserves_other_members_and_bindings`
- `test_member_scope_violation_writes_no_revision`
- `test_relaxation_creates_next_revision_without_gateway_call`
- `test_failed_gateway_keeps_current_unavailable_and_never_retries_same_command`

For every test, assert the gateway call count as well as the stored revision count. In the member-scope test, make the gateway alter another member and a shared trip field; assert `PARTICIPANT_SCOPE_VIOLATION`, no completed new revision, and only one gateway call for that command. In the failure replay test, invoke the same key and digest twice and assert the second invocation returns the persisted failure without incrementing the count.

The concurrent service test must hold the first gateway call open while a second identical coroutine enters the service. Assert the second result is `DRAFT_PARSE_IN_PROGRESS` (or the completed saved revision if the first has already committed), the counting gateway is exactly 1, and only one immutable revision exists.

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest backend/tests/test_s2_t002_revision_service.py -q
```

Expected: FAIL because the application service and gateway protocol do not exist.

### Step 2: Define the narrow gateway over the Task 1 extraction result

```python
class TripUnderstandingGateway(Protocol):
    async def extract(self, request: TripUnderstandingRequest) -> TripUnderstandingExtraction: ...
```

`UnavailableTripUnderstandingGateway.extract()` must raise `TRIP_UNDERSTANDING_UNAVAILABLE` and write no revision. This is the default until T004 supplies the real gateway.

### Step 3: Implement the frozen T003 port

`TripDraftRevisionService` must implement `get_current`, `submit_participant_conversation`, and `apply_relaxation`, plus `create_initial` for the existing conversations route.

Use this sequencing for model-backed commands:

```python
claim = repository.claim_next(
    command,
    draft_id=draft_id,
    trip_id=trip_id,
    base_revision=base_revision,
)
if isinstance(claim, CompletedCommand):
    return claim.revision
if isinstance(claim, CommandInProgress):
    raise AppError("DRAFT_PARSE_IN_PROGRESS", "草稿解析正在进行", 409, True)
if isinstance(claim, FailedCommand):
    raise saved_failure_to_app_error(claim.code)

try:
    extraction = await gateway.extract(extraction_request)
    candidate = validate_and_scope_merge(extraction.proposal, current, actor)
    revision = build_revision(candidate, claim.target_revision, current.memberBindings)
    repository.complete(claim, revision, extraction)
    return revision
except Exception as error:
    failure = map_revision_failure(error)
    repository.fail(claim, code=failure.code)
    raise failure from error
```

Implement `saved_failure_to_app_error()` as a private total mapping for persisted codes: `PARTICIPANT_SCOPE_VIOLATION -> 403/non-retryable`, `DRAFT_BINDINGS_IMMUTABLE -> 409/non-retryable`, `TRIP_UNDERSTANDING_INVALID -> 502/non-retryable`, and `TRIP_UNDERSTANDING_UNAVAILABLE -> 503/retryable`; unknown persisted codes fail closed as `TRIP_DRAFT_REVISION_UNAVAILABLE/503/retryable`. `map_revision_failure()` must preserve an existing `AppError`, map strict proposal `ValidationError` to `TRIP_UNDERSTANDING_INVALID`, and map gateway transport/unavailable and every unexpected exception to `TRIP_UNDERSTANDING_UNAVAILABLE`. Persist the mapped code before returning the error, and make replay return that saved classification without calling the gateway.

The gateway call must occur after claim commit and before completion transaction. `create_initial()` and `submit_participant_conversation()` are async; `apply_relaxation()` remains synchronous because it never calls the gateway. Build `draftId`, `tripId`, participant UUID bindings, `revision`, and `sourceDigest` in application code. The gateway cannot supply them.

Use stable command actors: initial creation is `SYSTEM/INITIAL_CONVERSATION`, member correction is `PARTICIPANT/<participant UUID>`, and a T003-authenticated relaxation is `SYSTEM/<trip UUID>`. The operation name remains part of the command identity, so the same external key can safely cross T002 creation and T003 bootstrap without sharing rows.

For a participant correction, reuse the current canonical shared trip and all other members. Accept only fields mapped to the authenticated participant binding. Reject party-size, member order, another member, shared trip, or binding changes. For `apply_relaxation`, apply the design's action/path allowlist deterministically to the current proposal and assert the gateway count remains zero.

Compute `sourceDigest` from canonical JSON containing `draftId`, target revision, `tripId`, the exact proposal, ordered bindings, and source request digest. Reuse `collaboration_digest.py`'s canonical serialization helper if it is public; otherwise add one private canonical JSON helper in this service, not a second collaboration digest scheme.

### Step 4: Run service and frozen-port tests, then commit

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest backend/tests/test_s2_t002_revision_service.py backend/tests/test_s2_t003_revision_port.py -q
```

Expected: PASS. Existing unavailable-port tests must remain unchanged and pass.

```powershell
git add app/application/trip_draft_revision_service.py backend/tests/test_s2_t002_revision_service.py
git commit -m "feat(s2-t002): implement single-parse revision service"
```

---

## Task 4: Close the T003 preflight and planning race windows

**Files:**

- Modify: `app/application/collaboration_service.py`
- Modify: `app/application/collaboration_readiness.py`
- Modify: `app/infrastructure/collaboration_store.py`
- Modify: `backend/tests/test_s2_t003_collaboration_service.py`
- Modify: `backend/tests/test_s2_t003_readiness_guard.py`

### Step 1: Prove stale collaboration input is rejected before T002

Add:

- `test_member_submit_stale_expected_version_rejects_before_t002`
- `test_member_submit_replay_finishes_collaboration_advance_without_reparse`

The first test supplies a spy revision port and stale `expectedVersion`; assert its submit count is zero. The second simulates T002 success followed by a failed collaboration advance, then replays the same key; assert the saved revision is reused, T003 reaches that revision, and the spy parse count remains one.

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest backend/tests/test_s2_t003_collaboration_service.py -q
```

Expected: the stale-preflight test FAILS against the current `submit_member()` ordering.

### Step 2: Reorder preflight without changing the T003 state machine

In `submit_member()`:

1. Authenticate the participant.
2. Call a new read-only `has_completed_operation(actor_scope, actor_id, operation, idempotency_key)` repository helper. If the same T003 `ADVANCE_REVISION` record exists, skip stale preflight, let T002 return its saved revision, and enter the existing `advance_revision()` replay branch.
3. Otherwise read collaboration state and validate `expectedVersion`, `baseRevision`, and active planning lease.
4. Call `submit_participant_conversation()` only after those checks.
5. Validate the returned trip, contiguous revision, and bindings; then call the existing `advance_revision()` CAS.

Do not add a second collaboration transaction or state enum.

### Step 3: Prove READY is revalidated after lease acquisition

Add `test_revision_change_between_ready_check_and_lease_never_enters_body`. Its fake readiness service returns READY for the first check, changes `sourceDigest` while the lease is acquired, and fails the second check. Assert the guarded body, Provider, planner, and `PlanVersion` writer are never invoked, and the lease is released.

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest backend/tests/test_s2_t003_readiness_guard.py -q
```

Expected: FAIL because the current guard checks readiness only before acquiring the lease.

### Step 4: Add the second digest-bound check and run regressions

After lease acquisition and before yielding to downstream code, call `require_ready()` again and require the second `readinessDigest` to equal the leased digest. Keep lease release in the existing `finally` block.

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest backend/tests/test_s2_t003_collaboration_service.py backend/tests/test_s2_t003_readiness_guard.py -q
```

Expected: PASS, including all existing confirmation invalidation and lease tests.

```powershell
git add app/application/collaboration_service.py app/application/collaboration_readiness.py app/infrastructure/collaboration_store.py backend/tests/test_s2_t003_collaboration_service.py backend/tests/test_s2_t003_readiness_guard.py
git commit -m "fix(s2-t002): preflight revision changes before parsing"
```

---

## Task 5: Connect the existing conversations route and production wiring

**Files:**

- Modify: `app/api/collaboration_routes.py`
- Modify: `app/main.py`
- Create: `backend/tests/test_s2_t002_http.py`
- Modify: `backend/tests/test_s2_t003_runtime_schema.py`

### Step 1: Write the failing HTTP acceptance tests

Add these tests:

- `test_conversations_creates_revision_and_bootstraps_existing_collaboration`
- `test_conversations_replay_reuses_revision_without_replaying_organizer_secret`
- `test_conversations_without_t004_gateway_fails_closed`
- `test_confirm_replay_does_not_increment_gateway_count`

Assert the first response contains revision 1 plus the existing T003 bootstrap response; all responses carry `Cache-Control: no-store`. For replay, assert the same `draftId/revision/sourceDigest`, no second gateway call, and no second raw organizer token. For unavailable gateway, assert HTTP 503 with `TRIP_UNDERSTANDING_UNAVAILABLE` and no completed revision. For confirmation and its replay, assert the gateway count remains unchanged.

Update the runtime test to `test_default_runtime_uses_concrete_revision_port_with_unavailable_gateway`: assert default state contains `TripDraftRevisionService`, `get_current()` still fails closed when no revision exists, and initial parsing fails predictably until a gateway is injected.

Run:

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest backend/tests/test_s2_t002_http.py backend/tests/test_s2_t003_runtime_schema.py backend/tests/test_s2_t003_http_boundaries.py -q
```

Expected: FAIL because the route is currently a fixed 503 and default wiring injects `UnavailableTripDraftRevisionPort`.

### Step 2: Replace only the existing stub

Implement the already published route; add no path:

```python
@router.post("/trips/conversations")
async def create_conversation(
    payload: OrganizerConversationRequest,
    request: Request,
    response: Response,
    current: CollaborationService = Depends(service),
) -> ApiResponse[OrganizerConversationCreated]:
    response.headers["Cache-Control"] = "no-store"
    idempotency_key = require_idempotency_key(request)
    creator = request.app.state.trip_draft_revision_creator
    revision = await creator.create_initial(payload, idempotency_key=idempotency_key)
    organizer_access = current.bootstrap(
        revision=revision,
        idempotency_key=idempotency_key,
    )
    return ApiResponse(data=OrganizerConversationCreated(
        revision=revision,
        organizer_access=organizer_access,
    ))
```

Use the existing error envelope and idempotency-header validator. Preserve T003's one-time secret behavior during bootstrap replay; do not cache a raw token in the T002 command row.

### Step 3: Wire one service instance into creation and T003

In `create_app()`, accept an optional `trip_understanding_gateway`. Construct one `SqliteTripDraftRevisionRepository` on the existing planning database path and one `TripDraftRevisionService`. Use that service as both `app.state.trip_draft_revision_creator` and the default `trip_draft_revision_port`. Preserve the explicit `trip_draft_revision_port` injection hook for T003 unit tests. If no gateway is provided, inject `UnavailableTripUnderstandingGateway`; do not fall back to the legacy `LlmTripDraftFields` extractor.

### Step 4: Run HTTP and legacy regressions, then commit

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest backend/tests/test_s2_t002_http.py backend/tests/test_s2_t003_runtime_schema.py backend/tests/test_s2_t003_http_boundaries.py backend/tests/test_trip_draft_llm_integration.py backend/tests/test_s1_t024_golden_path.py backend/tests/test_trip_understanding_schema.py -q
```

Expected: PASS. The existing `/api/v1/trips/drafts/*` tests must show no behavior change.

```powershell
git add app/api/collaboration_routes.py app/main.py backend/tests/test_s2_t002_http.py backend/tests/test_s2_t003_runtime_schema.py
git commit -m "feat(s2-t002): connect persistent conversation drafts"
```

---

## Task 6: Verify the complete backend boundary

**Files:**

- Verify: all files changed in Tasks 1–5

### Step 1: Run the focused S2 boundary suite

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest backend/tests/test_s2_t002_contract.py backend/tests/test_s2_t002_revision_store.py backend/tests/test_s2_t002_revision_service.py backend/tests/test_s2_t002_http.py backend/tests/test_s2_t003_revision_port.py backend/tests/test_s2_t003_collaboration_service.py backend/tests/test_s2_t003_readiness_guard.py backend/tests/test_s2_t003_http_boundaries.py backend/tests/test_s2_t003_runtime_schema.py backend/tests/test_trip_understanding_schema.py -q
```

Expected: PASS with no failures. Check specifically that every counting-gateway assertion is 0 or 1 as specified.

### Step 2: Run the backend suite once

```powershell
& 'C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe' -m pytest backend/tests -q
```

Expected: PASS with no failures. The recorded baseline is 511 passing tests before T002 additions.

### Step 3: Inspect scope and repository hygiene

```powershell
git diff --check
git status --short
$t002Baseline = git merge-base HEAD czy-S2-T002
git diff --stat "$t002Baseline...HEAD"
```

Expected: no whitespace errors; no `frontend/**` change; no changes to v1 route semantics; only the backend/domain/application/infrastructure/test files listed above plus the approved docs.

### Step 4: Commit any verification-only test correction

Only if a test assertion required a correction that did not broaden product scope:

```powershell
git add backend/tests
git commit -m "test(s2-t002): lock revision reuse acceptance"
```

Do not push. Hand off the branch with test output, commit SHAs, and confirmation that the gateway never writes formal trip/planning/collaboration state.

## Recommended execution order and ownership

1. T002 Tasks 1–3: contract, store, and service.
2. T003 integration patch in Task 4: preflight/recovery and the post-lease readiness check only.
3. T002 Task 5: replace the existing stub and production wiring.
4. T004: inject the real strict gateway after T002 is green; do not bypass command claims.
5. Wang Jingbo's frontend task consumes the existing v2 DTO; T002 adds no page.
6. T005 may create formal `Trip`/`PlanVersion` only after the existing T003 READY guard succeeds.

## Code-window handoff constraints

- Treat `TripDraftRevisionPort`, its method names, T003 DTOs, digest invalidation, and READY semantics as frozen.
- The same `(actor scope, actor id, operation, Idempotency-Key, request digest)` can cause at most one gateway invocation for its lifetime, including after restart and after failure.
- A corrected fixed-question answer uses a new idempotency key and the current `baseRevision`; it may create only `baseRevision + 1`.
- Reserve the command and pending target in a short SQLite transaction, call the gateway outside every transaction, then complete by CAS.
- Confirmation is a read-only consumer of the saved current revision and must never call the gateway.
- A member correction cannot change shared data, another member, membership order/count, or bindings. Organizer relaxation is a deterministic allowlisted patch with zero gateway calls.
- If T002 advances but T003 does not, `canPlan` remains false; replay must converge T003 without parsing again.
- Do not let Provider, recommendation, planner, formal-trip, constraint, or plan-version writes execute until the digest-bound READY check succeeds after lease acquisition.
- Keep T004-unavailable behavior explicit and fail closed. Never route S2 through the legacy S1 extractor.
