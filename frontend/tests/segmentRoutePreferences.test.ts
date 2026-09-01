import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'

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
  PlanSnapshot,
  StoredPlanVersion,
  TravelMode,
} from '../src/domain/trip.ts'
import {
  acceptInitialCandidatePlan,
  loadAmapPlan,
  orderByShortestNextSegment,
  replaceAmapPlanSegment,
  requestDefaultAmapRoute,
} from '../src/services/amapPlan.ts'
import * as amapPlan from '../src/services/amapPlan.ts'
import { buildCandidateRequestFromConfirmedTrip } from '../src/services/candidateRequestBuilder.ts'

const workspaceSource = readFileSync(
  fileURLToPath(new URL('../src/pages/WorkspacePage.tsx', import.meta.url)),
  'utf8',
)
const amapPlanSource = readFileSync(
  fileURLToPath(new URL('../src/services/amapPlan.ts', import.meta.url)),
  'utf8',
)
const stateTransitionPath = fileURLToPath(
  new URL('../src/services/segmentRouteReplacementState.ts', import.meta.url),
)

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
    place('poi-2', points[2], '餐饮服务;中餐厅'),
    place('poi-3', points[3], '餐饮服务;中餐厅'),
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

const failingPreview: CandidatePlanPreview = {
  ...passingPreview,
  validationStatus: 'FAIL',
  metrics: null,
  constraintResults: [{
    ruleId: 'time.window',
    scope: 'TRIP',
    hardness: 'HARD',
    status: 'FAIL',
    referenceId: null,
    observed: {},
    suggestion: '行程超过确认的时间窗。',
  }, {
    ruleId: 'budget.total',
    scope: 'TRIP',
    hardness: 'HARD',
    status: 'FAIL',
    referenceId: null,
    observed: {},
    suggestion: '行程超过确认的预算。',
  }],
}

const needsConfirmationPreview: CandidatePlanPreview = {
  ...passingPreview,
  validationStatus: 'NEEDS_CONFIRMATION',
  metrics: {
    ...passingPreview.metrics!,
    validationStatus: 'NEEDS_CONFIRMATION',
  },
  constraintResults: [{
    ruleId: 'price.reference',
    scope: 'TASK',
    hardness: 'HARD',
    status: 'NEEDS_CONFIRMATION',
    referenceId: 'poi-1',
    observed: {},
    suggestion: '请核对景点票价。',
  }],
  warnings: [{
    code: 'UNKNOWN_PRICE',
    severity: 'WARNING',
    resolution: 'NEEDS_CONFIRMATION',
    referenceId: 'poi-1',
    field: 'priceReference.amountCents',
    message: '景点票价仍未知。',
  }],
}

function planSnapshotFor(base: CandidatePlanRequest): PlanSnapshot {
  return {
    id: 'candidate-plan',
    version: 1,
    cityName: base.trip.cityContext.cityName,
    totalCostCents: 6_000,
    bufferCents: 39_000,
    totalWalkMeters: 2_000,
    transferCount: 0,
    validationStatus: 'PASS',
    tasks: base.taskFacts.map((fact, index) => ({
      id: fact.taskId,
      order: fact.order,
      title: fact.title,
      category: fact.category,
      timeRange: `${fact.startAt.slice(0, 5)}—${fact.endAt.slice(0, 5)}`,
      durationMinutes: 60,
      transport: `${fact.route.mode} ${fact.route.distanceMeters}`,
      costCents: 1_500,
      priceKnown: true,
      walkMeters: fact.route.distanceMeters,
      note: fact.note,
      status: index === 0 ? 'current' as const : 'upcoming' as const,
      coordinates: [index * 10, index * 10] as [number, number],
    })),
  }
}

