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
})


test('parent-trip creation blocks a past start date', async ({ page }) => {
  await page.goto('/parent-trips/new')
  const dateInput = page.getByLabel('开始日期')
  await expect(dateInput).toHaveAttribute('min', localDateValue())

  await dateInput.fill(futureDateValue(new Date(), -1))
  await expect(page.getByRole('alert')).toContainText('出行日期不能早于今天')
  await expect(page.getByRole('button', { name: /创建父行程/ })).toBeDisabled()
})
