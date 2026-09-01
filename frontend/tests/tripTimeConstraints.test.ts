import assert from 'node:assert/strict'
import test from 'node:test'

import {
  defaultPlanningTimeWindow,
  futureDateValue,
  localDateValue,
  localTimeValue,
  minimumStartTime,
  tripDateRangeDayCount,
  validateFutureDate,
  validateTripDateRange,
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

test('date ranges count inclusive days and reject invalid boundaries', () => {
  assert.equal(tripDateRangeDayCount({
    startDate: '2026-09-02',
    endDate: '2026-09-04',
  }), 3)
  assert.equal(validateTripDateRange({
    startDate: '2026-08-31',
    endDate: '2026-09-02',
  }, NOW), '出发日期不能早于今天。')
  assert.equal(validateTripDateRange({
    startDate: '2026-09-03',
    endDate: '2026-09-02',
  }, NOW), '结束日期不能早于出发日期。')
  assert.equal(validateTripDateRange({
    startDate: '2026-09-02',
    endDate: '2026-10-02',
  }, NOW), '多日行程目前最多支持 30 天。')
})

test('hidden planning window defaults to 08:30-21:00 and skips elapsed time', () => {
  assert.deepEqual(defaultPlanningTimeWindow('2026-09-02', NOW), {
    startTime: '08:30',
    endTime: '21:00',
  })
  assert.deepEqual(defaultPlanningTimeWindow('2026-09-01', NOW), {
    startTime: '14:45',
    endTime: '21:00',
  })
  assert.equal(
    defaultPlanningTimeWindow('2026-09-01', new Date(2026, 8, 1, 20, 59)),
    null,
  )
})
