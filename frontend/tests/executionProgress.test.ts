import assert from 'node:assert/strict'
import test from 'node:test'

import {
  continueExecutionFromRestoredState,
  decideAndContinueExecution,
  executionEventIdempotencyKey,
  firstUnfinishedTaskIndex,
  plannedPlusFiftyYuan,
  sprint1SummaryView,
  submitTaskCompletionEvents,
} from '../src/services/executionReplan.ts'

const plan = {
  planId: 'plan-v1',
  days: [{
    tasks: [
      { taskId: 'task-1' },
      { taskId: 'task-2' },
      { taskId: 'task-3' },
    ],
  }],
}

const completedFirstTask = [
  { taskId: 'task-1', eventType: 'START' as const },
  { taskId: 'task-1', eventType: 'EXPENSE' as const },
  { taskId: 'task-1', eventType: 'COMPLETE' as const },
]

test('first unfinished task follows terminal server events', () => {
  assert.equal(firstUnfinishedTaskIndex(plan, completedFirstTask), 1)
  assert.equal(
    firstUnfinishedTaskIndex(plan, [
      ...completedFirstTask,
      { taskId: 'task-2', eventType: 'COMPLETE' },
    ]),
    2,
  )
  assert.equal(
    firstUnfinishedTaskIndex(plan, [
      ...completedFirstTask,
      { taskId: 'task-2', eventType: 'COMPLETE' },
      { taskId: 'task-3', eventType: 'SKIP' },
    ]),
    null,
  )
})

test('accept decision restores server V2 and starts its exact first unfinished task once', async () => {
  const acceptedPlan = { ...plan, planId: 'plan-v2' }
  const starts: Array<{ planId: string; taskIndex: number; taskId: string }> = []
  const sequence: string[] = []
  let rejectCount = 0
  let summaryCount = 0

  const result = await decideAndContinueExecution(
    'accept',
    'candidate-v2',
    {
      acceptPlan: async (candidatePlanId) => {
        sequence.push(`accept:${candidatePlanId}`)
      },
      rejectPlan: async () => { rejectCount += 1 },
      restoreTrip: async () => {
        sequence.push('restore')
        return { currentPlan: acceptedPlan, events: completedFirstTask }
      },
      applyRestoredState: (restored) => {
        sequence.push(`apply:${restored.currentPlan?.planId}`)
      },
      startTask: async (restoredPlan, taskIndex) => {
        sequence.push(`start:${restoredPlan.days[0].tasks[taskIndex].taskId}`)
        starts.push({
          planId: restoredPlan.planId,
          taskIndex,
          taskId: restoredPlan.days[0].tasks[taskIndex].taskId,
        })
      },
      showSummary: () => { summaryCount += 1 },
    },
  )

  assert.equal(result.nextTaskIndex, 1)
  assert.equal(result.adjustmentCount, 1)
  assert.deepEqual(sequence, ['accept:candidate-v2', 'restore', 'apply:plan-v2', 'start:task-2'])
  assert.equal(rejectCount, 0)
  assert.deepEqual(starts, [{ planId: 'plan-v2', taskIndex: 1, taskId: 'task-2' }])
  assert.equal(summaryCount, 0)
})

test('reject decision restores server V1 and starts its exact first unfinished task once', async () => {
  const starts: Array<{ planId: string; taskIndex: number; taskId: string }> = []
  const sequence: string[] = []
  let acceptCount = 0
  let summaryCount = 0

  const result = await decideAndContinueExecution(
    'reject',
    'candidate-v2',
    {
      acceptPlan: async () => { acceptCount += 1 },
      rejectPlan: async (candidatePlanId) => {
        sequence.push(`reject:${candidatePlanId}`)
      },
      restoreTrip: async () => {
        sequence.push('restore')
        return { currentPlan: plan, events: completedFirstTask }
      },
      applyRestoredState: (restored) => {
        sequence.push(`apply:${restored.currentPlan?.planId}`)
      },
      startTask: async (restoredPlan, taskIndex) => {
        sequence.push(`start:${restoredPlan.days[0].tasks[taskIndex].taskId}`)
        starts.push({
          planId: restoredPlan.planId,
          taskIndex,
          taskId: restoredPlan.days[0].tasks[taskIndex].taskId,
        })
      },
      showSummary: () => { summaryCount += 1 },
    },
  )

  assert.equal(result.nextTaskIndex, 1)
  assert.equal(result.adjustmentCount, 1)
  assert.deepEqual(sequence, ['reject:candidate-v2', 'restore', 'apply:plan-v1', 'start:task-2'])
  assert.equal(acceptCount, 0)
  assert.deepEqual(starts, [{ planId: 'plan-v1', taskIndex: 1, taskId: 'task-2' }])
  assert.equal(summaryCount, 0)
})

