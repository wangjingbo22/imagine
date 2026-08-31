import { expect, test, type Page } from '@playwright/test'
import {
  T024_TRIP_ID,
  T024_V2_ID,
  collaborationState,
  currentPlanV1,
  organizerConversation,
  planDiff,
  recommendationBundle,
  tripSnapshot,
  tripState,
  tripSummary,
} from './s2-t024-fixtures'

function api(data: unknown) {
  return JSON.stringify({ code: 200, message: 'OK', data })
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
})

async function installSession(page: Page) {
  await page.addInitScript((tripId) => {
    window.sessionStorage.setItem(`organizer-token:${tripId}`, 't024-browser-only-token')
  }, T024_TRIP_ID)
}

async function assertResponsiveContract(page: Page) {
  await page.waitForLoadState('domcontentloaded')
  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1)

  const undersized = await page.locator('button:visible, a[href]:visible, [role="button"]:visible').evaluateAll((elements) =>
    elements.flatMap((element) => {
      if (
        (element instanceof HTMLButtonElement && element.disabled) ||
        element.getAttribute('aria-disabled') === 'true'
      ) return []
      const rect = element.getBoundingClientRect()
      const text = (element.textContent || element.getAttribute('aria-label') || element.className).trim()
      return rect.width + 0.01 < 44 || rect.height + 0.01 < 44
        ? [{ text, width: rect.width, height: rect.height }]
        : []
    }),
  )
  expect(undersized).toEqual([])
  await page.keyboard.press('Tab')
  const keyboardFocus = await page.locator(':focus').evaluate((element) => {
    const style = getComputedStyle(element)
    return {
      tagName: element.tagName,
      outlineStyle: style.outlineStyle,
      outlineWidth: Number.parseFloat(style.outlineWidth),
    }
  })
  expect(['BUTTON', 'A', 'INPUT', 'TEXTAREA']).toContain(keyboardFocus.tagName)
  expect(keyboardFocus.outlineStyle).not.toBe('none')
  expect(keyboardFocus.outlineWidth).toBeGreaterThan(0)
  await assertReducedMotionContract(page)
}

async function assertReducedMotionContract(page: Page) {
  const audit = await page.locator('html, body, body *').evaluateAll((elements) => {
    const seconds = (value: string) => {
      const parsed = Number.parseFloat(value)
      if (!Number.isFinite(parsed)) return 0
      return value.trim().endsWith('ms') ? parsed / 1000 : parsed
    }
    const durations = (value: string) => value.split(',').map(seconds)
    const offenders: Array<{ target: string; pseudo: string; animation: number; transition: number; iterations: string }> = []
    let maximumDuration = 0

    for (const element of elements) {
      if (!(element instanceof HTMLElement) || (
        element !== document.documentElement &&
        element !== document.body &&
        element.getClientRects().length === 0
      )) continue
      for (const pseudo of ['', '::before', '::after']) {
        const style = getComputedStyle(element, pseudo || null)
        const animation = Math.max(0, ...durations(style.animationDuration))
        const transition = Math.max(0, ...durations(style.transitionDuration))
        maximumDuration = Math.max(maximumDuration, animation, transition)
        const hasInfiniteIteration = style.animationName !== 'none' &&
          style.animationIterationCount.split(',').some((value) => value.trim() === 'infinite')
        if (animation > 0.001 || transition > 0.001 || hasInfiniteIteration) {
          offenders.push({
            target: element.id || element.className || element.tagName.toLowerCase(),
            pseudo: pseudo || 'element',
            animation,
            transition,
            iterations: style.animationIterationCount,
          })
        }
      }
    }
    return {
      maximumDuration,
      offenders: offenders.slice(0, 20),
      documentScrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
    }
  })
  expect(audit.documentScrollBehavior).toBe('auto')
  expect(audit.maximumDuration).toBeLessThanOrEqual(0.001)
  expect(audit.offenders).toEqual([])
}

const providerProvenance = {
  provider: 'AMAP', sourceStatus: 'ONLINE', fetchedAt: '2026-09-05T01:00:00Z', isStale: false,
}

const providerPlaces = Array.from({ length: 8 }, (_, index) => {
  const location = {
    longitude: 116.407387 + (index + 1) * 0.00015,
    latitude: 39.904179 + (index + 1) * 0.0001,
  }
  return {
    placeId: `place-${index + 1}`,
    name: `高德核验地点 ${index + 1}`,
    address: `北京市测试路 ${index + 1} 号`,
    cityCode: '110000',
    adCode: '110101',
    location,
    category: '历史文化',
    telephone: null,
    rating: 4.6,
    priceReference: {
      amountCents: 1000,
      currency: 'CNY',
      kind: 'ticket',
      provenance: providerProvenance,
    },
    provenance: providerProvenance,
  }
})

