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
    { longitude: 116.35, latitude: 39.95 },
    { longitude: 116.36, latitude: 39.96 },
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
    location: points[6],
    provenance,
  }
  const places = [
    place('poi-1', '景点一', points[1]),
    place('poi-2', '景点二', points[2]),
    place('lunch-restaurant', '午餐餐厅', points[3], '餐饮服务;中餐厅'),
    place('poi-3', '景点三', points[4]),
    place('dinner-restaurant', '晚餐餐厅', points[5], '餐饮服务;中餐厅'),
    place('return-home', '已确认住处', points[6], 'RETURN'),
  ]
  const routes = [
    route('route-1', points[0], points[1]),
    route('route-2', points[1], points[2]),
    route('route-3', points[2], points[3]),
    route('route-4', points[3], points[4]),
    route('route-5', points[4], points[5]),
    route('route-return', points[5], points[6]),
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
  assert.equal(request.taskFacts[2].title, '午餐 · 午餐餐厅')
  assert.equal(request.taskFacts[2].category, 'MEAL_LUNCH')
  assert.deepEqual(
    [request.taskFacts[2].startAt, request.taskFacts[2].endAt],
    ['12:00', '13:00'],
  )
  assert.equal(request.taskFacts[4].title, '晚餐 · 晚餐餐厅')
  assert.equal(request.taskFacts[4].category, 'MEAL_DINNER')
  assert.deepEqual(
    [request.taskFacts[4].startAt, request.taskFacts[4].endAt],
    ['18:00', '19:00'],
  )
  assert.ok(request.taskFacts.every((fact) => (
    /^\d{2}:\d{2}$/.test(fact.startAt) && /^\d{2}:\d{2}$/.test(fact.endAt)
  )))
  assert.deepEqual(
    request.confirmedConstraints,
    compileAssistanceConstraints(input.confirmedTrip.participants[0].assistanceProfile!),
  )
})

test('candidate builder rejects a fake final place or a route that misses the endpoint', () => {
  const wrongPlace = fixture()
  wrongPlace.places[5] = place(
    'wrong-end',
    '其他地点',
    { longitude: 116.36, latitude: 39.96 },
    'RETURN',
  )
  wrongPlace.routes[5] = route(
    'route-wrong-place',
    wrongPlace.places[4].location,
    wrongPlace.places[5].location,
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
  wrongRoute.routes[5] = route(
    'route-wrong-destination',
    wrongRoute.places[4].location,
    { longitude: 116.37, latitude: 39.97 },
  )
  assert.throws(
    () => buildCandidateRequestFromConfirmedTrip(
      wrongRoute.confirmedTrip,
      wrongRoute.startLocation,
      wrongRoute.endLocation,
      wrongRoute.places,
      wrongRoute.routes,
    ),
    /第 6 段路线终点与对应地点不一致/,
  )
})

test('candidate builder rejects lodging as an intermediate one-day task', () => {
  const input = fixture()
  input.places[0] = place(
    'hotel-task',
    '城市商务酒店',
    input.places[0].location,
    '住宿服务;宾馆酒店',
  )

  assert.throws(
    () => buildCandidateRequestFromConfirmedTrip(
      input.confirmedTrip,
      input.startLocation,
      input.endLocation,
      input.places,
      input.routes,
    ),
    /不能把酒店或住宿地点/,
  )
})

test('candidate builder gives nested scenic POIs shorter visits than a museum', () => {
  const input = fixture()
  input.places[0] = place(
    'temple-hall',
    '天坛公园-斋宫',
    input.places[0].location,
    '风景名胜;公园景区',
  )
  input.places[1] = place(
    'palace-museum',
    '故宫博物院',
    input.places[1].location,
    '科教文化服务;博物馆',
  )
  input.places[3] = place(
    'temple-altar',
    '天坛公园-圜丘',
    input.places[3].location,
    '风景名胜;公园景区',
  )

  const request = buildCandidateRequestFromConfirmedTrip(
    input.confirmedTrip,
    input.startLocation,
    input.endLocation,
    input.places,
    input.routes,
  )
  const durationMinutes = (index: number) => {
    const fact = request.taskFacts[index]
    const [startHour, startMinute] = fact.startAt.split(':').map(Number)
    const [endHour, endMinute] = fact.endAt.split(':').map(Number)
    return (endHour * 60 + endMinute) - (startHour * 60 + startMinute)
  }

  assert.equal(durationMinutes(0), 40)
  assert.equal(durationMinutes(1), 75)
  assert.equal(durationMinutes(3), 40)
})

test('candidate builder fits the real Beijing-to-Badaling driving durations into 09:00-18:00', () => {
  const input = fixture()
  input.confirmedTrip.days[0].timeWindow.end = '18:00:00'
  input.places = [
    place('temple-of-heaven', '天坛公园', input.places[0].location, '风景名胜;公园广场;公园'),
    place('palace-museum', '故宫博物院', input.places[1].location, '科教文化服务;博物馆'),
    place('lunch-restaurant', '景运门故宫餐厅', input.places[2].location, '餐饮服务;中餐厅'),
    place('badaling', '八达岭长城', input.places[3].location, '风景名胜;国家级景点'),
    place('return-station', '已确认住处', input.places[5].location, 'RETURN'),
  ]
  input.routes = [
    route('station-to-temple', input.startLocation.location, input.places[0].location),
    route('temple-to-palace', input.places[0].location, input.places[1].location),
    route('palace-to-lunch', input.places[1].location, input.places[2].location),
    route('lunch-to-badaling', input.places[2].location, input.places[3].location),
    route('badaling-to-station', input.places[3].location, input.places[4].location),
  ]
  const durations = [1_351, 1_285, 86, 4_680, 4_470]
  input.routes.forEach((item, index) => {
    item.durationSeconds = durations[index]
    if (index >= 3) item.mode = 'DRIVING'
  })

  const request = buildCandidateRequestFromConfirmedTrip(
    input.confirmedTrip,
    input.startLocation,
    input.endLocation,
    input.places,
    input.routes,
  )

  assert.equal(request.taskFacts[2].startAt, '12:00')
  assert.equal(request.taskFacts[2].endAt, '13:00')
  assert.deepEqual(request.taskFacts.slice(3).map((fact) => fact.route.mode), [
    'DRIVING',
    'DRIVING',
  ])
  assert.ok(request.taskFacts.at(-1)!.endAt <= '18:00')
})