test('initial planning previews exactly one candidate without issuing V1', async (t) => {
  const originalFetch = globalThis.fetch
  const originalDateNow = Date.now
  t.after(() => {
    globalThis.fetch = originalFetch
    Date.now = originalDateNow
  })
  let now = 0
  Date.now = () => (now += 2_000)
  const { base, city } = fixture()
  const calls: Array<{ url: string; init: RequestInit }> = []
  const nearbyPlaces = [
    { ...base.taskFacts[0].place, category: '景点' },
    { ...base.taskFacts[1].place, category: '景点' },
    { ...base.taskFacts[2].place, category: '景点' },
    { ...base.taskFacts[1].place, placeId: 'meal-lunch', name: '午餐餐厅' },
    { ...base.taskFacts[2].place, placeId: 'meal-dinner', name: '晚餐餐厅' },
  ]
  let previewResponse = passingPreview
  globalThis.fetch = (async (input, init = {}) => {
    const url = String(input)
    calls.push({ url, init })
    if (url.endsWith('/api/v1/cities/resolve')) return ok(city)
    if (url.endsWith('/api/v1/geocoding/forward')) {
      return ok({
        cityCode: base.trip.cityContext.cityCode,
        adCode: '110101',
        formattedAddress: base.trip.days[0].startLocationText,
        location: base.startLocation.location,
        provenance,
      })
    }
    if (url.endsWith('/api/v1/places/nearby')) return ok({ places: nearbyPlaces })
    if (url.endsWith('/api/v1/routes/plan')) {
      const request = JSON.parse(String(init.body)) as { origin: GeoPoint; destination: GeoPoint; mode: TravelMode }
      return ok({
        cityCode: base.trip.cityContext.cityCode,
        routes: [route(
          `initial-${request.destination.longitude}`,
          request.origin,
          request.destination,
          request.mode,
        )],
        provenance,
      })
    }
    if (url.includes('/plan-previews/validate')) {
      return ok(previewResponse)
    }
    if (url.includes('/plan-versions/generate')) {
      throw new Error('initial planning must not issue Plan V1')
    }
    throw new Error(`unexpected request: ${url}`)
  }) as typeof fetch

  const result = await loadAmapPlan(base.trip.tripId, {
    schemaVersion: '1.0',
    cityName: base.trip.cityContext.cityName,
    travelDate: base.trip.days[0].date,
    startTime: '09:00',
    endTime: '20:00',
    startLocationText: base.trip.days[0].startLocationText,
    endLocationText: base.trip.days[0].endLocationText,
    budgetCents: base.trip.totalBudgetCents,
    interests: [],
    mustVisit: ['fixture'],
    avoidPlaces: [],
    assistanceMode: 'standard',
    assistanceProfile: { maxSegmentWalkMeters: null, maxTransfers: null, restIntervalMinutes: null },
    naturalLanguageRequest: 'fixture',
  }, undefined, {
    confirmedTrip: base.trip,
    organizerToken: 'organizer-token',
  })

  const previews = calls.filter((call) => call.url.endsWith('/plan-previews/validate'))
  assert.equal(previews.length, 1)
  assert.equal(calls.filter((call) => call.url.includes('/plan-versions/generate')).length, 0)
  assert.equal(new Headers(previews[0].init.headers).get('X-Organizer-Token'), 'organizer-token')
  assert.deepEqual(JSON.parse(String(previews[0].init.body)), result.candidateRequest)
  assert.equal(result.registeredPlan, null)
  assert.equal(result.plan.validationStatus, 'PASS')
  assert.deepEqual(result.candidatePreview, passingPreview)

  const failedTrip = structuredClone(base.trip)
  failedTrip.tripId = '11111111-1111-4111-8111-111111111112'
  previewResponse = failingPreview
  const failedResult = await loadAmapPlan(failedTrip.tripId, {
    schemaVersion: '1.0',
    cityName: failedTrip.cityContext.cityName,
    travelDate: failedTrip.days[0].date,
    startTime: '09:00',
    endTime: '20:00',
    startLocationText: failedTrip.days[0].startLocationText,
    endLocationText: failedTrip.days[0].endLocationText,
    budgetCents: failedTrip.totalBudgetCents,
    interests: [],
    mustVisit: ['fixture'],
    avoidPlaces: [],
    assistanceMode: 'standard',
    assistanceProfile: { maxSegmentWalkMeters: null, maxTransfers: null, restIntervalMinutes: null },
    naturalLanguageRequest: 'fixture failure',
  }, undefined, { confirmedTrip: failedTrip, organizerToken: 'organizer-token' })
  assert.equal(failedResult.registeredPlan, null)
  assert.equal(failedResult.plan.validationStatus, 'FAIL')
  assert.equal(failedResult.planningIssue?.code, 'CANDIDATE_PREVIEW_REJECTED')
  assert.match(failedResult.planningIssue?.message ?? '', /时间窗/)
  assert.equal(failedResult.planningIssue?.review, null)
  assert.deepEqual(failedResult.candidatePreview, failingPreview)
})

