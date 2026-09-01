import { expect, test, type Page } from '@playwright/test'
import { futureDateValue } from '../src/services/tripTimeConstraints'
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
  await page.route('**/api/v1/account/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({
        userId: '90000000-0000-4000-8000-000000000024',
        email: 'acceptance@example.com',
        displayName: '验收用户',
        homeCity: '北京',
        interests: ['历史文化'],
      }),
    })
  })
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
  const candidate = recommendationBundle.candidates[index]
  const location = {
    longitude: 116.407387 + (index + 1) * 0.00015,
    latitude: 39.904179 + (index + 1) * 0.0001,
  }
  return {
    placeId: `place-${index + 1}`,
    name: candidate.name,
    address: `北京市测试路 ${index + 1} 号`,
    cityCode: '110000',
    adCode: '110101',
    location,
    category: candidate.category,
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

async function mockRecommendationRouteBuild(page: Page, routeDurationSeconds = 600) {
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
          durationSeconds: routeDurationSeconds,
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
  await page.route(`**/api/v1/trips/${T024_TRIP_ID}/plan-previews/validate`, async (route) => {
    generatedCandidate = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({
        schemaVersion: '1.0',
        validationStatus: 'PASS',
        metrics: {
          totalCostCents: 5000,
          knownTotalCostCents: 5000,
          unknownAmountCount: 0,
          budgetLimitCents: 35000,
          knownBudgetBufferCents: 30000,
          totalWalkMeters: 720,
          transferCount: 0,
          validationStatus: 'PASS',
        },
        constraintResults: [],
        warnings: [],
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
  await page.route(`**/api/v1/trips/${T024_TRIP_ID}/memory-timeline`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({
        schemaVersion: '1.0',
        tripId: T024_TRIP_ID,
        summary: {
          completedTaskCount: 3,
          skippedTaskCount: 0,
          totalTaskCount: 3,
          completionRatePercent: 100,
          plannedCostCents: 35000,
          actualCostCents: 32000,
          costDifferenceCents: -3000,
          currency: 'CNY',
          currentPlanVersion: 2,
          planChangeCount: 1,
          photoCount: 0,
          participantCareResults: [],
          assistanceProfile: null,
        },
        items: [],
      }),
    })
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
  await installSession(page)
  let ready = false
  const conversationRequests: Array<{ answers: Array<{ questionId: string; answer: string }> }> = []
  const routeAudit = await mockRecommendationRouteBuild(page)
  await page.route('**/api/v2/trips/conversations', async (route) => {
    conversationRequests.push(route.request().postDataJSON())
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
  await page.getByRole('button', { name: /开始回答 5 个问题/ }).click()
  await page.getByLabel('目的城市').fill('北京')
  const travelDate = futureDateValue()
  await page.getByLabel('出发日期').fill(travelDate)
  await page.getByLabel('结束日期').fill(travelDate)
  await page.getByRole('button', { name: /下一个问题/ }).click()
  await page.getByLabel('出发地').fill('北京站')
  await page.getByLabel('结束地').fill('北京站')
  await page.getByRole('button', { name: /下一个问题/ }).click()
  await page.locator('.conversation-textarea--answer').fill('喜欢历史文化，没有必去和避开地点。')
  await page.getByRole('button', { name: /下一个问题/ }).click()
  await page.getByLabel('个人预算上限（元）').fill('350')
  await page.getByRole('button', { name: /下一个问题/ }).click()
  await page.locator('.conversation-textarea--answer').fill('以上信息正确。')
  await page.getByRole('button', { name: /完成问答并智能整理/ }).click()
  await expect(page.getByText('智能整理完成')).toBeVisible()
  expect(conversationRequests[0].answers[0].answer).toContain('出行时间：08:30到21:00')

  await page.getByRole('button', { name: '调整时间' }).click()
  await page.getByLabel('开始时间').fill('10:00')
  await page.getByLabel('结束时间').fill('19:00')
  await page.getByRole('button', { name: '应用并重新整理' }).click()
  await expect.poll(() => conversationRequests.length).toBe(2)
  expect(conversationRequests[1].answers[0].answer).toContain('出行时间：10:00到19:00')

  await page.getByRole('button', { name: /确认并生成推荐方案/ }).click()
  await expect.poll(() => page.evaluate((tripId) => Boolean(window.sessionStorage.getItem(`s2-plan-context:${tripId}`)), T024_TRIP_ID)).toBe(true)
  await expect(page).toHaveURL(new RegExp(`/recommendation/${T024_TRIP_ID}$`))
  await expect(page.getByRole('heading', { name: '推荐方案' })).toBeVisible()
  await page.getByRole('combobox', { name: '第 1 个地点', exact: true }).selectOption('place-fact-6')
  await page.getByRole('button', { name: '将第 2 个地点上移' }).click()
  await expect(page.getByRole('combobox', { name: '第 1 个地点', exact: true })).toHaveValue('place-fact-1')
  await expect(page.getByRole('combobox', { name: '第 2 个地点', exact: true })).toHaveValue('place-fact-6')
  await expect(page.getByRole('combobox', { name: '第 3 个地点', exact: true })).toHaveValue('place-fact-2')
  await expect(page.getByRole('combobox', { name: '第 4 个地点', exact: true })).toHaveValue('place-fact-4')
  await expect(page.getByRole('combobox', { name: '第 5 个地点', exact: true })).toHaveValue('place-fact-5')
  await page.getByRole('button', { name: /确认此方案/ }).click()
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
  await expect(page.getByText('关怀校验', { exact: true })).toHaveCount(0)
  await expect(page.getByText('LIVE EXECUTION · CONTINUOUS PLAN', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '计划工作台' }).click()
  await expect(page.getByRole('heading', { name: '今天的路线' })).toBeVisible()
  const timelineTasks = page.locator('.timeline-item')
  const routePickers = page.locator('.route-mode-picker')
  const visibleTaskCount = await timelineTasks.count()
  expect(visibleTaskCount).toBeGreaterThan(0)
  await expect(routePickers).toHaveCount(visibleTaskCount)
  for (const picker of await routePickers.all()) {
    await expect(picker.getByRole('button', { name: '自驾', exact: true })).toBeVisible()
    await expect(picker.getByRole('button', { name: '骑行', exact: true })).toBeVisible()
    await expect(picker.getByRole('button', { name: '打车', exact: true })).toBeVisible()
  }
  await expect(page.locator('.route-price-summary')).toContainText('共享单车每 15 分钟 ¥1.50 估算')
  await expect(page.locator('.route-price-summary')).toContainText('采用高德出租车估价')
  await expect(page.locator('.route-price-summary')).toContainText('只计高速/道路收费')
  expect(routeAudit.placeSearchCalls()).toBe(0)
  expect(
    routeAudit.generatedCandidate()?.taskFacts?.map((item) => item.place?.placeId),
  ).toEqual([
    'place-1',
    'place-6',
    'place-2',
    'place-4',
    'place-5',
    expect.stringMatching(/^return-/),
  ])
  expect(routeAudit.generatedCandidate()?.taskFacts).toMatchObject([
    { category: '历史文化' },
    { category: '历史文化' },
    { category: 'MEAL_LUNCH', startAt: '12:00', endAt: '13:00' },
    { category: '历史文化' },
    { category: 'MEAL_DINNER', startAt: '18:00', endAt: '19:00' },
    { category: 'RETURN' },
  ])
  const trace = await page.evaluate(
    (tripId) => JSON.parse(window.sessionStorage.getItem(`s2-recommendation-trace:${tripId}`) || 'null'),
    T024_TRIP_ID,
  )
  expect(trace).toMatchObject({
    factSetId: recommendationBundle.factSetId,
    providerFactDigest: recommendationBundle.providerFactDigest,
    selectedPlaces: [
      { factRefId: 'place-fact-1', placeId: 'place-1' },
      { factRefId: 'place-fact-6', placeId: 'place-6' },
      { factRefId: 'place-fact-2', placeId: 'place-2' },
      { factRefId: 'place-fact-4', placeId: 'place-4' },
      { factRefId: 'place-fact-5', placeId: 'place-5' },
    ],
  })
  await assertResponsiveContract(page)
})

test('editable recommendation remains readable and survives account navigation', async ({ page }) => {
  await installSession(page)
  let recommendationCalls = 0
  await page.route('**/api/v1/account/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({
        userId: '90000000-0000-4000-8000-000000000024',
        email: 'acceptance@example.com',
        displayName: '验收用户',
        homeCity: '北京',
        interests: ['历史文化'],
      }),
    })
  })
  await page.route(`**/api/v2/trips/${T024_TRIP_ID}/recommendations`, async (route) => {
    recommendationCalls += 1
    const response = recommendationCalls === 1
      ? recommendationBundle
      : {
          ...recommendationBundle,
          factSetId: 'fact-set-that-must-not-replace-the-edited-session',
          providerFactDigest: 'd'.repeat(64),
          trustedPlan: {
            ...recommendationBundle.trustedPlan,
            tasks: recommendationBundle.candidates.slice(1, 4),
          },
        }
    await route.fulfill({ status: 200, contentType: 'application/json', body: api(response) })
  })
  await page.goto(`/recommendation/${T024_TRIP_ID}`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '推荐方案' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '行程地点' })).toBeVisible()
  await expect(page.locator('.recommendation-location option').first()).not.toContainText('（历史文化）')
  await expect(page.getByRole('button', { name: '返回上一个页面' })).toHaveCount(0)
  await expect(page.getByText(/FactRef|最低成员分|扣分规则|未知事实/)).toHaveCount(0)
  await page.getByRole('combobox', { name: '第 1 个地点', exact: true }).selectOption('place-fact-6')

  const account = page.getByRole('link', { name: '验收用户的账户' })
  await expect(account).toHaveAttribute(
    'href',
    `/account?returnTo=${encodeURIComponent(`/recommendation/${T024_TRIP_ID}`)}`,
  )
  await account.click()
  await expect(page).toHaveURL(new RegExp(`/recommendation/${T024_TRIP_ID}$`))
  await expect(page.getByRole('combobox', { name: '第 1 个地点', exact: true })).toHaveValue('place-fact-6')
  expect(recommendationCalls).toBe(1)
  await assertResponsiveContract(page)
})

