import type { Place, SourceStatus } from '../domain/trip'

export interface RecommendationCandidate {
  factRefId: string
  placeId: string
  name: string
  category: string | null
}

export interface RecommendationProvenance {
  factRefId: string
  providerObjectId: string
  sourceStatus: SourceStatus
  fetchedAt: string
  isStale: boolean
}

export interface RecommendationBundle {
  candidates: RecommendationCandidate[]
  recommendations: Array<{ placeId: string; reason: string }>
  usedDeterministicFallback: boolean
  trustedPlan: null | {
    tasks: RecommendationCandidate[]
    memberScores: Array<{
      participantId: string
      score: number
      penaltyRuleIds: string[]
      reasons: string[]
    }>
    lowestMemberScore: number
    carePoints: string[]
    compromises: string[]
    unknownFacts: string[]
    confirmationMessage: string
  }
  factSetId: string | null
  providerFactDigest: string | null
  provenance: RecommendationProvenance[]
}

export interface ConfirmedRecommendationPlace {
  factRefId: string
  placeId: string
  name: string
  category: string | null
}

export interface ConfirmedRecommendationSelection {
  schemaVersion: '1.0'
  tripId: string
  factSetId: string
  providerFactDigest: string
  selectedPlaces: readonly ConfirmedRecommendationPlace[]
}

export interface ProviderFactReferenceSummary {
  factRefId: string
  kind: 'PLACE' | 'ROUTE'
  providerObjectId: string
  payloadDigest: string
  sourceStatus: SourceStatus
  fetchedAt: string
  isStale: boolean
}

export interface ProviderFactSetSummary {
  schemaVersion: '1.0'
  factSetId: string
  providerFactDigest: string
  tripId: string
  issuedAt: string
  references: ProviderFactReferenceSummary[]
}

export interface ProviderFactPlacePayload {
  factRefId: string
  providerObjectId: string
  payloadDigest: string
  place: Place
}

export interface ProviderFactPlaceSet {
  schemaVersion: '1.0'
  factSetId: string
  providerFactDigest: string
  tripId: string
  places: ProviderFactPlacePayload[]
}

const digestPattern = /^[0-9a-f]{64}$/
const trustedSourceStatuses = new Set<SourceStatus>(['ONLINE', 'VERIFIED_CACHE'])

/**
 * Keep only the newest asynchronous recommendation load authoritative.
 *
 * React StrictMode, a route change, or a manual retry may overlap requests.
 * The page uses this generation gate before applying any response so an older
 * bundle can never replace the bundle whose confirmation is visible.
 */
export function createLatestRecommendationRequestGate() {
  let generation = 0
  return {
    begin() {
      generation += 1
      return generation
    },
    isLatest(requestGeneration: number) {
      return requestGeneration === generation
    },
    invalidate() {
      generation += 1
    },
  }
}

function requireOpaqueId(value: string | null | undefined, label: string) {
  const normalized = value?.trim() ?? ''
  if (!normalized) throw new Error(`${label} 缺失，不能确认唯一推荐。`)
  return normalized
}

function requireDigest(value: string | null | undefined) {
  const normalized = value?.trim() ?? ''
  if (!digestPattern.test(normalized)) {
    throw new Error('Provider FactRef 摘要无效，不能确认唯一推荐。')
  }
  return normalized
}

/**
 * Freeze the exact server recommendation that the organizer confirmed.
 *
 * The two-to-three intermediate-place limit is intentional: T011 requires a
 * three-to-four-task candidate and the final task is the separately verified
 * return to the confirmed Trip endpoint.
 */
