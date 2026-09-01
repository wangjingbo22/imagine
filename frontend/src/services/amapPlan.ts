import { tripApi } from '../api/tripApi'
import { ApiError } from '../api/client'
import type {
  AddressResolution,
  CandidateEndpointFact,
  CandidatePlanPreview,
  CandidatePlanReview,
  CandidatePlanRequest,
  CandidatePlanningTrip,
  CandidateTaskFact,
  CityContext,
  CityResolution,
  CreateDayTrip,
  CreateSingleDayTrip,
  GeoPoint,
  Place,
  PlanSnapshot,
  ProviderRoute,
  StoredPlanVersion,
  TravelMode,
  TripDraftInput,
} from '../domain/trip'
import {
  buildCandidateRequestFromConfirmedTrip,
  buildCandidateTaskFacts,
  CandidateScheduleError,
  replaceCandidateSegmentRoute,
} from './candidateRequestBuilder'
import {
  compileGroupAssistanceConstraints,
  planningCareFromConstraints,
  type GroupPlanningCare,
} from './assistanceConstraints'
import {
  calculateElapsedSinceRestMinutes,
  scheduleTaskRanges,
  secondsSinceMidnight,
} from './restClock'
import {
  hasCompleteRouteRiskFacts,
  routeWalkingMeters,
} from './routeRiskFacts'
import {
  appendConfirmedReturnPlace,
  selectedPlacesFromSignedFactSet,
  type ConfirmedRecommendationSelection,
} from './recommendationSelection'

export type AmapPlanningPhase = 'CITY' | 'PLACES' | 'ROUTES' | 'PLAN'

export interface LocationEvidence {
  city: CityResolution
  places: Place[]
  routes: ProviderRoute[]
  queries: string[]
}

export interface AmapPlanResult {
  evidence: LocationEvidence
  plan: PlanSnapshot
  candidateRequest: CandidatePlanRequest
  registeredPlan: StoredPlanVersion | null
  planningIssue: PlanningIssue | null
  knownCostCents: number
  unknownPriceCount: number
  recommendationTrace: ConfirmedRecommendationSelection | null
}

export interface PlanningIssue {
  code: string
  message: string
  review: CandidatePlanReview | null
}

export interface AmapReplanCandidateResult {
  evidence: LocationEvidence
  candidateRequest: CandidatePlanRequest
  plan: PlanSnapshot
  knownCostCents: number
  unknownPriceCount: number
}

export interface AmapSegmentReplacementResult {
  evidence: {
    segmentIndex: number
    route: ProviderRoute
  }
  candidateRequest: CandidatePlanRequest | null
  preview: CandidatePlanPreview
}

export interface AmapPlanOptions {
  extraQueries?: string[]
  excludePlaceIds?: string[]
  preferredMaxWalkMeters?: number
  confirmedTrip?: CreateDayTrip | CreateSingleDayTrip | CandidatePlanningTrip
  organizerToken?: string | null
  recommendationSelection?: ConfirmedRecommendationSelection
}

export interface AmapReplanOptions extends AmapPlanOptions {
  feedback: string
  lockedThroughIndex: number
}

const interestKeywords: Record<string, string> = {
  历史文化: '历史文化景点',
  特色餐饮: '特色餐饮',
  城市漫步: '历史街区',
  摄影: '摄影景点',
  自然风景: '公园景区',
  博物馆: '博物馆',
}

const fallbackQueries = ['旅游景点', '博物馆', '公园', '餐饮服务']
const planningRadiusMeters = 25_000
// The student's AMap quota is effectively one request per second. Keep every
// browser-driven Provider operation below that limit so non-cached cities do
// not fail while Beijing happens to succeed from cache.
const providerMinimumIntervalMs = 1_150
const inFlightPlans = new Map<string, InFlightPlan>()

type PhaseListener = (phase: AmapPlanningPhase, detail: string) => void

interface InFlightPlan {
  promise: Promise<AmapPlanResult>
  listeners: Set<PhaseListener>
  latestPhase: { phase: AmapPlanningPhase; detail: string } | null
}

let providerQueue: Promise<void> = Promise.resolve()
let lastProviderRequestAt = 0

function delay(milliseconds: number) {
  return new Promise<void>((resolve) => globalThis.setTimeout(resolve, milliseconds))
}

function scheduleProviderOperation<T>(operation: () => Promise<T>) {
  const scheduled = providerQueue.then(async () => {
    const waitMilliseconds = Math.max(
      0,
      providerMinimumIntervalMs - (Date.now() - lastProviderRequestAt),
    )
    if (waitMilliseconds > 0) {
      await delay(waitMilliseconds)
    }
    lastProviderRequestAt = Date.now()
    return operation()
  })
  providerQueue = scheduled.then(() => undefined, () => undefined)
  return scheduled
}

