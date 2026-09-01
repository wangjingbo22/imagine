import assert from 'node:assert/strict'
import test from 'node:test'

import type { GeoPoint, Place } from '../src/domain/trip.ts'
import {
  appendConfirmedReturnPlace,
  assertProviderFactSetMatchesSelection,
  clearRecommendationSession,
  confirmRecommendationSelection,
  createLatestRecommendationRequestGate,
  recommendationBundleStorageKey,
  recommendationDraftStorageKey,
  recommendationTraceStorageKey,
  restoreRecommendationBundle,
  selectedPlacesFromSignedFactSet,
  storeRecommendationBundle,
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

function memoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value) },
    removeItem: (key) => { values.delete(key) },
    clear: () => { values.clear() },
    key: (index) => [...values.keys()][index] ?? null,
    get length() { return values.size },
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

test('confirmation accepts organizer-edited signed candidates and preserves their order', () => {
  const input = bundle()
  const edited = [
    { ...input.candidates[4], name: '浏览器篡改名称' },
    input.candidates[3],
    input.candidates[0],
  ]
  const selection = confirmRecommendationSelection(tripId, input, edited)

  assert.deepEqual(
    selection.selectedPlaces.map((item) => [item.placeId, item.name]),
    [
      ['poi-5', '地点5'],
      ['poi-4', '地点4'],
      ['poi-1', '地点1'],
    ],
  )
  assert.deepEqual(
    selectedPlacesFromSignedFactSet(placeSet(input), selection).map((item) => item.placeId),
    ['poi-5', 'poi-4', 'poi-1'],
  )
})

test('meal-aware edits keep restaurant slots and reject lodging candidates', () => {
  const mealAware = bundle()
  mealAware.candidates[0] = {
    ...mealAware.candidates[0],
    name: '高德本地美食街',
    category: '购物服务;特色商业街',
  }
  mealAware.trustedPlan!.tasks = [
    mealAware.candidates[2],
    mealAware.candidates[0],
    mealAware.candidates[1],
  ]

  assert.throws(
    () => confirmRecommendationSelection(
      tripId,
      mealAware,
      [mealAware.candidates[2], mealAware.candidates[3], mealAware.candidates[1]],
    ),
    /必须保留 1 个真实餐饮地点/,
  )

  const withHotel = bundle()
  withHotel.candidates[0] = {
    ...withHotel.candidates[0],
    name: '高德商务酒店',
    category: '住宿服务;宾馆酒店',
  }
  withHotel.trustedPlan!.tasks = [
    withHotel.candidates[2],
    withHotel.candidates[0],
    withHotel.candidates[1],
  ]
  assert.throws(
    () => confirmRecommendationSelection(tripId, withHotel),
    /不能把酒店或住宿地点/,
  )
})

test('edited selections reject duplicate, unsigned and stale candidates', () => {
  const duplicated = bundle()
  assert.throws(
    () => confirmRecommendationSelection(
      tripId,
      duplicated,
      [duplicated.candidates[0], duplicated.candidates[0]],
    ),
    /重复地点/,
  )

  const unsigned = bundle()
  assert.throws(
    () => confirmRecommendationSelection(
      tripId,
      unsigned,
      [unsigned.candidates[0], candidate(99)],
    ),
    /核验信息已失效/,
  )

  const stale = bundle()
  stale.provenance[0] = { ...stale.provenance[0], isStale: true }
  assert.throws(
    () => confirmRecommendationSelection(
      tripId,
      stale,
      [stale.candidates[0], stale.candidates[1]],
    ),
    /核验信息已失效/,
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

test('missing trace, six intermediates or changed server facts fail closed', () => {
  const missingDigest = bundle()
  missingDigest.providerFactDigest = null
  assert.throws(
    () => confirmRecommendationSelection(tripId, missingDigest),
    /核验信息无效/,
  )

  const tooMany = bundle()
  tooMany.trustedPlan!.tasks = [
    ...tooMany.candidates.slice(0, 5),
    candidate(99),
  ]
  assert.throws(
    () => confirmRecommendationSelection(tripId, tooMany),
    /2—5 个中间地点/,
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
    /推荐地点的信息已失效/,
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

test('signed recommendation session restores the same bundle and clears all related state', () => {
  const storage = memoryStorage()
  const input = bundle()
  storeRecommendationBundle(storage, tripId, input)
  storage.setItem(recommendationDraftStorageKey(tripId), '{"draft":true}')
  storage.setItem(recommendationTraceStorageKey(tripId), '{"trace":true}')

  assert.deepEqual(restoreRecommendationBundle(storage, tripId), input)
  assert.ok(storage.getItem(recommendationBundleStorageKey(tripId)))

  clearRecommendationSession(storage, tripId)
  assert.equal(storage.getItem(recommendationBundleStorageKey(tripId)), null)
  assert.equal(storage.getItem(recommendationDraftStorageKey(tripId)), null)
  assert.equal(storage.getItem(recommendationTraceStorageKey(tripId)), null)
})

test('recommendation sessions from the old filtering policy are discarded', () => {
  const storage = memoryStorage()
  storage.setItem(recommendationBundleStorageKey(tripId), JSON.stringify({
    schemaVersion: '1.6',
    tripId,
    bundle: bundle(),
  }))

  assert.equal(restoreRecommendationBundle(storage, tripId), null)
  assert.equal(storage.getItem(recommendationBundleStorageKey(tripId)), null)
})

test('tampered recommendation session is discarded instead of being displayed', () => {
  const storage = memoryStorage()
  const input = bundle()
  input.providerFactDigest = 'not-a-digest'
  storage.setItem(recommendationBundleStorageKey(tripId), JSON.stringify({
    schemaVersion: '1.7',
    tripId,
    bundle: input,
  }))

  assert.equal(restoreRecommendationBundle(storage, tripId), null)
  assert.equal(storage.getItem(recommendationBundleStorageKey(tripId)), null)
})
