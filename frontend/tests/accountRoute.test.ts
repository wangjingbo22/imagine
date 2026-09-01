import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { safeReturnPath } from '../src/services/accountReturnPath.ts'

test('account page is reachable from the application router and shell', async () => {
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const shell = await readFile(new URL('../src/components/AppShell.tsx', import.meta.url), 'utf8')

  assert.match(app, /<Route\s+path=["']\/account["']/)
  assert.match(app, /AccountPage/)
  assert.match(app, /function RequireAccount/)
  assert.match(app, /<RequireAccount><HomePage \/><\/RequireAccount>/)
  assert.match(app, /<RequireAccount><ConversationPlannerPage \/><\/RequireAccount>/)
  assert.match(app, /<Route path="\/parent-join" element=\{<ParentTripMemberPage \/>\} \/>/)
  assert.doesNotMatch(app, /<RequireAccount><ParentTripMemberPage/)
  assert.match(shell, /const accountPath =/)
  assert.match(shell, /to=\{accountPath\}/)
  assert.match(shell, /className="topbar__model-link"/)
  assert.match(shell, /绑定模型/)
})

test('multi-day trip creation accepts a typed city with optional suggestions', async () => {
  const page = await readFile(new URL('../src/pages/ParentTripPage.tsx', import.meta.url), 'utf8')

  assert.match(page, /list="parent-trip-city-suggestions"/)
  assert.match(page, /<datalist id="parent-trip-city-suggestions">/)
  assert.doesNotMatch(page, /<label>城市<select/)
})

test('top navigation keeps only enlarged model binding and account actions', async () => {
  const [shell, styles] = await Promise.all([
    readFile(new URL('../src/components/AppShell.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/styles/future-system.css', import.meta.url), 'utf8'),
  ])

  assert.doesNotMatch(shell, /CircleHelp|aria-label="帮助"/)
  assert.match(shell, /SlidersHorizontal size=\{21\}/)
  assert.match(shell, /UserRound size=\{21\}/)
  assert.match(styles, /\.avatar \{ width: 52px; height: 52px/)
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

test('model settings show the server error instead of masking failed API Key storage', async () => {
  const page = await readFile(new URL('../src/pages/ModelSettingsPage.tsx', import.meta.url), 'utf8')

  assert.match(page, /import \{ ApiError \} from '\.\.\/api\/client'/)
  assert.match(page, /error instanceof ApiError\) return error\.message/)
  assert.match(page, /保存失败：\$\{saveErrorMessage\(error\)\}/)
  assert.match(page, /await saveModelSettings[\s\S]*navigate\('\/', \{ replace: true \}\)/)
})

test('recommendation loading presents staged analysis instead of an empty status area', async () => {
  const page = await readFile(new URL('../src/pages/RecommendationPage.tsx', import.meta.url), 'utf8')
  const styles = await readFile(new URL('../src/styles/future-system.css', import.meta.url), 'utf8')

  assert.match(page, /LIVE ANALYSIS/)
  assert.match(page, /正在编排行程候选/)
  assert.match(page, /恢复已确认的出行事实/)
  assert.match(page, /计算路线与预算可行性/)
  assert.match(styles, /\.recommendation-loading__steps/)
  assert.match(styles, /@keyframes recommendationScan/)
})

test('application shell has no pointer-tracking grid effect', async () => {
  const shell = await readFile(new URL('../src/components/AppShell.tsx', import.meta.url), 'utf8')
  const styles = await readFile(new URL('../src/styles/white-web.css', import.meta.url), 'utf8')

  assert.doesNotMatch(shell, /onPointerMove|onPointerLeave|grid-focus/)
  assert.doesNotMatch(styles, /grid-focus|Pointer-aware grid/)
})

test('account page sends signed-in users to model binding without collecting a profile', async () => {
  const page = await readFile(new URL('../src/pages/AccountPage.tsx', import.meta.url), 'utf8')

  assert.match(page, /registerAccount/)
  assert.match(page, /loginAccount/)
  assert.match(page, /useAccountSession/)
  assert.match(page, /navigate\('\/model-settings', \{ replace: true \}\)/)
  assert.match(page, /绑定模型/)
  assert.doesNotMatch(page, /updateAccountProfile|常用城市|保存画像|ProfileDraft/)
  assert.doesNotMatch(page, /localStorage/)
})

test('account session is globally owned and synchronizes account mutations with every shell', async () => {
  const [main, page, shell, provider, context] = await Promise.all([
    readFile(new URL('../src/main.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/AccountPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/AppShell.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/session/AccountSessionProvider.tsx', import.meta.url), 'utf8').catch(() => ''),
    readFile(new URL('../src/session/AccountSessionContext.ts', import.meta.url), 'utf8').catch(() => ''),
  ])

  assert.match(main, /<AccountSessionProvider>/)
  assert.match(context, /createContext/)
  assert.match(provider, /getCurrentUser/)
  assert.match(provider, /ACCOUNT_SESSION_REQUIRED/)
  assert.match(provider, /error\.status === 401/)
  assert.match(provider, /sessionVersionRef/)
  assert.match(provider, /if \(isSessionRequired\(caught\)\) \{\s*clearCurrentUser\(\)/)
  assert.match(page, /useAccountSession/)
  assert.equal(page.match(/setCurrentUser\(response\.data\)/g)?.length, 1)
  assert.match(shell, /useAccountSession\(\)/)
  assert.doesNotMatch(page, /getCurrentUser/)
  assert.doesNotMatch(shell, /getCurrentUser/)
  assert.doesNotMatch(page, /useState<CurrentUser/)
  assert.doesNotMatch(shell, /useState<CurrentUser/)
})

test('account logout clears only shared account session artifacts after server logout succeeds', async () => {
  const [page, provider, parentTripCollaboration] = await Promise.all([
    readFile(new URL('../src/pages/AccountPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/session/AccountSessionProvider.tsx', import.meta.url), 'utf8').catch(() => ''),
    readFile(new URL('../src/services/parentTripCollaboration.ts', import.meta.url), 'utf8'),
  ])

  assert.match(page, /await logout\(\)/)
  assert.match(provider, /logoutAccount/)
  assert.match(provider, /await logoutAccount\(\)\s*\n\s*clearCurrentUser\(\)/)
  assert.match(provider, /clearAccountBoundParentTripMemberSessions/)
  assert.match(parentTripCollaboration, /clearAccountBoundParentTripMemberSessions/)
  assert.match(parentTripCollaboration, /parent-trip-member-session:/)
  assert.match(provider, /setUser\(null\)/)
  assert.doesNotMatch(provider, /localStorage\.clear\(\)/)
  assert.doesNotMatch(provider, /sessionStorage\.clear\(\)/)
})

test('session read errors remain visible once outside the mobile-hidden account status', async () => {
  const [page, shell, styles] = await Promise.all([
    readFile(new URL('../src/pages/AccountPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/AppShell.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/index.css', import.meta.url), 'utf8'),
  ])

  assert.match(shell, /app-shell__session-error/)
  assert.match(shell, /app-shell__session-error" role="alert"/)
  assert.doesNotMatch(shell, /<span role="alert">/)
  assert.doesNotMatch(page, /sessionError/)
  assert.match(styles, /\.app-shell__session-error\s*\{[^}]*display:\s*block/)
})

test('account content mounted after the initial session check is visible', async () => {
  const page = await readFile(new URL('../src/pages/AccountPage.tsx', import.meta.url), 'utf8')

  assert.doesNotMatch(page, /className="account-intro" data-reveal=/)
  assert.doesNotMatch(page, /className="account-panel account-panel--profile" data-reveal=/)
  assert.doesNotMatch(page, /className="account-panel" data-reveal=/)
})

test('account page only treats an invalid session as signed out', async () => {
  const provider = await readFile(
    new URL('../src/session/AccountSessionProvider.tsx', import.meta.url),
    'utf8',
  ).catch(() => '')

  assert.match(provider, /ACCOUNT_SESSION_REQUIRED/)
  assert.match(provider, /账户状态读取失败，请刷新重试/)
})

test('an HTTP 200 body code 401 is not treated as an invalid account session', async () => {
  const provider = await readFile(
    new URL('../src/session/AccountSessionProvider.tsx', import.meta.url),
    'utf8',
  ).catch(() => '')

  assert.match(provider, /error\.code === 'ACCOUNT_SESSION_REQUIRED' \|\| error\.status === 401/)
  assert.doesNotMatch(provider, /error\.code === 401/)
})

test('account flow enters model binding directly after login', async () => {
  const page = await readFile(new URL('../src/pages/AccountPage.tsx', import.meta.url), 'utf8')

  assert.match(page, /navigate\('\/model-settings', \{ replace: true \}\)/)
  assert.doesNotMatch(page, /用户画像|常用城市|保存画像/)
  assert.doesNotMatch(page, /navigate\(returnTo/)
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
