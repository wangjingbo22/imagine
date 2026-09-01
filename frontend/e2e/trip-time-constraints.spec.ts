import { expect, test } from '@playwright/test'

import {
  futureDateValue,
  localDateValue,
} from '../src/services/tripTimeConstraints'

function api(data: unknown) {
  return JSON.stringify({ code: 200, message: 'OK', data })
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/account/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({
        userId: '90000000-0000-4000-8000-000000000031',
        email: 'time-window@example.com',
        displayName: '时间测试用户',
        homeCity: '北京',
        interests: [],
      }),
    })
  })
})

test('a protected planner revealed after account restoration remains visible', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.route('**/api/v1/account/me', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 150))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: api({
        userId: '90000000-0000-4000-8000-000000000031',
        email: 'time-window@example.com',
        displayName: '时间测试用户',
        homeCity: '北京',
        interests: [],
      }),
    })
  })
  await page.goto('/plan')

  const panel = page.locator('.conversation-panel')
  await expect(panel).toHaveClass(/is-revealed/)
  await expect(page.getByRole('button', { name: /单人创建/ })).toBeVisible()
})

test('parent day planning opens today expectation and omits inherited city and date', async ({ page }) => {
  const travelDate = futureDateValue()
  const parentTripId = '90000000-0000-4000-8000-000000000041'
  const baseParams = {
    parentTripId,
    dayIndex: '0',
    city: '北京',
    date: travelDate,
    budget: '50000',
  }

  await page.goto(`/plan?${new URLSearchParams({ ...baseParams, mode: 'single' })}`)
  await expect(page.getByRole('button', { name: /单人创建|多人创建/ })).toHaveCount(0)
  await expect(page.getByText('已有多人邀请？')).toHaveCount(0)
  await expect(page.getByText('先填写今天的期待', { exact: true })).toBeVisible()
  await page.getByLabel('今天，你最希望得到什么？').fill('今天想轻松看看北京的历史景点。')
  await page.getByRole('button', { name: /开始回答 4 个问题/ }).click()
  await expect(page.getByLabel('目的城市')).toHaveCount(0)
  await expect(page.getByText('问题 1 / 4')).toBeVisible()
  await expect(page.getByRole('heading', { name: '从哪里出发、最终回到哪里？' })).toBeVisible()
  await expect(page.getByLabel('当日预算（多日行程已分配）')).toHaveValue('500')

  await page.goto(`/plan?${new URLSearchParams({ ...baseParams, mode: 'group' })}`)
  await expect(page.getByText('先填写今天的期待', { exact: true })).toBeVisible()
  await page.getByLabel('今天，你最希望得到什么？').fill('今天希望大家走得轻松，也能兼顾共同兴趣。')
  await page.getByRole('button', { name: /开始回答 5 个问题/ }).click()
  await expect(page.getByLabel('目的城市')).toHaveCount(0)
  await expect(page.getByText('问题 1 / 5')).toBeVisible()
  await expect(page.getByRole('heading', { name: '一共几个人出行？谁是组织者？' })).toBeVisible()
})


