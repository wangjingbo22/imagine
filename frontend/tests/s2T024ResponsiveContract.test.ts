import assert from 'node:assert/strict'
import test from 'node:test'
import {
  S2_T024_GOLDEN_PHASES,
  S2_T024_MINIMUM_TARGET_PX,
  S2_T024_VIEWPORTS,
  S3_T001_VIEWPORTS,
  hasNoHorizontalOverflow,
  isPrimaryTargetReachable,
  isT024AcceptanceScope,
} from '../src/services/s2T024Acceptance.ts'

test('RESP-S2-001 freezes the 375px and 768px viewports', () => {
  assert.deepEqual(
    S2_T024_VIEWPORTS.map(({ id, width }) => ({ id, width })),
    [
      { id: 'RESP-S2-001-375', width: 375 },
      { id: 'RESP-S2-001-768', width: 768 },
    ],
  )
})

test('RESP-S3-001 adds the 1366px and 1440px release-candidate desktop gates', () => {
  assert.deepEqual(
    S3_T001_VIEWPORTS.map(({ width }) => width),
    [375, 768, 1366, 1440],
  )
})

test('the responsive contract allows a one-pixel rounding tolerance only', () => {
  assert.equal(hasNoHorizontalOverflow(375, 376), true)
  assert.equal(hasNoHorizontalOverflow(375, 377), false)
})

test('primary controls must be at least 44 by 44 CSS pixels', () => {
  assert.equal(S2_T024_MINIMUM_TARGET_PX, 44)
  assert.equal(isPrimaryTargetReachable(44, 44), true)
  assert.equal(isPrimaryTargetReachable(43.9, 44), false)
  assert.equal(isPrimaryTargetReachable(44, 43.9), false)
})

test('T024 keeps the required golden phases and does not claim T032', () => {
  assert.deepEqual(S2_T024_GOLDEN_PHASES, [
    'SIX_QUESTION_CONFIRMATION',
    'UNIQUE_RECOMMENDATION',
    'EXECUTION_AND_GPS',
    'TASK_PHOTO',
    'LATE_OR_FATIGUE_V2',
    'ORGANIZER_DECISION',
    'MEMORY_TIMELINE',
  ])
  assert.equal(isT024AcceptanceScope('S2-T024'), true)
  assert.equal(isT024AcceptanceScope('S2-T032'), false)
})
