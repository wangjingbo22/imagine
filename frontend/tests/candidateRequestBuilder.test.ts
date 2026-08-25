import assert from 'node:assert/strict'
import test from 'node:test'

import type {
  CandidateEndpointFact,
  CreateSingleDayTrip,
  GeoPoint,
  Place,
  ProviderRoute,
} from '../src/domain/trip.ts'
import { compileAssistanceConstraints } from '../src/services/assistanceConstraints.ts'
import { buildCandidateRequestFromConfirmedTrip } from '../src/services/candidateRequestBuilder.ts'

const provenance = {
  provider: 'AMAP' as const,
  sourceStatus: 'ONLINE' as const,
  fetchedAt: '2026-08-25T09:00:00+08:00',
  isStale: false,
}

function place(placeId: string, name: string, location: GeoPoint, category = '景点'): Place {
  return {
    placeId,
    name,
    address: `${name}地址`,
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

function route(routeId: string, origin: GeoPoint, destination: GeoPoint): ProviderRoute {
  return {
    routeId,
    mode: 'WALKING',
    origin,
    destination,
    distanceMeters: 300,
    durationSeconds: 600,
    walkingDistanceMeters: null,
    transferCount: null,
    steps: [],
    facilityEvidence: [],
    priceReference: {
      amountCents: 0,
      currency: 'CNY',
      kind: 'walking',
      provenance,
    },
    provenance,
  }
}

function fixture() {
  const points: GeoPoint[] = [
    { longitude: 116.30, latitude: 39.90 },
    { longitude: 116.31, latitude: 39.91 },
    { longitude: 116.32, latitude: 39.92 },
    { longitude: 116.33, latitude: 39.93 },
    { longitude: 116.34, latitude: 39.94 },
  ]
  const confirmedTrip: CreateSingleDayTrip = {
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
    startDate: '2026-08-25',
    endDate: '2026-08-25',
    currency: 'CNY',
    totalBudgetCents: 35_000,
    participants: [{
      participantId: '22222222-2222-4222-8222-222222222222',
      nickname: '已确认旅客',
      budgetCapCents: 35_000,
      preferences: [{ type: 'INTEREST', value: '历史文化', weight: 4, isHard: false }],
      assistanceProfile: {
        type: 'LOW_STAMINA',
        childAge: null,
        walkLimits: { maxContinuousMeters: 500, maxDailyMeters: 3_000 },
        maxTransfers: 2,
        restInterval: 90,
        napWindow: null,
        avoidStairs: false,
      },
    }],
    days: [{
      dayIndex: 0,
      date: '2026-08-25',
      dailyBudgetCents: 30_000,
      startLocationText: '已确认起点',
      endLocationText: '已确认住处',
      timeWindow: { start: '09:00:00', end: '20:00:00' },
    }],
  }
  const startLocation: CandidateEndpointFact = {
    locationText: '已确认起点',
    cityCode: '110100',
    location: points[0],
    provenance,
  }
  const endLocation: CandidateEndpointFact = {
    locationText: '已确认住处',
    cityCode: '110100',
    location: points[4],
    provenance,
  }
  const places = [
    place('poi-1', '景点一', points[1]),
    place('poi-2', '景点二', points[2]),
    place('poi-3', '景点三', points[3]),
    place('return-home', '已确认住处', points[4], 'RETURN'),
  ]
  const routes = [
    route('route-1', points[0], points[1]),
    route('route-2', points[1], points[2]),
    route('route-3', points[2], points[3]),
    route('route-return', points[3], points[4]),
  ]
  return { confirmedTrip, startLocation, endLocation, places, routes }
}

test('candidate builder preserves the confirmed Trip and models a separate return task', () => {
  const input = fixture()
  const request = buildCandidateRequestFromConfirmedTrip(
    input.confirmedTrip,
    input.startLocation,
    input.endLocation,
    input.places,
    input.routes,
  )

  assert.deepEqual(request.trip, { ...input.confirmedTrip, status: 'PLANNING' })
  assert.equal(input.confirmedTrip.status, 'DRAFT')
  assert.equal(request.trip.participants[0].participantId, input.confirmedTrip.participants[0].participantId)
  assert.equal(request.trip.totalBudgetCents, input.confirmedTrip.totalBudgetCents)
  assert.deepEqual(request.trip.days[0], input.confirmedTrip.days[0])
  assert.deepEqual(request.taskFacts.at(-1)?.place, input.places.at(-1))
  assert.deepEqual(request.taskFacts.at(-1)?.route.destination, input.endLocation.location)
  assert.equal(request.taskFacts.at(-1)?.category, 'RETURN')
  assert.deepEqual(
    request.confirmedConstraints,
    compileAssistanceConstraints(input.confirmedTrip.participants[0].assistanceProfile!),
  )
})

test('candidate builder rejects a fake final place or a route that misses the endpoint', () => {
  const wrongPlace = fixture()
  wrongPlace.places[3] = place(
    'wrong-end',
    '其他地点',
    { longitude: 116.35, latitude: 39.95 },
    'RETURN',
  )
  wrongPlace.routes[3] = route(
    'route-wrong-place',
    wrongPlace.places[2].location,
    wrongPlace.places[3].location,
  )
  assert.throws(
    () => buildCandidateRequestFromConfirmedTrip(
      wrongPlace.confirmedTrip,
      wrongPlace.startLocation,
      wrongPlace.endLocation,
      wrongPlace.places,
      wrongPlace.routes,
    ),
    /末项必须是返回 T004 已确认终点/,
  )

  const wrongRoute = fixture()
  wrongRoute.routes[3] = route(
    'route-wrong-destination',
    wrongRoute.places[2].location,
    { longitude: 116.36, latitude: 39.96 },
  )
  assert.throws(
    () => buildCandidateRequestFromConfirmedTrip(
      wrongRoute.confirmedTrip,
      wrongRoute.startLocation,
      wrongRoute.endLocation,
      wrongRoute.places,
      wrongRoute.routes,
    ),
    /第 4 段路线终点与对应地点不一致/,
  )
})