async function providerCall<T>(operation: () => Promise<T>): Promise<T> {
  // AmapClient owns provider retries. Retrying here would multiply every
  // provider operation and can turn one logical plan into fifteen requests.
  return scheduleProviderOperation(operation)
}

function unique(values: string[]) {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))]
}

function searchQueries(draft: TripDraftInput, extraQueries: string[] = []) {
  return unique([
    ...extraQueries,
    ...draft.mustVisit,
    ...draft.interests.map((interest) => interestKeywords[interest] ?? interest),
  ]).slice(0, 5)
}

function avoidFragments(draft: TripDraftInput) {
  return draft.avoidPlaces
    .flatMap((value) => value.split(/[，,、；;\s]+/))
    .map((value) => value.trim().toLowerCase())
    .filter((value) => value.length >= 2)
}

function isAvoided(place: Place, fragments: string[]) {
  const searchable = `${place.name} ${place.address ?? ''} ${place.category ?? ''}`.toLowerCase()
  return fragments.some((fragment) => searchable.includes(fragment))
}

function placeIdentity(place: Place) {
  return `${place.name.trim().toLowerCase()}|${place.address?.trim().toLowerCase() ?? ''}`
}

async function searchByQuery(
  tripId: string,
  city: CityResolution,
  center: GeoPoint,
  query: string,
  organizerToken?: string | null,
) {
  const response = await tripApi.searchNearbyPlaces(
    tripId,
    city.cityContext,
    center,
    { keywords: query },
    planningRadiusMeters,
    1,
    8,
    organizerToken,
  )
  return response.data.places
}

async function collectPlaces(
  tripId: string,
  draft: TripDraftInput,
  city: CityResolution,
  searchCenter: GeoPoint,
  options: AmapPlanOptions,
) {
  const requestedQueries = searchQueries(draft, options.extraQueries)
  const queries = requestedQueries.length > 0 ? requestedQueries : fallbackQueries.slice(0, 3)
  const fragments = avoidFragments(draft)
  const excludedIds = new Set(options.excludePlaceIds ?? [])
  const buckets: Place[][] = []
  const successfulQueries: string[] = []
  let lastSearchError: unknown

  for (const query of queries) {
    try {
      const result = await providerCall(() => searchByQuery(
        tripId,
        city,
        searchCenter,
        query,
        options.organizerToken,
      ))
      buckets.push(result.filter((place) =>
        directDistanceMeters(searchCenter, place.location) <= planningRadiusMeters &&
        !excludedIds.has(place.placeId) &&
        !isAvoided(place, fragments),
      ))
      successfulQueries.push(query)
      await delay(180)
    } catch (error) {
      lastSearchError = error
      // Continue with successful same-city keyword buckets.
    }
  }

  for (const query of fallbackQueries) {
    if (buckets.flat().length >= 8 || successfulQueries.includes(query)) {
      continue
    }
    try {
      buckets.push(
        (await providerCall(() => searchByQuery(
          tripId,
          city,
          searchCenter,
          query,
          options.organizerToken,
        ))).filter((place) =>
          directDistanceMeters(searchCenter, place.location) <= planningRadiusMeters &&
          !excludedIds.has(place.placeId) &&
          !isAvoided(place, fragments),
        ),
      )
      successfulQueries.push(query)
      await delay(180)
    } catch (error) {
      lastSearchError = error
      // A single keyword failure must not turn successful Provider results into mock data.
    }
  }

  if (successfulQueries.length === 0 && lastSearchError !== undefined) {
    throw lastSearchError
  }

  const selected: Place[] = []
  const seenIds = new Set<string>()
  const seenPlaces = new Set<string>()
  const maxBucketSize = Math.max(0, ...buckets.map((bucket) => bucket.length))
  for (let row = 0; row < maxBucketSize && selected.length < 4; row += 1) {
    for (const bucket of buckets) {
      const place = bucket[row]
      if (!place || seenIds.has(place.placeId) || seenPlaces.has(placeIdentity(place))) {
        continue
      }
      seenIds.add(place.placeId)
      seenPlaces.add(placeIdentity(place))
      selected.push(place)
      if (selected.length === 4) break
    }
  }

  if (selected.length < 3) {
    throw new Error(
      `高德仅返回 ${selected.length} 个可用且未命中避开条件的同城地点，至少需要 3 个才能生成真实计划。`,
    )
  }
  return { places: selected, queries: successfulQueries }
}

