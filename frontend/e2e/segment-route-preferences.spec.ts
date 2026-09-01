import { expect, test, type Page } from '@playwright/test'

const tripId = '66666666-0000-4000-8000-000000000006'
const organizerToken = 'segment-route-e2e-organizer-token'

const provenance = {
  provider: 'AMAP',
  sourceStatus: 'ONLINE',
  fetchedAt: '2026-09-02T09:00:00Z',
  isStale: false,
} as const

const points = [
  { longitude: 116.397, latitude: 39.908 },
  { longitude: 116.407, latitude: 39.913 },
  { longitude: 116.417, latitude: 39.918 },
  { longitude: 116.427, latitude: 39.923 },
]

function api(data: unknown) {
  return JSON.stringify({ code: 200, message: 'OK', data })
}

function place(index: number, name: string) {
  return {
    placeId: `segment-place-${index}`,
    name,
    address: `北京市测试路 ${index} 号`,
    cityCode: '110000',
    adCode: '110101',
    location: points[index],
    category: index === 3 ? 'RETURN' : '文化景点',
    telephone: null,
    rating: 4.8,
    priceReference: { amountCents: 1000, currency: 'CNY', kind: 'ticket', provenance },
    provenance,
  }
}

const places = [
  place(1, '晨光博物馆'),
  place(2, '河畔展馆'),
  place(3, '确认终点'),
]

function route(index: number, mode: 'WALKING' | 'DRIVING', distanceMeters: number, durationSeconds: number) {
  return {
    routeId: `segment-route-${index}-${mode}`,
    mode,
    origin: points[index],
    destination: points[index + 1],
    distanceMeters,
    durationSeconds,
    walkingDistanceMeters: mode === 'WALKING' ? distanceMeters : 80,
    transferCount: null,
    steps: [],
    facilityEvidence: [],
    priceReference: { amountCents: mode === 'DRIVING' ? 1200 : 0, currency: 'CNY', kind: 'route', provenance },
    provenance,
  }
}

const originalRoutes = [
  route(0, 'WALKING', 400, 600),
  route(1, 'WALKING', 500, 720),
  route(2, 'WALKING', 600, 780),
]

const trip = {
  schemaVersion: '1.0',
  tripId,
  mode: 'SINGLE',
  status: 'PLANNING',
  cityContext: {
    countryCode: 'CN', cityCode: '110000', cityName: '北京市', center: points[0],
    providerConfig: { provider: 'AMAP', coordinateSystem: 'GCJ02' },
  },
  startDate: '2026-09-02', endDate: '2026-09-02', currency: 'CNY', totalBudgetCents: 30_000,
  participants: [{
    participantId: '66666666-0000-4000-8000-000000000007', nickname: '组织者', budgetCapCents: 30_000,
    assistanceProfile: { type: 'ORDINARY', childAge: null, walkLimits: { maxContinuousMeters: null, maxDailyMeters: null }, maxTransfers: null, restInterval: null, napWindow: null, avoidStairs: false },
  }],
  days: [{ dayIndex: 0, date: '2026-09-02', dailyBudgetCents: 30_000, startLocationText: '确认起点', endLocationText: '确认终点', timeWindow: { start: '09:00:00', end: '20:00:00' } }],
} as const

const candidateRequest = {
  schemaVersion: '1.0',
  trip,
  startLocation: { locationText: '确认起点', cityCode: '110000', location: points[0], provenance },
  endLocation: { locationText: '确认终点', cityCode: '110000', location: points[3], provenance },
  taskFacts: places.map((currentPlace, index) => ({
    taskId: currentPlace.placeId,
    order: index + 1,
    title: index === 2 ? '返回确认终点' : currentPlace.name,
    category: currentPlace.category,
    startAt: ['09:10:00', '10:22:00', '11:35:00'][index],
    endAt: ['10:10:00', '11:22:00', '12:35:00'][index],
    endLocationText: currentPlace.name,
    cityCode: '110000',
    place: currentPlace,
    route: originalRoutes[index],
    elapsedSinceRestMinutes: index * 60,
    note: `地点 ${currentPlace.name} 保持不变`,
  })),
  confirmedConstraints: [],
} as const

function initialPlan() {
  return {
    id: 'segment-route-candidate', version: 1, cityName: '北京市', totalCostCents: 6600,
    bufferCents: 23_400, totalWalkMeters: 1500, transferCount: 0, validationStatus: 'PASS',
    tasks: candidateRequest.taskFacts.map((fact, index) => ({
      id: fact.taskId, order: fact.order, title: fact.title, category: fact.category,
      timeRange: `${fact.startAt.slice(0, 5)}—${fact.endAt.slice(0, 5)}`,
      durationMinutes: 60, transport: `步行 ${fact.route.distanceMeters} 米`, costCents: 2200,
      priceKnown: true, walkMeters: fact.route.distanceMeters, note: fact.note,
      status: index === 0 ? 'current' : 'upcoming', coordinates: [index * 10, index * 10],
    })),
  }
}

function passingPreview() {
  return {
    schemaVersion: '1.0', validationStatus: 'PASS',
    metrics: { totalCostCents: 7800, knownTotalCostCents: 7800, unknownAmountCount: 0, budgetLimitCents: 30_000, knownBudgetBufferCents: 22_200, totalWalkMeters: 1080, transferCount: 0, validationStatus: 'PASS' },
    constraintResults: [], warnings: [],
  }
}