async function mockRecommendationRouteBuild(page: Page) {
  let generatedCandidate: unknown = null
  let placeSearchCalls = 0
  await page.route(`**/api/v2/trips/${T024_TRIP_ID}/planning-trip`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(tripSnapshot) })
  })
  await page.route('**/api/v1/cities/resolve', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({ cityContext: tripSnapshot.cityContext, adCode: '110101', formattedAddress: '北京市', provenance: providerProvenance }),
    })
  })
  await page.route('**/api/v1/geocoding/forward', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({
        formattedAddress: '北京市北京站',
        cityCode: '110000',
        adCode: '110101',
        location: tripSnapshot.cityContext.center,
        provenance: providerProvenance,
      }),
    })
  })
  await page.route('**/api/v1/trips/*/provider-fact-sets/*/places**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({
        schemaVersion: '1.0',
        factSetId: recommendationBundle.factSetId,
        providerFactDigest: recommendationBundle.providerFactDigest,
        tripId: T024_TRIP_ID,
        places: recommendationBundle.candidates.map((candidate, index) => ({
          factRefId: candidate.factRefId,
          providerObjectId: candidate.placeId,
          payloadDigest: `${index + 1}`.repeat(64),
          place: providerPlaces[index],
        })),
      }),
    })
  })
  await page.route('**/api/v1/places/search', async (route) => {
    placeSearchCalls += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({ cityCode: '110000', total: providerPlaces.length, places: providerPlaces, provenance: providerProvenance }),
    })
  })
  await page.route('**/api/v1/routes/plan', async (route) => {
    const request = route.request().postDataJSON() as {
      origin: { longitude: number; latitude: number }
      destination: { longitude: number; latitude: number }
      mode: 'WALKING' | 'TRANSIT' | 'DRIVING' | 'BICYCLING'
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({
        cityCode: '110000',
        routes: [{
          routeId: `fixture-${request.mode}-${request.destination.longitude}`,
          mode: request.mode,
          origin: request.origin,
          destination: request.destination,
          distanceMeters: 120,
          durationSeconds: 600,
          walkingDistanceMeters: request.mode === 'TRANSIT' ? 120 : null,
          transferCount: request.mode === 'TRANSIT' ? 0 : null,
          steps: [],
          facilityEvidence: [],
          priceReference: { amountCents: 0, currency: 'CNY', kind: 'route', provenance: providerProvenance },
          provenance: providerProvenance,
        }],
        provenance: providerProvenance,
      }),
    })
  })
  await page.route(`**/api/v1/trips/${T024_TRIP_ID}/plan-versions/generate`, async (route) => {
    generatedCandidate = route.request().postDataJSON()
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(currentPlanV1) })
  })
  await page.route(`**/api/v1/trips/${T024_TRIP_ID}/planning-facts`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(generatedCandidate) })
  })
  await page.route(`**/api/v1/trips/${T024_TRIP_ID}`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(tripState('execute')) })
  })
  return {
    generatedCandidate: () => generatedCandidate as { taskFacts?: Array<{ place?: { placeId?: string } }> } | null,
    placeSearchCalls: () => placeSearchCalls,
  }
}

async function mockWorkspace(page: Page, kind: 'execute' | 'diff' | 'summary') {
  await page.route(`**/api/v1/trips/${T024_TRIP_ID}`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(tripState(kind)) })
  })
  await page.route(`**/api/v1/trips/${T024_TRIP_ID}/planning-facts`, async (route) => {
    await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ code: 'PLANNING_FACTS_NOT_FOUND', message: 'fixture intentionally omits provider payload' }) })
  })
  await page.route(`**/api/v1/trips/${T024_TRIP_ID}/plan-versions/${T024_V2_ID}/diff`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(planDiff) })
  })
  await page.route(`**/api/v1/trips/${T024_TRIP_ID}/summary`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(tripSummary) })
  })
  await page.route(`**/api/v2/trips/${T024_TRIP_ID}/tasks/*/media`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(null) })
  })
}

test('six-question entry has no horizontal overflow and reachable actions', async ({ page }) => {
  await page.goto('/plan', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: /对话|旅行/ })).toBeVisible()
  await assertResponsiveContract(page)
})

