import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canRequestS1PlanV2,
  executionAdjustmentBlockReason,
  S1_REPLAN_LIMIT_MESSAGE,
} from '../src/services/replanPolicy.ts'

test('S1 permits the first V2 request only while V1 is current', () => {
  assert.equal(canRequestS1PlanV2(1, 0), true)
  assert.equal(canRequestS1PlanV2(null, 0), false)
})

const executingV1 = {
  currentVersion: 1,
  completedV2Decisions: 0,
  hasPendingCandidate: false,
  hasCurrentTask: true,
  hasAdjustableSuffix: true,
  hasOrganizerToken: true,
}

test('adjustment entry closes after V2 acceptance or rejection, including refresh', () => {
  assert.equal(executionAdjustmentBlockReason(executingV1), null)
  assert.match(executionAdjustmentBlockReason({ ...executingV1, currentVersion: 2 })!, /正在执行 Plan V2/)
  assert.match(executionAdjustmentBlockReason({ ...executingV1, completedV2Decisions: 1 })!, /调整已处理/)
})

test('adjustment entry explains pending, unauthenticated and terminal states', () => {
  assert.match(executionAdjustmentBlockReason({ ...executingV1, hasPendingCandidate: true })!, /已有待确认/)
  assert.match(executionAdjustmentBlockReason({ ...executingV1, hasOrganizerToken: false })!, /没有组织者凭证/)
  assert.match(executionAdjustmentBlockReason({ ...executingV1, hasAdjustableSuffix: false })!, /最后一个任务/)
  assert.match(executionAdjustmentBlockReason({ ...executingV1, currentVersion: null })!, /恢复当前计划/)
})

test('S1 blocks another replan after a V2 decision or when V2 is current', () => {
  assert.equal(canRequestS1PlanV2(1, 1), false)
  assert.equal(canRequestS1PlanV2(2, 0), false)
  assert.match(S1_REPLAN_LIMIT_MESSAGE, /仅支持一次 V2/)
})
