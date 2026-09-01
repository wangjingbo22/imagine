import assert from 'node:assert/strict'
import test from 'node:test'

import type { ProviderRoute } from '../src/domain/trip.ts'
import {
  facilityEvidenceNeedsConfirmation,
  hasCompleteRouteRiskFacts,
  routeWalkingMeters,
} from '../src/services/routeRiskFacts.ts'

function route(overrides: Partial<ProviderRoute> = {}): ProviderRoute {
  return {
    routeId: 'route-1',
    mode: 'TRANSIT',
    origin: { longitude: 116.3, latitude: 39.9 },
    destination: { longitude: 116.4, latitude: 39.8 },
    distanceMeters: 2_000,
    durationSeconds: 1_200,
    walkingDistanceMeters: 300,
    transferCount: 1,
    steps: [],
    facilityEvidence: [],
    priceReference: {
      amountCents: 400,
      currency: 'CNY',
      kind: 'TRANSIT_FARE',
      provenance: {
        provider: 'AMAP',
        sourceStatus: 'ONLINE',
        fetchedAt: '2026-08-25T09:00:00+08:00',
        isStale: false,
      },
    },
    provenance: {
      provider: 'AMAP',
      sourceStatus: 'ONLINE',
      fetchedAt: '2026-08-25T09:00:00+08:00',
      isStale: false,
    },
    ...overrides,
  }
}

test('transit routes require both walking and transfer facts', () => {
  assert.equal(hasCompleteRouteRiskFacts(route()), true)
  assert.equal(hasCompleteRouteRiskFacts(route({ walkingDistanceMeters: null })), false)
  assert.equal(hasCompleteRouteRiskFacts(route({ transferCount: null })), false)
})

test('walking uses distanceMeters exactly as the backend adapter does', () => {
  const walking = route({
    mode: 'WALKING',
    distanceMeters: 750,
    walkingDistanceMeters: null,
    transferCount: null,
  })
  assert.equal(hasCompleteRouteRiskFacts(walking), true)
  assert.equal(routeWalkingMeters(walking), 750)
})

test('unknown facility provenance never renders as verified PASS', () => {
  const evidence = {
    facilityType: 'ELEVATOR' as const,
    label: '电梯',
    status: 'PASS' as const,
    message: '上游声明可用但来源未知',
    referenceId: 'facility-1',
    provenance: {
      provider: 'AMAP' as const,
      sourceStatus: 'UNKNOWN' as const,
      fetchedAt: '2026-08-25T09:00:00+08:00',
      isStale: false,
    },
  }
  assert.equal(facilityEvidenceNeedsConfirmation(evidence), true)
  assert.equal(facilityEvidenceNeedsConfirmation({
    ...evidence,
    provenance: { ...evidence.provenance, sourceStatus: 'ONLINE' },
  }), false)
})

test('explicit facility confirmation status remains blocking with online provenance', () => {
  const evidence = {
    facilityType: 'ELEVATOR' as const,
    label: '电梯',
    status: 'NEEDS_CONFIRMATION' as const,
    message: '需要现场确认',
    referenceId: 'facility-2',
    provenance: {
      provider: 'AMAP' as const,
      sourceStatus: 'ONLINE' as const,
      fetchedAt: '2026-08-25T09:00:00+08:00',
      isStale: false,
    },
  }
  assert.equal(facilityEvidenceNeedsConfirmation(evidence), true)
})
