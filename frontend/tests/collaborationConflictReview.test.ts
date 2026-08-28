import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import {
  canEnterRecommendation,
  organizerRelaxations,
  participantIdsForIssue,
  participantRelaxations,
  type CollaborationAggregate,
  type CollaborationIssue,
} from '../src/domain/collaboration.ts'

const apiSource = readFileSync(
  fileURLToPath(new URL('../src/api/collaborationApi.ts', import.meta.url)),
  'utf8',
)
const panelSource = readFileSync(
  fileURLToPath(new URL('../src/components/ConflictReviewPanel.tsx', import.meta.url)),
  'utf8',
)
const pageSource = readFileSync(
  fileURLToPath(new URL('../src/pages/ConversationPlannerPage.tsx', import.meta.url)),
  'utf8',
)
const cssSource = readFileSync(
  fileURLToPath(new URL('../src/index.css', import.meta.url)),
  'utf8',
)

const issue: CollaborationIssue = {
  itemId: 'ci_0123456789abcdef',
  fieldPath: 'participants[1].avoidPlaces[0]',
  participantId: '22222222-2222-4222-8222-222222222222',
  relatedParticipantIds: ['11111111-1111-4111-8111-111111111111'],
  ruleId: 'S2T003.PLACE.MUST_AVOID',
  code: 'CONFLICT',
  reason: '同一地点同时被设为必去和避开',
  candidates: [],
  allowedRelaxations: [
    {
      relaxationId: 'rx_1111111111111111',
      action: 'SET_SHARED_FIELD',
      actorScope: 'ORGANIZER',
      participantId: null,
      fieldPath: 'trip.endTime',
      proposedValue: null,
      label: '由组织者修改共享安排',
    },
    {
      relaxationId: 'rx_2222222222222222',
      action: 'REMOVE_AVOID_PLACE',
      actorScope: 'PARTICIPANT',
      participantId: '22222222-2222-4222-8222-222222222222',
      fieldPath: 'participants[1].avoidPlaces[0]',
      proposedValue: null,
      label: '由字段所有者移除避开限制',
    },
  ],
}

const state: CollaborationAggregate = {
  schemaVersion: '1.0',
  tripId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  draftId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  currentRevision: 7,
  organizerParticipantId: '11111111-1111-4111-8111-111111111111',
  status: 'CONFLICT_REVIEW',
  collaborationVersion: 9,
  policyVersion: 'S2-T003.1',
  readinessDigest: null,
  canPlan: false,
  progress: { expectedCount: 2, confirmedCount: 2, openIssueCount: 1 },
  participants: [],
  confirmationItems: [issue],
}

test('conflict review names every participant and preserves permission-scoped relaxations', () => {
  assert.deepEqual(participantIdsForIssue(issue), [
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
  ])
  assert.deepEqual(organizerRelaxations(issue).map((item) => item.relaxationId), ['rx_1111111111111111'])
  assert.deepEqual(participantRelaxations(issue).map((item) => item.relaxationId), ['rx_2222222222222222'])
})

test('recommendation remains hidden unless READY, canPlan and digest all agree', () => {
  assert.equal(canEnterRecommendation(state), false)
  assert.equal(canEnterRecommendation({
    ...state,
    status: 'READY_TO_PLAN',
    canPlan: true,
    readinessDigest: 'a'.repeat(64),
    confirmationItems: [],
    progress: { ...state.progress, openIssueCount: 0 },
  }), true)
  assert.equal(canEnterRecommendation({ ...state, status: 'READY_TO_PLAN', canPlan: true }), false)
})

test('organizer refresh uses the frozen capability header', () => {
  assert.match(apiSource, /\/api\/v2\/trips\/\$\{encodeURIComponent\(tripId\)\}\/collaboration/)
  assert.match(apiSource, /'X-Organizer-Token': organizerToken/)
})

test('organizer resolution uses item endpoint, version binding and idempotency', () => {
  assert.match(apiSource, /\/confirmation-items\/\$\{encodeURIComponent\(itemId\)\}\/resolve/)
  assert.doesNotMatch(apiSource, /\/conflicts\//)
  assert.match(apiSource, /'Idempotency-Key': idempotencyKey\('s2-t029-organizer-resolve'\)/)
  assert.match(apiSource, /baseRevision: state\.currentRevision/)
  assert.match(apiSource, /expectedVersion: state\.collaborationVersion/)
  assert.match(apiSource, /relaxationId,/)
})

test('conflict view keeps the six-question mobile path and visible accessible state', () => {
  assert.match(cssSource, /@media \(max-width: 820px\)/)
  assert.match(cssSource, /grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)/)
  assert.match(cssSource, /overflow-wrap: anywhere/)
  assert.match(cssSource, /\.conflict-review__member-action \{ min-height: 44px/)
  assert.match(panelSource, /aria-live="polite"/)
  assert.match(panelSource, /需对应成员本人处理/)
  assert.match(pageSource, /role="alert"/)
  assert.match(pageSource, /aria-current=/)
})
