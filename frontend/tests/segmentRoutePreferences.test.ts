import assert from 'node:assert/strict'
import test from 'node:test'

import { ApiError } from '../src/api/client.ts'
import type {
  CandidateEndpointFact,
  CandidatePlanPreview,
  CandidatePlanRequest,
  CityResolution,
  CreateSingleDayTrip,
  GeoPoint,
  Place,
  ProviderRoute,
  TravelMode,
} from '../src/domain/trip.ts'
import {
  orderByShortestNextSegment,
  replaceAmapPlanSegment,
  requestDefaultAmapRoute,
} from '../src/services/amapPlan.ts'
import { buildCandidateRequestFromConfirmedTrip } from '../src/services/candidateRequestBuilder.ts'

const provenance = {
  provider: 'AMAP' as const,
  sourceStatus: 'ONLINE' as const,
  fetchedAt: '2026-09-02T09:00:00+08:00',
  isStale: false,
}

function route(
  routeId: string,
  origin: GeoPoint,
  destination: GeoPoint,
  mode: TravelMode = 'WALKING',
  durationSeconds = 600,
  distanceMeters = 500,
): ProviderRoute {
  return {
    routeId,
    mode,
    origin,
    destination,
    distanceMeters,
    durationSeconds,
    walkingDistanceMeters: mode === 'TRANSIT' ? 100 : null,
    transferCount: mode === 'TRANSIT' ? 1 : null,
    steps: [],
    facilityEvidence: [],
    priceReference: {
      amountCents: mode === 'WALKING' || mode === 'BICYCLING' ? 0 : 1_500,
      currency: 'CNY',
      kind: mode,
      provenance,
    },
    provenance,
  }
}

function place(placeId: string, location: GeoPoint, category = '景点'): Place {
  return {
    placeId,
    name: placeId,
    address: `${placeId}地址`,
    cityCode: '110100',
    adCode: '110101',
    location,
    category,
    telephone: null,
    rating: null,
    priceReference: {
      amountCents: 0,
      currency: 'CNY',
      kind: category === 'RETURN' ? 'return-place' : 'admission',
      provenance,
    },
    provenance,
  }
}

function fixture(): { base: CandidatePlanRequest; city: CityResolution } {
  const points: GeoPoint[] = [
    { longitude: 116.30, latitude: 39.90 },
    { longitude: 116.31, latitude: 39.91 },
    { longitude: 116.32, latitude: 39.92 },
    { longitude: 116.33, latitude: 39.93 },
    { longitude: 116.34, latitude: 39.94 },
  ]
  const trip: CreateSingleDayTrip = {
    schemaVersion: '1.0',
    tripId: '11111111-1111-4111-8111-111111111111',
    mode: 'SINGLE',
    status: 'DRAFT',
    cityContext: {
      countryCode: 'CN',
      cityCode: '110100',
      cityName: '北京市',
      center: points[0],
      providerConfig: { provider: 'AMAP', coordinateSystem: 'GCJ02' },
    },
    startDate: '2026-09-02',
    endDate: '2026-09-02',
    currency: 'CNY',
    totalBudgetCents: 50_000,
    participants: [{
      participantId: '22222222-2222-4222-8222-222222222222',
      nickname: '测试用户',
      budgetCapCents: 50_000,
      assistanceProfile: {
        type: 'LOW_STAMINA',
        childAge: null,
        walkLimits: { maxContinuousMeters: 1_000, maxDailyMeters: 5_000 },
        maxTransfers: 2,
        restInterval: 90,
        napWindow: null,
        avoidStairs: false,
      },
    }],
    days: [{
      dayIndex: 0,
      date: '2026-09-02',
      dailyBudgetCents: 45_000,
      startLocationText: '确认起点',
      endLocationText: '确认终点',
      timeWindow: { start: '09:00:00', end: '20:00:00' },
    }],
  }
  const startLocation: CandidateEndpointFact = {
    locationText: '确认起点', cityCode: '110100', location: points[0], provenance,
  }
  const endLocation: CandidateEndpointFact = {
    locationText: '确认终点', cityCode: '110100', location: points[4], provenance,
  }
  const places = [
    place('poi-1', points[1]),
    place('poi-2', points[2]),
    place('poi-3', points[3]),
    { ...place('return-home', points[4], 'RETURN'), name: '确认终点' },
  ]
  const routes = places.map((item, index) => route(
    `route-${index + 1}`,
    index === 0 ? points[0] : places[index - 1].location,
    item.location,
  ))
  return {
    base: buildCandidateRequestFromConfirmedTrip(
      trip, startLocation, endLocation, places, routes,
    ),
    city: {
      cityContext: trip.cityContext,
      provenance,
    },
  }
}