async function collectConfirmedRecommendationPlaces(
  tripId: string,
  city: CityResolution,
  selection: ConfirmedRecommendationSelection,
  organizerToken: string | null | undefined,
) {
  if (!organizerToken) {
    throw new Error('组织者凭证缺失，不能核验已确认的 FactRef 推荐。')
  }
  if (selection.tripId !== tripId) {
    throw new Error('已确认推荐不属于当前 Trip，请刷新后重新确认。')
  }
  const factSet = (
    await tripApi.getProviderFactSetPlaces(
      tripId,
      selection.factSetId,
      selection.providerFactDigest,
      organizerToken,
    )
  ).data
  const places = selectedPlacesFromSignedFactSet(factSet, selection)
  for (const place of places) {
    if (place.cityCode !== city.cityContext.cityCode) {
      throw new Error(`推荐地点 ${place.placeId} 与已确认城市不一致，请刷新后重新确认。`)
    }
  }
  return {
    places,
    queries: selection.selectedPlaces.map(
      (selected) => `FactRef ${selected.factRefId}`,
    ),
  }
}

function endpointFact(
  locationText: string,
  resolved: AddressResolution,
): CandidateEndpointFact {
  return {
    locationText,
    cityCode: resolved.cityCode,
    location: resolved.location,
    provenance: resolved.provenance,
  }
}

function returnEndpointPlace(
  locationText: string,
  resolved: AddressResolution,
): Place {
  const longitude = resolved.location.longitude.toFixed(6)
  const latitude = resolved.location.latitude.toFixed(6)
  return {
    placeId: `return-${resolved.cityCode}-${longitude}-${latitude}`,
    name: locationText,
    address: resolved.formattedAddress,
    cityCode: resolved.cityCode,
    adCode: resolved.adCode,
    location: resolved.location,
    category: 'RETURN',
    telephone: null,
    rating: null,
    priceReference: {
      amountCents: 0,
      currency: 'CNY',
      kind: 'return-place',
      provenance: resolved.provenance,
    },
    provenance: resolved.provenance,
  }
}

async function resolveConfirmedEndpoints(
  tripId: string,
  trip: CreateDayTrip | CreateSingleDayTrip | CandidatePlanningTrip,
  organizerToken?: string | null,
) {
  if (trip.tripId !== tripId) {
    throw new Error('已确认 Trip 与当前 tripId 不一致，必须重新确认行程。')
  }
  const day = trip.days[0]
  const start = (await providerCall(() => tripApi.forwardGeocode(
    tripId,
    trip.cityContext,
    day.startLocationText,
    organizerToken,
  ))).data
  const end = day.endLocationText.trim() === day.startLocationText.trim()
    ? start
    : (await providerCall(() => tripApi.forwardGeocode(
        tripId,
        trip.cityContext,
        day.endLocationText,
        organizerToken,
      ))).data
  if (
    start.cityCode !== trip.cityContext.cityCode ||
    end.cityCode !== trip.cityContext.cityCode
  ) {
    throw new Error('已确认起终点无法解析到 Trip 的同一城市，必须重新确认行程。')
  }
  return {
    startLocation: endpointFact(day.startLocationText, start),
    endLocation: endpointFact(day.endLocationText, end),
    returnPlace: returnEndpointPlace(day.endLocationText, end),
  }
}

function radians(value: number) {
  return value * Math.PI / 180
}

