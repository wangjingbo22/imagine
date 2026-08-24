# S1-T014 Plan Snapshot Contract Design

**Date:** 2026-08-24  
**Owner:** 陈梓元  
**Traceability:** PBI-04-B / AC-04-B / S1-T014  
**Dependency:** S1-T013

## Context and Defect

Sprint 1 only supports one participant and one calendar day. The normalized Trip
entry contract already enforces that scope through `CreateSingleDayTrip` and
`validate_single_day_policy`, but `ProposedPlanVersion.trip_snapshot` currently
uses the wider `Trip` base model. A caller can therefore register a Plan V1 or V2
whose snapshot contains multiple participants, multiple days, mismatched dates,
an invalid day index, a reversed time window, or a daily budget above the total
budget. The Plan validator reads only `trip_snapshot.days[0]`, so some invalid
snapshots are persisted and others fail with an imprecise Plan-level message.

This is a contract-boundary defect in T014: state guards must never start from a
snapshot that is outside the Sprint 1 Trip contract.

## Goals

- Reject every Plan V1/V2 snapshot that violates the existing Sprint 1
  single-person, single-day Trip policy before repository persistence.
- Reuse the T001 policy implementation so Trip creation and Plan registration
  cannot drift.
- Return stable, field-addressable `TRIP_SCHEMA_INVALID` errors from the HTTP
  boundary.
- Preserve all valid V1/V2 registration, confirmation, execution, recovery,
  diff, acceptance, and rejection behavior.
- Prove that a rejected V1 creates no Trip state and a rejected V2 leaves the
  current V1 and `EXECUTING` state unchanged.

## Non-goals

- Do not change the T014 state-transition matrix or SQLite transaction logic.
- Do not implement T011 candidate generation, T015/T016 events and expenses,
  T017 replanning, or T018 minimum-disturbance selection.
- Do not add server-side recomputation of caller-supplied HARD constraint PASS
  values in this change; that requires the T007/T009/T011 production pipeline.
- Do not expand Sprint 1 to multiple participants or multiple days.

## Considered Approaches

### Route-only validation

The HTTP route could call `validate_single_day_policy` after parsing a generic
`Trip`. This is rejected because direct model, service, and repository callers
could still bypass the policy. The invalid state must be unrepresentable at the
Plan schema boundary.

### Reuse `CreateSingleDayTrip` directly

This model already enforces exactly one participant/day, but it fixes `status`
to `DRAFT`. A Plan snapshot must be `PLAN_REVIEW`, so direct reuse would encode
the wrong lifecycle state.

### Dedicated Plan-review subtype with shared policy (selected)

Add `PlanReviewTripSnapshot(Trip)` with enum-preserving
`mode = TripMode.SINGLE`, `status = TripStatus.PLAN_REVIEW`, and exactly one
participant/day. Its model validator
calls the existing T001 cross-field policy. `ProposedPlanVersion` then uses this
type instead of the generic `Trip`.

This keeps lifecycle types explicit, prevents bypasses at every caller, and
shares one implementation for the cross-field rules.

## Contract and Validation Matrix

| Invalid snapshot | Public error path | Error code |
|---|---|---|
| More than one participant | `tripSnapshot.participants` | Pydantic list maximum error |
| More than one Trip day | `tripSnapshot.days` | Pydantic list maximum error |
| `startDate != endDate` | `tripSnapshot.endDate` | `date_mismatch` |
| `days[0].date != startDate` | `tripSnapshot.days[0].date` | `date_mismatch` |
| `days[0].dayIndex != 0` | `tripSnapshot.days[0].dayIndex` | `invalid_day_index` |
| `timeWindow.end <= start` | `tripSnapshot.days[0].timeWindow.end` | `invalid_time_window` |
| `dailyBudgetCents > totalBudgetCents` | `tripSnapshot.days[0].dailyBudgetCents` | `budget_exceeded` |
| Preference `isHard` contradicts its type | `tripSnapshot.participants[0].preferences[i].isHard` | `invalid_preference_hardness` |
| Same normalized place is both must-visit and avoid | `tripSnapshot.participants[0].preferences[i].value` | `preference_conflict` |

All HTTP failures use status 422 and the existing envelope:

```json
{
  "code": "TRIP_SCHEMA_INVALID",
  "schemaVersion": "1.0",
  "errors": [
    {
      "path": "tripSnapshot.endDate",
      "code": "date_mismatch",
      "message": "startDate and endDate must match for a single-day trip"
    }
  ]
}
```

For shared-policy failures, the snapshot validator raises a Pydantic custom
error containing a `public_path` context value. `issues_from_pydantic` honors
that path when present; native Pydantic errors continue to use their normal
location tuple. The first policy issue is returned deterministically, matching
the model-validation boundary while preserving the standalone T001 validator's
ability to return its complete issue list.

## Data and Error Flow

1. `POST /api/v1/trips/{tripId}/plan-versions` parses
   `ProposedPlanVersion` in strict mode.
2. `tripSnapshot` is parsed as `PlanReviewTripSnapshot`.
3. Field/cardinality checks run before the shared cross-field policy.
4. Any validation error is mapped by `issues_from_pydantic` to the existing
   public error envelope; no service or repository call occurs.
5. Only a valid proposal reaches `PlanVersionService.register_proposed` and the
   SQLite repository.

## Acceptance and Test Strategy

- A parameterized HTTP contract test covers all nine invalid-snapshot cases,
  checks the exact error path/code, and verifies `GET /trips/{tripId}` remains
  `TRIP_NOT_FOUND` after each rejected V1.
- V2 regression cases start from a valid CURRENT V1 in `EXECUTING`, reject both
  a cardinality violation and a shared custom-policy violation, and verify the
  current plan, Trip state, and candidate list are unchanged.
- A model-level regression asserts `mode` and `status` remain `TripMode` and
  `TripStatus` enum members rather than being narrowed to plain strings.
- Existing V1/V2 tests remain green, proving valid snapshots and state flows are
  backward compatible.
- Full Python tests, frontend lint/build, and `git diff --check` must pass before
  the branch is offered for review.

## Review Boundary

This change touches a core lifecycle input contract. It requires independent
code review and the owner must be able to explain why the schema boundary—not
the route or repository—is the enforcement point. The transition matrix itself
is intentionally unchanged.
