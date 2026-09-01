import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import type { ProviderRoute } from '../src/domain/trip.ts'
import {
  DEFAULT_WALK_LIMIT_METERS,
  defaultModeForWalkingRoute,
  routeModeCandidates,
} from '../src/services/amapPlan.ts'

function walkingRoute(distanceMeters: number): ProviderRoute {
  return {
    routeId: `walking-${distanceMeters}`,
    mode: 'WALKING',
    origin: { longitude: 116.3, latitude: 39.9 },
    destination: { longitude: 116.31, latitude: 39.91 },
    distanceMeters,
    durationSeconds: 600,
    walkingDistanceMeters: null,
    transferCount: null,
    steps: [],
    facilityEvidence: [],
    priceReference: {
      amountCents: 0,
      currency: 'CNY',
      kind: 'walking',
      provenance: {
        provider: 'AMAP',
        sourceStatus: 'ONLINE',
        fetchedAt: '2026-09-02T09:00:00+08:00',
        isStale: false,
      },
    },
    provenance: {
      provider: 'AMAP',
      sourceStatus: 'ONLINE',
      fetchedAt: '2026-09-02T09:00:00+08:00',
      isStale: false,
    },
  }
}

test('defaults from the actual walking route using both product and care caps', () => {
  assert.equal(DEFAULT_WALK_LIMIT_METERS, 1_000)
  assert.equal(defaultModeForWalkingRoute(walkingRoute(1_000), 1_000), 'WALKING')
  assert.equal(defaultModeForWalkingRoute(walkingRoute(1_001), 2_000), 'DRIVING')
  assert.equal(defaultModeForWalkingRoute(walkingRoute(500), 400), 'DRIVING')
  assert.equal(defaultModeForWalkingRoute(walkingRoute(1_001), null), 'DRIVING')
  assert.equal(defaultModeForWalkingRoute({ ...walkingRoute(500), mode: 'TRANSIT' }, 1_000), 'DRIVING')
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
  assert.match(page, /isFeedbackOpen && !persistedPlanId/)
  assert.match(page, /\{!persistedPlanId && \(/)
  assert.doesNotMatch(page, /请确认后通过 Plan V2 调整/)
  assert.match(styles, /\.route-mode-picker__options/)
  assert.match(styles, /min-height: 44px/)
})
