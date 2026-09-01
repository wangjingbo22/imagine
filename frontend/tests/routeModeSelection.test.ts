import assert from 'node:assert/strict'
import test from 'node:test'

import type { ProviderRoute } from '../src/domain/trip.ts'
import {
  DEFAULT_WALK_LIMIT_METERS,
  defaultModeForWalkingRoute,
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
