import type {
  CandidateEndpointFact,
  CandidatePlanRequest,
  CandidatePlanningTrip,
  CandidateTaskFact,
  CreateSingleDayTrip,
  GeoPoint,
  Place,
  ProviderRoute,
} from '../domain/trip'
import { compileAssistanceConstraints } from './assistanceConstraints.ts'
import {
  calculateElapsedSinceRestMinutes,
  scheduleTaskRanges,
} from './restClock.ts'

function shortCategory(place: Place) {
  return (place.category?.split(/[;|]/)[0]?.trim() || '城市地点').slice(0, 80)
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
): CandidateTaskFact[] {
  return places.map((place, index) => {
    const route = routes[index]
    const priceKnown = place.priceReference.amountCents !== null &&
      route.priceReference.amountCents !== null
    return {
      taskId: place.placeId,
      order: orderOffset + index + 1,
      title: place.name,
      category: shortCategory(place),
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

function normalizedText(value: string) {
  return value.trim().replaceAll(/\s+/g, '').toLowerCase()
}

function validateCandidateFactChain(
  trip: CreateSingleDayTrip | CandidatePlanningTrip,
  startLocation: CandidateEndpointFact,
  endLocation: CandidateEndpointFact,
  places: Place[],
  routes: ProviderRoute[],
) {
  if (places.length < 3 || places.length > 4 || routes.length !== places.length) {
    throw new Error('候选计划必须包含 3—4 个地点及数量一致的逐段路线。')
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
}

export function buildCandidateRequestFromConfirmedTrip(
  confirmedTrip: CreateSingleDayTrip | CandidatePlanningTrip,
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
  const profile = confirmedTrip.participants[0].assistanceProfile ?? null
  const day = confirmedTrip.days[0]
  const ranges = scheduleTaskRanges(
    routes,
    day.timeWindow.start,
    day.timeWindow.end,
    profile?.napWindow ?? null,
    profile?.restInterval ?? null,
  )
  const elapsedSinceRestMinutes = calculateElapsedSinceRestMinutes(
    routes,
    ranges,
    day.timeWindow.start,
    profile?.napWindow ?? null,
  )
  const taskFacts = buildCandidateTaskFacts(
    places,
    routes,
    ranges,
    elapsedSinceRestMinutes,
    confirmedTrip.cityContext.cityCode,
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
    confirmedConstraints: profile ? compileAssistanceConstraints(profile) : [],
  }
}