export function confirmRecommendationSelection(
  tripId: string,
  bundle: RecommendationBundle,
): ConfirmedRecommendationSelection {
  const normalizedTripId = requireOpaqueId(tripId, 'tripId')
  const factSetId = requireOpaqueId(bundle.factSetId, 'factSetId')
  const providerFactDigest = requireDigest(bundle.providerFactDigest)
  const plan = bundle.trustedPlan
  if (!plan) throw new Error('服务端尚未生成唯一推荐，不能进入路线规划。')
  if (plan.tasks.length < 2 || plan.tasks.length > 3) {
    throw new Error('唯一推荐必须包含 2—3 个中间地点，另保留一个独立返程任务。')
  }

  const candidateByFactRef = new Map(
    bundle.candidates.map((candidate) => [candidate.factRefId, candidate]),
  )
  const provenanceByFactRef = new Map(
    bundle.provenance.map((item) => [item.factRefId, item]),
  )
  const seenFactRefs = new Set<string>()
  const seenPlaceIds = new Set<string>()
  const selectedPlaces = plan.tasks.map((task) => {
    const factRefId = requireOpaqueId(task.factRefId, 'FactRef')
    const placeId = requireOpaqueId(task.placeId, 'Provider 地点 ID')
    if (seenFactRefs.has(factRefId) || seenPlaceIds.has(placeId)) {
      throw new Error('唯一推荐包含重复地点，不能进入路线规划。')
    }
    const candidate = candidateByFactRef.get(factRefId)
    const provenance = provenanceByFactRef.get(factRefId)
    if (
      !candidate ||
      candidate.placeId !== placeId ||
      !provenance ||
      provenance.providerObjectId !== placeId ||
      !trustedSourceStatuses.has(provenance.sourceStatus)
    ) {
      throw new Error(`唯一推荐地点 ${placeId} 无法回溯到已签发 FactRef。`)
    }
    seenFactRefs.add(factRefId)
    seenPlaceIds.add(placeId)
    return Object.freeze({
      factRefId,
      placeId,
      name: task.name,
      category: task.category,
    })
  })

  return Object.freeze({
    schemaVersion: '1.0',
    tripId: normalizedTripId,
    factSetId,
    providerFactDigest,
    selectedPlaces: Object.freeze(selectedPlaces),
  })
}

/** Recheck the signed set immediately before Provider detail/route calls. */
export function assertProviderFactSetMatchesSelection(
  summary: ProviderFactSetSummary,
  selection: ConfirmedRecommendationSelection,
) {
  if (
    summary.schemaVersion !== '1.0' ||
    summary.tripId !== selection.tripId ||
    summary.factSetId !== selection.factSetId ||
    summary.providerFactDigest !== selection.providerFactDigest
  ) {
    throw new Error('已确认推荐与服务端 FactRef 快照不一致，请刷新后重新确认。')
  }
  const references = new Map(summary.references.map((item) => [item.factRefId, item]))
  for (const selected of selection.selectedPlaces) {
    const reference = references.get(selected.factRefId)
    if (
      !reference ||
      reference.kind !== 'PLACE' ||
      reference.providerObjectId !== selected.placeId ||
      !trustedSourceStatuses.has(reference.sourceStatus)
    ) {
      throw new Error(`FactRef ${selected.factRefId} 已失效，请刷新后重新确认。`)
    }
  }
}

/** Restore immutable signed Place payloads in organizer-confirmed order. */
export function selectedPlacesFromSignedFactSet(
  factSet: ProviderFactPlaceSet,
  selection: ConfirmedRecommendationSelection,
) {
  if (
    factSet.schemaVersion !== '1.0' ||
    factSet.tripId !== selection.tripId ||
    factSet.factSetId !== selection.factSetId ||
    factSet.providerFactDigest !== selection.providerFactDigest
  ) {
    throw new Error('已确认推荐与服务端 FactRef 地点快照不一致，请刷新后重新确认。')
  }
  const payloadByFactRef = new Map(
    factSet.places.map((item) => [item.factRefId, item]),
  )
  return selection.selectedPlaces.map((selected) => {
    const payload = payloadByFactRef.get(selected.factRefId)
    if (
      !payload ||
      payload.providerObjectId !== selected.placeId ||
      payload.place.placeId !== selected.placeId ||
      !digestPattern.test(payload.payloadDigest) ||
      !trustedSourceStatuses.has(payload.place.provenance.sourceStatus)
    ) {
      throw new Error(`FactRef ${selected.factRefId} 的签发地点已失效，请刷新后重新确认。`)
    }
    return payload.place
  })
}

/** Preserve the confirmed intermediate order and append exactly one return. */
export function appendConfirmedReturnPlace(
  selectedPlaces: readonly Place[],
  returnPlace: Place,
) {
  if (selectedPlaces.length < 2 || selectedPlaces.length > 3) {
    throw new Error('路线规划必须使用 2—3 个已确认中间地点。')
  }
  const placeIds = selectedPlaces.map((place) => place.placeId)
  if (new Set(placeIds).size !== placeIds.length || placeIds.includes(returnPlace.placeId)) {
    throw new Error('路线规划地点必须唯一，返程任务不能覆盖推荐地点。')
  }
  return [...selectedPlaces, returnPlace]
}
