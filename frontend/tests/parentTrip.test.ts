import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('T012 exposes a 2-3 day parent route and reuses the single-day planner', async () => {
  const [app, page, planner] = await Promise.all([
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/ParentTripPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/ConversationPlannerPage.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(app, /\/parent-trips\/new/)
  assert.match(app, /\/parent-trips\/:parentTripId/)
  assert.match(page, /dayCount: 2/)
  assert.match(page, /<option value=\{3\}>3 天<\/option>/)
  assert.match(page, /\/plan\?parentTripId=/)
  assert.match(planner, /linkParentTripDay/)
})

test('T012 keeps missing costs unknown and shows per-day allocation', async () => {
  const page = await readFile(new URL('../src/pages/ParentTripPage.tsx', import.meta.url), 'utf8')
  assert.match(page, /cents === null \? '尚未生成'/)
  assert.match(page, /当日预算/)
  assert.match(page, /已生成计划合计/)
  assert.match(page, /已记录支出合计/)
  assert.match(page, /不包含酒店、跨城搜索预订或跨日自动重规划/)
})

test('parent and child organizer capabilities are sent separately', async () => {
  const api = await readFile(new URL('../src/api/parentTripApi.ts', import.meta.url), 'utf8')
  assert.match(api, /X-Parent-Trip-Token/)
  assert.match(api, /X-Organizer-Token/)
  assert.doesNotMatch(api, /localStorage/)
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
  assert.match(recommendation, /已排除 \{parentPlaceMemory\.length\}/)
})
