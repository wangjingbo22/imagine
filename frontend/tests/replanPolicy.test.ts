import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canRequestS1PlanV2,
  S1_REPLAN_LIMIT_MESSAGE,
} from '../src/services/replanPolicy.ts'

test('S1 permits the first V2 request only while V1 is current', () => {
  assert.equal(canRequestS1PlanV2(1, 0), true)
  assert.equal(canRequestS1PlanV2(null, 0), false)
})

test('S1 blocks another replan after a V2 decision or when V2 is current', () => {
  assert.equal(canRequestS1PlanV2(1, 1), false)
  assert.equal(canRequestS1PlanV2(2, 0), false)
  assert.match(S1_REPLAN_LIMIT_MESSAGE, /仅支持一次 V2/)
})