test('single-day planner blocks past dates and hides the default time window', async ({ page }) => {
  const today = localDateValue()
  await page.goto('/plan')
  await page.getByRole('button', { name: /单人创建/ }).click()
  const startQuestions = page.getByRole('button', { name: /开始回答 5 个问题/ })
  await expect(startQuestions).toBeDisabled()
  await expect(page.getByLabel('目的城市')).toHaveCount(0)
  await page.getByLabel('这趟旅行，你最希望得到什么？').fill('想轻松游览北京的历史文化景点。')
  await expect(startQuestions).toBeEnabled()
  await startQuestions.click()
  await page.getByLabel('目的城市').fill('北京')

  const startDateInput = page.getByLabel('出发日期')
  const endDateInput = page.getByLabel('结束日期')
  await expect(startDateInput).toHaveAttribute('min', today)
  await expect(startDateInput).toHaveValue(today)
  await expect(endDateInput).toHaveValue(today)
  await expect(page.getByLabel('开始时间')).toHaveCount(0)
  await expect(page.getByLabel('结束时间')).toHaveCount(0)
  const tripInputs = page.locator('.question-field-cards--trip input')
  await expect(tripInputs).toHaveCount(3)
  for (const input of await tripInputs.all()) {
    expect(await input.evaluate((element) => element.getBoundingClientRect().width)).toBeGreaterThan(120)
  }
  await startDateInput.fill(futureDateValue(new Date(), -1))
  await expect(page.getByRole('alert')).toContainText('出发日期不能早于今天')
  await expect(page.getByRole('button', { name: /下一个问题/ })).toBeDisabled()

  const futureDate = futureDateValue()
  await startDateInput.fill(futureDate)
  await endDateInput.fill(today)
  await expect(page.getByRole('alert')).toContainText('结束日期不能早于出发日期')
  await expect(page.getByRole('button', { name: /下一个问题/ })).toBeDisabled()

  await endDateInput.fill(futureDate)
  await expect(page.getByText('系统默认按 08:30–21:00 规划，整理完成后仍可调整。')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /下一个问题/ })).toBeEnabled()

  await page.getByRole('button', { name: /下一个问题/ }).click()
  await expect(page.getByText('问题 2 / 5', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '从哪里出发、最终回到哪里？' })).toBeVisible()
  await expect(page.getByLabel('组织者昵称')).toHaveCount(0)
  await expect(page.getByLabel('共享预算')).toHaveCount(0)

  await page.getByLabel('出发地').fill('北京站')
  await page.getByLabel('结束地').fill('北京站')
  await page.getByRole('button', { name: /下一个问题/ }).click()
  await expect(page.getByText('问题 3 / 5', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '喜欢什么、必去哪里、希望避开什么？' })).toBeVisible()

  await page.locator('.conversation-textarea--answer').fill('喜欢历史文化，故宫必去，避开酒吧。')
  await page.getByRole('button', { name: /下一个问题/ }).click()
  await expect(page.getByText('问题 4 / 5', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '是否有预算上限、步行、换乘、休息或关怀需求？' })).toBeVisible()
})


test('group planner keeps party question and total trip budget', async ({ page }) => {
  const today = localDateValue()
  await page.goto('/plan?mode=group')

  await expect(page.getByText('问题 1 / 6', { exact: true })).toHaveCount(0)
  await page.getByLabel('这趟旅行，你最希望得到什么？').fill('和朋友轻松游览北京。')
  await page.getByRole('button', { name: /开始回答 6 个问题/ }).click()
  await expect(page.getByLabel('出发日期')).toHaveValue(today)
  await expect(page.getByLabel('结束日期')).toHaveValue(today)
  await expect(page.getByText('问题 1 / 6', { exact: true })).toBeVisible()
  await expect(page.getByText('出行时间', { exact: true })).toHaveCount(0)
  await page.getByLabel('目的城市').fill('北京')
  const futureDate = futureDateValue()
  await page.getByLabel('出发日期').fill(futureDate)
  await page.getByLabel('结束日期').fill(futureDate)
  await page.getByRole('button', { name: /下一个问题/ }).click()

  await expect(page.getByText('问题 2 / 6', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '一共几个人出行？谁是组织者？' })).toBeVisible()
  await page.getByLabel('组织者昵称').fill('小明')
  await page.getByRole('button', { name: /下一个问题/ }).click()

  await expect(page.getByText('问题 3 / 6', { exact: true })).toBeVisible()
  await expect(page.getByLabel('同行行程总预算')).toBeVisible()
})


test('parent-trip creation blocks a past start date', async ({ page }) => {
  await page.goto('/parent-trips/new')
  const dateInput = page.getByLabel('出发日期')
  await expect(dateInput).toHaveAttribute('min', localDateValue())

  await dateInput.fill(futureDateValue(new Date(), -1))
  await expect(page.getByRole('alert')).toContainText('出发日期不能早于今天')
  await expect(page.getByRole('button', { name: /创建父行程/ })).toBeDisabled()
})


test('a multi-day range continues in the parent-trip flow with preserved dates', async ({ page }) => {
  const startDate = futureDateValue()
  const endDate = futureDateValue(new Date(), 3)
  await page.goto('/plan')
  await page.getByRole('button', { name: /单人创建/ }).click()
  await page.getByLabel('这趟旅行，你最希望得到什么？').fill('想在杭州慢慢玩三天。')
  await page.getByRole('button', { name: /开始回答 5 个问题/ }).click()
  await page.getByLabel('目的城市').fill('杭州')
  await page.getByLabel('出发日期').fill(startDate)
  await page.getByLabel('结束日期').fill(endDate)
  await page.getByRole('button', { name: /继续创建多日行程/ }).click()

  await expect(page).toHaveURL(/\/parent-trips\/new\?/)
  await expect(page.getByLabel('城市')).toHaveValue('杭州')
  await expect(page.getByLabel('出发日期')).toHaveValue(startDate)
  await expect(page.getByLabel('结束日期')).toHaveValue(endDate)
})
