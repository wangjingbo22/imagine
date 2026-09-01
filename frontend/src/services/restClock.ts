export interface RestClockRoute {
  durationSeconds: number
}

export interface RestClockRange {
  startAt: string
  endAt: string
}

export interface RestClockWindow {
  start: string
  end: string
}

export interface RestClockTaskPreference {
  durationMinutes?: number
  preferredDurationMinutes?: number
  minimumDurationMinutes?: number
  fixedWindow?: RestClockWindow
  resetsRestClock?: boolean
}

export const MIN_REST_GAP_MINUTES = 30

export function secondsSinceMidnight(value: string) {
  const [hour, minute, second = 0] = value.split(':').map(Number)
  return hour * 3_600 + minute * 60 + second
}

function formatMinutePrecision(totalSeconds: number) {
  const normalized = Math.max(0, Math.min(24 * 3_600 - 60, totalSeconds))
  const hour = Math.floor(normalized / 3_600)
  const minute = Math.floor((normalized % 3_600) / 60)
  return [hour, minute].map((value) => String(value).padStart(2, '0')).join(':')
}

function ceilToMinute(totalSeconds: number) {
  return Math.ceil(totalSeconds / 60) * 60
}

export function calculateElapsedSinceRestMinutes(
  routes: RestClockRoute[],
  ranges: RestClockRange[],
  windowStart: string,
  napWindow: RestClockWindow | null,
  minimumRestGapMinutes = MIN_REST_GAP_MINUTES,
  resetAfterTaskIndices: ReadonlySet<number> = new Set(),
) {
  if (routes.length !== ranges.length) {
    throw new Error('routes and ranges must have the same length')
  }
  const minimumRestSeconds = minimumRestGapMinutes * 60
  const napStart = napWindow ? secondsSinceMidnight(napWindow.start) : null
  const napEnd = napWindow ? secondsSinceMidnight(napWindow.end) : null
  let previousEnd = secondsSinceMidnight(windowStart)
  let lastRestAt = previousEnd

  return ranges.map((range, index) => {
    const routeSeconds = routes[index].durationSeconds
    const taskStart = secondsSinceMidnight(range.startAt)
    const taskEnd = secondsSinceMidnight(range.endAt)
    const routeStart = taskStart - routeSeconds
    if (routeStart < previousEnd || taskEnd <= taskStart) {
      throw new Error('task ranges must leave enough time for their preceding routes')
    }

    if (
      napStart !== null &&
      napEnd !== null &&
      previousEnd <= napStart &&
      routeStart >= napEnd
    ) {
      lastRestAt = napEnd
    } else if (routeStart - previousEnd >= minimumRestSeconds) {
      lastRestAt = routeStart
    }

    const routeMinutes = Math.ceil(routeSeconds / 60)
    const elapsed = Math.max(
      routeMinutes,
      Math.ceil((taskStart - lastRestAt) / 60),
    )
    previousEnd = taskEnd
    if (resetAfterTaskIndices.has(index)) lastRestAt = taskEnd
    return elapsed
  })
}

