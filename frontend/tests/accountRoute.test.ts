import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('account page is reachable from the application router and shell', async () => {
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const shell = await readFile(new URL('../src/components/AppShell.tsx', import.meta.url), 'utf8')

  assert.match(app, /<Route\s+path=["']\/account["']/)
  assert.match(app, /AccountPage/)
  assert.match(shell, /to=["']\/account["']/)
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
