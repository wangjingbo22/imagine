import { expect, test, type Page } from '@playwright/test'


async function assertNoHorizontalOverflow(page: Page) {
  const widths = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(widths.scrollWidth).toBeLessThanOrEqual(widths.clientWidth + 1)
}


async function registerInvitedMember(
  page: Page,
  invitationUrl: string,
  profile: { displayName: string; email: string },
) {
  await page.goto(invitationUrl)
  await expect(page).toHaveURL(/\/account\?returnTo=%2Fparent-join$/)
  await page.getByRole('button', { name: '注册' }).click()
  await page.getByLabel('显示名称').fill(profile.displayName)
  await page.getByLabel('邮箱').fill(profile.email)
  await page.getByLabel('密码').fill('t010-account-password')
  await page.getByRole('button', { name: '创建账户' }).click()
}


test('S3-T010 three people collaborate through isolated polling sessions', async ({
  browser,
  page: organizer,
}, testInfo) => {
  test.setTimeout(90_000)
  const runId = Date.now()
  const title = `T010 同行 ${runId.toString().slice(-6)}`
  const memberOneContext = await browser.newContext({
    locale: 'zh-CN',
    reducedMotion: 'reduce',
    viewport: { width: 375, height: 812 },
  })
  const memberTwoContext = await browser.newContext({
    locale: 'zh-CN',
    reducedMotion: 'reduce',
    viewport: { width: 768, height: 1024 },
  })

  try {
    await organizer.goto('/parent-trips/new')
    await organizer.getByLabel('行程名称').fill(title)
    await organizer.getByRole('button', { name: '创建父行程' }).click()
    await expect(organizer).toHaveURL(/\/parent-trips\/[0-9a-f-]{36}$/)
    await expect(organizer.getByRole('heading', { name: title })).toBeVisible()
    await assertNoHorizontalOverflow(organizer)

    const invitationInput = organizer.getByLabel('成员邀请链接')
    await organizer.getByRole('button', { name: '生成成员邀请' }).click()
    await expect(invitationInput).toBeVisible()
    const firstInvitation = await invitationInput.inputValue()

    const memberOne = await memberOneContext.newPage()
    await registerInvitedMember(memberOne, firstInvitation, {
      displayName: '小林账号',
      email: `t010-member-one-${runId}@example.com`,
    })
    await expect(memberOne).toHaveURL(/\/parent-trips\/[0-9a-f-]{36}\/member$/)
    await expect(memberOne.getByRole('heading', { name: title })).toBeVisible()
    await memberOne.getByLabel('昵称').fill('小林')
    await memberOne.getByLabel('兴趣标签').fill('园林，摄影')
    await memberOne.getByLabel('个人预算上限（元）').fill('800')
    await memberOne.getByRole('button', { name: '保存资料' }).click()
    await expect(memberOne.getByText('版本 2')).toBeVisible()
    await assertNoHorizontalOverflow(memberOne)

    await expect(organizer.getByText('小林', { exact: true })).toBeVisible({
      timeout: 8_000,
    })
    await organizer.getByRole('button', { name: '生成成员邀请' }).click()
    await expect(invitationInput).not.toHaveValue(firstInvitation)
    const secondInvitation = await invitationInput.inputValue()

    const memberTwo = await memberTwoContext.newPage()
    await registerInvitedMember(memberTwo, secondInvitation, {
      displayName: '阿岚账号',
      email: `t010-member-two-${runId}@example.com`,
    })
    await expect(memberTwo).toHaveURL(/\/parent-trips\/[0-9a-f-]{36}\/member$/)
    await memberTwo.getByLabel('昵称').fill('阿岚')
    await memberTwo.getByLabel('兴趣标签').fill('美食')
    await memberTwo.getByLabel('个人预算上限（元）').fill('600')
    await memberTwo.getByRole('button', { name: '保存资料' }).click()
    await expect(memberTwo.getByText('版本 2')).toBeVisible()
    await assertNoHorizontalOverflow(memberTwo)

    await expect(organizer.getByText('阿岚', { exact: true })).toBeVisible({
      timeout: 8_000,
    })
    await expect(
      organizer.getByRole('button', { name: '生成成员邀请' }),
    ).toBeDisabled()
    await memberOne.waitForTimeout(5_200)
    await expect(memberOne.getByText('阿岚', { exact: true })).toHaveCount(0)

    await organizer.screenshot({
      path: testInfo.outputPath('organizer-parent-collaboration.png'),
      fullPage: true,
    })
    await memberOne.screenshot({
      path: testInfo.outputPath('member-parent-collaboration-375.png'),
      fullPage: true,
    })
  } finally {
    await memberOneContext.close()
    await memberTwoContext.close()
  }
})
