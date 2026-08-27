import { ArrowRight, LoaderCircle, RefreshCw, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { request } from '../api/client'
import { tripApi } from '../api/tripApi'
import { AppShell } from '../components/AppShell'
import type { CreateSingleDayTrip, TripDraftInput } from '../domain/trip'
import { loadAmapPlan } from '../services/amapPlan'

type Recommendation = { placeId: string; reason: string }
type Candidate = { factRefId: string; placeId: string; name: string; category: string | null }
type Bundle = {
  candidates: Candidate[]; recommendations: Recommendation[]; usedDeterministicFallback: boolean
  trustedPlan: null | {
    tasks: Candidate[]
    memberScores: Array<{ participantId: string; score: number; penaltyRuleIds: string[]; reasons: string[] }>
    lowestMemberScore: number
    carePoints: string[]
    compromises: string[]
    unknownFacts: string[]
    confirmationMessage: string
  }
}

export function RecommendationPage() {
  const { tripId = '' } = useParams()
  const navigate = useNavigate()
  const [bundle, setBundle] = useState<Bundle | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [building, setBuilding] = useState(false)
  const [confirmed, setConfirmed] = useState(false)

  async function load() {
    const token = window.sessionStorage.getItem(`organizer-token:${tripId}`)
    if (!token) { setError('当前浏览器没有组织者凭证，无法读取推荐。'); setLoading(false); return }
    setLoading(true); setError('')
    try {
      const result = await request<Bundle>(`/api/v2/trips/${tripId}/recommendations`, { headers: { 'X-Organizer-Token': token } })
      setBundle(result.data)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '推荐获取失败。') }
    finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [tripId])
  const trustedPlan = bundle?.trustedPlan

  async function buildRoute() {
    const token = window.sessionStorage.getItem(`organizer-token:${tripId}`)
    const saved = window.sessionStorage.getItem(`s2-plan-context:${tripId}`)
    if (!token || !saved) { setError('当前浏览器缺少已确认的行程上下文。请返回对话页重新创建行程后继续。'); return }
    try {
      const context = JSON.parse(saved) as { draft: TripDraftInput; trip: CreateSingleDayTrip }
      setBuilding(true); setError('')
      // Idempotently confirm the exact Trip used for this route.  This also
      // repairs browser sessions that were created before the S2 workflow
      // hand-off existed.
      const confirmed = await tripApi.confirmDraft({ ...context.draft, tripId })
      const confirmedTrip = confirmed.data
      // The organizer already confirmed care needs in question 5. Mirror that
      // confirmation into the existing deterministic planning boundary.
      const profile = confirmedTrip.participants[0]?.assistanceProfile
      if (!profile) throw new Error('已确认行程缺少关怀配置，请返回对话页重新创建。')
      await tripApi.saveConstraintDraft(tripId, profile)
      await tripApi.confirmConstraints(tripId)
      const result = await loadAmapPlan(tripId, context.draft, undefined, { confirmedTrip, organizerToken: token })
      navigate(`/workspace?tripId=${tripId}`, { state: { tripId, draft: context.draft, trip: confirmedTrip, amapPlanResult: result } })
    } catch (caught) { setError(caught instanceof Error ? caught.message : '路线生成失败，请检查地点和高德服务。') }
    finally { setBuilding(false) }
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
      <div className="trusted-plan__explain"><article><strong>照顾点</strong><ul>{trustedPlan.carePoints.map((point) => <li key={point}>{point}</li>)}</ul></article><article><strong>妥协说明</strong><ul>{trustedPlan.compromises.length ? trustedPlan.compromises.map((item) => <li key={item}>{item}</li>) : <li>单人行程，无需跨成员妥协。</li>}</ul></article><article className={trustedPlan.unknownFacts.length ? 'is-unknown' : ''}><strong>未知事实</strong><ul>{trustedPlan.unknownFacts.length ? trustedPlan.unknownFacts.map((item) => <li key={item}>{item}</li>) : <li>当前任务的必要地点事实已齐全。</li>}</ul></article></div>
      <div className="planner-actions"><span className="save-state">{confirmed ? '方案已确认。下一步将核验起终点、路线、价格与约束。' : trustedPlan.confirmationMessage}</span>{!confirmed ? <button className="button button--primary" onClick={() => setConfirmed(true)}>确认唯一方案 <ShieldCheck size={17} /></button> : <button className="button button--primary" disabled={building} onClick={() => void buildRoute()}>{building ? <LoaderCircle className="spin-icon" size={17} /> : '生成完整路线'} <ArrowRight size={17} /></button>}</div>
    </section>}
    {bundle && !trustedPlan && <section className="draft-confirmation"><p className="form-error">服务端尚未生成唯一方案，请刷新后重试。</p></section>}
  </section></main></AppShell>
}