async function openWorkspace(page: Page) {
  const initialState = {
    tripId,
    trip,
    amapPlanResult: {
      evidence: {
        city: { cityContext: trip.cityContext, provenance },
        places,
        routes: originalRoutes,
        queries: ['文化景点'],
      },
      plan: initialPlan(),
      candidateRequest,
      candidatePreview: passingPreview(),
      planningIssue: null,
      registeredPlan: null,
    },
  }
  await page.addInitScript(({ state, url, token }) => {
    history.replaceState({ usr: state, key: 'segment-route-e2e', idx: 0 }, '', url)
    sessionStorage.setItem(`organizer-token:${state.tripId}`, token)
  }, { state: initialState, url: `/workspace?tripId=${tripId}`, token: organizerToken })
  await page.goto(`/workspace?tripId=${tripId}`, { waitUntil: 'domcontentloaded' })
}

async function mockWorkspaceFacts(page: Page) {
  await page.route(`**/api/v1/trips/${tripId}`, async (routeRequest) => {
    await routeRequest.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({ tripId, tripStatus: 'PLAN_REVIEW', currentPlan: null, proposedPlans: [], events: [], actualBudget: null }),
    })
  })
  await page.route(`**/api/v1/trips/${tripId}/planning-facts`, async (routeRequest) => {
    await routeRequest.fulfill({ status: 200, contentType: 'application/json', body: api(candidateRequest) })
  })
}

test('switching one segment replaces its route and refreshes the visible timeline summary', async ({ page }) => {
  const routeRequests: Array<{ mode: string; organizerToken: string | null }> = []
  const requestOrder: string[] = []
  await mockWorkspaceFacts(page)
  await page.route('**/api/v1/routes/plan', async (routeRequest) => {
    const body = routeRequest.request().postDataJSON() as { mode: string }
    routeRequests.push({ mode: body.mode, organizerToken: await routeRequest.request().headerValue('X-Organizer-Token') })
    requestOrder.push('route')
    await routeRequest.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({ cityCode: '110000', routes: [route(1, 'DRIVING', 980, 1800)], provenance }),
    })
  })
  await page.route(`**/api/v1/trips/${tripId}/plan-previews/validate`, async (routeRequest) => {
    requestOrder.push('preview')
    await routeRequest.fulfill({ status: 200, contentType: 'application/json', body: api(passingPreview()) })
  })

  await openWorkspace(page)
  const timeline = page.locator('.timeline-panel')
  await expect(timeline.getByRole('heading', { name: '河畔展馆' })).toBeVisible()
  await expect(timeline.getByText('步行 500 米', { exact: true })).toBeVisible()

  const segment = page.locator('.provider-route-evidence').nth(1)
  const targetHeights = await segment.getByRole('button').evaluateAll((buttons) =>
    buttons.map((button) => Math.round(button.getBoundingClientRect().height)),
  )
  expect(targetHeights.every((height) => height >= 44)).toBe(true)
  await segment.getByRole('button', { name: '打车路线' }).click()

  await expect(segment).toContainText('驾车 980 米')
  await expect(page.getByText('驾车 980 米 · 约30 分钟', { exact: true })).toBeVisible()
  await expect(page.getByText('全天步行').locator('..')).toContainText('1.08 km')
  await expect(timeline.getByRole('heading', { name: '晨光博物馆' })).toBeVisible()
  await expect(timeline.getByRole('heading', { name: '河畔展馆' })).toBeVisible()
  await expect(timeline.getByRole('heading', { name: '返回确认终点' })).toBeVisible()
  expect(routeRequests).toEqual([{ mode: 'DRIVING', organizerToken }])
  expect(requestOrder).toEqual(['route', 'preview'])
})

test('a provider failure keeps the visible route and retries the requested mode', async ({ page }) => {
  const attemptedModes: string[] = []
  await mockWorkspaceFacts(page)
  await page.route('**/api/v1/routes/plan', async (routeRequest) => {
    const body = routeRequest.request().postDataJSON() as { mode: string }
    attemptedModes.push(body.mode)
    if (attemptedModes.length === 1) {
      await routeRequest.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 'PROVIDER_ROUTE_UNAVAILABLE', message: '驾车服务暂不可用' }) })
      return
    }
    await routeRequest.fulfill({ status: 200, contentType: 'application/json', body: api({ cityCode: '110000', routes: [route(1, 'DRIVING', 980, 1800)], provenance }) })
  })
  await page.route(`**/api/v1/trips/${tripId}/plan-previews/validate`, async (routeRequest) => {
    await routeRequest.fulfill({ status: 200, contentType: 'application/json', body: api(passingPreview()) })
  })

  await openWorkspace(page)
  const segment = page.locator('.provider-route-evidence').nth(1)
  await segment.getByRole('button', { name: '打车路线' }).click()

  await expect(segment).toContainText('步行 500 米')
  await expect(segment.getByRole('button', { name: '重试这段路线' })).toBeVisible()
  await segment.getByRole('button', { name: '重试这段路线' }).click()
  await expect(segment).toContainText('驾车 980 米')
  expect(attemptedModes).toEqual(['DRIVING', 'DRIVING'])
})
