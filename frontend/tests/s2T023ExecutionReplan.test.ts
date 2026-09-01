import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { ApiError } from '../src/api/client.ts'
import { tripApi } from '../src/api/tripApi.ts'
import type {
  ConfirmedExecutionAdjustmentEventInput,
  ExecutionAdjustmentReplanRequest,
  ExecutionEventDraft,
} from '../src/domain/executionAdjustment.ts'
import {
  buildConfirmedAdjustment,
  canConfirmAdjustmentDraft,
  createAdjustmentIdempotencyKey,
} from '../src/services/executionAdjustment.ts'

const lateDraft: ExecutionEventDraft = {
  schemaVersion: '1.0',
  eventType: 'LATE',
  taskId: 'task-museum',
  lateMinutes: 20,
  fatigueLevel: null,
  clarificationQuestions: [],
}

test('LATE and FATIGUE drafts become only the confirmed deterministic fields', () => {
  assert.equal(canConfirmAdjustmentDraft(lateDraft), true)
  assert.deepEqual(buildConfirmedAdjustment(lateDraft), {
    schemaVersion: '1.0',
    confirmationStatus: 'CONFIRMED',
    eventType: 'LATE',
    taskId: 'task-museum',
    lateMinutes: 20,
    fatigueLevel: null,
  })

  const fatigueDraft: ExecutionEventDraft = {
    ...lateDraft,
    eventType: 'FATIGUE',
    lateMinutes: null,
    fatigueLevel: null,
    clarificationQuestions: [
      {
        questionKey: 'FATIGUE_LEVEL_REQUIRED',
        prompt: '请确认当前疲劳程度。',
        options: ['MILD', 'MODERATE', 'SEVERE'],
      },
    ],
  }
  assert.equal(canConfirmAdjustmentDraft(fatigueDraft), false)
  assert.deepEqual(
    buildConfirmedAdjustment(fatigueDraft, { fatigueLevel: 'MODERATE' }),
    {
      schemaVersion: '1.0',
      confirmationStatus: 'CONFIRMED',
      eventType: 'FATIGUE',
      taskId: 'task-museum',
      lateMinutes: null,
      fatigueLevel: 'MODERATE',
    },
  )
})

test('adjustment idempotency key normalizes one instant and rejects a naive time', () => {
  const fromChinaTime = createAdjustmentIdempotencyKey(
    'plan-v1',
    'task-museum',
    'LATE',
    '2026-09-05T12:10:00+08:00',
  )
  const fromUtc = createAdjustmentIdempotencyKey(
    'plan-v1',
    'task-museum',
    'LATE',
    '2026-09-05T04:10:00Z',
  )

  assert.equal(fromChinaTime, fromUtc)
  assert.notEqual(
    fromChinaTime,
    createAdjustmentIdempotencyKey(
      'plan-v1',
      'task-museum',
      'FATIGUE',
      '2026-09-05T04:10:00Z',
    ),
  )
  assert.ok(fromChinaTime.length <= 160)
  assert.throws(
    () => createAdjustmentIdempotencyKey(
      'plan-v1',
      'task-museum',
      'LATE',
      '2026-09-05T12:10:00',
    ),
    /时区/,
  )
})