test('initial planning defers V1 issuance to the workspace acceptance action', () => {
  assert.doesNotMatch(amapPlanSource, /generatePlanVersion\(tripId, candidateRequest/)
  assert.match(amapPlanSource, /previewCandidatePlan/)
  assert.match(workspaceSource, /generatePlanVersion\(tripId, candidateRequest/)
})

test('final acceptance blocks a failed preview before issuing V1', async () => {
  const calls: string[] = []
  await assert.rejects(
    acceptInitialCandidatePlan({
      validationStatus: 'FAIL',
      persistedPlanId: null,
      issuePlan: async () => {
        calls.push('issue')
        return {} as StoredPlanVersion
      },
      confirmPlan: async () => { calls.push('confirm') },
      startExecution: async () => { calls.push('start') },
    }),
    /未通过服务端预览校验/,
  )
  assert.deepEqual(calls, [])
})

test('final acceptance issues a previewed candidate then confirms and starts its V1 in order', async () => {
  const calls: string[] = []
  const result = await acceptInitialCandidatePlan({
    validationStatus: 'NEEDS_CONFIRMATION',
    persistedPlanId: null,
    issuePlan: async () => {
      calls.push('issue')
      return { planId: 'issued-v1' } as StoredPlanVersion
    },
    confirmPlan: async (planId) => { calls.push(`confirm:${planId}`) },
    startExecution: async () => { calls.push('start') },
  })
  assert.deepEqual(result, { kind: 'STARTED', planId: 'issued-v1' })
  assert.deepEqual(calls, ['issue', 'confirm:issued-v1', 'start'])
})

test('final acceptance records an issued V1 before a failed confirm retry', async () => {
  const calls: string[] = []
  let persistedPlanId: string | null = null
  const issuePlan = async () => {
    calls.push('issue')
    return { planId: 'issued-v1' } as StoredPlanVersion
  }
  const onPlanIssued = (planId: string) => {
    calls.push(`record:${planId}`)
    persistedPlanId = planId
  }
  await assert.rejects(
    acceptInitialCandidatePlan({
      validationStatus: 'PASS',
      persistedPlanId,
      issuePlan,
      onPlanIssued,
      confirmPlan: async (planId) => {
        calls.push(`confirm:${planId}`)
        throw new Error('confirm unavailable')
      },
      startExecution: async () => { calls.push('start') },
    } as Parameters<typeof acceptInitialCandidatePlan>[0] & { onPlanIssued: (planId: string) => void }),
    /confirm unavailable/,
  )
  assert.equal(persistedPlanId, 'issued-v1')
  const retried = await acceptInitialCandidatePlan({
    validationStatus: 'PASS',
    persistedPlanId,
    issuePlan,
    onPlanIssued,
    confirmPlan: async (planId) => { calls.push(`confirm:${planId}`) },
    startExecution: async () => { calls.push('start') },
  } as Parameters<typeof acceptInitialCandidatePlan>[0] & { onPlanIssued: (planId: string) => void })
  assert.deepEqual(retried, { kind: 'STARTED', planId: 'issued-v1' })
  assert.deepEqual(calls, [
    'issue', 'record:issued-v1', 'confirm:issued-v1', 'confirm:issued-v1', 'start',
  ])
})

test('workspace interaction predicates block acceptance during route replacement and replacement during acceptance', () => {
  const predicates = amapPlan as typeof amapPlan & {
    canAcceptCurrentCandidate: (input: {
      hasCandidateRequest: boolean
      validationStatus: PlanSnapshot['validationStatus']
      hasPlanningIssue: boolean
      hasLocalSegmentFailure: boolean
      pendingSegmentIndex: number | null
    }) => boolean
    canReplaceCandidateSegment: (input: {
      hasTripId: boolean
      hasCandidateRequest: boolean
      pendingSegmentIndex: number | null
      hasExecutingPlanV1: boolean
      isConfirmingPlan: boolean
    }) => boolean
  }
  assert.equal(predicates.canAcceptCurrentCandidate({
    hasCandidateRequest: true,
    validationStatus: 'PASS',
    hasPlanningIssue: false,
    hasLocalSegmentFailure: false,
    pendingSegmentIndex: 1,
  }), false)
  assert.equal(predicates.canReplaceCandidateSegment({
    hasTripId: true,
    hasCandidateRequest: true,
    pendingSegmentIndex: null,
    hasExecutingPlanV1: false,
    isConfirmingPlan: true,
  }), false)
})

test('NEEDS_CONFIRMATION preview notice retains concrete facts without blocking final issuance', () => {
  const helpers = amapPlan as typeof amapPlan & {
    candidatePreviewConfirmationNotice: (preview: CandidatePlanPreview | null) => {
      summary: string
      details: string[]
      actionLabel: string
    } | null
  }
  const notice = helpers.candidatePreviewConfirmationNotice(needsConfirmationPreview)
  assert.deepEqual(notice, {
    summary: '候选计划已通过预览校验，仍需核对计划事实。',
    details: ['景点票价仍未知。', '请核对景点票价。'],
    actionLabel: '继续核对计划事实',
  })
  assert.equal(amapPlan.canAcceptCurrentCandidate({
    hasCandidateRequest: true,
    validationStatus: needsConfirmationPreview.validationStatus,
    hasPlanningIssue: false,
    hasLocalSegmentFailure: false,
    pendingSegmentIndex: null,
  }), true)
})

test('a hard server preview failure retains rebuilt facts and route evidence until a later PASS replacement', async () => {
  const transitionModule = await import(pathToFileURL(stateTransitionPath).href)
  const applyResult = transitionModule.applySegmentReplacementResult
  const { base } = fixture()
  const replacement = route(
    'route-preview-fail',
    base.taskFacts[0].place.location,
    base.taskFacts[1].place.location,
    'DRIVING',
    1_800,
    4_000,
  )
  const candidate = structuredClone(base)
  candidate.taskFacts[1].route = replacement
  const initial = {
    candidateRequest: base,
    providerPlan: planSnapshotFor(base),
    locationEvidence: {
      city: { cityContext: base.trip.cityContext, provenance },
      places: base.taskFacts.map((fact) => fact.place),
      routes: base.taskFacts.map((fact) => fact.route),
      queries: ['fixture'],
    },
    persistedPlanId: null,
    restoredPlan: null,
    planningIssue: null,
    localFailure: null,
    candidatePreview: null,
  }
  const failed = applyResult(initial, {
    evidence: { segmentIndex: 1, route: replacement },
    candidateRequest: candidate,
    preview: failingPreview,
  })
  assert.equal(failed.kind, 'SUCCESS')
  assert.equal(failed.state.candidateRequest, candidate)
  assert.equal(failed.state.locationEvidence.routes[1], replacement)
  assert.equal(failed.state.providerPlan.validationStatus, 'FAIL')
  assert.equal(failed.state.planningIssue?.code, 'CANDIDATE_PREVIEW_REJECTED')
  assert.match(failed.state.planningIssue?.message ?? '', /时间窗/)
  assert.equal(failed.state.planningIssue?.review, null)
  assert.equal(failed.state.localFailure, null)
  assert.equal(failed.state.candidatePreview, failingPreview)
  assert.equal(
    failed.state.providerPlan.tasks[1].timeRange,
    `${candidate.taskFacts[1].startAt.slice(0, 5)}—${candidate.taskFacts[1].endAt.slice(0, 5)}`,
  )

  const recovered = applyResult(failed.state, {
    evidence: { segmentIndex: 1, route: replacement },
    candidateRequest: candidate,
    preview: passingPreview,
  })
  assert.equal(recovered.state.planningIssue, null)
  assert.equal(recovered.state.providerPlan.validationStatus, 'PASS')
  assert.equal(recovered.state.candidateRequest, candidate)
  assert.equal(recovered.state.candidatePreview, passingPreview)
})

test('final acceptance opens server fact review without confirming or starting an issued candidate', async () => {
  const calls: string[] = []
  const result = await acceptInitialCandidatePlan({
    validationStatus: 'NEEDS_CONFIRMATION',
    persistedPlanId: null,
    issuePlan: async () => {
      calls.push('issue')
      throw new ApiError('CANDIDATE_CONFIRMATION_REQUIRED', 'review required', [], [{
        review: {
          schemaVersion: '1.0',
          reviewId: 'review-1',
          tripId: 'trip-1',
          candidateId: 'candidate-1',
          status: 'PENDING',
          createdAt: '2026-09-02T09:00:00+08:00',
          confirmedAt: null,
          items: [],
        },
      }])
    },
    confirmPlan: async () => { calls.push('confirm') },
    startExecution: async () => { calls.push('start') },
  })
  assert.equal(result.kind, 'REVIEW_REQUIRED')
  assert.equal(result.planningIssue.review?.reviewId, 'review-1')
  assert.deepEqual(calls, ['issue'])
})

test('workspace keeps route replacement mechanics out of the route fact display', () => {
  assert.doesNotMatch(workspaceSource, /SegmentRouteModePicker/)
  assert.match(workspaceSource, /provider-route-evidence/)
  assert.match(workspaceSource, /route\.distanceMeters/)
  assert.match(workspaceSource, /route\.durationSeconds/)
})

test('local schedule failure renders its returned route as FAIL without accepting stale candidate facts', async (t) => {
  const originalFetch = globalThis.fetch
  t.after(() => { globalThis.fetch = originalFetch })
  const { base } = fixture()
  const impossible = route(
    'route-local-failure',
    base.taskFacts[0].place.location,
    base.taskFacts[1].place.location,
    'DRIVING',
    24 * 60 * 60,
    100_000,
  )
  globalThis.fetch = (async () => ok({ cityCode: '110100', routes: [impossible], provenance })) as typeof fetch
  const localResult = await replaceAmapPlanSegment(base.trip.tripId, base, 1, 'DRIVING')
  assert.equal(localResult.candidateRequest, null)

  const transitionModule = existsSync(stateTransitionPath)
    ? await import(pathToFileURL(stateTransitionPath).href)
    : null
  assert.ok(transitionModule, 'local schedule failures need a real Workspace state transition')
  const applyResult = (transitionModule as {
    applySegmentReplacementResult: (state: unknown, result: unknown) => {
      kind: 'SUCCESS' | 'LOCAL_FAILURE'
      state: {
        candidateRequest: CandidatePlanRequest
        providerPlan: PlanSnapshot
        locationEvidence: { routes: ProviderRoute[] }
        persistedPlanId: string | null
        planningIssue: { message: string } | null
        localFailure: { segmentIndex: number; route: ProviderRoute; message: string } | null
      }
    }
  }).applySegmentReplacementResult
  const initial = {
    candidateRequest: base,
    providerPlan: planSnapshotFor(base),
    locationEvidence: {
      city: { cityContext: base.trip.cityContext, provenance },
      places: base.taskFacts.map((fact) => fact.place),
      routes: base.taskFacts.map((fact) => fact.route),
      queries: ['fixture'],
    },
    persistedPlanId: 'issued-v1',
    restoredPlan: planSnapshotFor(base),
  }
  const failed = applyResult(initial, localResult)

  assert.equal(failed.kind, 'LOCAL_FAILURE')
  assert.equal(failed.state.locationEvidence.routes[1].routeId, localResult.evidence.route.routeId)
  assert.equal(failed.state.providerPlan.validationStatus, 'FAIL')
  assert.equal(failed.state.persistedPlanId, null)
  assert.equal(failed.state.planningIssue?.message, localResult.preview.constraintResults[0].suggestion)
  assert.equal(failed.state.localFailure?.route.routeId, localResult.evidence.route.routeId)
  assert.equal(failed.state.candidateRequest, base)
  assert.equal(failed.state.providerPlan.totalCostCents, initial.providerPlan.totalCostCents)
  assert.equal(failed.state.providerPlan.tasks[1].durationMinutes, initial.providerPlan.tasks[1].durationMinutes)
  assert.equal(failed.state.providerPlan.tasks[1].costCents, initial.providerPlan.tasks[1].costCents)

  const valid = route(
    'route-recovered-transit',
    base.taskFacts[0].place.location,
    base.taskFacts[1].place.location,
    'TRANSIT',
    1_200,
    2_400,
  )
  globalThis.fetch = (async (input) => {
    const url = String(input)
    if (url.endsWith('/api/v1/routes/plan')) {
      return ok({ cityCode: '110100', routes: [valid], provenance })
    }
    if (url.endsWith(`/api/v1/trips/${base.trip.tripId}/plan-previews/validate`)) {
      return ok(passingPreview)
    }
    throw new Error(`unexpected request: ${url}`)
  }) as typeof fetch
  const successResult = await replaceAmapPlanSegment(
    base.trip.tripId,
    failed.state.candidateRequest,
    1,
    'TRANSIT',
  )
  const recovered = applyResult(failed.state, successResult)

  assert.equal(recovered.kind, 'SUCCESS')
  assert.equal(recovered.state.localFailure, null)
  assert.equal(recovered.state.locationEvidence.routes[1].mode, 'TRANSIT')
  assert.equal(recovered.state.candidateRequest.taskFacts[1].route.routeId, valid.routeId)
  assert.equal(recovered.state.providerPlan.validationStatus, 'PASS')
})

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
  assert.match(result.preview.constraintResults[0].suggestion ?? '', /时间窗|规定时间/)
  assert.deepEqual(result.evidence.route, impossible)
  assert.deepEqual(base, before)
})
