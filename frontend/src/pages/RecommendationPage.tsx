import {
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ChevronDown,
  HeartHandshake,
  ListChecks,
  LoaderCircle,
  MapPin,
  RefreshCw,
  ShieldCheck,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { request } from '../api/client'
import { tripApi } from '../api/tripApi'
import { AppShell } from '../components/AppShell'
import { loadAmapPlan } from '../services/amapPlan'
import { planningDraftFromConfirmedTrip } from '../services/collaborationDraft'
import { getStoredOrganizerToken } from '../services/organizerStorage'
import { isDiningPlaceLike } from '../services/itineraryPlaces'
import {
  clearRecommendationSession,
  confirmRecommendationSelection,
  createLatestRecommendationRequestGate,
  recommendationDraftStorageKey,
  recommendationTraceStorageKey,
  restoreRecommendationBundle,
  storeRecommendationBundle,
  type ConfirmedRecommendationSelection,
  type RecommendationBundle,
  type RecommendationCandidate,
} from '../services/recommendationSelection'

// React StrictMode intentionally re-runs mount effects in development. A
// recommendation request owns the collaboration planning lease, so share an
// in-flight request instead of making a competing second request.
const inFlightRecommendations = new Map<string, Promise<RecommendationBundle>>()

interface StoredRecommendationDraft {
  schemaVersion: '1.0'
  factSetId: string
  providerFactDigest: string
  selectedFactRefIds: string[]
}

function loadRecommendationsOnce(
  tripId: string,
  organizerToken: string,
): Promise<RecommendationBundle> {
  const requestKey = `${tripId}:${organizerToken}`
  const existing = inFlightRecommendations.get(requestKey)
  if (existing) return existing

  const operation = request<RecommendationBundle>(`/api/v2/trips/${tripId}/recommendations`, {
    headers: { 'X-Organizer-Token': organizerToken },
  }).then((response) => response.data)
  inFlightRecommendations.set(requestKey, operation)
  void operation.finally(() => inFlightRecommendations.delete(requestKey))
  return operation
}

function restoreRecommendationDraft(
  tripId: string,
  bundle: RecommendationBundle,
  storageKey: string,
): RecommendationCandidate[] {
  const defaultTasks = bundle.trustedPlan?.tasks ?? []
  const raw = window.sessionStorage.getItem(storageKey)
  if (!raw || !bundle.trustedPlan) return [...defaultTasks]

  try {
    const stored = JSON.parse(raw) as Partial<StoredRecommendationDraft>
    if (
      stored.schemaVersion !== '1.0' ||
      stored.factSetId !== bundle.factSetId ||
      stored.providerFactDigest !== bundle.providerFactDigest ||
      !Array.isArray(stored.selectedFactRefIds) ||
      stored.selectedFactRefIds.length < 2 ||
      stored.selectedFactRefIds.length > 5 ||
      stored.selectedFactRefIds.some((factRefId) => typeof factRefId !== 'string') ||
      new Set(stored.selectedFactRefIds).size !== stored.selectedFactRefIds.length
    ) {
      throw new Error('Stored recommendation draft does not match the current fact set.')
    }

    const candidateByFactRef = new Map(
      bundle.candidates.map((candidate) => [candidate.factRefId, candidate]),
    )
    const restored = stored.selectedFactRefIds.map((factRefId) =>
      candidateByFactRef.get(factRefId),
    )
    if (restored.some((candidate) => !candidate)) {
      throw new Error('Stored recommendation draft contains an unavailable place.')
    }

    const tasks = restored as RecommendationCandidate[]
    confirmRecommendationSelection(tripId, bundle, tasks)
    return tasks
  } catch {
    window.sessionStorage.removeItem(storageKey)
    return [...defaultTasks]
  }
}

export function RecommendationPage() {
  const { tripId = '' } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const parentTripId = searchParams.get('parentTripId')
  const parentDayIndex = searchParams.get('dayIndex')
  const [bundle, setBundle] = useState<RecommendationBundle | null>(null)
  const [selectedTasks, setSelectedTasks] = useState<RecommendationCandidate[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [building, setBuilding] = useState(false)
  const [confirmedSelection, setConfirmedSelection] = useState<
    ConfirmedRecommendationSelection | null
  >(null)
  const requestGate = useRef(createLatestRecommendationRequestGate())
  const buildingRef = useRef(false)

  const traceStorageKey = recommendationTraceStorageKey(tripId)
  const draftStorageKey = recommendationDraftStorageKey(tripId)

  const load = useCallback(async (forceRefresh = false) => {
    const requestGeneration = requestGate.current.begin()
    const token = getStoredOrganizerToken(tripId)
    if (!token) {
      if (requestGate.current.isLatest(requestGeneration)) {
        setError('当前浏览器没有组织者凭证，无法读取推荐。')
        setLoading(false)
      }
      return
    }

    if (!forceRefresh) {
      const cachedBundle = restoreRecommendationBundle(window.sessionStorage, tripId)
      if (cachedBundle) {
        setBundle(cachedBundle)
        setSelectedTasks(restoreRecommendationDraft(tripId, cachedBundle, draftStorageKey))
        setConfirmedSelection(null)
        window.sessionStorage.removeItem(traceStorageKey)
        setError('')
        setLoading(false)
        return
      }
    } else {
      clearRecommendationSession(window.sessionStorage, tripId)
    }

    setBundle(null)
    setSelectedTasks([])
    setConfirmedSelection(null)
    window.sessionStorage.removeItem(traceStorageKey)
    setLoading(true)
    setError('')
    try {
      const result = await loadRecommendationsOnce(tripId, token)
      if (!requestGate.current.isLatest(requestGeneration)) return
      storeRecommendationBundle(window.sessionStorage, tripId, result)
      setBundle(result)
      setSelectedTasks(restoreRecommendationDraft(tripId, result, draftStorageKey))
      setConfirmedSelection(null)
      window.sessionStorage.removeItem(traceStorageKey)
    } catch (caught) {
      if (requestGate.current.isLatest(requestGeneration)) {
        setError(caught instanceof Error ? caught.message : '推荐获取失败。')
      }
    } finally {
      if (requestGate.current.isLatest(requestGeneration)) setLoading(false)
    }
  }, [draftStorageKey, traceStorageKey, tripId])

  useEffect(() => {
    const gate = requestGate.current
    const scheduledLoad = window.setTimeout(() => { void load() }, 0)
    return () => {
      window.clearTimeout(scheduledLoad)
      gate.invalidate()
    }
  }, [load])

  const trustedPlan = bundle?.trustedPlan
  const parentPlaceMemory = bundle?.parentPlaceMemory ?? []
  const selectedFactRefs = new Set(selectedTasks.map((task) => task.factRefId))
  const mealAwarePlan = trustedPlan?.tasks.some((task) =>
    isDiningPlaceLike(task.name, task.category),
  ) ?? false

  function applySelectedTasks(nextTasks: readonly RecommendationCandidate[]) {
    if (!bundle) return
    try {
      const validatedSelection = confirmRecommendationSelection(tripId, bundle, nextTasks)
      setSelectedTasks([...nextTasks])
      setConfirmedSelection(null)
      setError('')
      window.sessionStorage.removeItem(traceStorageKey)
      const draft: StoredRecommendationDraft = {
        schemaVersion: '1.0',
        factSetId: validatedSelection.factSetId,
        providerFactDigest: validatedSelection.providerFactDigest,
        selectedFactRefIds: nextTasks.map((task) => task.factRefId),
      }
      window.sessionStorage.setItem(draftStorageKey, JSON.stringify(draft))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '地点调整失败，请刷新后重试。')
    }
  }

  function replacePlace(index: number, factRefId: string) {
    if (!bundle) return
    const replacement = bundle.candidates.find((candidate) => candidate.factRefId === factRefId)
    if (!replacement || selectedTasks[index]?.factRefId === factRefId) return
    const nextTasks = [...selectedTasks]
    nextTasks[index] = replacement
    applySelectedTasks(nextTasks)
  }

  function moveDestination(index: number, direction: -1 | 1) {
    if (!mealAwarePlan) {
      const destination = index + direction
      return destination >= 0 && destination < selectedTasks.length ? destination : -1
    }
    const diningSlot = isDiningPlaceLike(
      selectedTasks[index]?.name ?? '',
      selectedTasks[index]?.category,
    )
    for (
      let destination = index + direction;
      destination >= 0 && destination < selectedTasks.length;
      destination += direction
    ) {
      const candidate = selectedTasks[destination]
      if (isDiningPlaceLike(candidate.name, candidate.category) === diningSlot) {
        return destination
      }
    }
    return -1
  }

  function movePlace(index: number, direction: -1 | 1) {
    const destination = moveDestination(index, direction)
    if (destination < 0) return
    const nextTasks = [...selectedTasks]
    const movedTask = nextTasks[index]
    nextTasks[index] = nextTasks[destination]
    nextTasks[destination] = movedTask
    applySelectedTasks(nextTasks)
  }

  function recommendationReason(place: RecommendationCandidate) {
    return bundle?.recommendations.find((item) => item.placeId === place.placeId)?.reason
      ?? `${place.category || '该地点'}符合当前已确认的出行条件`
  }

  function confirmRecommendation() {
    if (!bundle) return
    try {
      setError('')
      setConfirmedSelection(confirmRecommendationSelection(tripId, bundle, selectedTasks))
    } catch (caught) {
      setConfirmedSelection(null)
      setError(caught instanceof Error ? caught.message : '推荐方案信息不完整，请刷新后重试。')
    }
  }

  async function buildRoute() {
    if (buildingRef.current) return
    const token = getStoredOrganizerToken(tripId)
    if (!token || !confirmedSelection) {
      setError('当前浏览器缺少组织者凭证或方案尚未确认。请刷新推荐并重新确认后继续。')
      return
    }
    buildingRef.current = true
    try {
      setBuilding(true)
      setError('')
      const confirmedTrip = (
        await tripApi.getCollaborationPlanningTrip(tripId, token)
      ).data
      const draft = planningDraftFromConfirmedTrip(confirmedTrip)
      const result = await loadAmapPlan(tripId, draft, undefined, {
        confirmedTrip,
        organizerToken: token,
        recommendationSelection: confirmedSelection,
      })
      if (
        result.recommendationTrace?.factSetId !== confirmedSelection.factSetId ||
        result.recommendationTrace.providerFactDigest !== confirmedSelection.providerFactDigest
      ) {
        throw new Error('路线结果与当前推荐方案不一致，请刷新推荐后重试。')
      }
      window.sessionStorage.setItem(
        traceStorageKey,
        JSON.stringify(result.recommendationTrace),
      )
      const workspaceParams = new URLSearchParams({ tripId })
      if (parentTripId) workspaceParams.set('parentTripId', parentTripId)
      if (parentDayIndex) workspaceParams.set('dayIndex', parentDayIndex)
      navigate(`/workspace?${workspaceParams.toString()}`, {
        state: { tripId, draft, trip: confirmedTrip, amapPlanResult: result },
      })
    } catch (caught) {
      setConfirmedSelection(null)
      window.sessionStorage.removeItem(traceStorageKey)
      setError(caught instanceof Error ? caught.message : '路线生成失败，请重新确认方案。')
    } finally {
      buildingRef.current = false
      setBuilding(false)
    }
  }

  return (
    <AppShell compact showBackButton={false}>
      <main className="recommendation-layout">
        {error && (
          <div className="recommendation-error-overlay">
            <section
              aria-describedby="recommendation-error-message"
              aria-labelledby="recommendation-error-title"
              aria-modal="true"
              className="recommendation-error-dialog"
              role="alertdialog"
            >
              <header>
                <span className="recommendation-error-dialog__icon" aria-hidden="true">
                  <AlertTriangle size={22} />
                </span>
                <div>
                  <h2 id="recommendation-error-title">
                    {bundle ? '方案暂时无法生成' : '推荐加载失败'}
                  </h2>
                  <p id="recommendation-error-message">{error}</p>
                </div>
                <button
                  aria-label="关闭提示"
                  autoFocus
                  className="recommendation-error-dialog__close"
                  onClick={() => setError('')}
                  title="关闭"
                  type="button"
                >
                  <X size={18} />
                </button>
              </header>
              <div className="recommendation-error-dialog__actions">
                {bundle ? (
                  <button
                    className="button button--soft"
                    onClick={() => setError('')}
                    type="button"
                  >
                    返回调整地点
                  </button>
                ) : (
                  <button
                    className="button button--primary"
                    onClick={() => void load(true)}
                    type="button"
                  >
                    <RefreshCw size={16} />重新加载
                  </button>
                )}
              </div>
            </section>
          </div>
        )}
        {parentTripId && (
          <button
            className="parent-trip-return"
            type="button"
            onClick={() => navigate(`/parent-trips/${parentTripId}`)}
          >
            ← 返回多日行程规划
          </button>
        )}
        <section className="recommendation-panel" data-reveal="panel">
          <header className="recommendation-hero">
            <span className="section-kicker">TRIP RECOMMENDATION</span>
            <h1>推荐方案</h1>
            <p>根据你确认的时间、预算、偏好和同行需求，我们整理了这份地点方案。确认后将为你生成完整路线。</p>
          </header>

          {loading && (
            <p className="recommendation-loading" role="status">
              <LoaderCircle className="spin-icon" size={18} /> 正在整理推荐地点…
            </p>
          )}
          {bundle && parentPlaceMemory.length > 0 && (
            <section className="recommendation-place-memory" aria-label="其他日期已安排地点">
              <header>
                <MapPin size={20} />
                <div>
                  <strong>已避开其他日期的地点</strong>
                  <span>本日推荐不会重复以下 {parentPlaceMemory.length} 个地点</span>
                </div>
              </header>
              <ul>
                {parentPlaceMemory.map((place) => (
                  <li key={`${place.childTripId}:${place.planId}:${place.placeId}`}>
                    <span>{place.placeName}</span>
                    <small>第 {place.dayIndex + 1} 天 · {place.date}</small>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {bundle && trustedPlan && (
            <section className="trusted-plan" aria-labelledby="recommendation-editor-title">
              <header className="trusted-plan__heading">
                <span className="trusted-plan__heading-icon"><ListChecks size={20} /></span>
                <div>
                  <h2 id="recommendation-editor-title">行程地点</h2>
                  <p>已选择 {selectedTasks.length} 个地点，路线将按下列顺序生成。</p>
                </div>
              </header>

              <ol className="recommendation-location-list">
                {selectedTasks.map((place, index) => (
                  <li className="recommendation-location" key={place.factRefId}>
                    <span className="recommendation-location__order">{index + 1}</span>
                    <div className="recommendation-location__body">
                      <label>
                        <span>第 {index + 1} 站</span>
                        <span className="recommendation-location__select">
                          <select
                            aria-label={`第 ${index + 1} 个地点`}
                            disabled={building}
                            value={place.factRefId}
                            onChange={(event) => replacePlace(index, event.target.value)}
                          >
                            {bundle.candidates
                              .filter((candidate) => (
                                (
                                  candidate.factRefId === place.factRefId ||
                                  !selectedFactRefs.has(candidate.factRefId)
                                ) && (
                                  !mealAwarePlan ||
                                  isDiningPlaceLike(candidate.name, candidate.category) ===
                                    isDiningPlaceLike(place.name, place.category)
                                )
                              ))
                              .map((candidate) => (
                                <option key={candidate.factRefId} value={candidate.factRefId}>
                                  {candidate.name}
                                </option>
                              ))}
                          </select>
                          <ChevronDown aria-hidden="true" size={18} />
                        </span>
                      </label>
                      <p>{recommendationReason(place)}</p>
                    </div>
                    <div className="recommendation-location__actions" aria-label={`调整第 ${index + 1} 个地点的顺序`}>
                      <button
                        aria-label={`将第 ${index + 1} 个地点上移`}
                        disabled={building || moveDestination(index, -1) < 0}
                        onClick={() => movePlace(index, -1)}
                        title="上移"
                        type="button"
                      >
                        <ArrowUp size={17} />
                      </button>
                      <button
                        aria-label={`将第 ${index + 1} 个地点下移`}
                        disabled={building || moveDestination(index, 1) < 0}
                        onClick={() => movePlace(index, 1)}
                        title="下移"
                        type="button"
                      >
                        <ArrowDown size={17} />
                      </button>
                    </div>
                  </li>
                ))}
              </ol>

              {trustedPlan.carePoints.length > 0 && (
                <div className="recommendation-care-note">
                  <HeartHandshake size={20} />
                  <div>
                    <strong>已纳入同行照顾需求</strong>
                    <p>{trustedPlan.carePoints.join('；')}</p>
                  </div>
                </div>
              )}

              <div className="planner-actions recommendation-actions">
                <p className="recommendation-status" role="status" aria-live="polite">
                  {confirmedSelection
                    ? '方案已确认，可以生成完整路线。'
                    : `已选择 ${selectedTasks.length} 个地点，确认前可继续调整。`}
                </p>
                {!confirmedSelection ? (
                  <button
                    className="button button--primary"
                    disabled={building || loading}
                    onClick={confirmRecommendation}
                    type="button"
                  >
                    确认此方案 <ShieldCheck size={17} />
                  </button>
                ) : (
                  <button
                    className="button button--primary"
                    disabled={building || loading}
                    onClick={() => void buildRoute()}
                    type="button"
                  >
                    {building ? <LoaderCircle className="spin-icon" size={17} /> : null}
                    {building ? '正在生成路线' : '生成完整路线'} <ArrowRight size={17} />
                  </button>
                )}
              </div>
            </section>
          )}

          {bundle && !trustedPlan && (
            <section className="draft-confirmation">
              <p className="form-error">服务端尚未生成推荐方案，请刷新后重试。</p>
            </section>
          )}
        </section>
      </main>
    </AppShell>
  )
}
