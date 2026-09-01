import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { routeModeCandidates } from '../src/services/amapPlan.ts'

test('does not select cycling unless it is explicitly allowed', () => {
  assert.deepEqual(routeModeCandidates(4_000, Number.POSITIVE_INFINITY), [
    'TRANSIT',
    'DRIVING',
    'WALKING',
  ])
})

test('keeps walking first for a short segment', () => {
  assert.deepEqual(routeModeCandidates(900, Number.POSITIVE_INFINITY), [
    'WALKING',
    'TRANSIT',
    'DRIVING',
  ])
})

test('allows cycling only for an explicit cycling preference', () => {
  assert.deepEqual(routeModeCandidates(4_000, Number.POSITIVE_INFINITY, true), [
    'BICYCLING',
    'TRANSIT',
    'DRIVING',
    'WALKING',
  ])
})

test('tries driving before cycling for an explicitly allowed medium-long segment', () => {
  assert.deepEqual(routeModeCandidates(12_000, Number.POSITIVE_INFINITY, true), [
    'TRANSIT',
    'DRIVING',
    'BICYCLING',
    'WALKING',
  ])
})

test('uses driving first for a long-distance segment', () => {
  assert.deepEqual(routeModeCandidates(55_000, 100, true), [
    'DRIVING',
    'TRANSIT',
    'BICYCLING',
    'WALKING',
  ])
})

test('does not prefer bicycling for a care profile that disallows it', () => {
  assert.deepEqual(routeModeCandidates(4_000, 500, false), [
    'TRANSIT',
    'DRIVING',
    'WALKING',
  ])
})

test('workspace exposes per-segment paid route choices and actionable review states', async () => {
  const [page, styles] = await Promise.all([
    readFile(new URL('../src/pages/WorkspacePage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/styles/white-web.css', import.meta.url), 'utf8'),
  ])

  for (const mode of ['DRIVING', 'BICYCLING', 'TAXI']) {
    assert.match(page, new RegExp(`value: '${mode}'`))
  }
  assert.match(page, /activePlan\.tasks\.map\(\(task, index\)/)
  assert.match(page, /handleRouteModeChange\(index, option\.value\)/)
  assert.match(page, /共享单车每 15 分钟 ¥1\.50 估算/)
  assert.match(page, /采用高德出租车估价/)
  assert.match(page, /只计高速\/道路收费/)
  assert.match(page, /id="evidence-review"/)
  assert.match(page, /查看未通过的硬约束/)
  assert.doesNotMatch(page, /证据待确认，暂不可接受/)
  assert.match(styles, /\.route-mode-picker__options/)
  assert.match(styles, /min-height: 44px/)
})