export function scheduleTaskRanges(
  routes: RestClockRoute[],
  windowStart: string,
  windowEnd: string,
  napWindow: RestClockWindow | null,
  restIntervalMinutes: number | null,
  taskPreferences: readonly RestClockTaskPreference[] = [],
  minimumRestGapMinutes = MIN_REST_GAP_MINUTES,
): RestClockRange[] {
  if (routes.length === 0) return []
  if (taskPreferences.length > routes.length) {
    throw new Error('task preferences cannot outnumber routes')
  }
  const startSeconds = secondsSinceMidnight(windowStart)
  const endSeconds = secondsSinceMidnight(windowEnd)
  const travelSeconds = routes.reduce((total, route) => total + route.durationSeconds, 0)
  const fixedVisitSeconds = routes.reduce((total, _route, index) => {
    const preference = taskPreferences[index]
    if (preference?.fixedWindow) {
      return total + secondsSinceMidnight(preference.fixedWindow.end) -
        secondsSinceMidnight(preference.fixedWindow.start)
    }
    return total + (preference?.durationMinutes ?? 0) * 60
  }, 0)
  const flexibleDurations = routes.map((_route, index) => {
    const preference = taskPreferences[index]
    if (preference?.fixedWindow || preference?.durationMinutes !== undefined) {
      return null
    }
    const preferred = Math.max(
      5,
      Math.floor(preference?.preferredDurationMinutes ?? 90),
    )
    const minimum = Math.min(
      preferred,
      Math.max(5, Math.floor(preference?.minimumDurationMinutes ?? 5)),
    )
    return { preferred, minimum }
  })
  const availableFlexibleMinutes = Math.floor(
    (endSeconds - startSeconds - travelSeconds - fixedVisitSeconds) / 60,
  )
  const minimumFlexibleMinutes = flexibleDurations.reduce(
    (total, duration) => total + (duration?.minimum ?? 0),
    0,
  )
  const shrinkableFlexibleMinutes = flexibleDurations.reduce(
    (total, duration) => total + (
      duration ? duration.preferred - duration.minimum : 0
    ),
    0,
  )
  const initialScalePercent = shrinkableFlexibleMinutes === 0
    ? 0
    : Math.max(
        0,
        Math.min(
          100,
          Math.floor(
            (availableFlexibleMinutes - minimumFlexibleMinutes) /
              shrinkableFlexibleMinutes * 100,
          ),
        ),
      )
  const napStart = napWindow ? secondsSinceMidnight(napWindow.start) : null
  const napEnd = napWindow ? secondsSinceMidnight(napWindow.end) : null
  const minimumRestSeconds = minimumRestGapMinutes * 60

  for (
    let scalePercent = initialScalePercent;
    scalePercent >= 0;
    scalePercent -= 1
  ) {
    const ranges: RestClockRange[] = []
    let cursor = startSeconds
    let lastRestAt = startSeconds
    let fits = true

    for (const [index, route] of routes.entries()) {
      const preference = taskPreferences[index]
      const fixedWindow = preference?.fixedWindow
      if (fixedWindow) {
        const taskStart = secondsSinceMidnight(fixedWindow.start)
        const taskEnd = secondsSinceMidnight(fixedWindow.end)
        const routeStart = taskStart - route.durationSeconds
        if (
          taskStart < startSeconds ||
          taskEnd > endSeconds ||
          taskEnd <= taskStart ||
          routeStart < cursor ||
          (
            napStart !== null &&
            napEnd !== null &&
            routeStart < napEnd &&
            taskEnd > napStart
          )
        ) {
          fits = false
          break
        }

        if (
          napStart !== null &&
          napEnd !== null &&
          cursor <= napStart &&
          routeStart >= napEnd
        ) {
          lastRestAt = napEnd
        } else if (routeStart - cursor >= minimumRestSeconds) {
          lastRestAt = routeStart
        }
        if (
          restIntervalMinutes !== null &&
          Math.ceil((taskStart - lastRestAt) / 60) > restIntervalMinutes
        ) {
          fits = false
          break
        }

        ranges.push({
          startAt: formatMinutePrecision(taskStart),
          endAt: formatMinutePrecision(taskEnd),
        })
        cursor = taskEnd
        if (preference.resetsRestClock) lastRestAt = taskEnd
        continue
      }

      const flexibleDuration = flexibleDurations[index]
      const visitMinutes = preference?.durationMinutes ?? (
        flexibleDuration
          ? flexibleDuration.minimum + Math.floor(
              (flexibleDuration.preferred - flexibleDuration.minimum) *
                scalePercent / 100,
            )
          : 5
      )
      const visitSeconds = visitMinutes * 60
      let routeStart = cursor
      let taskStart = ceilToMinute(routeStart + route.durationSeconds)
      let taskEnd = taskStart + visitSeconds

      if (
        napStart !== null &&
        napEnd !== null &&
        routeStart < napEnd &&
        taskEnd > napStart
      ) {
        routeStart = napEnd
        taskStart = ceilToMinute(routeStart + route.durationSeconds)
        taskEnd = taskStart + visitSeconds
        lastRestAt = routeStart
      }

      let elapsedMinutes = Math.ceil((taskStart - lastRestAt) / 60)
      if (restIntervalMinutes !== null && elapsedMinutes > restIntervalMinutes) {
        routeStart = cursor + minimumRestSeconds
        taskStart = ceilToMinute(routeStart + route.durationSeconds)
        taskEnd = taskStart + visitSeconds
        if (
          napStart !== null &&
          napEnd !== null &&
          routeStart < napEnd &&
          taskEnd > napStart
        ) {
          routeStart = napEnd
          taskStart = ceilToMinute(routeStart + route.durationSeconds)
          taskEnd = taskStart + visitSeconds
        }
        lastRestAt = routeStart
        elapsedMinutes = Math.ceil((taskStart - lastRestAt) / 60)
      }

      if (taskEnd > endSeconds) {
        fits = false
        break
      }
      ranges.push({
        startAt: formatMinutePrecision(taskStart),
        endAt: formatMinutePrecision(taskEnd),
      })
      cursor = taskEnd
      if (preference?.resetsRestClock) lastRestAt = taskEnd
    }

    if (fits && ranges.length === routes.length) return ranges
  }

  throw new Error(
    `地点之间路程较远，无法在 ${windowStart.slice(0, 5)}–${windowEnd.slice(0, 5)} ` +
    '的规定时间内完成。请延长出行时间、减少地点，或更换距离较近的地点。',
  )
}
