import type {
  CandidateEndpointFact,
  CandidatePlanRequest,
  CandidatePlanningTrip,
  CandidateTaskFact,
  CreateDayTrip,
  CreateSingleDayTrip,
  GeoPoint,
  Place,
  ProviderRoute,
} from '../domain/trip'
import {
  compileGroupAssistanceConstraints,
  planningCareFromConstraints,
} from './assistanceConstraints.ts'
import {
  calculateElapsedSinceRestMinutes,
  scheduleTaskRanges,
  type RestClockTaskPreference,
} from './restClock.ts'
import {
  isDiningPlaceLike,
  isLodgingPlaceLike,
  requiredMealSlots,
  type MealSlot,
} from './itineraryPlaces.ts'

function shortCategory(place: Place) {
  return (place.category?.split(/[;|]/)[0]?.trim() || '城市地点').slice(0, 80)
}

function attractionDurationPreference(place: Place): RestClockTaskPreference {
  const text = `${place.name} ${place.category ?? ''}`.normalize('NFKC').toLowerCase()
  const isNestedAttraction = /[-\u2013\u2014\u00b7]/.test(place.name) &&
    /(公园|景区|风景|博物馆|名胜|古迹)/.test(text)
  if (isNestedAttraction) {
    return { preferredDurationMinutes: 40, minimumDurationMinutes: 20 }
  }
  if (/(博物馆|纪念馆|美术馆|科技馆|展览馆)/.test(text)) {
    return { preferredDurationMinutes: 75, minimumDurationMinutes: 40 }
  }
  if (/(公园|景区|风景区|名胜区|动物园|植物园|游乐园)/.test(text)) {
    return { preferredDurationMinutes: 60, minimumDurationMinutes: 30 }
  }
  if (/(寺|庙|宫|殿|塔|故居|古镇|历史街区|遗址)/.test(text)) {
    return { preferredDurationMinutes: 50, minimumDurationMinutes: 25 }
  }
  return { preferredDurationMinutes: 60, minimumDurationMinutes: 25 }
}

function taskNote(place: Place, priceKnown: boolean, feedback = '') {
  const address = place.address ? `地址：${place.address}` : '地址由高德地点 ID 核验'
  const priceNote = priceKnown
    ? '地点与交通参考价格均由 Provider 返回'
    : '仅累计 Provider 已返回的金额，未知价格仍需确认'
  const feedbackNote = feedback ? `；调整依据：${feedback}` : ''
  return `${address}；${priceNote}${feedbackNote}`.slice(0, 500)
}

export function buildCandidateTaskFacts(
  places: Place[],
  routes: ProviderRoute[],
  ranges: Array<{ startAt: string; endAt: string }>,
  elapsedSinceRestMinutes: number[],
  cityCode: string,
  orderOffset = 0,
  feedback = '',
  mealSlotByTaskIndex: ReadonlyMap<number, MealSlot> = new Map(),
): CandidateTaskFact[] {
  return places.map((place, index) => {
    const route = routes[index]
    const mealSlot = mealSlotByTaskIndex.get(index)
    const priceKnown = place.priceReference.amountCents !== null &&
      route.priceReference.amountCents !== null
    return {
      taskId: place.placeId,
      order: orderOffset + index + 1,
      title: mealSlot ? `${mealSlot.label} · ${place.name}` : place.name,
      category: mealSlot ? `MEAL_${mealSlot.kind}` : shortCategory(place),
      startAt: ranges[index].startAt,
      endAt: ranges[index].endAt,
      endLocationText: place.name,
      cityCode,
      place,
      route,
      elapsedSinceRestMinutes: elapsedSinceRestMinutes[index],
      note: taskNote(place, priceKnown, feedback),
    }
  })
}

function samePoint(left: GeoPoint, right: GeoPoint) {
  return left.longitude === right.longitude && left.latitude === right.latitude
}

export class CandidateScheduleError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'CandidateScheduleError'
  }
}

function normalizedText(value: string) {
  return value.trim().replaceAll(/\s+/g, '').toLowerCase()
}

