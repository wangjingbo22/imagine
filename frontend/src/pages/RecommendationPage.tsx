import { ArrowRight, LoaderCircle, RefreshCw, ShieldCheck } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { request } from '../api/client'
import { tripApi } from '../api/tripApi'
import { AppShell } from '../components/AppShell'
import { loadAmapPlan } from '../services/amapPlan'
import { planningDraftFromConfirmedTrip } from '../services/collaborationDraft'
import { getStoredOrganizerToken } from '../services/organizerStorage'
import {
  confirmRecommendationSelection,
  createLatestRecommendationRequestGate,
  type ConfirmedRecommendationSelection,
  type RecommendationBundle,
} from '../services/recommendationSelection'

// React StrictMode intentionally re-runs mount effects in development.  A
// recommendation request owns the collaboration planning lease, so share an
// in-flight request instead of making a competing second request for the same
// organizer and Trip.
const inFlightRecommendations = new Map<string, Promise<RecommendationBundle>>()

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

export function RecommendationPage() {
  const { tripId = '' } = useParams()
  const navigate = useNavigate()
  const [bundle, setBundle] = useState<RecommendationBundle | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [building, setBuilding] = useState(false)
  const [confirmedSelection, setConfirmedSelection] = useState<
    ConfirmedRecommendationSelection | null
  >(null)
  const requestGate = useRef(createLatestRecommendationRequestGate())
  const buildingRef = useRef(false)

  const traceStorageKey = `s2-recommendation-trace:${tripId}`

  const load = useCallback(async () => {
    const requestGeneration = requestGate.current.begin()
    const token = getStoredOrganizerToken(tripId)
    setBundle(null)
    setConfirmedSelection(null)
    window.sessionStorage.removeItem(traceStorageKey)
    if (!token) {
      if (requestGate.current.isLatest(requestGeneration)) {
        setError('当前浏览器没有组织者凭证，无法读取推荐。')
        setLoading(false)
      }
      return
    }
    setLoading(true); setError('')
    try {
      const result = await loadRecommendationsOnce(tripId, token)
      if (!requestGate.current.isLatest(requestGeneration)) return
      // Applying a new bundle and clearing its predecessor's confirmation are
      // one authoritative state transition. React batches these updates.
      setBundle(result)
      setConfirmedSelection(null)
      window.sessionStorage.removeItem(traceStorageKey)
    } catch (caught) {
      if (requestGate.current.isLatest(requestGeneration)) {
        setError(caught instanceof Error ? caught.message : '推荐获取失败。')
      }
    } finally {
      if (requestGate.current.isLatest(requestGeneration)) setLoading(false)
    }
  }, [traceStorageKey, tripId])

  useEffect(() => {
    const gate = requestGate.current
    const scheduledLoad = window.setTimeout(() => { void load() }, 0)
    return () => {
      window.clearTimeout(scheduledLoad)
      gate.invalidate()
    }
  }, [load])
  const trustedPlan = bundle?.trustedPlan

  function confirmUniqueRecommendation() {
    if (!bundle) return
    try {
      setError('')
      setConfirmedSelection(confirmRecommendationSelection(tripId, bundle))
    } catch (caught) {
      setConfirmedSelection(null)
      setError(caught instanceof Error ? caught.message : '唯一推荐事实不完整，请刷新后重试。')
    }
  }

  async function buildRoute() {
    if (buildingRef.current) return
    const token = getStoredOrganizerToken(tripId)
    if (!token || !confirmedSelection) { setError('当前浏览器缺少组织者凭证或已确认推荐事实。请刷新推荐并重新确认后继续。'); return }
    buildingRef.current = true
    try {
      setBuilding(true); setError('')
      // The collaboration revision owns participant ids, care facts and the
      // immutable Trip.  Fetch that guarded server projection instead of
      // calling the legacy browser-draft confirmation path a second time.
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
        throw new Error('路线结果缺少已确认推荐的 FactRef 追溯信息。')
      }
      window.sessionStorage.setItem(
        traceStorageKey,
        JSON.stringify(result.recommendationTrace),
      )
      navigate(`/workspace?tripId=${tripId}`, { state: { tripId, draft, trip: confirmedTrip, amapPlanResult: result } })
    } catch (caught) {
      setConfirmedSelection(null)
      window.sessionStorage.removeItem(traceStorageKey)
      setError(caught instanceof Error ? caught.message : '路线生成失败，请刷新推荐并重新确认。')
    }
    finally {
      buildingRef.current = false
      setBuilding(false)
    }
  }

  return <AppShell compact><main className="recommendation-layout"><section className="recommendation-panel" data-reveal="panel">
    <header className="recommendation-hero"><span className="section-kicker">ONE TRUSTED RECOMMENDATION</span><h1>唯一推荐方案</h1>
    <p>地点均来自高德事实；模型只负责白名单内的排序与简短理由，不会生成价格、路线或计划状态。</p>
    <ol className="recommendation-flow"><li className="is-done"><span>1</span><div><strong>需求确认</strong><small>六问已完成</small></div></li><li className="is-done"><span>2</span><div><strong>可信地点</strong><small>高德 FactRef</small></div></li><li className="is-current"><span>3</span><div><strong>生成路线</strong><small>核验路线与约束</small></div></li><li><span>4</span><div><strong>行程工作台</strong><small>确认并执行</small></div></li></ol>
    </header>
    {loading && <p>正在读取已核验地点…</p>}
    {error && <section className="draft-confirmation"><p className="form-error">{error}</p><button className="button button--soft" onClick={() => void load()}><RefreshCw size={16} />重试</button></section>}
    {bundle && trustedPlan && <section className="trusted-plan"><div className="draft-confirmation__heading"><span><ShieldCheck size={18} /></span><div><strong>唯一方案 · {bundle.usedDeterministicFallback ? '确定性排序' : '白名单排序'}</strong><p>按所有成员中的最低分优先选择；每一项均可回溯至高德 FactRef。</p></div></div>
      <section className="trusted-plan__tasks"><header><span>唯一行程骨架</span><strong>{trustedPlan.tasks.length} 个核验任务</strong></header><ol>{trustedPlan.tasks.map((place, index) => <li key={place.placeId}><span>{index + 1}</span><div><strong>{place.name}</strong><small>{place.category || '地点'} · FactRef: {place.factRefId}</small></div></li>)}</ol></section>
      <section className="trusted-plan__scores"><header><div><span>公平评分</span><strong>最低成员分 {trustedPlan.lowestMemberScore}/100</strong></div><small>排序优先保障分数最低的成员。</small></header><div>{trustedPlan.memberScores.map((member, index) => <article key={member.participantId}><span>成员 {index + 1}</span><strong>{member.score}</strong><p>{member.reasons.join('；')}</p>{member.penaltyRuleIds.map((rule) => <small key={rule}>规则：{rule}</small>)}</article>)}</div></section>
      <div className="trusted-plan__explain"><article><strong>照顾点</strong><ul>{trustedPlan.carePoints.map((point) => <li key={point}>{point}</li>)}</ul></article><article><strong>妥协说明</strong><ul>{trustedPlan.compromises.length ? trustedPlan.compromises.map((item) => <li key={item}>{item}</li>) : <li>{trustedPlan.memberScores.length > 1 ? '当前方案同时满足全部成员，无需额外放宽。' : '单人行程，无需跨成员妥协。'}</li>}</ul></article><article className={trustedPlan.unknownFacts.length ? 'is-unknown' : ''}><strong>未知事实</strong><ul>{trustedPlan.unknownFacts.length ? trustedPlan.unknownFacts.map((item) => <li key={item}>{item}</li>) : <li>当前任务的必要地点事实已齐全。</li>}</ul></article></div>
      <div className="planner-actions"><span className="save-state">{confirmedSelection ? `方案已确认 · FactRef 集合 ${confirmedSelection.factSetId} · 摘要 ${confirmedSelection.providerFactDigest.slice(0, 12)}…` : trustedPlan.confirmationMessage}</span>{!confirmedSelection ? <button className="button button--primary" onClick={confirmUniqueRecommendation}>确认唯一方案 <ShieldCheck size={17} /></button> : <button className="button button--primary" disabled={building || loading} onClick={() => void buildRoute()}>{building ? <LoaderCircle className="spin-icon" size={17} /> : '生成完整路线'} <ArrowRight size={17} /></button>}</div>
    </section>}
    {bundle && !trustedPlan && <section className="draft-confirmation"><p className="form-error">服务端尚未生成唯一方案，请刷新后重试。</p></section>}
  </section></main></AppShell>
}
