import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  createExpenseChangeReplanRequest,
  parseYuanAmountToCents,
} from '../src/services/executionReplan.ts'

test('expense-change replan request contains only the server event trigger contract', () => {
  const request = createExpenseChangeReplanRequest()

  assert.deepEqual(request, {
    schemaVersion: '1.0',
    reason: 'EXPENSE_CHANGE',
  })
  assert.deepEqual(Object.keys(request), ['schemaVersion', 'reason'])
})

test('yuan amount string is rounded to integer cents', () => {
  assert.equal(parseYuanAmountToCents('50.55'), 5_055)
  assert.equal(parseYuanAmountToCents(' 12.345 '), 1_235)
  assert.equal(parseYuanAmountToCents('0'), 0)
})

test('empty, negative, and non-finite yuan amounts are invalid', () => {
  assert.equal(parseYuanAmountToCents(''), null)
  assert.equal(parseYuanAmountToCents('   '), null)
  assert.equal(parseYuanAmountToCents('-0.01'), null)
  assert.equal(parseYuanAmountToCents('not-a-number'), null)
  assert.equal(parseYuanAmountToCents('NaN'), null)
  assert.equal(parseYuanAmountToCents('Infinity'), null)
})

test('trip API posts the exact event-replan payload without legacy candidate fields', async () => {
  const source = await readFile(
    new URL('../src/api/tripApi.ts', import.meta.url),
    'utf8',
  )
  const start = source.indexOf('replanFromEvents(')
  const end = source.indexOf('\n  suggestPlaces(', start)

  assert.notEqual(start, -1, 'tripApi.replanFromEvents must exist')
  assert.notEqual(end, -1, 'replanFromEvents must be defined before suggestPlaces')
  const method = source.slice(start, end)
  assert.match(method, /\/api\/v1\/trips\/\$\{tripId\}\/replans\/from-events/)
  assert.match(method, /body:\s*JSON\.stringify\(createExpenseChangeReplanRequest\(\)\)/)
  assert.doesNotMatch(method, /feedback|candidates|lockedTaskIds|taskFacts/)
})

test('Workspace uses server event replanning and deterministic adjustment controls', async () => {
  const source = await readFile(
    new URL('../src/pages/WorkspacePage.tsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /tripApi\.replanFromEvents\(tripId\)/)
  assert.match(source, /confirmExecutionAdjustment/)
  assert.doesNotMatch(source, /tripApi\.parseExecutionAdjustment/)
  assert.doesNotMatch(source, /buildAmapReplanCandidate/)
  assert.doesNotMatch(source, /tripApi\.selectReplan/)
  assert.doesNotMatch(source, /USER_FEEDBACK/)
})
