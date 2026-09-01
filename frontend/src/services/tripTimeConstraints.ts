type TripSchedule = {
  date: string
  startTime: string
  endTime: string
}

type TripDateRange = {
  startDate: string
  endDate: string
}

export type PlanningTimeWindow = {
  startTime: string
  endTime: string
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/
const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/
export const DEFAULT_PLANNING_START_TIME = '08:30'
export const DEFAULT_PLANNING_END_TIME = '21:00'

function twoDigits(value: number): string {
  return String(value).padStart(2, '0')
}

function timeMinutes(value: string): number | null {
  if (!TIME_PATTERN.test(value)) return null
  const [hours, minutes] = value.split(':').map(Number)
  return hours * 60 + minutes
}

export function localDateValue(value = new Date()): string {
  return `${value.getFullYear()}-${twoDigits(value.getMonth() + 1)}-${twoDigits(value.getDate())}`
}

export function localTimeValue(value = new Date()): string {
  return `${twoDigits(value.getHours())}:${twoDigits(value.getMinutes())}`
}

export function futureDateValue(value = new Date(), days = 1): string {
  const result = new Date(value.getFullYear(), value.getMonth(), value.getDate() + days)
  return localDateValue(result)
}

function dateValueAsUtcMilliseconds(value: string): number | null {
  if (!DATE_PATTERN.test(value)) return null
  const [year, month, day] = value.split('-').map(Number)
  const timestamp = Date.UTC(year, month - 1, day)
  const parsed = new Date(timestamp)
  if (
    parsed.getUTCFullYear() !== year
    || parsed.getUTCMonth() !== month - 1
    || parsed.getUTCDate() !== day
  ) return null
  return timestamp
}

export function tripDateRangeDayCount(range: TripDateRange): number | null {
  const start = dateValueAsUtcMilliseconds(range.startDate)
  const end = dateValueAsUtcMilliseconds(range.endDate)
  if (start === null || end === null || end < start) return null
  return Math.floor((end - start) / 86_400_000) + 1
}

export function validateTripDateRange(
  range: TripDateRange,
  now = new Date(),
  maximumDays = 30,
): string | null {
  if (!range.startDate || !range.endDate) return null
  if (dateValueAsUtcMilliseconds(range.startDate) === null) return '请选择有效的出发日期。'
  if (dateValueAsUtcMilliseconds(range.endDate) === null) return '请选择有效的结束日期。'
  if (range.startDate < localDateValue(now)) return '出发日期不能早于今天。'
  if (range.endDate < range.startDate) return '结束日期不能早于出发日期。'
  const dayCount = tripDateRangeDayCount(range)
  if (dayCount !== null && dayCount > maximumDays) {
    return `多日行程目前最多支持 ${maximumDays} 天。`
  }
  return null
}

function formatTimeMinutes(value: number): string {
  return `${twoDigits(Math.floor(value / 60))}:${twoDigits(value % 60)}`
}

/**
 * The questionnaire no longer asks for a daily time window. Future dates use
 * the product default; a same-day trip starts at the next available quarter
 * hour so it can never silently schedule tasks in the past.
 */
export function defaultPlanningTimeWindow(
  travelDate: string,
  now = new Date(),
): PlanningTimeWindow | null {
  if (travelDate !== localDateValue(now)) {
    return {
      startTime: DEFAULT_PLANNING_START_TIME,
      endTime: DEFAULT_PLANNING_END_TIME,
    }
  }
  const defaultStartMinutes = 8 * 60 + 30
  const defaultEndMinutes = 21 * 60
  const currentMinutes = now.getHours() * 60 + now.getMinutes()
  const nextMinute = currentMinutes + 1
  const nextQuarterHour = Math.ceil(nextMinute / 15) * 15
  const startMinutes = Math.max(defaultStartMinutes, nextQuarterHour)
  if (startMinutes >= defaultEndMinutes) return null
  return {
    startTime: formatTimeMinutes(startMinutes),
    endTime: DEFAULT_PLANNING_END_TIME,
  }
}

export function minimumStartTime(
  travelDate: string,
  now = new Date(),
): string | undefined {
  if (travelDate !== localDateValue(now)) return undefined
  const roundUp = now.getSeconds() > 0 || now.getMilliseconds() > 0 ? 1 : 0
  const minutes = Math.min(now.getHours() * 60 + now.getMinutes() + roundUp, 23 * 60 + 59)
  return `${twoDigits(Math.floor(minutes / 60))}:${twoDigits(minutes % 60)}`
}

export function validateFutureDate(
  travelDate: string,
  now = new Date(),
): string | null {
  if (!travelDate) return null
  if (!DATE_PATTERN.test(travelDate)) return '请选择有效的出行日期。'
  if (travelDate < localDateValue(now)) return '出行日期不能早于今天。'
  return null
}

export function validateTripSchedule(
  schedule: TripSchedule,
  now = new Date(),
): string | null {
  const dateError = validateFutureDate(schedule.date, now)
  if (dateError) return dateError

  const startMinutes = timeMinutes(schedule.startTime)
  const endMinutes = timeMinutes(schedule.endTime)
  if (schedule.startTime && startMinutes === null) return '请选择有效的开始时间。'
  if (schedule.endTime && endMinutes === null) return '请选择有效的结束时间。'

  if (
    schedule.date === localDateValue(now) &&
    startMinutes !== null
  ) {
    const start = new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate(),
      Math.floor(startMinutes / 60),
      startMinutes % 60,
    )
    if (start.getTime() <= now.getTime()) {
      return '今天的开始时间必须晚于当前时间。'
    }
  }

  if (startMinutes !== null && endMinutes !== null && endMinutes <= startMinutes) {
    return '结束时间必须晚于开始时间。'
  }
  return null
}
