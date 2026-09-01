import assert from 'node:assert/strict'
import test from 'node:test'

import {
  futureDateValue,
  localDateValue,
  localTimeValue,
  minimumStartTime,
  validateFutureDate,
  validateTripSchedule,
} from '../src/services/tripTimeConstraints.ts'

const NOW = new Date(2026, 8, 1, 14, 30, 20)

test('local date helpers do not use UTC date conversion', () => {
  assert.equal(localDateValue(NOW), '2026-09-01')
  assert.equal(localTimeValue(NOW), '14:30')
  assert.equal(futureDateValue(NOW), '2026-09-02')
  assert.equal(minimumStartTime('2026-09-01', NOW), '14:31')
  assert.equal(minimumStartTime('2026-09-02', NOW), undefined)
})

test('past dates and elapsed same-day start times are rejected', () => {
  assert.equal(validateFutureDate('2026-08-31', NOW), '出行日期不能早于今天。')
  assert.equal(validateTripSchedule({
    date: '2026-09-01',
    startTime: '14:30',
    endTime: '18:00',
  }, NOW), '今天的开始时间必须晚于当前时间。')
})

test('future windows pass and reversed windows fail', () => {
  assert.equal(validateTripSchedule({
    date: '2026-09-02',
    startTime: '09:00',
    endTime: '18:00',
  }, NOW), null)
  assert.equal(validateTripSchedule({
    date: '2026-09-02',
    startTime: '18:00',
    endTime: '09:00',
  }, NOW), '结束时间必须晚于开始时间。')
})