function validateCandidateFactChain(
  trip: CreateDayTrip | CreateSingleDayTrip | CandidatePlanningTrip,
  startLocation: CandidateEndpointFact,
  endLocation: CandidateEndpointFact,
  places: Place[],
  routes: ProviderRoute[],
) {
  if (places.length < 3 || places.length > 6 || routes.length !== places.length) {
    throw new Error('候选计划必须包含 3—6 个地点及数量一致的逐段路线。')
  }
  const day = trip.days[0]
  if (
    normalizedText(startLocation.locationText) !== normalizedText(day.startLocationText) ||
    normalizedText(endLocation.locationText) !== normalizedText(day.endLocationText)
  ) {
    throw new Error('候选起终点必须复用 T004 已确认 Trip 的文本。')
  }
  if (
    startLocation.cityCode !== trip.cityContext.cityCode ||
    endLocation.cityCode !== trip.cityContext.cityCode
  ) {
    throw new Error('候选起终点必须位于 T004 已确认 Trip 的城市。')
  }
  let expectedOrigin = startLocation.location
  places.forEach((place, index) => {
    const route = routes[index]
    if (!samePoint(route.origin, expectedOrigin)) {
      throw new Error(`第 ${index + 1} 段路线未从已确认起点或上一地点出发。`)
    }
    if (!samePoint(route.destination, place.location)) {
      throw new Error(`第 ${index + 1} 段路线终点与对应地点不一致。`)
    }
    expectedOrigin = place.location
  })
  const returnPlace = places.at(-1)
  const returnRoute = routes.at(-1)
  if (
    !returnPlace ||
    normalizedText(returnPlace.name) !== normalizedText(endLocation.locationText) ||
    !samePoint(returnPlace.location, endLocation.location) ||
    !returnRoute ||
    !samePoint(returnRoute.destination, endLocation.location)
  ) {
    throw new Error('末项必须是返回 T004 已确认终点的独立任务。')
  }
  const lodgingTask = places.slice(0, -1).find((place) =>
    isLodgingPlaceLike(place.name, place.category),
  )
  if (lodgingTask) {
    throw new Error(`一日行程不能把酒店或住宿地点“${lodgingTask.name}”作为游览任务。`)
  }
}

export function buildCandidateRequestFromConfirmedTrip(
  confirmedTrip: CreateDayTrip | CreateSingleDayTrip | CandidatePlanningTrip,
  startLocation: CandidateEndpointFact,
  endLocation: CandidateEndpointFact,
  places: Place[],
  routes: ProviderRoute[],
): CandidatePlanRequest {
  validateCandidateFactChain(
    confirmedTrip,
    startLocation,
    endLocation,
    places,
    routes,
  )
  const confirmedConstraints = compileGroupAssistanceConstraints(
    confirmedTrip.participants.map((participant) => participant.assistanceProfile),
  )
  const care = planningCareFromConstraints(confirmedConstraints)
  const day = confirmedTrip.days[0]
  const mealSlots = requiredMealSlots(day.timeWindow.start, day.timeWindow.end)
  const diningTaskIndices = places.slice(0, -1).flatMap((place, index) =>
    isDiningPlaceLike(place.name, place.category) ? [index] : [],
  )
  if (diningTaskIndices.length < mealSlots.length) {
    throw new Error(
      `当前时间窗需要安排${mealSlots.map((slot) => slot.label).join('和')}，` +
      '但推荐方案缺少足够的高德餐饮地点。',
    )
  }
  const mealSlotByTaskIndex = new Map<number, MealSlot>()
  mealSlots.forEach((slot, index) => {
    mealSlotByTaskIndex.set(diningTaskIndices[index], slot)
  })
  const taskPreferences: RestClockTaskPreference[] = places.map((place, index) => {
    const mealSlot = mealSlotByTaskIndex.get(index)
    if (mealSlot) {
      return {
        fixedWindow: { start: mealSlot.start, end: mealSlot.end },
        resetsRestClock: true,
      }
    }
    if (index === places.length - 1) return { durationMinutes: 5 }
    return attractionDurationPreference(place)
  })
  const ranges = scheduleTaskRanges(
    routes,
    day.timeWindow.start,
    day.timeWindow.end,
    care.napWindow,
    care.restInterval,
    taskPreferences,
  )
  const mealTaskIndices = new Set(mealSlotByTaskIndex.keys())
  const elapsedSinceRestMinutes = calculateElapsedSinceRestMinutes(
    routes,
    ranges,
    day.timeWindow.start,
    care.napWindow,
    undefined,
    mealTaskIndices,
  )
  const taskFacts = buildCandidateTaskFacts(
    places,
    routes,
    ranges,
    elapsedSinceRestMinutes,
    confirmedTrip.cityContext.cityCode,
    0,
    '',
    mealSlotByTaskIndex,
  )
  const returnFact = taskFacts.at(-1)
  if (!returnFact) throw new Error('候选计划缺少已确认的返程任务。')
  taskFacts[taskFacts.length - 1] = {
    ...returnFact,
    title: `返回${endLocation.locationText}`.slice(0, 120),
    category: 'RETURN',
    note: `在已确认的截止时间前返回 ${endLocation.locationText}`.slice(0, 500),
  }
  const planningTrip: CandidatePlanningTrip = {
    ...confirmedTrip,
    status: 'PLANNING',
  }
  return {
    schemaVersion: '1.0',
    trip: planningTrip,
    startLocation,
    endLocation,
    taskFacts,
    confirmedConstraints,
  }
}

