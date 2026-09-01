import assert from 'node:assert/strict'
import test from 'node:test'

import type { GeoPoint, Place } from '../src/domain/trip.ts'
import {
  appendConfirmedReturnPlace,
  assertProviderFactSetMatchesSelection,
  confirmRecommendationSelection,
  createLatestRecommendationRequestGate,
  selectedPlacesFromSignedFactSet,
  type ProviderFactPlaceSet,
  type ProviderFactSetSummary,
  type RecommendationBundle,
} from '../src/services/recommendationSelection.ts'

const digest = 'a'.repeat(64)
const tripId = '11111111-1111-4111-8111-111111111111'
const provenance = {
  provider: 'AMAP' as const,
  sourceStatus: 'ONLINE' as const,
  fetchedAt: '2026-08-28T09:00:00+08:00',
  isStale: false,
}

function candidate(index: number) {
  return {
    factRefId: `AMAP:poi-${index}:digest-${index}`,
    placeId: `poi-${index}`,
    name: `地点${index}`,
    category: '景点',
  }
}

function bundle(): RecommendationBundle {
  const candidates = Array.from({ length: 6 }, (_, index) => candidate(index + 1))
  const tasks = [candidates[2], candidates[0], candidates[1]]
  return {
    candidates,
    recommendations: tasks.map((item) => ({ placeId: item.placeId, reason: '白名单排序' })),
    usedDeterministicFallback: true,
    trustedPlan: {
      tasks,
      memberScores: [{ participantId: 'member-1', score: 80, penaltyRuleIds: [], reasons: ['稳定'] }],
      lowestMemberScore: 80,
      carePoints: [],
      compromises: [],
      unknownFacts: [],
      confirmationMessage: '请确认',
    },
    factSetId: 'facts-trip-revision-1',
    providerFactDigest: digest,
    parentPlaceMemory: [],
    provenance: candidates.map((item) => ({
      factRefId: item.factRefId,
      providerObjectId: item.placeId,
      sourceStatus: 'ONLINE',
      fetchedAt: provenance.fetchedAt,
      isStale: false,
    })),
  }
}

function summary(input = bundle()): ProviderFactSetSummary {
  return {
    schemaVersion: '1.0',
    factSetId: input.factSetId!,
    providerFactDigest: input.providerFactDigest!,
    tripId,
    issuedAt: provenance.fetchedAt,
    references: input.provenance.map((item) => ({
      ...item,
      kind: 'PLACE',
      payloadDigest: 'b'.repeat(64),
    })),
  }
}

function place(placeId: string, point: GeoPoint): Place {
  return {
    placeId,
    name: placeId,
    address: `${placeId}地址`,
    cityCode: '110000',
    adCode: '110101',
    location: point,
    category: '景点',
    telephone: null,
    rating: null,
    priceReference: {
      amountCents: 0,
      currency: 'CNY',
      kind: 'admission',
      provenance,
    },
    provenance,
  }
}

function placeSet(input = bundle()): ProviderFactPlaceSet {
  return {
    schemaVersion: '1.0',
    factSetId: input.factSetId!,
    providerFactDigest: input.providerFactDigest!,
    tripId,
    places: input.candidates.map((item, index) => ({
      factRefId: item.factRefId,
      providerObjectId: item.placeId,
      payloadDigest: 'c'.repeat(64),
      place: place(item.placeId, {
        longitude: 116.40 + index / 100,
        latitude: 39.90 + index / 100,
      }),
    })),
  }
}

test('confirmation freezes the exact FactRef IDs and trusted-plan order', () => {
  const input = bundle()
  const selection = confirmRecommendationSelection(tripId, input)

  assert.deepEqual(
    selection.selectedPlaces.map((item) => [item.factRefId, item.placeId]),
    [
      ['AMAP:poi-3:digest-3', 'poi-3'],
      ['AMAP:poi-1:digest-1', 'poi-1'],
      ['AMAP:poi-2:digest-2', 'poi-2'],
    ],
  )
  assert.equal(selection.factSetId, input.factSetId)
  assert.equal(selection.providerFactDigest, digest)
  assert.equal(Object.isFrozen(selection), true)
  assert.equal(Object.isFrozen(selection.selectedPlaces), true)
  assert.doesNotThrow(() => assertProviderFactSetMatchesSelection(summary(input), selection))
  assert.deepEqual(
    selectedPlacesFromSignedFactSet(placeSet(input), selection).map((item) => item.placeId),
    ['poi-3', 'poi-1', 'poi-2'],
  )
})

test('deterministic fallback keeps three intermediates and appends one return', () => {
  const selection = confirmRecommendationSelection(tripId, bundle())
  const points = Array.from({ length: 4 }, (_, index) => ({
    longitude: 116.40 + index / 100,
    latitude: 39.90 + index / 100,
  }))
  const selected = selection.selectedPlaces.map((item, index) => place(item.placeId, points[index]))
  const planningPlaces = appendConfirmedReturnPlace(
    selected,
    place('return-home', points[3]),
  )

  assert.deepEqual(
    planningPlaces.map((item) => item.placeId),
    ['poi-3', 'poi-1', 'poi-2', 'return-home'],
  )
  assert.equal(planningPlaces.length, 4)
})

test('missing trace, four intermediates or changed server facts fail closed', () => {
  const missingDigest = bundle()
  missingDigest.providerFactDigest = null
  assert.throws(
    () => confirmRecommendationSelection(tripId, missingDigest),
    /摘要无效/,
  )

  const tooMany = bundle()
  tooMany.trustedPlan!.tasks = tooMany.candidates.slice(0, 4)
  assert.throws(
    () => confirmRecommendationSelection(tripId, tooMany),
    /2—3 个中间地点/,
  )

  const valid = bundle()
  const selection = confirmRecommendationSelection(tripId, valid)
  const changed = summary(valid)
  changed.references[0] = {
    ...changed.references[0],
    providerObjectId: 'different-place',
  }
  assert.throws(
    () => assertProviderFactSetMatchesSelection(changed, selection),
    /已失效/,
  )

  const tamperedPayload = placeSet(valid)
  tamperedPayload.places[2] = {
    ...tamperedPayload.places[2],
    place: place('different-place', { longitude: 116.5, latitude: 40 }),
  }
  assert.throws(
    () => selectedPlacesFromSignedFactSet(tamperedPayload, selection),
    /签发地点已失效/,
  )
})

test('only the latest recommendation request may update the visible bundle', () => {
  const gate = createLatestRecommendationRequestGate()
  const firstRequest = gate.begin()
  const retryRequest = gate.begin()

  assert.equal(gate.isLatest(firstRequest), false)
  assert.equal(gate.isLatest(retryRequest), true)

  gate.invalidate()
  assert.equal(gate.isLatest(retryRequest), false)
})
