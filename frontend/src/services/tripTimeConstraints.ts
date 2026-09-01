type TripSchedule = {
  date: string
  startTime: string
  endTime: string
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/
const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/

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