test('T023 calls parse, persistence, preview, and dedicated decision contracts', async (t) => {
  const originalFetch = globalThis.fetch
  t.after(() => {
    globalThis.fetch = originalFetch
  })

  const calls: Array<{ url: string; init: RequestInit }> = []
  globalThis.fetch = (async (input: string | URL | Request, init = {}) => {
    const url = String(input)
    calls.push({ url, init })
    if (url.endsWith('/api/v1/execution-adjustments/parse')) {
      return new Response(JSON.stringify(lateDraft), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'X-Recognition-Source': 'DEGRADED_FORM',
          'X-Degraded-Reason': 'BAILIAN_EXECUTION_DEADLINE_EXCEEDED',
        },
      })
    }

    return new Response(JSON.stringify({
      code: 200,
      message: 'ok',
      data: { acceptedByContractTest: true },
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }) as typeof fetch

  const organizerToken = 'organizer-capability'
  const parsed = await tripApi.parseExecutionAdjustment(
    {
      schemaVersion: '1.0',
      rawText: '晚了二十分钟',
      taskId: 'task-museum',
      currentTask: { taskId: 'task-museum', title: '参观博物馆' },
    },
    organizerToken,
  )
  assert.deepEqual(parsed, {
    draft: lateDraft,
    recognition: {
      source: 'DEGRADED_FORM',
      model: null,
      degradedReason: 'BAILIAN_EXECUTION_DEADLINE_EXCEEDED',
    },
  })

  const occurredAt = '2026-09-05T12:10:00+08:00'
  const adjustment = buildConfirmedAdjustment(parsed.draft)
  const persisted: ConfirmedExecutionAdjustmentEventInput = {
    ...adjustment,
    planVersionId: 'plan / v1',
    idempotencyKey: createAdjustmentIdempotencyKey(
      'plan / v1',
      adjustment.taskId,
      adjustment.eventType,
      occurredAt,
    ),
    occurredAt,
  }
  await tripApi.confirmExecutionAdjustment('trip / one', persisted, organizerToken)

  const preview: ExecutionAdjustmentReplanRequest = {
    schemaVersion: '1.0',
    adjustmentEventId: 'adjustment-event-1',
    adjustment,
    lockedTaskIds: ['task-locked'],
    explainDifferences: true,
  }
  await tripApi.previewExecutionReplan('trip / one', preview, organizerToken)
  await tripApi.decideExecutionReplan(
    'trip / one',
    'plan / v2',
    'ACCEPT',
    organizerToken,
  )

  assert.deepEqual(
    calls.map(({ url }) => new URL(url, 'http://local.test').pathname),
    [
      '/api/v1/execution-adjustments/parse',
      '/api/v1/execution-adjustments/trips/trip%20%2F%20one/events',
      '/api/v1/trips/trip%20%2F%20one/replans/from-adjustment',
      '/api/v1/trips/trip%20%2F%20one/replans/plan%20%2F%20v2/decision',
    ],
  )
  for (const { init } of calls) {
    const headers = new Headers(init.headers)
    assert.equal(headers.get('Content-Type'), 'application/json')
    assert.equal(headers.get('X-Organizer-Token'), organizerToken)
    assert.equal(init.method, 'POST')
  }
  assert.deepEqual(JSON.parse(String(calls[1].init.body)), persisted)
  assert.deepEqual(JSON.parse(String(calls[2].init.body)), preview)
  assert.deepEqual(JSON.parse(String(calls[3].init.body)), {
    schemaVersion: '1.0',
    decision: 'ACCEPT',
  })
})

test('event persistence exposes the backend idempotency conflict code', async (t) => {
  const originalFetch = globalThis.fetch
  t.after(() => {
    globalThis.fetch = originalFetch
  })
  globalThis.fetch = (async () => new Response(JSON.stringify({
    code: 'EVENT_IDEMPOTENCY_CONFLICT',
    message: '同一 idempotencyKey 对应的事件内容不一致',
  }), {
    status: 409,
    headers: { 'Content-Type': 'application/json' },
  })) as typeof fetch

  const input: ConfirmedExecutionAdjustmentEventInput = {
    ...buildConfirmedAdjustment(lateDraft),
    planVersionId: 'plan-v1',
    idempotencyKey: 's2-adjust:test',
    occurredAt: '2026-09-05T12:10:00+08:00',
  }
  await assert.rejects(
    tripApi.confirmExecutionAdjustment('trip-1', input, 'organizer-capability'),
    (error: unknown) => {
      assert.ok(error instanceof ApiError)
      assert.equal(error.code, 'EVENT_IDEMPOTENCY_CONFLICT')
      return true
    },
  )
})

test('Workspace uses direct deterministic Plan V2 controls and blocks an empty suffix', async () => {
  const source = await readFile(
    new URL('../src/pages/WorkspacePage.tsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /selectExecutionAdjustment\('LATE', minutes\)/)
  assert.match(source, /selectExecutionAdjustment\('FATIGUE', level\)/)
  assert.match(source, /aria-label="自定义迟到分钟数"/)
  assert.doesNotMatch(source, /tripApi\.parseExecutionAdjustment/)
  assert.doesNotMatch(source, /识别自定义描述/)
  assert.match(source, /hasAdjustableSuffix/)
  assert.match(source, /当前已经是最后一个任务，没有后续安排可生成 Plan V2/)
  assert.match(source, /describePlanV2Error\(error\)/)
})

test('facility evidence is grouped but remains individually correctable', async () => {
  const source = await readFile(
    new URL('../src/pages/WorkspacePage.tsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /facilityReviewGroups/)
  assert.match(source, /查看并逐段修正/)
  assert.match(source, /setReviewItems\(\[item\], 'PASS'\)/)
  assert.match(source, /completedReviewCount !== reviewItems\.length/)
})

test('V2 review separates actual changes from retained fields and blocks empty acceptance', async () => {
  const source = await readFile(new URL('../src/pages/WorkspacePage.tsx', import.meta.url), 'utf8')
  assert.match(source, /changedExecutionTasks/)
  assert.match(source, /休息与关怀安排/)
  assert.match(source, /item\.changeType !== 'RETAINED'/)
  assert.match(source, /<details className="plan-diff-retained">/)
  assert.match(source, /disabled=\{isDecidingV2 \|\| changedExecutionTasks\.length === 0\}/)
  assert.match(source, /REPLAN_ADJUSTMENT_NO_CHANGE/)
})
