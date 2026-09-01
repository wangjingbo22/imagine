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
    [30, 165, 15, 30],
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
  assert.ok(ranges.every((range) => (
    /^\d{2}:\d{2}$/.test(range.startAt) && /^\d{2}:\d{2}$/.test(range.endAt)
  )))
})

test('scheduler anchors real lunch and dinner tasks while preserving the return route', () => {
  const routes = Array.from({ length: 6 }, () => ({ durationSeconds: 600 }))
  const ranges = scheduleTaskRanges(
    routes,
    '09:00',
    '20:00',
    null,
    null,
    [
      {},
      { fixedWindow: { start: '12:00', end: '13:00' }, resetsRestClock: true },
      {},
      {},
      { fixedWindow: { start: '18:00', end: '19:00' }, resetsRestClock: true },
      { durationMinutes: 5 },
    ],
  )

  assert.deepEqual(ranges[1], { startAt: '12:00', endAt: '13:00' })
  assert.deepEqual(ranges[4], { startAt: '18:00', endAt: '19:00' })
  assert.equal(
    secondsSinceMidnight(ranges[5].endAt) - secondsSinceMidnight(ranges[5].startAt),
    5 * 60,
  )
})

test('scheduler scales different attraction durations without crossing their minimums', () => {
  const routes = Array.from({ length: 4 }, () => ({ durationSeconds: 600 }))
  const ranges = scheduleTaskRanges(
    routes,
    '09:00',
    '12:00',
    null,
    null,
    [
      { preferredDurationMinutes: 40, minimumDurationMinutes: 20 },
      { preferredDurationMinutes: 75, minimumDurationMinutes: 40 },
      { preferredDurationMinutes: 60, minimumDurationMinutes: 30 },
      { durationMinutes: 5 },
    ],
  )
  const durations = ranges.map((range) => (
    secondsSinceMidnight(range.endAt) - secondsSinceMidnight(range.startAt)
  ) / 60)

  assert.ok(durations[0] >= 20 && durations[0] < 40)
  assert.ok(durations[1] >= 40 && durations[1] < 75)
  assert.ok(durations[2] >= 30 && durations[2] < 60)
  assert.ok(durations[1] > durations[0])
  assert.equal(durations[3], 5)
  assert.ok(secondsSinceMidnight(ranges.at(-1)!.endAt) <= secondsSinceMidnight('12:00'))
})

test('scheduler explains when distant places cannot fit inside the confirmed window', () => {
  assert.throws(
    () => scheduleTaskRanges(
      [{ durationSeconds: 10 * 60 * 60 }],
      '09:00',
      '18:00',
      null,
      null,
      [{ minimumDurationMinutes: 30, preferredDurationMinutes: 60 }],
    ),
    /地点之间路程较远，无法在 09:00–18:00 的规定时间内完成/,
  )
})
