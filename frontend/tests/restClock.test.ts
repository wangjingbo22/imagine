import assert from 'node:assert/strict'
import test from 'node:test'

import {
  calculateElapsedSinceRestMinutes,
  scheduleTaskRanges,
  secondsSinceMidnight,
} from '../src/services/restClock.ts'

test('elapsed clock accumulates activity time and resets at real rest boundaries', () => {
  const routes = [1_800, 600, 900, 1_800].map((durationSeconds) => ({ durationSeconds }))
  const ranges = [
    { startAt: '09:30:00', endAt: '11:30:00' },
    { startAt: '11:45:00', endAt: '12:45:00' },
    { startAt: '14:15:00', endAt: '16:00:00' },
    { startAt: '17:00:00', endAt: '18:00:00' },
  ]

  assert.deepEqual(
    calculateElapsedSinceRestMinutes(
      routes,
      ranges,
      '09:00:00',
      { start: '13:00:00', end: '14:00:00' },
    ),
    [30, 165, 15, 60],
  )
})

test('scheduler keeps activities outside nap time and inserts rests before the limit', () => {
  const routes = Array.from({ length: 4 }, () => ({ durationSeconds: 600 }))
  const napWindow = { start: '13:00:00', end: '14:00:00' }
  const ranges = scheduleTaskRanges(
    routes,
    '09:00:00',
    '20:00:00',
    napWindow,
    90,
  )
  const napStart = secondsSinceMidnight(napWindow.start)
  const napEnd = secondsSinceMidnight(napWindow.end)

  assert.equal(ranges.length, 4)
  assert.ok(ranges.every((range) => {
    const start = secondsSinceMidnight(range.startAt)
    const end = secondsSinceMidnight(range.endAt)
    return end <= napStart || start >= napEnd
  }))
  const elapsed = calculateElapsedSinceRestMinutes(
    routes,
    ranges,
    '09:00:00',
    napWindow,
  )
  assert.ok(elapsed.every((minutes) => minutes <= 90))
  assert.ok(elapsed.slice(1).some((minutes) => minutes === 10))
})
