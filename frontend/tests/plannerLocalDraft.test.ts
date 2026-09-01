import assert from 'node:assert/strict'
import test from 'node:test'

import {
  clearPlannerLocalDraft,
  createPlannerLocalDraftWriteGate,
  loadPlannerLocalDraft,
  plannerLocalDraftKey,
  plannerLocalDraftScope,
  persistPlannerFallbackDraft,
  savePlannerLocalDraft,
} from '../src/services/plannerLocalDraft.ts'

function memoryStorage(): Storage {
  const entries = new Map<string, string>()
  return {
    get length() { return entries.size },
    clear() { entries.clear() },
    getItem(key) { return entries.get(key) ?? null },
    key(index) { return [...entries.keys()][index] ?? null },
    removeItem(key) { entries.delete(key) },
    setItem(key, value) { entries.set(key, value) },
  }
}

const draft = {
  entryMode: 'single' as const,
  questionnaireStarted: true,
  step: 2,
  description: '周末去宁德吃小吃并看海。',
  answers: ['宁德', '1 人', '宁德站到三都澳', '海鲜', '500 元', '避开拥挤'] as const,
  tripFields: { city: '宁德', startDate: '2026-09-12', endDate: '2026-09-12' },
  customTimeWindow: { startTime: '09:00', endTime: '18:00' },
  routeFields: { start: '宁德站', end: '宁德站', budget: '500' },
  organizerNickname: '旅行者',
  partyCount: 1,
  personalBudget: '500',
  assistanceMode: 'ORDINARY',
}

test('planner local draft restores only its account and scope without storing credentials', () => {
  const storage = memoryStorage()
  const standard = plannerLocalDraftScope(null, null)
  const parentDay = plannerLocalDraftScope('11111111-1111-4111-8111-111111111111', 1)

  assert.equal(savePlannerLocalDraft(storage, 'account-a', standard, draft, new Date('2026-09-02T08:00:00Z')), true)
  assert.deepEqual(loadPlannerLocalDraft(storage, 'account-a', standard, new Date('2026-09-02T08:01:00Z')), {
    schemaVersion: 1,
    savedAt: '2026-09-02T08:00:00.000Z',
    ...draft,
  })
  assert.equal(loadPlannerLocalDraft(storage, 'account-b', standard, new Date('2026-09-02T08:01:00Z')), null)
  assert.equal(loadPlannerLocalDraft(storage, 'account-a', parentDay, new Date('2026-09-02T08:01:00Z')), null)

  const raw = storage.getItem(plannerLocalDraftKey('account-a', standard)) ?? ''
  assert.doesNotMatch(raw, /apiKey|organizerToken|invitationToken|password|cookie/i)
})

test('planner local draft removes only its own corrupt and expired entry', () => {
  const storage = memoryStorage()
  const standard = plannerLocalDraftScope(null, null)
  const other = plannerLocalDraftScope('22222222-2222-4222-8222-222222222222', 0)
  const key = plannerLocalDraftKey('account-a', standard)
  const otherKey = plannerLocalDraftKey('account-a', other)

  storage.setItem(key, '{not-json')
  storage.setItem(otherKey, JSON.stringify({ retained: true }))
  assert.equal(loadPlannerLocalDraft(storage, 'account-a', standard), null)
  assert.equal(storage.getItem(key), null)
  assert.equal(storage.getItem(otherKey), JSON.stringify({ retained: true }))

  assert.equal(savePlannerLocalDraft(storage, 'account-a', standard, draft, new Date('2026-07-01T08:00:00Z')), true)
  assert.equal(loadPlannerLocalDraft(storage, 'account-a', standard, new Date('2026-09-02T08:00:00Z')), null)
  assert.equal(storage.getItem(key), null)
  assert.equal(storage.getItem(otherKey), JSON.stringify({ retained: true }))
})

test('planner local draft clear affects only the requested account and scope', () => {
  const storage = memoryStorage()
  const standard = plannerLocalDraftScope(null, null)
  const otherAccountKey = plannerLocalDraftKey('account-b', standard)
  const ownKey = plannerLocalDraftKey('account-a', standard)
  savePlannerLocalDraft(storage, 'account-a', standard, draft)
  savePlannerLocalDraft(storage, 'account-b', standard, draft)

  clearPlannerLocalDraft(storage, 'account-a', standard)

  assert.equal(storage.getItem(ownKey), null)
  assert.ok(storage.getItem(otherAccountKey))
})

test('authoritative creation blocks an already queued local draft write until the user edits again', () => {
  const storage = memoryStorage()
  const scope = plannerLocalDraftScope(null, null)
  const gate = createPlannerLocalDraftWriteGate()
  const queuedWrite = () => {
    if (!gate.canPersist()) return false
    return savePlannerLocalDraft(storage, 'account-a', scope, draft)
  }

  gate.blockAfterAuthoritativeCreation()
  assert.equal(queuedWrite(), false)
  assert.equal(storage.getItem(plannerLocalDraftKey('account-a', scope)), null)

  gate.allowAfterUserEdit()
  assert.equal(queuedWrite(), true)
  assert.ok(storage.getItem(plannerLocalDraftKey('account-a', scope)))
})

test('a parent trip id without a valid day index uses the standard local draft scope', () => {
  assert.equal(
    plannerLocalDraftScope('11111111-1111-4111-8111-111111111111', null),
    'standard',
  )
})

test('fallback persistence writes the latest submitted answers even when a debounce would be cancelled', () => {
  const storage = memoryStorage()
  const scope = plannerLocalDraftScope(null, null)
  const gate = createPlannerLocalDraftWriteGate()
  const submittedDraft = {
    ...draft,
    answers: [...draft.answers.slice(0, 5), '模型不可用后仍需保留的最新限制'] as const,
  }

  assert.equal(persistPlannerFallbackDraft(storage, 'account-a', scope, submittedDraft, gate), true)
  assert.equal(
    loadPlannerLocalDraft(storage, 'account-a', scope)?.answers[5],
    '模型不可用后仍需保留的最新限制',
  )
})

test('unsafe parent day indexes cannot create a parent-day draft scope', () => {
  assert.equal(
    plannerLocalDraftScope('11111111-1111-4111-8111-111111111111', Number.MAX_SAFE_INTEGER + 1),
    'standard',
  )
})
