import { expect, test, type Page } from '@playwright/test'

import {
  T024_TRIP_ID,
  recommendationBundle,
} from './s2-t024-fixtures'

const parentTripId = '70000000-0000-4000-8000-000000000013'
const firstChildTripId = '71000000-0000-4000-8000-000000000013'
const secondChildTripId = T024_TRIP_ID
const placeMemory = [
  {
    dayIndex: 0,
    date: '2026-09-06',
    childTripId: firstChildTripId,
    planId: '72000000-0000-4000-8000-000000000013',
    planStatus: 'CURRENT' as const,
    placeId: 'amap-palace-museum',
    placeName: '故宫博物院',
  },
  {
    dayIndex: 0,
    date: '2026-09-06',
    childTripId: firstChildTripId,
    planId: '72000000-0000-4000-8000-000000000013',
    planStatus: 'CURRENT' as const,
    placeId: 'amap-jingshan-park',
    placeName: '景山公园',
  },
]

function api(data: unknown) {
  return JSON.stringify({ code: 200, message: 'OK', data })
}

async function assertNoHorizontalOverflow(page: Page) {
  const widths = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(widths.scrollWidth).toBeLessThanOrEqual(widths.clientWidth + 1)
}

test('cross-day place memory is visible on parent and recommendation pages', async ({
  page,
}, testInfo) => {
  await page.addInitScript(({ parentId, childId }) => {
    window.sessionStorage.setItem(`parent-trip-token:${parentId}`, 'parent-token')
    window.sessionStorage.setItem(`organizer-token:${childId}`, 'organizer-token')
  }, { parentId: parentTripId, childId: secondChildTripId })

  await page.route(`**/api/v3/parent-trips/${parentTripId}/sync`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({
        schemaVersion: '1.0',
        parentTrip: {
          schemaVersion: '1.0',
          parentTripId,
          title: '北京跨日记忆验收',
          cityName: '北京',
          startDate: '2026-09-06',
          endDate: '2026-09-07',
          totalBudgetCents: 100_000,
          plannedCostCents: 18_000,
          actualSpentCents: null,
          days: [
            {
              dayIndex: 0, date: '2026-09-06', budgetCents: 50_000,
              childTripId: firstChildTripId, childBudgetCents: 50_000,
              plannedCostCents: 18_000, actualSpentCents: null,
              remainingBudgetCents: null, childStatus: 'CONFIRMED',
              costStatus: 'PLANNED',
            },
            {
              dayIndex: 1, date: '2026-09-07', budgetCents: 50_000,
              childTripId: secondChildTripId, childBudgetCents: 50_000,
              plannedCostCents: null, actualSpentCents: null,
              remainingBudgetCents: null, childStatus: 'PLAN_REVIEW',
              costStatus: 'NOT_AVAILABLE',
            },
          ],
          placeMemory,
        },
        syncVersion: 4,
        viewerRole: 'ORGANIZER',
        viewerParticipantId: '73000000-0000-4000-8000-000000000013',
        visibleProfiles: [{
          participantId: '73000000-0000-4000-8000-000000000013',
          role: 'ORGANIZER',
          accessStatus: 'ORGANIZER_ACTIVE',
          nickname: '组织者',
          interests: ['历史文化'],
          budgetCapCents: 100_000,
          profileVersion: 1,
          updatedAt: '2026-09-01T08:00:00Z',
        }],
        pollAfterSeconds: 5,
        changedAt: '2026-09-01T08:00:00Z',
      }),
    })
  })
  await page.route(`**/api/v2/trips/${secondChildTripId}/recommendations`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({ ...recommendationBundle, parentPlaceMemory: placeMemory }),
    })
  })

  await page.goto(`/parent-trips/${parentTripId}`, { waitUntil: 'domcontentloaded' })
  const parentMemory = page.getByLabel('跨日地点记忆')
  await expect(parentMemory).toBeVisible()
  await expect(parentMemory).toContainText('2 个地点已占用')
  await expect(parentMemory).toContainText('故宫博物院')
  await expect(parentMemory).toContainText('景山公园')
  await assertNoHorizontalOverflow(page)
  await page.screenshot({
    path: testInfo.outputPath('parent-place-memory.png'),
    fullPage: true,
  })

  await page.goto(
    `/recommendation/${secondChildTripId}?parentTripId=${parentTripId}&dayIndex=1`,
    { waitUntil: 'domcontentloaded' },
  )
  const recommendationMemory = page.getByLabel('本次跨日排除地点')
  await expect(recommendationMemory).toBeVisible()
  await expect(recommendationMemory).toContainText('已排除 2 个其他日期地点')
  await expect(recommendationMemory).toContainText('第 1 天 · 2026-09-06')
  const recommendationPanel = page.locator('.recommendation-panel')
  await expect(recommendationPanel).toHaveClass(/is-revealed/)
  await expect(recommendationPanel).toHaveCSS('filter', 'blur(0px)')
  await page.evaluate(() => document.fonts.ready)
  await assertNoHorizontalOverflow(page)
  await page.screenshot({
    path: testInfo.outputPath('recommendation-place-memory.png'),
    fullPage: true,
  })
})
