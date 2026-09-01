import { expect, test, type Page } from '@playwright/test'


const PASSWORD = 't013-account-password'

type Account = {
  displayName: string
  email: string
}

type SyncResponse = {
  data: {
    viewerRole: 'ORGANIZER' | 'MEMBER'
    visibleProfiles: Array<{
      nickname: string
      role: 'ORGANIZER' | 'MEMBER'
    }>
  }
}


async function assertNoHorizontalOverflow(page: Page) {
  const widths = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(widths.scrollWidth).toBeLessThanOrEqual(widths.clientWidth + 1)
}


function addDays(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}


async function registerAndSignOut(page: Page, account: Account) {
  await page.goto('/account')
  await page.getByRole('button', { name: '注册' }).click()
  await page.getByLabel('显示名称').fill(account.displayName)
  await page.getByLabel('邮箱').fill(account.email)
  await page.getByLabel('密码').fill(PASSWORD)
  await page.getByRole('button', { name: '创建账户' }).click()
  await expect(page.getByRole('heading', { name: account.email })).toBeVisible()
  await page.getByRole('button', { name: '退出' }).click()
  await expect(page.getByRole('heading', { name: '登录你的行知账户' })).toBeVisible()
}


async function login(page: Page, account: Account) {
  await page.getByLabel('邮箱').fill(account.email)
  await page.getByLabel('密码').fill(PASSWORD)
  await page.getByRole('button', { name: '登录账户' }).click()
}


async function readParentSync(
  page: Page,
  parentTripId: string,
  credential: 'organizer' | 'member',
): Promise<SyncResponse> {
  return page.evaluate(async ({ id, role }) => {
    const storageKey = role === 'organizer'
      ? `parent-trip-token:${id}`
      : `parent-trip-member-session:${id}`
    const value = window.sessionStorage.getItem(storageKey)
    if (!value) throw new Error(`missing ${role} parent-trip credential`)
    const header = role === 'organizer'
      ? { 'X-Parent-Trip-Token': value }
      : { 'X-Parent-Member-Session': value }
    const response = await window.fetch(`/api/v3/parent-trips/${id}/sync`, {
      credentials: 'include',
      headers: header,
    })
    if (!response.ok) throw new Error(`sync failed with HTTP ${response.status}`)
    return response.json() as Promise<SyncResponse>
  }, { id: parentTripId, role: credential })
}


