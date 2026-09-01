import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { safeReturnPath } from '../src/services/accountReturnPath.ts'

test('account page is reachable from the application router and shell', async () => {
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const shell = await readFile(new URL('../src/components/AppShell.tsx', import.meta.url), 'utf8')

  assert.match(app, /<Route\s+path=["']\/account["']/)
  assert.match(app, /AccountPage/)
  assert.match(shell, /const accountPath =/)
  assert.match(shell, /to=\{accountPath\}/)
})

test('account API uses the session cookie and the account contract paths', async () => {
  const api = await readFile(new URL('../src/api/accountApi.ts', import.meta.url), 'utf8').catch(() => '')
  const client = await readFile(new URL('../src/api/client.ts', import.meta.url), 'utf8')

  assert.match(api, /\/api\/v1\/account\/register/)
  assert.match(api, /\/api\/v1\/account\/login/)
  assert.match(api, /\/api\/v1\/account\/logout/)
  assert.match(api, /\/api\/v1\/account\/me/)
  assert.match(api, /\/api\/v1\/account\/me\/profile/)
  assert.match(client, /credentials:\s*["']include["']/)
  assert.match(client, /import\.meta\.env\?\.PROD/)
  assert.match(client, /\? ''\s*:\s*resolveApiBaseUrl/)
})

test('account page provides authentication and profile actions without local storage sessions', async () => {
  const page = await readFile(new URL('../src/pages/AccountPage.tsx', import.meta.url), 'utf8')

  assert.match(page, /registerAccount/)
  assert.match(page, /loginAccount/)
  assert.match(page, /getCurrentUser/)
  assert.match(page, /updateAccountProfile/)
  assert.match(page, /logoutAccount/)
  assert.match(page, /interests/)
  assert.doesNotMatch(page, /localStorage/)
})

test('account content mounted after the initial session check is visible', async () => {
  const page = await readFile(new URL('../src/pages/AccountPage.tsx', import.meta.url), 'utf8')

  assert.doesNotMatch(page, /className="account-intro" data-reveal=/)
  assert.doesNotMatch(page, /className="account-panel account-panel--profile" data-reveal=/)
  assert.doesNotMatch(page, /className="account-panel" data-reveal=/)
})

test('account page only treats an invalid session as signed out', async () => {
  const page = await readFile(new URL('../src/pages/AccountPage.tsx', import.meta.url), 'utf8')

  assert.match(page, /ACCOUNT_SESSION_REQUIRED/)
  assert.match(page, /账户状态读取失败，请刷新重试/)
})

test('account return path is allowlisted before resuming an invitation', async () => {
  const [page, returnPath] = await Promise.all([
    readFile(new URL('../src/pages/AccountPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/services/accountReturnPath.ts', import.meta.url), 'utf8'),
  ])

  assert.match(returnPath, /returnTo === '\/parent-join'/)
  assert.match(page, /navigate\(returnTo, \{ replace: true \}\)/)
  assert.doesNotMatch(page, /window\.location\s*=/)
})

test('account return path safely restores recommendation routes and their parent context', () => {
  const tripId = '11111111-1111-4111-8111-111111111111'
  const parentTripId = '22222222-2222-4222-8222-222222222222'
  const recommendation = `/recommendation/${tripId}`
  const parentRecommendation = `${recommendation}?parentTripId=${parentTripId}&dayIndex=2`

  assert.equal(
    safeReturnPath(`?returnTo=${encodeURIComponent(recommendation)}`),
    recommendation,
  )
  assert.equal(
    safeReturnPath(`?returnTo=${encodeURIComponent(parentRecommendation)}`),
    parentRecommendation,
  )
  assert.equal(safeReturnPath('?returnTo=https%3A%2F%2Fexample.com'), null)
  assert.equal(safeReturnPath(`?returnTo=${encodeURIComponent(`${recommendation}?next=/admin`)}`), null)
  assert.equal(safeReturnPath(`?returnTo=${encodeURIComponent(`${recommendation}#lost`)}`), null)
})

test('account inputs keep a visible keyboard focus indicator', async () => {
  const styles = await readFile(new URL('../src/styles/white-web.css', import.meta.url), 'utf8')

  assert.match(styles, /\.account-form input:focus-visible[\s\S]*outline:\s*3px solid #1d4ed8/)
})

test('account mode switch uses pressed-button semantics', async () => {
  const page = await readFile(new URL('../src/pages/AccountPage.tsx', import.meta.url), 'utf8')

  assert.match(page, /className="account-switcher" role="group" aria-label=/)
  assert.match(page, /aria-pressed=\{mode === 'login'\}/)
  assert.doesNotMatch(page, /role="tablist"/)
})

test('account layout keeps touch controls and mobile viewport space stable', async () => {
  const styles = await readFile(new URL('../src/styles/white-web.css', import.meta.url), 'utf8')

  assert.match(styles, /\.account-layout[\s\S]*min-height:\s*calc\(100dvh - 68px\)/)
  assert.match(styles, /\.account-switcher button[\s\S]*min-height:\s*44px/)
})
