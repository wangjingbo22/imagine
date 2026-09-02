import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { parentTripChildStatusLabel } from '../src/domain/parentTrip.ts'

test('parent trip child statuses never expose backend enum text', () => {
  assert.equal(parentTripChildStatusLabel('NOT_CREATED'), '尚未创建')
  assert.equal(parentTripChildStatusLabel('PLAN_REVIEW'), '方案待确认')
  assert.equal(parentTripChildStatusLabel('COMPLETED'), '已完成')
  assert.equal(parentTripChildStatusLabel('UNKNOWN_STATUS'), '状态待确认')
})

test('T012 exposes an expanded multi-day parent route and reuses the single-day planner', async () => {
  const [app, page, planner] = await Promise.all([
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/ParentTripPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/ConversationPlannerPage.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(app, /\/parent-trips\/new/)
  assert.match(app, /\/parent-trips\/:parentTripId/)
  assert.match(page, /tripDateRangeDayCount\(form\)/)
  assert.match(page, /searchParams\.get\('endDate'\)/)
  assert.match(page, /validateTripDateRange\(form, temporalNow, MAX_DAY_COUNT\)/)
  assert.match(page, /多日行程总预算/)
  assert.match(page, /MAX_DAY_COUNT = 30/)
  assert.match(page, /saveDayBudget/)
  assert.match(page, /navigate\(`\/plan\?\$\{params\.toString\(\)\}`\)/)
  assert.match(planner, /linkParentTripDay/)
})

test('T012 keeps missing costs unknown and shows per-day allocation', async () => {
  const page = await readFile(new URL('../src/pages/ParentTripPage.tsx', import.meta.url), 'utf8')
  assert.match(page, /cents === null \? '尚未生成'/)
  assert.match(page, /当日预算/)
  assert.match(page, /已生成计划合计/)
  assert.match(page, /已记录支出合计/)
  assert.match(page, /不包含酒店、跨城搜索预订或跨日自动重规划/)
  assert.doesNotMatch(page, /查看预算账本|同行成员/)
})

test('parent and child organizer capabilities are sent separately', async () => {
  const api = await readFile(new URL('../src/api/parentTripApi.ts', import.meta.url), 'utf8')
  assert.match(api, /X-Parent-Trip-Token/)
  assert.match(api, /X-Organizer-Token/)
  assert.doesNotMatch(api, /localStorage/)
})

test('a child trip is linked only after its final organizer review', async () => {
  const planner = await readFile(new URL('../src/pages/ConversationPlannerPage.tsx', import.meta.url), 'utf8')
  const analyzeBody = planner.slice(
    planner.indexOf('async function analyze('),
    planner.indexOf('async function retryAfterFallbackReview()'),
  )
  const confirmationBody = planner.slice(
    planner.indexOf('async function confirmAndPrepare()'),
    planner.indexOf('async function resolveConflict('),
  )

  assert.doesNotMatch(analyzeBody, /linkParentTripDay/)
  assert.match(confirmationBody, /linkParentTripDay/)
})

test('parent context survives recommendation and workspace navigation', async () => {
  const planner = await readFile(new URL('../src/pages/ConversationPlannerPage.tsx', import.meta.url), 'utf8')
  const recommendation = await readFile(new URL('../src/pages/RecommendationPage.tsx', import.meta.url), 'utf8')
  const workspace = await readFile(new URL('../src/pages/WorkspacePage.tsx', import.meta.url), 'utf8')

  assert.match(planner, /parentTripId=.*dayIndex=/)
  assert.match(recommendation, /workspaceParams\.set\('parentTripId'/)
  assert.match(recommendation, /返回多日行程规划/)
  assert.match(workspace, /返回多日行程规划/)
})

test('a child trip exposes its inherited daily budget for review and requires a budget before advancing', async () => {
  const planner = await readFile(new URL('../src/pages/ConversationPlannerPage.tsx', import.meta.url), 'utf8')
  assert.match(planner, /step === 4\s*\? Boolean\(personalBudget\.trim\(\)\)/)
  assert.match(planner, /已按多日行程预算预填，可按当天实际情况修改。/)
})

test('multi-day travel mode is preserved outside the simplified parent dashboard', async () => {
  const [parentPage, planner] = await Promise.all([
    readFile(new URL('../src/pages/ParentTripPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/ConversationPlannerPage.tsx', import.meta.url), 'utf8'),
  ])

  assert.match(planner, /params\.set\('mode', entryMode\)/)
  assert.match(parentPage, /navigate\(`\/parent-trips\/\$\{id\}\?mode=\$\{tripMode\}`/)
  assert.match(parentPage, /mode: tripMode/)
  assert.doesNotMatch(parentPage, /parent-collaboration|createParentTripInvitation/)
})

test('multi-day planning exposes and propagates cross-day place memory', async () => {
  const [domain, parentPage, recommendation, selection] = await Promise.all([
    readFile(new URL('../src/domain/parentTrip.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/ParentTripPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/RecommendationPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/services/recommendationSelection.ts', import.meta.url), 'utf8'),
  ])

  assert.match(domain, /placeMemory: ParentTripPlaceMemoryItem\[\]/)
  assert.match(domain, /planStatus: 'PROPOSED' \| 'CURRENT'/)
  assert.match(parentPage, /跨日地点记忆/)
  assert.match(parentPage, /placeMemory\.filter/)
  assert.match(selection, /parentPlaceMemory: ParentTripPlaceMemoryItem\[\]/)
  assert.match(recommendation, /不会重复以下 \{parentPlaceMemory\.length\} 个地点/)
})