export function replaceCandidateSegmentRoute(
  baseRequest: CandidatePlanRequest,
  segmentIndex: number,
  replacementRoute: ProviderRoute,
): CandidatePlanRequest {
  if (!Number.isInteger(segmentIndex) || segmentIndex < 0 || segmentIndex >= baseRequest.taskFacts.length) {
    throw new RangeError('segment index is outside the candidate route facts')
  }
  const replacedFact = baseRequest.taskFacts[segmentIndex]
  if (!samePoint(replacementRoute.origin, replacedFact.route.origin)) {
    throw new Error('replacement route origin does not match the selected segment origin')
  }
  if (!samePoint(replacementRoute.destination, replacedFact.route.destination)) {
    throw new Error('replacement route destination does not match the selected segment destination')
  }

  const day = baseRequest.trip.days[0]
  const care = planningCareFromConstraints(baseRequest.confirmedConstraints)
  const suffixRoutes = baseRequest.taskFacts
    .slice(segmentIndex)
    .map((fact, index) => index === 0 ? replacementRoute : fact.route)
  let suffixRanges: Array<{ startAt: string; endAt: string }>
  try {
    suffixRanges = scheduleTaskRanges(
      suffixRoutes,
      segmentIndex === 0 ? day.timeWindow.start : baseRequest.taskFacts[segmentIndex - 1].endAt,
      day.timeWindow.end,
      care.napWindow,
      care.restInterval,
    )
  } catch (error) {
    throw new CandidateScheduleError(
      error instanceof Error ? error.message : 'replacement route cannot fit the confirmed day window',
    )
  }

  const provisionalFacts = baseRequest.taskFacts.map((fact, index) => {
    if (index < segmentIndex) return fact
    const suffixIndex = index - segmentIndex
    return {
      ...fact,
      route: suffixRoutes[suffixIndex],
      startAt: suffixRanges[suffixIndex].startAt,
      endAt: suffixRanges[suffixIndex].endAt,
    }
  })
  const elapsedSinceRestMinutes = calculateElapsedSinceRestMinutes(
    provisionalFacts.map((fact) => fact.route),
    provisionalFacts.map((fact) => ({ startAt: fact.startAt, endAt: fact.endAt })),
    day.timeWindow.start,
    care.napWindow,
  )
  const taskFacts = provisionalFacts.map((fact, index) => index < segmentIndex
    ? fact
    : { ...fact, elapsedSinceRestMinutes: elapsedSinceRestMinutes[index] })

  return { ...baseRequest, taskFacts }
}
