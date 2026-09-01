import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'


test('T010 registers organizer invitation and resumable member routes', async () => {
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8')
  assert.match(app, /<Route path="\/join\/:token" element=\{<MemberPageErrorBoundary><MemberConversationPage \/><\/MemberPageErrorBoundary>\} \/>/)
  assert.doesNotMatch(app, /<RequireAccount><MemberPageErrorBoundary><MemberConversationPage/)
  assert.match(app, /\/parent-join\/:token/)
  assert.match(app, /\/parent-join"/)
  assert.match(app, /\/parent-trips\/:parentTripId\/member/)
  assert.match(app, /ParentTripMemberPage/)
})


test('T010 uses isolated capability headers and optimistic sync versions', async () => {
  const api = await readFile(
    new URL('../src/api/parentTripApi.ts', import.meta.url),
    'utf8',
  )
  assert.match(api, /X-Parent-Trip-Token/)
  assert.match(api, /X-Parent-Member-Session/)
  assert.match(api, /Idempotency-Key/)
  assert.match(api, /expectedSyncVersion/)
  assert.match(api, /\/api\/v1\/account\/parent-trip-invitations\/redeem/)
  assert.match(api, /\/member-profile/)
  assert.match(api, /must|必须且只能提供一种身份凭证/)
})


test('T010 stores capabilities per tab and polls without realtime transports', async () => {
  const [service, organizerPage, memberPage] = await Promise.all([
    readFile(
      new URL('../src/services/parentTripCollaboration.ts', import.meta.url),
      'utf8',
    ),
    readFile(new URL('../src/pages/ParentTripPage.tsx', import.meta.url), 'utf8'),
    readFile(
      new URL('../src/pages/ParentTripMemberPage.tsx', import.meta.url),
      'utf8',
    ),
  ])
  assert.match(service, /PARENT_TRIP_POLL_INTERVAL_MS = 5000/)
  assert.match(service, /window\.sessionStorage/)
  assert.doesNotMatch(service, /localStorage/)
  assert.match(organizerPage, /PARENT_TRIP_POLL_INTERVAL_MS/)
  assert.match(memberPage, /PARENT_TRIP_POLL_INTERVAL_MS/)
  assert.doesNotMatch(`${service}${organizerPage}${memberPage}`, /WebSocket|EventSource/)
})


test('T010 strips the bearer invitation from the URL before redemption', async () => {
  const page = await readFile(
    new URL('../src/pages/ParentTripMemberPage.tsx', import.meta.url),
    'utf8',
  )
  const stripIndex = page.indexOf('window.history.replaceState')
  const redemptionIndex = page.indexOf('const redemption =')
  assert.ok(stripIndex >= 0)
  assert.ok(redemptionIndex > stripIndex)
  assert.match(page, /storeParentMemberSession/)
  assert.match(page, /clearPendingInvitation/)
  assert.match(page, /redeemParentTripInvitation/)
  assert.doesNotMatch(page, /ACCOUNT_SESSION_REQUIRED|\/account\?returnTo=%2Fparent-join/)
})


test('T010 keeps member-owned profile editing outside the parent trip dashboard', async () => {
  const [organizerPage, memberPage] = await Promise.all([
    readFile(new URL('../src/pages/ParentTripPage.tsx', import.meta.url), 'utf8'),
    readFile(
      new URL('../src/pages/ParentTripMemberPage.tsx', import.meta.url),
      'utf8',
    ),
  ])
  assert.doesNotMatch(organizerPage, /createParentTripInvitation|同行成员|查看预算账本/)
  assert.match(memberPage, /viewerParticipantId/)
  assert.match(memberPage, /updateParentTripMemberProfile/)
  assert.match(memberPage, /个人预算上限/)
})
