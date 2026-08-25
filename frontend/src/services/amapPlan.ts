import { tripApi } from '../api/tripApi'
import type {
  CityResolution,
  GeoPoint,
  Place,
  PlanSnapshot,
  ProviderRoute,
  TravelMode,
  TripDraftInput,
} from '../domain/trip'

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
  knownCostCents: number
  unknownPriceCount: number
}

export interface AmapPlanOptions {
  extraQueries?: string[]
  excludePlaceIds?: string[]
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

function delay(milliseconds: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds))
}

async function providerCall<T>(operation: () => Promise<T>): Promise<T> {
  let lastError: unknown
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      const message = error instanceof Error ? error.message : String(error)
      if (!/CUQPS|QPS|EXCEEDED_THE_LIMIT/i.test(message) || attempt === 3) {
        throw error
      }
      await delay(450 * (attempt + 1))
    }
  }
  throw lastError
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
  query: string,
) {
  const response = await tripApi.searchPlaces(
    tripId,
    city.cityContext,
    query,
    [],
    1,
    8,
  )
  return response.data.places
}

async function collectPlaces(
  tripId: string,
  draft: TripDraftInput,
  city: CityResolution,
  options: AmapPlanOptions,
) {
  const requestedQueries = searchQueries(draft, options.extraQueries)
  const queries = requestedQueries.length > 0 ? requestedQueries : fallbackQueries.slice(0, 3)
  const fragments = avoidFragments(draft)
  const excludedIds = new Set(options.excludePlaceIds ?? [])
  const buckets: Place[][] = []
  const successfulQueries: string[] = []

  for (const query of queries) {
    try {
      const result = await providerCall(() => searchByQuery(tripId, city, query))
      buckets.push(result.filter(
        (place) => !excludedIds.has(place.placeId) && !isAvoided(place, fragments),
      ))
      successfulQueries.push(query)
      await delay(180)
    } catch {
      // Continue with successful same-city keyword buckets.
    }
  }

  for (const query of fallbackQueries) {
    if (buckets.flat().length >= 8 || successfulQueries.includes(query)) {
      continue
    }
    try {
      buckets.push(
        (await providerCall(() => searchByQuery(tripId, city, query))).filter(
          (place) => !excludedIds.has(place.placeId) && !isAvoided(place, fragments),
        ),
      )
      successfulQueries.push(query)
      await delay(180)
    } catch {
      // A single keyword failure must not turn successful Provider results into mock data.
    }
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

function orderByShortestNextSegment(places: Place[]) {
  if (places.length <= 2) return places
  const ordered = [places[0]]
  const remaining = places.slice(1)
  while (remaining.length > 0) {
    const origin = ordered[ordered.length - 1].location
    let nearestIndex = 0
    let nearestDistance = Number.POSITIVE_INFINITY
    remaining.forEach((place, index) => {
      const distance = directDistanceMeters(origin, place.location)
      if (distance < nearestDistance) {
        nearestDistance = distance
        nearestIndex = index
      }
    })
    ordered.push(remaining.splice(nearestIndex, 1)[0])
  }
  return ordered
}

function routeWalkingMeters(route: ProviderRoute) {
  if (route.walkingDistanceMeters !== null) return route.walkingDistanceMeters
  return route.mode === 'WALKING' ? route.distanceMeters : 0
}

async function requestFirstRoute(
  tripId: string,
  city: CityResolution,
  origin: GeoPoint,
  destination: GeoPoint,
  mode: TravelMode,
) {
  const response = await tripApi.planRoute(
    tripId,
    city.cityContext,
    origin,
    destination,
    mode,
  )
  const route = response.data.routes[0]
  if (!route) throw new Error(`高德未返回 ${mode} 路线`)
  return route
}

async function selectRoute(
  tripId: string,
  draft: TripDraftInput,
  city: CityResolution,
  origin: GeoPoint,
  destination: GeoPoint,
) {
  const maxWalk = Math.max(100, draft.assistanceProfile.maxSegmentWalkMeters)
  const directDistance = directDistanceMeters(origin, destination)
  const preferred: TravelMode = directDistance <= maxWalk * 0.8 ? 'WALKING' : 'TRANSIT'
  const attempts: TravelMode[] = unique([
    preferred,
    preferred === 'WALKING' ? 'TRANSIT' : 'DRIVING',
    'DRIVING',
    'WALKING',
  ]) as TravelMode[]
  let lastError: unknown
  for (const mode of attempts) {
    try {
      const route = await providerCall(
        () => requestFirstRoute(tripId, city, origin, destination, mode),
      )
      const walkMeters = routeWalkingMeters(route)
      const transfers = route.transferCount ?? 0
      if (
        mode !== 'DRIVING' &&
        (walkMeters > maxWalk || transfers > draft.assistanceProfile.maxTransfers)
      ) {
        continue
      }
      return route
    } catch (error) {
      lastError = error
    }
  }
  throw lastError instanceof Error ? lastError : new Error('高德没有返回满足关怀约束的路线')
}

function minutesSinceMidnight(value: string) {
  const [hour, minute] = value.split(':').map(Number)
  return hour * 60 + minute
}

function formatTime(totalMinutes: number) {
  const normalized = Math.max(0, Math.min(23 * 60 + 59, totalMinutes))
  return `${String(Math.floor(normalized / 60)).padStart(2, '0')}:${String(normalized % 60).padStart(2, '0')}`
}

function routeLabel(route: ProviderRoute) {
  const labels: Record<TravelMode, string> = {
    WALKING: '步行',
    TRANSIT: '公共交通',
    DRIVING: '驾车',
    BICYCLING: '骑行',
  }
  return `${labels[route.mode]} ${route.distanceMeters} 米 · ${Math.max(1, Math.round(route.durationSeconds / 60))} 分钟`
}

function shortCategory(place: Place) {
  return (place.category?.split(/[;|]/)[0]?.trim() || '城市地点').slice(0, 80)
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

function buildPlan(
  draft: TripDraftInput,
  city: CityResolution,
  places: Place[],
  routes: ProviderRoute[],
): AmapPlanResult['plan'] {
  const startMinutes = minutesSinceMidnight(draft.startTime)
  const endMinutes = minutesSinceMidnight(draft.endTime)
  const travelMinutes = routes.reduce(
    (total, route) => total + Math.max(1, Math.round(route.durationSeconds / 60)),
    0,
  )
  const visitMinutes = Math.max(
    45,
    Math.min(
      120,
      draft.assistanceProfile.restIntervalMinutes,
      Math.floor((endMinutes - startMinutes - travelMinutes - 30) / places.length),
    ),
  )
  const coordinates = normalizedCoordinates(places)
  let cursor = startMinutes
  let totalCostCents = 0
  let totalWalkMeters = 0
  let transferCount = 0

  const tasks = places.map((place, index) => {
    const route = routes[index]
    cursor += Math.max(1, Math.round(route.durationSeconds / 60))
    const taskStart = cursor
    const taskEnd = Math.min(endMinutes, taskStart + visitMinutes)
    cursor = taskEnd
    const knownCosts = [place.priceReference.amountCents, route.priceReference.amountCents]
      .filter((amount): amount is number => amount !== null)
    const costCents = knownCosts.reduce((total, amount) => total + amount, 0)
    const priceKnown = place.priceReference.amountCents !== null &&
      route.priceReference.amountCents !== null
    const walkMeters = routeWalkingMeters(route)
    totalCostCents += costCents
    totalWalkMeters += walkMeters
    transferCount += route.transferCount ?? 0
    const address = place.address ? `地址：${place.address}` : '地址由高德地点 ID 核验'
    const priceNote = priceKnown
      ? '地点与交通参考价格均由 Provider 返回'
      : '仅累计 Provider 已返回的金额，未知价格仍需确认'
    return {
      id: place.placeId,
      order: index + 1,
      title: place.name,
      category: shortCategory(place),
      timeRange: `${formatTime(taskStart)} — ${formatTime(taskEnd)}`,
      durationMinutes: Math.max(1, taskEnd - taskStart),
      transport: routeLabel(route),
      costCents,
      priceKnown,
      walkMeters,
      note: `${address}；${priceNote}`.slice(0, 500),
      status: index === 0 ? 'current' as const : 'upcoming' as const,
      coordinates: coordinates[index],
    }
  })

  return {
    id: crypto.randomUUID(),
    version: 1,
    cityName: city.cityContext.cityName,
    totalCostCents,
    bufferCents: Math.max(0, draft.budgetCents - totalCostCents),
    totalWalkMeters,
    transferCount,
    validationStatus: totalCostCents <= draft.budgetCents ? 'PASS' : 'FAIL',
    tasks,
  }
}

export async function loadAmapPlan(
  tripId: string,
  draft: TripDraftInput,
  onPhase?: (phase: AmapPlanningPhase, detail: string) => void,
  options: AmapPlanOptions = {},
): Promise<AmapPlanResult> {
  onPhase?.('CITY', `正在通过高德解析“${draft.cityName}”`)
  const city = (await providerCall(() => tripApi.resolveCity(draft.cityName))).data
  onPhase?.('PLACES', `已解析 cityCode ${city.cityContext.cityCode}，正在检索同城地点`)
  const collected = await collectPlaces(tripId, draft, city, options)
  const places = orderByShortestNextSegment(collected.places)
  const { queries } = collected
  onPhase?.('ROUTES', `已获得 ${places.length} 个真实地点，正在逐段规划路线`)

  const origins = [city.cityContext.center, ...places.slice(0, -1).map((place) => place.location)]
  const routes: ProviderRoute[] = []
  for (const [index, place] of places.entries()) {
    routes.push(await selectRoute(
      tripId,
      draft,
      city,
      origins[index],
      place.location,
    ))
    await delay(220)
  }
  onPhase?.('PLAN', `已获得 ${routes.length} 段高德路线，正在按时间窗生成计划`)
  const plan = buildPlan(draft, city, places, routes)
  const unknownPriceCount = places.reduce(
    (count, place, index) => count +
      Number(place.priceReference.amountCents === null) +
      Number(routes[index].priceReference.amountCents === null),
    0,
  )
  return {
    evidence: { city, places, routes, queries },
    plan,
    knownCostCents: plan.totalCostCents,
    unknownPriceCount,
  }
}