function ok<T>(data: T) {
  return new Response(JSON.stringify({ code: 200, message: 'ok', data }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

const passingPreview: CandidatePlanPreview = {
  schemaVersion: '1.0',
  validationStatus: 'PASS',
  metrics: {
    totalCostCents: 1_500,
    knownTotalCostCents: 1_500,
    unknownAmountCount: 0,
    budgetLimitCents: 45_000,
    knownBudgetBufferCents: 43_500,
    totalWalkMeters: 1_500,
    transferCount: 0,
    validationStatus: 'PASS',
  },
  constraintResults: [{
    ruleId: 'budget.total',
    scope: 'TRIP',
    hardness: 'HARD',
    status: 'PASS',
    referenceId: null,
    observed: {},
    suggestion: null,
  }],
  warnings: [],
}

test('nearest-neighbor ordering starts from the confirmed coordinate and does not mutate input', () => {
  const seed = { longitude: 0, latitude: 0 }
  const supplied = [
    place('far-first', { longitude: 0.09, latitude: 0 }),
    place('nearest', { longitude: 0.01, latitude: 0 }),
    place('middle', { longitude: 0.05, latitude: 0 }),
  ]
  const before = [...supplied]

  const ordered = orderByShortestNextSegment(supplied, seed)

  assert.deepEqual(ordered.map((item) => item.placeId), ['nearest', 'middle', 'far-first'])
  assert.deepEqual(supplied, before)
})

test('walking unavailability requests driving once and never requests transit or cycling', async (t) => {
  const originalFetch = globalThis.fetch
  t.after(() => { globalThis.fetch = originalFetch })
  const { base, city } = fixture()
  const modes: TravelMode[] = []
  globalThis.fetch = (async (_input, init = {}) => {
    const body = JSON.parse(String(init.body)) as { mode: TravelMode; origin: GeoPoint; destination: GeoPoint }
    modes.push(body.mode)
    if (body.mode === 'WALKING') {
      return new Response(JSON.stringify({ code: 'PROVIDER_ROUTE_UNAVAILABLE', message: '步行路线不可用' }), { status: 503 })
    }
    return ok({
      cityCode: '110100',
      routes: [route('driving-fallback', body.origin, body.destination, 'DRIVING')],
      provenance,
    })
  }) as typeof fetch

  const selected = await requestDefaultAmapRoute(
    base.trip.tripId,
    city,
    base.startLocation.location,
    base.taskFacts[0].place.location,
    1_000,
  )

  assert.equal(selected.mode, 'DRIVING')
  assert.deepEqual(modes, ['WALKING', 'DRIVING'])
})

test('rejects a provider route whose mode differs from the requested driving fallback', async (t) => {
  const originalFetch = globalThis.fetch
  t.after(() => { globalThis.fetch = originalFetch })
  const { base, city } = fixture()
  const modes: TravelMode[] = []
  globalThis.fetch = (async (_input, init = {}) => {
    const body = JSON.parse(String(init.body)) as {
      mode: TravelMode
      origin: GeoPoint
      destination: GeoPoint
    }
    modes.push(body.mode)
    const returned = body.mode === 'WALKING'
      ? route('walking-over-limit', body.origin, body.destination, 'WALKING', 1_200, 1_001)
      : route('wrong-mode', body.origin, body.destination, 'BICYCLING')
    return ok({ cityCode: '110100', routes: [returned], provenance })
  }) as typeof fetch

  await assert.rejects(
    requestDefaultAmapRoute(
      base.trip.tripId,
      city,
      base.startLocation.location,
      base.taskFacts[0].place.location,
      2_000,
    ),
    (error: unknown) => {
      assert.ok(error instanceof Error)
      assert.match(error.message, /DRIVING/)
      assert.match(error.message, /BICYCLING/)
      return true
    },
  )
  assert.deepEqual(modes, ['WALKING', 'DRIVING'])
})

test('driving failure remains readable and does not fall back to transit or cycling', async (t) => {
  const originalFetch = globalThis.fetch
  t.after(() => { globalThis.fetch = originalFetch })
  const { base, city } = fixture()
  const modes: TravelMode[] = []
  globalThis.fetch = (async (_input, init = {}) => {
    const body = JSON.parse(String(init.body)) as { mode: TravelMode }
    modes.push(body.mode)
    return new Response(JSON.stringify({
      code: 'PROVIDER_ROUTE_UNAVAILABLE',
      message: `${body.mode}路线不可用`,
    }), { status: 503 })
  }) as typeof fetch

  await assert.rejects(
    requestDefaultAmapRoute(
      base.trip.tripId,
      city,
      base.startLocation.location,
      base.taskFacts[0].place.location,
      1_000,
    ),
    (error: unknown) => {
      assert.ok(error instanceof ApiError)
      assert.equal(error.message, 'DRIVING路线不可用')
      return true
    },
  )
  assert.deepEqual(modes, ['WALKING', 'DRIVING'])
})

test('segment replacement requests exactly one route then previews the rebuilt candidate', async (t) => {
  const originalFetch = globalThis.fetch
  t.after(() => { globalThis.fetch = originalFetch })
  const { base } = fixture()
  const calls: Array<{ url: string; init: RequestInit }> = []
  const replacement = route(
    'route-2-driving',
    base.taskFacts[0].place.location,
    base.taskFacts[1].place.location,
    'DRIVING',
    1_800,
    4_000,
  )
  globalThis.fetch = (async (input, init = {}) => {
    const url = String(input)
    calls.push({ url, init })
    if (url.endsWith('/api/v1/routes/plan')) {
      return ok({ cityCode: '110100', routes: [replacement], provenance })
    }
    if (url.endsWith(`/api/v1/trips/${base.trip.tripId}/plan-previews/validate`)) {
      return ok(passingPreview)
    }
    throw new Error(`unexpected request: ${url}`)
  }) as typeof fetch

  const result = await replaceAmapPlanSegment(base.trip.tripId, base, 1, 'DRIVING', 'organizer-token')

  assert.equal(calls.length, 2)
  assert.equal(calls.filter((call) => call.url.endsWith('/api/v1/routes/plan')).length, 1)
  assert.equal(calls.filter((call) => call.url.includes('/plan-previews/validate')).length, 1)
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), {
    schemaVersion: '1.0',
    tripId: base.trip.tripId,
    cityContext: base.trip.cityContext,
    origin: base.taskFacts[0].place.location,
    destination: base.taskFacts[1].place.location,
    mode: 'DRIVING',
    strategy: null,
  })
  assert.equal(new Headers(calls[0].init.headers).get('X-Organizer-Token'), 'organizer-token')
  assert.equal(new Headers(calls[1].init.headers).get('X-Organizer-Token'), 'organizer-token')
  assert.equal(result.candidateRequest?.taskFacts[1].route.routeId, replacement.routeId)
  assert.deepEqual(JSON.parse(String(calls[1].init.body)), result.candidateRequest)
  assert.deepEqual(result.preview, passingPreview)
  assert.deepEqual(result.evidence, { segmentIndex: 1, route: replacement })
})

test('provider replacement failure leaves the original candidate unchanged', async (t) => {
  const originalFetch = globalThis.fetch
  t.after(() => { globalThis.fetch = originalFetch })
  const { base } = fixture()
  const before = structuredClone(base)
  let requestCount = 0
  globalThis.fetch = (async () => {
    requestCount += 1
    return new Response(JSON.stringify({
      code: 'PROVIDER_TIMEOUT',
      message: '高德路线服务暂时不可用',
    }), { status: 504 })
  }) as typeof fetch

  await assert.rejects(
    replaceAmapPlanSegment(base.trip.tripId, base, 1, 'TRANSIT'),
    (error: unknown) => {
      assert.ok(error instanceof ApiError)
      assert.equal(error.message, '高德路线服务暂时不可用')
      return true
    },
  )
  assert.equal(requestCount, 1)
  assert.deepEqual(base, before)
})

test('unschedulable returned route stays in local FAIL evidence without previewing', async (t) => {
  const originalFetch = globalThis.fetch
  t.after(() => { globalThis.fetch = originalFetch })
  const { base } = fixture()
  const before = structuredClone(base)
  const impossible = route(
    'route-impossible',
    base.taskFacts[0].place.location,
    base.taskFacts[1].place.location,
    'DRIVING',
    24 * 60 * 60,
    100_000,
  )
  let requestCount = 0
  globalThis.fetch = (async () => {
    requestCount += 1
    return ok({ cityCode: '110100', routes: [impossible], provenance })
  }) as typeof fetch

  const result = await replaceAmapPlanSegment(base.trip.tripId, base, 1, 'DRIVING')

  assert.equal(requestCount, 1)
  assert.equal(result.candidateRequest, null)
  assert.equal(result.preview.validationStatus, 'FAIL')
  assert.equal(result.preview.metrics, null)
  assert.match(result.preview.constraintResults[0].suggestion ?? '', /时间窗/)
  assert.deepEqual(result.evidence.route, impossible)
  assert.deepEqual(base, before)
})