test('mocked single-person UI integration confirms the recommendation and enters the workspace', async ({ page }) => {
  let ready = false
  const routeAudit = await mockRecommendationRouteBuild(page)
  await page.route('**/api/v2/trips/conversations', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(organizerConversation) })
  })
  await page.route(`**/api/v2/trips/${T024_TRIP_ID}/collaboration`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(collaborationState(ready)) })
  })
  await page.route(`**/api/v2/trips/${T024_TRIP_ID}/participants/*/confirm`, async (route) => {
    ready = true
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(collaborationState(true)) })
  })
  await page.route(`**/api/v2/trips/${T024_TRIP_ID}/recommendations`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(recommendationBundle) })
  })

  await page.goto('/plan', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: /单人创建/ }).click()
  await page.getByLabel('这趟旅行，你最希望得到什么？').fill('想轻松游览北京的历史文化景点。')
  await page.getByLabel('目的城市').fill('北京')
  await page.getByLabel('出行日期').fill('2026-09-05')
  await page.getByLabel('开始').fill('09:00')
  await page.getByLabel('结束').fill('20:00')
  await page.getByRole('button', { name: /下一个问题/ }).click()
  await page.getByRole('button', { name: /下一个问题/ }).click()
  await page.getByLabel('出发地').fill('北京站')
  await page.getByLabel('结束地').fill('北京站')
  await page.getByLabel('共享预算').fill('350元')
  await page.getByRole('button', { name: /下一个问题/ }).click()
  await page.locator('.conversation-textarea--answer').fill('喜欢历史文化，没有必去和避开地点。')
  await page.getByRole('button', { name: /下一个问题/ }).click()
  await page.locator('.conversation-textarea--answer').fill('预算上限350元，普通出行。')
  await page.getByRole('button', { name: /下一个问题/ }).click()
  await page.locator('.conversation-textarea--answer').fill('以上信息正确。')
  await page.getByRole('button', { name: /完成问答并智能整理/ }).click()
  await expect(page.getByText('Agent 解析确认卡')).toBeVisible()
  await page.getByRole('button', { name: /确认组织者资料/ }).click()
  const recommendation = page.getByRole('button', { name: /查看唯一推荐/ })
  await expect(recommendation).toBeVisible()
  await expect.poll(() => page.evaluate((tripId) => Boolean(window.sessionStorage.getItem(`s2-plan-context:${tripId}`)), T024_TRIP_ID)).toBe(true)
  await recommendation.click()
  await expect(page).toHaveURL(new RegExp(`/recommendation/${T024_TRIP_ID}$`))
  await expect(page.getByRole('heading', { name: '唯一推荐方案' })).toBeVisible()
  await page.getByRole('button', { name: /确认唯一方案/ }).click()
  const buildRoute = page.getByRole('button', { name: /生成完整路线/ })
  await expect(buildRoute).toBeVisible()
  await buildRoute.click()
  await expect(page).toHaveURL(
    new RegExp(`/workspace[?]tripId=${T024_TRIP_ID}$`),
    { timeout: 30_000 },
  )
  await expect(page.getByRole('heading', { name: /北京.*一日计划/ })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '行程视图' })).toBeVisible()
  await expect(page.getByRole('button', { name: '执行旅程' })).toBeVisible()
  expect(routeAudit.placeSearchCalls()).toBe(0)
  expect(
    routeAudit.generatedCandidate()?.taskFacts?.map((item) => item.place?.placeId),
  ).toEqual(['place-3', 'place-1', 'place-2', expect.stringMatching(/^return-/)])
  const trace = await page.evaluate(
    (tripId) => JSON.parse(window.sessionStorage.getItem(`s2-recommendation-trace:${tripId}`) || 'null'),
    T024_TRIP_ID,
  )
  expect(trace).toMatchObject({
    factSetId: recommendationBundle.factSetId,
    providerFactDigest: recommendationBundle.providerFactDigest,
    selectedPlaces: recommendationBundle.trustedPlan.tasks.map((item) => ({
      factRefId: item.factRefId,
      placeId: item.placeId,
    })),
  })
  await assertResponsiveContract(page)
})

test('unique recommendation remains readable at the acceptance viewport', async ({ page }) => {
  await installSession(page)
  await page.route(`**/api/v2/trips/${T024_TRIP_ID}/recommendations`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(recommendationBundle) })
  })
  await page.goto(`/recommendation/${T024_TRIP_ID}`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '唯一推荐方案' })).toBeVisible()
  await expect(page.getByText('最低成员分 92/100')).toBeVisible()
  await assertResponsiveContract(page)
})

for (const fixture of [
  { kind: 'execute' as const, expected: '执行旅程' },
  { kind: 'diff' as const, expected: 'Plan V2' },
  { kind: 'summary' as const, expected: '旅途回忆' },
]) {
  test(`mocked ${fixture.kind} fixture stays responsive (UI contract only)`, async ({ page }) => {
    await installSession(page)
    await mockWorkspace(page, fixture.kind)
    await page.goto(`/workspace?tripId=${T024_TRIP_ID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText(fixture.expected, { exact: false }).first()).toBeVisible()
    await assertResponsiveContract(page)
  })
}

test('reduced-motion audit scans every rendered element and pseudo-element', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/plan', { waitUntil: 'domcontentloaded' })
  await assertReducedMotionContract(page)
})