test('decision continuation shows Summary without START when all tasks are terminal', async () => {
  let startCount = 0
  let summaryCount = 0

  const result = await continueExecutionFromRestoredState(
    {
      currentPlan: plan,
      events: [
        ...completedFirstTask,
        { taskId: 'task-2', eventType: 'COMPLETE' },
        { taskId: 'task-3', eventType: 'SKIP' },
      ],
    },
    {
      startTask: async () => { startCount += 1 },
      showSummary: () => { summaryCount += 1 },
    },
  )

  assert.equal(result, null)
  assert.equal(startCount, 0)
  assert.equal(summaryCount, 1)
})

test('expense logical idempotency key is stable when amount changes', () => {
  assert.equal(
    executionEventIdempotencyKey('plan-1', 'task-1', 'EXPENSE', 1_000),
    'plan-1:task-1:EXPENSE',
  )
  assert.equal(
    executionEventIdempotencyKey('plan-1', 'task-1', 'EXPENSE', 6_000),
    'plan-1:task-1:EXPENSE',
  )
  assert.equal(
    executionEventIdempotencyKey('plan-1', 'task-1', 'COMPLETE'),
    'plan-1:task-1:COMPLETE',
  )
})

test('+¥50 changes only the input until completion submits EXPENSE then COMPLETE', async () => {
  const apiCalls: Array<{ eventType: string; amountCents: number | null }> = []
  let input = ''

  input = plannedPlusFiftyYuan(1_250)
  assert.equal(input, '62.5')
  assert.deepEqual(apiCalls, [])

  const actualCents = await submitTaskCompletionEvents(
    input,
    async (eventType, amountCents = null) => {
      apiCalls.push({ eventType, amountCents })
    },
  )

  assert.equal(actualCents, 6_250)
  assert.deepEqual(apiCalls, [
    { eventType: 'EXPENSE', amountCents: 6_250 },
    { eventType: 'COMPLETE', amountCents: null },
  ])
})

test('Sprint 1 Summary view uses server DTO numbers and exposes no future media actions', () => {
  const view = sprint1SummaryView(
    {
      tripId: 'trip-1',
      tripStatus: 'COMPLETED',
      plannedCostCents: 3_800,
      actualCostCents: 8_800,
      differenceCents: 5_000,
      completedTaskIds: ['task-1', 'task-2'],
      skippedTaskIds: [],
      totalTasks: 3,
      currentPlanVersion: 2,
      planHistory: [
        { planId: 'plan-v1', version: 1, status: 'SUPERSEDED', reason: 'INITIAL_PLAN' },
        { planId: 'plan-v2', version: 2, status: 'CURRENT', reason: 'EXPENSE_CHANGE' },
      ],
      events: [
        {
          schemaVersion: '1.0',
          eventId: 'event-1',
          tripId: 'trip-1',
          taskId: 'task-1',
          planVersionId: 'plan-v1',
          eventType: 'COMPLETE',
          idempotencyKey: 'plan-v1:task-1:COMPLETE',
          occurredAt: '2026-08-26T10:30:00+08:00',
        },
      ],
    },
    (cents) => `¥${(cents / 100).toFixed(2)}`,
  )

  assert.equal(view.completion.completed, 2)
  assert.equal(view.completion.total, 3)
  assert.ok(Math.abs(view.completion.progressPercent - (2 / 3) * 100) < Number.EPSILON)
  assert.deepEqual(view.cost, {
    actual: '¥88.00',
    detail: '计划 ¥38.00 · +¥50.00',
  })
  assert.equal(view.eventCount, 1)
  assert.deepEqual(view.version, { current: 'V2', historyCount: 2 })
  assert.deepEqual(view.visibleSections, ['metrics', 'history'])
  assert.deepEqual(view.actions, [])
  assert.doesNotMatch(JSON.stringify(view), /关怀满足率|100%|4 项硬约束|照片|视频|导出/)
})
