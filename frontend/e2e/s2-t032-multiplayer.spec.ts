import { expect, test, type Page } from '@playwright/test'

const INVITATION_TOKEN = 'm'.repeat(43)
const PARTICIPANT_SESSION = 'local-t032-participant-session'

const memberSession = {
  schemaVersion: '1.0',
  tripId: '10000000-0000-4000-8000-000000000032',
  participantId: '20000000-0000-4000-8000-000000000032',
  currentRevision: 3,
  collaborationVersion: 7,
  sharedTrip: {
    cityName: '杭州市',
    travelDate: '2026-09-06',
    startTime: '09:00',
    endTime: '20:00',
    startLocationText: '杭州东站',
    endLocationText: '杭州东站',
    budgetCents: 60_000,
  },
  participant: {
    memberKey: 'member-2',
    nickname: '成员乙',
    budgetCapCents: 25_000,
    interests: ['园林', '美食'],
    mustVisit: ['西湖'],
    avoidPlaces: ['拥挤商场'],
    careDraft: {
      assistanceTypeHint: 'LOW_STAMINA',
      childAge: null,
      walkLimits: { maxContinuousMeters: 500, maxDailyMeters: 3_000 },
      maxTransfers: 2,
      restIntervalMinutes: 60,
      napWindow: null,
      avoidStairs: false,
    },
  },
  accessStatus: 'SESSION_ACTIVE',
  confirmationStatus: 'DRAFT',
  confirmationItems: [],
}

function api(data: unknown) {
  return JSON.stringify({ code: 200, message: 'OK', data })
}

async function mockValidMemberInvitation(page: Page) {
  await page.route('**/api/v2/participant-invitations/redeem', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({
        tripId: memberSession.tripId,
        participantId: memberSession.participantId,
        participantSessionToken: PARTICIPANT_SESSION,
        sessionTokenAvailable: true,
        expiresAt: '2026-09-06T12:00:00Z',
      }),
    })
  })
  await page.route('**/api/v2/member-session', async (route) => {
    expect(route.request().headers()['x-participant-session']).toBe(PARTICIPANT_SESSION)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api(memberSession),
    })
  })
}

async function assertResponsiveContract(page: Page) {
  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1)

  const undersized = await page
    .locator('button:visible, a[href]:visible, [role="button"]:visible')
    .evaluateAll((elements) => elements.flatMap((element) => {
      if (
        (element instanceof HTMLButtonElement && element.disabled) ||
        element.getAttribute('aria-disabled') === 'true'
      ) return []
      const rect = element.getBoundingClientRect()
      if (rect.width + 0.01 >= 44 && rect.height + 0.01 >= 44) return []
      return [{
        label: (element.textContent || element.getAttribute('aria-label') || element.tagName).trim(),
        width: rect.width,
        height: rect.height,
      }]
    }))
  expect(undersized).toEqual([])
}

async function assertReducedMotionContract(page: Page) {
  const audit = await page.locator('html, body, body *').evaluateAll((elements) => {
    const seconds = (value: string) => {
      const parsed = Number.parseFloat(value)
      if (!Number.isFinite(parsed)) return 0
      return value.trim().endsWith('ms') ? parsed / 1_000 : parsed
    }
    const durations = (value: string) => value.split(',').map(seconds)
    const offenders: Array<{
      target: string
      pseudo: string
      animation: number
      transition: number
      iterations: string
    }> = []

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
        const infinite = style.animationName !== 'none' &&
          style.animationIterationCount.split(',').some((value) => value.trim() === 'infinite')
        if (animation > 0.001 || transition > 0.001 || infinite) {
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
      scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
      offenders: offenders.slice(0, 20),
    }
  })
  expect(audit.scrollBehavior).toBe('auto')
  expect(audit.offenders).toEqual([])
}

async function assertSharedQuestionIsReadOnly(
  page: Page,
  questionNumber: number,
  expectedText: string,
) {
  await expect(page.getByText(`问题 ${questionNumber} / 6`)).toBeVisible()
  const sharedFacts = page.getByRole('group', {
    name: '组织者已确认的共享行程，只读',
  })
  await expect(sharedFacts).toContainText(expectedText)
  await expect(sharedFacts.locator('input, textarea, select')).toHaveCount(0)
  await expect(page.locator('.draft-confirmation > textarea')).toHaveCount(0)
}

test.describe('S2-T032 local mocked multiplayer UI contract', () => {
  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
  })

  test('shared questions stay read-only and personal questions stay editable', async ({ page }) => {
    await mockValidMemberInvitation(page)
    await page.goto(`/join/${INVITATION_TOKEN}`)

    await expect(page.getByRole('heading', { name: '填写你的旅行偏好' })).toBeVisible()
    await expect(page.getByText('你只能读取和修改自己的成员资料')).toBeVisible()
    await assertSharedQuestionIsReadOnly(page, 1, '杭州市')
    await assertResponsiveContract(page)
    await assertReducedMotionContract(page)

    await page.getByRole('button', { name: /下一个问题/ }).click()
    await assertSharedQuestionIsReadOnly(page, 2, '同行人数与组织者由创建者管理')

    await page.getByRole('button', { name: /下一个问题/ }).click()
    await assertSharedQuestionIsReadOnly(page, 3, '杭州东站')

    await page.getByRole('button', { name: /下一个问题/ }).click()
    const personalAnswer = page.locator('.draft-confirmation > textarea')
    await expect(page.getByText('问题 4 / 6')).toBeVisible()
    await expect(personalAnswer).toBeEditable()
    await personalAnswer.fill('我喜欢园林，西湖必去，并避开拥挤商场。')

    await page.getByRole('button', { name: /下一个问题/ }).click()
    await expect(page.getByText('问题 5 / 6')).toBeVisible()
    await expect(personalAnswer).toBeEditable()
    await personalAnswer.fill('个人预算上限 250 元，每 60 分钟休息一次。')

    await page.getByRole('button', { name: /下一个问题/ }).click()
    await expect(page.getByText('问题 6 / 6')).toBeVisible()
    await expect(personalAnswer).toBeEditable()
    await personalAnswer.fill('以上是我本人的需求，确认无误。')
    await expect(page.getByText('杭州市', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('共享预算').first()).toBeVisible()

    await assertResponsiveContract(page)
    await assertReducedMotionContract(page)
  })

  test('an expired invitation exposes a visible recovery error', async ({ page }) => {
    await page.route('**/api/v2/participant-invitations/redeem', async (route) => {
      await route.fulfill({
        status: 410,
        contentType: 'application/json',
        body: JSON.stringify({ code: 'INVITATION_EXPIRED', message: '邀请已过期或被撤销。' }),
      })
    })
    await page.goto(`/join/${INVITATION_TOKEN}`)

    await expect(page.getByRole('heading', { name: '此邀请不可用' })).toBeVisible()
    await expect(page.getByRole('alert')).toContainText('邀请已过期或被撤销')
    await expect(page.getByRole('link', { name: '返回行程创建页' })).toBeVisible()
    await assertResponsiveContract(page)
    await assertReducedMotionContract(page)
  })
})
