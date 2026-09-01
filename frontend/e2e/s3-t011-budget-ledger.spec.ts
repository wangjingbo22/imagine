import { expect, test } from '@playwright/test'

test('S3-T011 exposes auditable budget lines and lets users record a non-payment correction', async ({ page }) => {
  await page.goto('/budget-ledger', { waitUntil: 'domcontentloaded' })

  await expect(page.getByRole('heading', { name: '北京周末关怀行程' })).toBeVisible()
  await expect(page.getByText('待确认费用')).toBeVisible()
  await expect(page.getByText('尚未取得费用')).toBeVisible()
  await expect(page.locator('.ledger-status--unknown')).toHaveText('待确认')

  await page.getByRole('button', { name: '修正' }).first().click()
  await page.getByLabel('地铁与接驳 手动修正金额').fill('8.5')
  await page.getByRole('button', { name: '保存' }).click()

  await expect(page.getByRole('status')).toContainText('不会发起支付')
  await expect(page.getByRole('button', { name: '+¥8.50' })).toBeVisible()
})