function directDistanceMeters(origin: GeoPoint, destination: GeoPoint) {
  const earthRadius = 6_371_000
  const latitudeDelta = radians(destination.latitude - origin.latitude)
  const longitudeDelta = radians(destination.longitude - origin.longitude)
  const originLatitude = radians(origin.latitude)
  const destinationLatitude = radians(destination.latitude)
  const a = Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(originLatitude) * Math.cos(destinationLatitude) *
    Math.sin(longitudeDelta / 2) ** 2
  return earthRadius * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

export const DEFAULT_WALK_LIMIT_METERS = 1_000

export function defaultModeForWalkingRoute(
  route: ProviderRoute,
  maxWalkMeters: number | null,
): 'WALKING' | 'DRIVING' {
  const careLimit = maxWalkMeters === null
    ? Number.POSITIVE_INFINITY
    : maxWalkMeters
  return route.mode === 'WALKING' &&
    route.distanceMeters <= DEFAULT_WALK_LIMIT_METERS &&
    route.distanceMeters <= careLimit
    ? 'WALKING'
    : 'DRIVING'
}

export function orderByShortestNextSegment(places: Place[], seed: GeoPoint) {
  const ordered: Place[] = []
  const remaining = [...places]
  let origin = seed
  while (remaining.length > 0) {
    let nearestIndex = 0
    let nearestDistance = Number.POSITIVE_INFINITY
    remaining.forEach((place, index) => {
      const distance = directDistanceMeters(origin, place.location)
      if (distance < nearestDistance) {
        nearestDistance = distance
        nearestIndex = index
      }
    })
    const nearest = remaining.splice(nearestIndex, 1)[0]
    ordered.push(nearest)
    origin = nearest.location
  }
  return ordered
}

async function requestFirstRoute(
  tripId: string,
  cityContext: CityContext,
  origin: GeoPoint,
  destination: GeoPoint,
  mode: TravelMode,
  organizerToken?: string | null,
) {
  const response = await tripApi.planRoute(
    tripId,
    cityContext,
    origin,
    destination,
    mode,
    null,
    organizerToken,
  )
  const route = response.data.routes[0]
  if (!route) throw new Error(`高德未返回 ${mode} 路线`)
  if (route.mode !== mode) {
    throw new Error(`高德为 ${mode} 请求返回了 ${route.mode} 路线`)
  }
  return route
}

export async function requestDefaultAmapRoute(
  tripId: string,
  city: CityResolution,
  origin: GeoPoint,
  destination: GeoPoint,
  maxWalkMeters: number | null,
  organizerToken?: string | null,
) {
  let walking: ProviderRoute | null = null
  try {
    walking = await providerCall(() => requestFirstRoute(
      tripId,
      city.cityContext,
      origin,
      destination,
      'WALKING',
      organizerToken,
    ))
  } catch {
    // A walking failure still permits the single explicit driving default request.
  }
  if (
    walking &&
    hasCompleteRouteRiskFacts(walking) &&
    defaultModeForWalkingRoute(walking, maxWalkMeters) === 'WALKING'
  ) {
    return walking
  }
  return providerCall(() => requestFirstRoute(
    tripId,
    city.cityContext,
    origin,
    destination,
    'DRIVING',
    organizerToken,
  ))
}

async function selectRoute(
  tripId: string,
  draft: TripDraftInput,
  city: CityResolution,
  origin: GeoPoint,
  destination: GeoPoint,
  confirmedCare: GroupPlanningCare | undefined,
  preferredMaxWalkMeters?: number,
  organizerToken?: string | null,
) {
  const maxWalkLimit = preferredMaxWalkMeters !== undefined
    ? preferredMaxWalkMeters
    : confirmedCare !== undefined
      ? confirmedCare.maxContinuousMeters
      : draft.assistanceProfile.maxSegmentWalkMeters
  return requestDefaultAmapRoute(
    tripId,
    city,
    origin,
    destination,
    maxWalkLimit,
    organizerToken,
  )
}

function routeLabel(route: ProviderRoute) {
  const labels: Record<TravelMode, string> = {
    WALKING: '步行',
    TRANSIT: '公共交通',
    DRIVING: '打车路线',
    BICYCLING: '骑行',
  }
  return `${labels[route.mode]} ${route.distanceMeters} 米 · ${Math.max(1, Math.round(route.durationSeconds / 60))} 分钟`
}

function normalizedCoordinates(places: Place[]): Array<[number, number]> {
  const longitudes = places.map((place) => place.location.longitude)
  const latitudes = places.map((place) => place.location.latitude)
  const minLongitude = Math.min(...longitudes)
  const maxLongitude = Math.max(...longitudes)
  const minLatitude = Math.min(...latitudes)
  const maxLatitude = Math.max(...latitudes)
  return places.map((place, index) => {
    const x = maxLongitude === minLongitude
      ? 20 + index * 20
      : 12 + (place.location.longitude - minLongitude) / (maxLongitude - minLongitude) * 76
    const y = maxLatitude === minLatitude
      ? 70 - index * 16
      : 82 - (place.location.latitude - minLatitude) / (maxLatitude - minLatitude) * 64
    return [Math.round(x), Math.round(y)]
  })
}


function previewFromCandidate(
  request: CandidatePlanRequest,
  version: 1 | 2,
  validationStatus: PlanSnapshot['validationStatus'] = 'NEEDS_CONFIRMATION',
): PlanSnapshot {
  const places = request.taskFacts.map((fact) => fact.place)
  const coordinates = normalizedCoordinates(places)
  let totalCostCents = 0
  let totalWalkMeters = 0
  let transferCount = 0
  const tasks = request.taskFacts.map((fact, index) => {
    const knownCosts = [
      fact.place.priceReference.amountCents,
      fact.route.priceReference.amountCents,
    ].filter((amount): amount is number => amount !== null)
    const costCents = knownCosts.reduce((total, amount) => total + amount, 0)
    const priceKnown = fact.place.priceReference.amountCents !== null &&
      fact.route.priceReference.amountCents !== null
    const walkMeters = routeWalkingMeters(fact.route)
    totalCostCents += costCents
    totalWalkMeters += walkMeters
    transferCount += fact.route.transferCount ?? 0
    return {
      id: fact.taskId,
      order: fact.order,
      title: fact.title,
      category: fact.category,
      timeRange: `${fact.startAt} — ${fact.endAt}`,
      durationMinutes: Math.ceil(
        (secondsSinceMidnight(fact.endAt) - secondsSinceMidnight(fact.startAt)) / 60,
      ),
      transport: routeLabel(fact.route),
      costCents,
      priceKnown,
      walkMeters,
      note: fact.note,
      status: index === 0 ? 'current' as const : 'upcoming' as const,
      coordinates: coordinates[index],
    }
  })
  return {
    id: `server-candidate-preview:${request.trip.tripId}:v${version}`,
    version,
    cityName: request.trip.cityContext.cityName,
    totalCostCents,
    bufferCents: Math.max(0, request.trip.totalBudgetCents - totalCostCents),
    totalWalkMeters,
    transferCount,
    validationStatus,
    tasks,
  }
}

function countUnknownPrices(request: CandidatePlanRequest) {
  return request.taskFacts.reduce(
    (count, fact) => count +
      Number(fact.place.priceReference.amountCents === null) +
      Number(fact.route.priceReference.amountCents === null),
    0,
  )
}

function elapsedForFacts(
  facts: CandidateTaskFact[],
  windowStart: string,
  napWindow: { start: string; end: string } | null,
) {
  return calculateElapsedSinceRestMinutes(
    facts.map((fact) => fact.route),
    facts.map((fact) => ({ startAt: fact.startAt, endAt: fact.endAt })),
    windowStart,
    napWindow,
  )
}

export function candidatePlanningIssue(error: unknown): PlanningIssue | null {
  if (!(error instanceof ApiError) || (
    error.code !== 'CANDIDATE_CONFIRMATION_REQUIRED' &&
    error.code !== 'CANDIDATE_PLAN_REJECTED'
  )) {
    return null
  }
  const detail = error.details[0]
  const review = detail?.review && typeof detail.review === 'object'
    ? detail.review as CandidatePlanReview
    : null
  return {
    code: String(error.code),
    message: error.code === 'CANDIDATE_CONFIRMATION_REQUIRED'
      ? '服务端发现价格、设施或来源证据仍为未知；补齐可信事实前不能确认该计划。'
      : `服务端硬约束校验未通过：${error.message}`,
    review,
  }
}

export async function acceptInitialCandidatePlan({
  validationStatus,
  persistedPlanId,
  issuePlan,
  confirmPlan,
  startExecution,
}: {
  validationStatus: PlanSnapshot['validationStatus']
  persistedPlanId: string | null
  issuePlan: () => Promise<StoredPlanVersion>
  confirmPlan: (planId: string) => Promise<unknown>
  startExecution: () => Promise<unknown>
}): Promise<
  | { kind: 'STARTED'; planId: string }
  | { kind: 'REVIEW_REQUIRED'; planningIssue: NonNullable<ReturnType<typeof candidatePlanningIssue>> }
> {
  if (validationStatus !== 'PASS' && validationStatus !== 'NEEDS_CONFIRMATION') {
    throw new Error('候选事实未通过服务端预览校验，当前计划不能确认。')
  }
  let planId = persistedPlanId
  if (!planId) {
    try {
      planId = (await issuePlan()).planId
    } catch (error) {
      const planningIssue = candidatePlanningIssue(error)
      if (planningIssue?.code === 'CANDIDATE_CONFIRMATION_REQUIRED') {
        return { kind: 'REVIEW_REQUIRED', planningIssue }
      }
      throw error
    }
  }
  await confirmPlan(planId)
  await startExecution()
  return { kind: 'STARTED', planId }
}

async function createAmapPlan(
  tripId: string,
  draft: TripDraftInput,
  onPhase?: (phase: AmapPlanningPhase, detail: string) => void,
  options: AmapPlanOptions = {},
): Promise<AmapPlanResult> {
  const confirmedTrip = options.confirmedTrip
  if (!confirmedTrip) {
    throw new Error('缺少 T004 已确认 Trip，不能在客户端猜测起点、终点或参与者。')
  }
  if (confirmedTrip.tripId !== tripId) {
    throw new Error('T004 已确认 Trip 与当前 tripId 不一致，请重新确认行程。')
  }
  onPhase?.('CITY', `正在通过高德解析“${confirmedTrip.cityContext.cityName}”及已确认起终点`)
  const providerCity = (await providerCall(
    () => tripApi.resolveCity(confirmedTrip.cityContext.cityName),
  )).data
  if (providerCity.cityContext.cityCode !== confirmedTrip.cityContext.cityCode) {
    throw new Error('Provider 城市解析与 T004 已确认 Trip 不一致，请重新确认行程。')
  }
  const city: CityResolution = {
    ...providerCity,
    cityContext: confirmedTrip.cityContext,
  }
  const endpoints = await resolveConfirmedEndpoints(
    tripId,
    confirmedTrip,
    options.organizerToken,
  )
  const selection = options.recommendationSelection
  onPhase?.(
    'PLACES',
    selection
      ? `正在核验已确认 FactRef 集合 ${selection.factSetId}`
      : `已解析 cityCode ${city.cityContext.cityCode}，正在检索同城地点并保留返程任务`,
  )
  const collected = selection
    ? await collectConfirmedRecommendationPlaces(
        tripId,
        city,
        selection,
        options.organizerToken,
      )
    : await collectPlaces(
        tripId,
        draft,
        city,
        endpoints.startLocation.location,
        options,
      )
  const intermediatePlaces = orderByShortestNextSegment(
    collected.places,
    endpoints.startLocation.location,
  ).slice(0, 3)
  const places = appendConfirmedReturnPlace(
    intermediatePlaces,
    endpoints.returnPlace,
  )
  const { queries } = collected
  onPhase?.('ROUTES', `已获得 ${places.length} 个真实地点，正在逐段规划路线`)
  const confirmedCare = planningCareFromConstraints(
    compileGroupAssistanceConstraints(
      confirmedTrip.participants.map((participant) => participant.assistanceProfile),
    ),
  )

  const origins = [
    endpoints.startLocation.location,
    ...places.slice(0, -1).map((place) => place.location),
  ]
  const routes: ProviderRoute[] = []
  for (const [index, place] of places.entries()) {
    routes.push(await selectRoute(
      tripId,
      draft,
      city,
      origins[index],
      place.location,
      confirmedCare,
      options.preferredMaxWalkMeters,
      options.organizerToken,
    ))
    await delay(220)
  }
  onPhase?.('PLAN', `已获得 ${routes.length} 段高德路线，正在按时间窗生成计划`)
  const candidateRequest = buildCandidateRequestFromConfirmedTrip(
    confirmedTrip,
    endpoints.startLocation,
    endpoints.endLocation,
    places,
    routes,
  )
  const candidatePreview = (await tripApi.previewCandidatePlan(
    tripId,
    candidateRequest,
    options.organizerToken,
  )).data
  const plan = previewFromCandidate(
    candidateRequest,
    1,
    candidatePreview.validationStatus,
  )
  const unknownPriceCount = countUnknownPrices(candidateRequest)
  return {
    evidence: {
      city,
      places,
      routes,
      queries: [...queries, confirmedTrip.days[0].endLocationText],
    },
    plan,
    candidateRequest,
    registeredPlan: null,
    planningIssue: null,
    knownCostCents: plan.totalCostCents,
    unknownPriceCount,
    recommendationTrace: selection ?? null,
  }
}

export async function buildAmapReplanCandidate(
  tripId: string,
  draft: TripDraftInput,
  baseRequest: CandidatePlanRequest,
  onPhase: ((phase: AmapPlanningPhase, detail: string) => void) | undefined,
  options: AmapReplanOptions,
): Promise<AmapReplanCandidateResult> {
  if (baseRequest.trip.tripId !== tripId) {
    throw new Error('原始候选事实与当前 tripId 不一致，不能生成 Plan V2。')
  }
  const baseFacts = baseRequest.taskFacts
  const confirmedCare = planningCareFromConstraints(
    baseRequest.confirmedConstraints,
  )
  const prefixLength = Math.max(
    0,
    Math.min(baseFacts.length, options.lockedThroughIndex + 1),
  )
  if (prefixLength >= baseFacts.length) {
    throw new Error('当前没有可调整的未完成任务。')
  }

  onPhase?.('CITY', `正在核验 ${baseRequest.trip.cityContext.cityName} 的重规划范围`)
  const resolvedCity = (await providerCall(
    () => tripApi.resolveCity(baseRequest.trip.cityContext.cityName),
  )).data
  if (resolvedCity.cityContext.cityCode !== baseRequest.trip.cityContext.cityCode) {
    throw new Error('重规划城市与不可变 Trip 快照不一致。')
  }
  const city: CityResolution = {
    ...resolvedCity,
    cityContext: baseRequest.trip.cityContext,
  }
  const finalFact = baseFacts.at(-1)
  if (!finalFact) throw new Error('原始候选事实缺少固定终点。')
  const replaceableCount = Math.max(0, baseFacts.length - prefixLength - 1)

  if (replaceableCount === 0) {
    const recalculatedElapsed = elapsedForFacts(
      baseFacts,
      baseRequest.trip.days[0].timeWindow.start,
      confirmedCare.napWindow,
    )
    const taskFacts = baseFacts.map((fact, index) => index === baseFacts.length - 1
      ? {
          ...fact,
          elapsedSinceRestMinutes: recalculatedElapsed[index],
          note: `${fact.note}；调整依据：${options.feedback}`.slice(0, 500),
        }
      : fact)
    const candidateRequest: CandidatePlanRequest = {
      ...baseRequest,
      taskFacts,
    }
    return {
      evidence: {
        city,
        places: [finalFact.place],
        routes: [finalFact.route],
        queries: [],
      },
      candidateRequest,
      plan: previewFromCandidate(candidateRequest, 2),
      knownCostCents: previewFromCandidate(candidateRequest, 2).totalCostCents,
      unknownPriceCount: countUnknownPrices(candidateRequest),
    }
  }

  onPhase?.('PLACES', '正在检索替代地点，并固定复用 Plan V1 的最终目的地')
  const previousFact = prefixLength > 0 ? baseFacts[prefixLength - 1] : null
  const collected = await collectPlaces(
    tripId,
    draft,
    city,
    previousFact?.place.location ?? baseRequest.startLocation.location,
    {
      extraQueries: options.extraQueries,
      organizerToken: options.organizerToken,
      excludePlaceIds: [
        ...baseFacts.map((fact) => fact.place.placeId),
        ...(options.excludePlaceIds ?? []),
      ],
    },
  )
  const replacementPlaces = orderByShortestNextSegment(
    collected.places,
    previousFact?.place.location ?? baseRequest.startLocation.location,
  )
    .slice(0, replaceableCount)
  if (replacementPlaces.length < replaceableCount) {
    throw new Error('高德没有返回足够的新地点，未生成 Plan V2。')
  }
  const suffixPlaces = [...replacementPlaces, finalFact.place]
  let origin = previousFact?.place.location ?? baseRequest.startLocation.location
  const suffixRoutes: ProviderRoute[] = []
  onPhase?.('ROUTES', `正在生成 ${suffixPlaces.length} 段连续路线并回到固定终点`)
  for (const place of suffixPlaces) {
    suffixRoutes.push(await selectRoute(
      tripId,
      draft,
      city,
      origin,
      place.location,
      confirmedCare,
      options.preferredMaxWalkMeters,
      options.organizerToken,
    ))
    origin = place.location
    await delay(220)
  }
  const day = baseRequest.trip.days[0]
  const suffixRanges = scheduleTaskRanges(
    suffixRoutes,
    previousFact?.endAt ?? day.timeWindow.start,
    day.timeWindow.end,
    confirmedCare.napWindow,
    confirmedCare.restInterval,
  )
  const provisionalSuffixFacts = buildCandidateTaskFacts(
    suffixPlaces,
    suffixRoutes,
    suffixRanges,
    suffixRoutes.map((route) => Math.ceil(route.durationSeconds / 60)),
    baseRequest.trip.cityContext.cityCode,
    prefixLength,
    options.feedback,
  )
  const returnFactIndex = provisionalSuffixFacts.length - 1
  provisionalSuffixFacts[returnFactIndex] = {
    ...provisionalSuffixFacts[returnFactIndex],
    title: finalFact.title,
    category: finalFact.category,
    note: `${finalFact.note}；调整依据：${options.feedback}`.slice(0, 500),
  }
  const provisionalFacts = [
    ...baseFacts.slice(0, prefixLength),
    ...provisionalSuffixFacts,
  ]
  const recalculatedElapsed = elapsedForFacts(
    provisionalFacts,
    day.timeWindow.start,
    confirmedCare.napWindow,
  )
  const taskFacts = provisionalFacts.map((fact, index) => index < prefixLength
    ? fact
    : { ...fact, elapsedSinceRestMinutes: recalculatedElapsed[index] })
  const candidateRequest: CandidatePlanRequest = {
    ...baseRequest,
    taskFacts,
  }
  const plan = previewFromCandidate(candidateRequest, 2)
  onPhase?.('PLAN', '候选事实已完成，等待服务端 T011 与 T018 选择')
  return {
    evidence: {
      city,
      places: suffixPlaces,
      routes: suffixRoutes,
      queries: collected.queries,
    },
    candidateRequest,
    plan,
    knownCostCents: plan.totalCostCents,
    unknownPriceCount: countUnknownPrices(candidateRequest),
  }
}

function localScheduleFailurePreview(
  segmentIndex: number,
  route: ProviderRoute,
  message: string,
): CandidatePlanPreview {
  return {
    schemaVersion: '1.0',
    validationStatus: 'FAIL',
    metrics: null,
    constraintResults: [{
      ruleId: 'local.day-window',
      scope: 'DAY:0',
      hardness: 'HARD',
      status: 'FAIL',
      referenceId: route.routeId,
      observed: {
        segmentIndex,
        routeId: route.routeId,
        mode: route.mode,
        durationSeconds: route.durationSeconds,
      },
      suggestion: message,
    }],
    warnings: [],
  }
}

export async function replaceAmapPlanSegment(
  tripId: string,
  baseRequest: CandidatePlanRequest,
  segmentIndex: number,
  mode: TravelMode,
  organizerToken?: string | null,
): Promise<AmapSegmentReplacementResult> {
  if (baseRequest.trip.tripId !== tripId) {
    throw new Error('candidate facts do not belong to the requested trip')
  }
  if (!Number.isInteger(segmentIndex) || segmentIndex < 0 || segmentIndex >= baseRequest.taskFacts.length) {
    throw new RangeError('segment index is outside the candidate route facts')
  }
  const selectedFact = baseRequest.taskFacts[segmentIndex]
  const route = await providerCall(() => requestFirstRoute(
    tripId,
    baseRequest.trip.cityContext,
    selectedFact.route.origin,
    selectedFact.route.destination,
    mode,
    organizerToken,
  ))

  const evidence = { segmentIndex, route }
  let candidateRequest: CandidatePlanRequest
  try {
    candidateRequest = replaceCandidateSegmentRoute(baseRequest, segmentIndex, route)
  } catch (error) {
    if (!(error instanceof CandidateScheduleError)) throw error
    return {
      evidence,
      candidateRequest: null,
      preview: localScheduleFailurePreview(segmentIndex, route, error.message),
    }
  }
  const preview = (await tripApi.previewCandidatePlan(
    tripId,
    candidateRequest,
    organizerToken,
  )).data
  return { evidence, candidateRequest, preview }
}

function planRequestKey(
  tripId: string,
  draft: TripDraftInput,
  options: AmapPlanOptions,
) {
  return JSON.stringify({
    tripId,
    draft,
    extraQueries: options.extraQueries ?? [],
    excludePlaceIds: options.excludePlaceIds ?? [],
    preferredMaxWalkMeters: options.preferredMaxWalkMeters ?? null,
    confirmedTrip: options.confirmedTrip ?? null,
    recommendationSelection: options.recommendationSelection ?? null,
  })
}

export function loadAmapPlan(
  tripId: string,
  draft: TripDraftInput,
  onPhase?: PhaseListener,
  options: AmapPlanOptions = {},
): Promise<AmapPlanResult> {
  const key = planRequestKey(tripId, draft, options)
  const existing = inFlightPlans.get(key)
  if (existing) {
    if (onPhase) {
      existing.listeners.add(onPhase)
      if (existing.latestPhase) {
        onPhase(existing.latestPhase.phase, existing.latestPhase.detail)
      }
    }
    return existing.promise
  }

  const listeners = new Set<PhaseListener>()
  if (onPhase) listeners.add(onPhase)
  let latestPhase: InFlightPlan['latestPhase'] = null
  const emitPhase: PhaseListener = (phase, detail) => {
    latestPhase = { phase, detail }
    for (const listener of listeners) listener(phase, detail)
  }
  const promise = createAmapPlan(tripId, draft, emitPhase, options)
  const entry: InFlightPlan = {
    promise,
    listeners,
    get latestPhase() {
      return latestPhase
    },
    set latestPhase(value) {
      latestPhase = value
    },
  }
  inFlightPlans.set(key, entry)
  const removeCompletedEntry = () => {
    if (inFlightPlans.get(key)?.promise === promise) {
      inFlightPlans.delete(key)
    }
  }
  void promise.then(removeCompletedEntry, removeCompletedEntry)
  return promise
}