test('an itinerary that cannot fit opens a clear route-distance dialog and remains editable', async ({ page }) => {
  await installSession(page)
  const routeAudit = await mockRecommendationRouteBuild(page, 10 * 60 * 60)
  await page.route(`**/api/v2/trips/${T024_TRIP_ID}/recommendations`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api(recommendationBundle),
    })
  })

  await page.goto(`/recommendation/${T024_TRIP_ID}`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: /确认此方案/ }).click()
  await page.getByRole('button', { name: /生成完整路线/ }).click()

  const dialog = page.getByRole('alertdialog', { name: '方案暂时无法生成' })
  await expect(dialog).toBeVisible({ timeout: 20_000 })
  await expect(dialog).toContainText(
    '地点之间路程较远，无法在 09:00–20:00 的规定时间内完成。',
  )
  expect(routeAudit.generatedCandidate()).toBeNull()
  await assertResponsiveContract(page)
  await dialog.getByRole('button', { name: '返回调整地点' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('combobox', { name: '第 1 个地点', exact: true })).toBeEnabled()
})

for (const fixture of [
  { kind: 'execute' as const, expected: '执行旅程' },
  { kind: 'diff' as const, expected: 'Plan V2' },
  { kind: 'summary' as const, expected: '真实旅程时间线' },
]) {
  test(`mocked ${fixture.kind} fixture stays responsive (UI contract only)`, async ({ page }) => {
    await installSession(page)
    await mockWorkspace(page, fixture.kind)
    await page.goto(`/workspace?tripId=${T024_TRIP_ID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText(fixture.expected, { exact: false }).first()).toBeVisible()
    if (fixture.kind === 'execute') {
      await expect(page.getByText('调整后续行程', { exact: true })).toBeVisible()
      await page.getByRole('button', { name: '迟到', exact: true }).click()
      await page.getByLabel('自定义迟到分钟数').fill('45')
      await expect(page.getByRole('button', { name: '确认并生成 Plan V2 预览' })).toBeEnabled()
      await assertResponsiveContract(page)
      await page.getByRole('button', { name: '计划工作台' }).click()
      const timeSortLabel = page.getByText('按时间', { exact: true })
      await expect(timeSortLabel).toBeVisible()
      expect(await timeSortLabel.evaluate((element) => element.tagName)).toBe('SPAN')
      await expect(timeSortLabel.locator('svg')).toHaveCount(0)
      await expect(page.getByText('问问 Agent', { exact: true })).toHaveCount(0)
      const displayedTimes = await page.locator('.timeline-item__time').allTextContents()
      expect(displayedTimes.length).toBeGreaterThan(0)
      expect(displayedTimes.every((value) => !/\d{2}:\d{2}:\d{2}/.test(value))).toBe(true)
    }
    await assertResponsiveContract(page)
  })
}

test('reduced-motion audit scans every rendered element and pseudo-element', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/plan', { waitUntil: 'domcontentloaded' })
  await assertReducedMotionContract(page)
})
