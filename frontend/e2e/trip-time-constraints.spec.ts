import { expect, test } from '@playwright/test'

import {
  futureDateValue,
  localDateValue,
} from '../src/services/tripTimeConstraints'


test('single-day planner blocks past dates and invalid time windows', async ({ page }) => {
  const today = localDateValue()
  await page.goto('/plan')
  await page.getByRole('button', { name: /单人创建/ }).click()
  await page.getByLabel('目的城市').fill('北京')

  const dateInput = page.getByLabel('出行日期')
  await expect(dateInput).toHaveAttribute('min', today)
  await expect(dateInput).toHaveValue(today)
  await dateInput.fill(futureDateValue(new Date(), -1))
  await expect(page.getByRole('alert')).toContainText('出行日期不能早于今天')
  await expect(page.getByRole('button', { name: /下一个问题/ })).toBeDisabled()

  await dateInput.fill(futureDateValue())
  await page.getByLabel('开始').fill('18:00')
  await page.getByLabel('结束').fill('09:00')
  await expect(page.getByRole('alert')).toContainText('结束时间必须晚于开始时间')
  await expect(page.getByRole('button', { name: /下一个问题/ })).toBeDisabled()

  await page.getByLabel('开始').fill('09:00')
  await page.getByLabel('结束').fill('18:00')
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

  await expect(page.getByLabel('出行日期')).toHaveValue(today)
  await expect(page.getByText('问题 1 / 6', { exact: true })).toBeVisible()
  await expect(page.getByText('出行时间', { exact: true })).toBeVisible()
  await page.getByLabel('目的城市').fill('北京')
  await page.getByLabel('出行日期').fill(futureDateValue())
  await page.getByLabel('开始').fill('09:00')
  await page.getByLabel('结束').fill('18:00')
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
  const dateInput = page.getByLabel('开始日期')
  await expect(dateInput).toHaveAttribute('min', localDateValue())

  await dateInput.fill(futureDateValue(new Date(), -1))
  await expect(page.getByRole('alert')).toContainText('出行日期不能早于今天')
  await expect(page.getByRole('button', { name: /创建父行程/ })).toBeDisabled()
})