for (const dayCount of [2, 3] as const) {
  test(`S3-T013 ${dayCount}-day flow covers two logins, polling, day entry and budget provenance`, async ({
    browser,
    page: organizer,
  }, testInfo) => {
    test.setTimeout(120_000)
    const suffix = `${dayCount}-${testInfo.project.name.replace(/[^a-zA-Z0-9]/g, '')}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    const title = `T013 ${dayCount} 日同行 ${suffix.slice(-6)}`
    const organizerAccount = {
      displayName: `T013 组织者 ${dayCount}日`,
      email: `t013-organizer-${suffix}@example.com`,
    }
    const memberAccount = {
      displayName: `T013 成员账号 ${dayCount}日`,
      email: `t013-member-${suffix}@example.com`,
    }
    const memberNickname = `T013 成员 ${dayCount}日`
    const startDate = dayCount === 2 ? '2026-09-12' : '2026-09-19'
    const budgets = ['500', '600', '700']
    const memberContext = await browser.newContext({
      locale: 'zh-CN',
      reducedMotion: 'reduce',
      viewport: dayCount === 2
        ? { width: 375, height: 812 }
        : { width: 768, height: 1024 },
    })

    try {
      await registerAndSignOut(organizer, organizerAccount)
      await login(organizer, organizerAccount)
      await expect(organizer.getByRole('heading', { name: organizerAccount.email })).toBeVisible()
      await organizer.screenshot({
        path: testInfo.outputPath(`${dayCount}-day-organizer-login.png`),
        fullPage: true,
      })

      await organizer.goto('/parent-trips/new')
      await organizer.getByLabel('行程名称').fill(title)
      await organizer.getByLabel('城市').selectOption('北京')
      await organizer.getByLabel('开始日期').fill(startDate)
      await organizer.getByLabel('天数').selectOption(String(dayCount))
      for (let index = 0; index < dayCount; index += 1) {
        await organizer.getByLabel(`第 ${index + 1} 天预算（元）`).fill(budgets[index])
      }
      await organizer.getByRole('button', { name: /创建父行程/ }).click()
      await expect(organizer).toHaveURL(/\/parent-trips\/[0-9a-f-]{36}$/)
      await expect(organizer.getByRole('heading', { name: title })).toBeVisible()
      const parentTripId = new URL(organizer.url()).pathname.split('/').at(-1)
      expect(parentTripId).toMatch(/^[0-9a-f-]{36}$/)
      if (!parentTripId) throw new Error('parent trip id was not created')

      await organizer.getByRole('button', { name: '生成成员邀请' }).click()
      const invitationInput = organizer.getByLabel('成员邀请链接')
      await expect(invitationInput).toBeVisible()
      const invitationUrl = await invitationInput.inputValue()

      const member = await memberContext.newPage()
      await registerAndSignOut(member, memberAccount)
      await member.goto(invitationUrl)
      await expect(member).toHaveURL(/\/account\?returnTo=%2Fparent-join$/)
      await login(member, memberAccount)
      await expect(member).toHaveURL(
        new RegExp(`/parent-trips/${parentTripId}/member$`),
      )
      await expect(member.getByRole('heading', { name: title })).toBeVisible()
      await member.getByLabel('昵称').fill(memberNickname)
      await member.getByLabel('兴趣标签').fill('园林，摄影')
      await member.getByLabel('个人预算上限（元）').fill('800')
      await member.getByRole('button', { name: '保存资料' }).click()
      await expect(member.getByText('版本 2')).toBeVisible()

      // The organizer stays on the page; this assertion is satisfied by the
      // fixed five-second short poll rather than a manual refresh.
      await expect(organizer.getByText(memberNickname, { exact: true })).toBeVisible({
        timeout: 8_500,
      })

      const organizerSync = await readParentSync(
        organizer,
        parentTripId,
        'organizer',
      )
      const memberSync = await readParentSync(member, parentTripId, 'member')
      expect(organizerSync.data.viewerRole).toBe('ORGANIZER')
      expect(organizerSync.data.visibleProfiles).toHaveLength(2)
      expect(organizerSync.data.visibleProfiles.map((profile) => profile.nickname)).toContain(
        memberNickname,
      )
      expect(memberSync.data.viewerRole).toBe('MEMBER')
      expect(memberSync.data.visibleProfiles).toEqual([
        expect.objectContaining({ nickname: memberNickname, role: 'MEMBER' }),
      ])
      await assertNoHorizontalOverflow(member)
      await member.screenshot({
        path: testInfo.outputPath(`${dayCount}-day-member-isolated-profile.png`),
        fullPage: true,
      })

      await organizer.screenshot({
        path: testInfo.outputPath(`${dayCount}-day-parent-collaboration.png`),
        fullPage: true,
      })
      await assertNoHorizontalOverflow(organizer)

      for (let index = 0; index < dayCount; index += 1) {
        await organizer.getByRole('button', { name: '创建当日行程' }).nth(index).click()
        await expect(organizer).toHaveURL(/\/plan\?/)
        const target = new URL(organizer.url())
        expect(target.pathname).toBe('/plan')
        expect(target.searchParams.get('parentTripId')).toBe(parentTripId)
        expect(target.searchParams.get('dayIndex')).toBe(String(index))
        expect(target.searchParams.get('city')).toBe('北京')
        expect(target.searchParams.get('budget')).toBe(String(Number(budgets[index]) * 100))
        await organizer.getByRole('button', { name: /单人创建/ }).click()
        await expect(organizer.getByLabel('目的城市')).toHaveValue('北京')
        await expect(organizer.getByLabel('出行日期')).toHaveValue(addDays(startDate, index))
        if (index === dayCount - 1) {
          await organizer.screenshot({
            path: testInfo.outputPath(`${dayCount}-day-child-trip-entry.png`),
            fullPage: true,
          })
        }
        await organizer.goto(`/parent-trips/${parentTripId}`)
        await expect(organizer.getByRole('heading', { name: title })).toBeVisible()
      }

      const nonPaymentRequests: string[] = []
      organizer.on('request', (request) => {
        if (request.method() !== 'GET') nonPaymentRequests.push(request.url())
      })
      await organizer.goto('/budget-ledger')
      await expect(organizer.getByRole('heading', { name: '北京周末关怀行程' })).toBeVisible()
      await expect(organizer.getByText('高德路线费用')).toBeVisible()
      await expect(organizer.getByText('场馆公开票价').first()).toBeVisible()
      await expect(organizer.locator('.ledger-status--realtime').first()).toHaveText('实时来源')
      await expect(organizer.locator('.ledger-status--estimated').first()).toHaveText('估算')
      await expect(organizer.locator('.ledger-status--unknown')).toHaveText('待确认')
      await expect(organizer.getByText('尚未取得费用')).toBeVisible()
      await organizer.getByRole('button', { name: '修正' }).first().click()
      await organizer.getByLabel('地铁与接驳 手动修正金额').fill(String(dayCount + 6.5))
      await organizer.getByRole('button', { name: '保存' }).click()
      await expect(organizer.getByRole('status')).toContainText('不会发起支付')
      expect(nonPaymentRequests.filter((url) => /payment|pay|order/i.test(url))).toEqual([])
      const ledgerCard = organizer.locator('.ledger-card')
      await ledgerCard.scrollIntoViewIfNeeded()
      await expect(ledgerCard).toHaveClass(/is-revealed/)
      await ledgerCard.locator('.ledger-table-wrap').evaluate((element) => {
        const sourceColumn = element.querySelector<HTMLElement>('thead th:nth-child(4)')
        element.scrollLeft = Math.max(0, (sourceColumn?.offsetLeft ?? 0) - 16)
      })
      await organizer.evaluate(() => window.scrollTo({ top: 0, behavior: 'auto' }))
      await assertNoHorizontalOverflow(organizer)
      await organizer.screenshot({
        path: testInfo.outputPath(`${dayCount}-day-budget-provenance.png`),
        fullPage: true,
      })
    } finally {
      await memberContext.close()
    }
  })
}
