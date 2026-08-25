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

export const MIN_REST_GAP_MINUTES = 30

export function secondsSinceMidnight(value: string) {
  const [hour, minute, second = 0] = value.split(':').map(Number)
  return hour * 3_600 + minute * 60 + second
}

function formatSecondPrecision(totalSeconds: number) {
  const normalized = Math.max(0, Math.min(24 * 3_600 - 1, totalSeconds))
  const hour = Math.floor(normalized / 3_600)
  const minute = Math.floor((normalized % 3_600) / 60)
  const second = normalized % 60
  return [hour, minute, second].map((value) => String(value).padStart(2, '0')).join(':')
}

export function calculateElapsedSinceRestMinutes(
  routes: RestClockRoute[],
  ranges: RestClockRange[],
  windowStart: string,
  napWindow: RestClockWindow | null,
  minimumRestGapMinutes = MIN_REST_GAP_MINUTES,
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
      // Count the whole conservative gap after the preceding activity.  We
      // know it contains a real rest but do not invent a more precise instant.
      lastRestAt = previousEnd
    }

    const routeMinutes = Math.ceil(routeSeconds / 60)
    const elapsed = Math.max(
      routeMinutes,
      Math.ceil((taskStart - lastRestAt) / 60),
    )
    previousEnd = taskEnd
    return elapsed
  })
}

export function scheduleTaskRanges(
  routes: RestClockRoute[],
  windowStart: string,
  windowEnd: string,
  napWindow: RestClockWindow | null,
  restIntervalMinutes: number | null,
  minimumRestGapMinutes = MIN_REST_GAP_MINUTES,
): RestClockRange[] {
  if (routes.length === 0) return []
  const startSeconds = secondsSinceMidnight(windowStart)
  const endSeconds = secondsSinceMidnight(windowEnd)
  const travelSeconds = routes.reduce((total, route) => total + route.durationSeconds, 0)
  const availableVisitSeconds = endSeconds - startSeconds - travelSeconds
  const initialVisitMinutes = Math.min(
    90,
    Math.max(5, Math.floor(availableVisitSeconds / routes.length / 60)),
  )
  const napStart = napWindow ? secondsSinceMidnight(napWindow.start) : null
  const napEnd = napWindow ? secondsSinceMidnight(napWindow.end) : null
  const minimumRestSeconds = minimumRestGapMinutes * 60

  for (let visitMinutes = initialVisitMinutes; visitMinutes >= 5; visitMinutes -= 1) {
    const visitSeconds = visitMinutes * 60
    const ranges: RestClockRange[] = []
    let cursor = startSeconds
    let lastRestAt = startSeconds
    let fits = true

    for (const route of routes) {
      let routeStart = cursor
      let taskStart = routeStart + route.durationSeconds
      let taskEnd = taskStart + visitSeconds

      if (
        napStart !== null &&
        napEnd !== null &&
        routeStart < napEnd &&
        taskEnd > napStart
      ) {
        routeStart = napEnd
        taskStart = routeStart + route.durationSeconds
        taskEnd = taskStart + visitSeconds
        lastRestAt = routeStart
      }

      let elapsedMinutes = Math.ceil((taskStart - lastRestAt) / 60)
      if (restIntervalMinutes !== null && elapsedMinutes > restIntervalMinutes) {
        routeStart = cursor + minimumRestSeconds
        taskStart = routeStart + route.durationSeconds
        taskEnd = taskStart + visitSeconds
        let resetByNap = false
        if (
          napStart !== null &&
          napEnd !== null &&
          routeStart < napEnd &&
          taskEnd > napStart
        ) {
          routeStart = napEnd
          taskStart = routeStart + route.durationSeconds
          taskEnd = taskStart + visitSeconds
          resetByNap = true
        }
        lastRestAt = resetByNap ? routeStart : cursor
        elapsedMinutes = Math.ceil((taskStart - lastRestAt) / 60)
      }

      if (taskEnd > endSeconds) {
        fits = false
        break
      }
      ranges.push({
        startAt: formatSecondPrecision(taskStart),
        endAt: formatSecondPrecision(taskEnd),
      })
      cursor = taskEnd
    }

    if (fits && ranges.length === routes.length) return ranges
  }

  throw new Error('高德路线无法完整放入已确认的单日时间窗，请延长时间或减少地点。')
}
