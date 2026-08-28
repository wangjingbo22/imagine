import { ArrowRight, CalendarDays, Check, Copy, Link2, LockKeyhole, MapPin, Sparkles, UserRound, UsersRound, WalletCards, Clock3 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppShell } from '../components/AppShell'
import { request } from '../api/client'

const questions = [
  ['trip', '这次想去哪里、哪天出发、当天大约什么时间可用？'],
  ['party', '一共几个人出行？谁是组织者？'],
  ['endpoints_budget', '从哪里出发、最终回到哪里？共享预算大约是多少？'],
  ['preferences', '每个人喜欢什么、必去哪里、希望避开什么？'],
  ['assistance', '是否有人有预算上限、步行、换乘、休息或关怀需求？'],
  ['confirm', '请确认以上描述；还需要补充什么不可妥协的限制吗？'],
] as const

type Parsed = {
  cityName: string | null
  travelDate: string | null
  startTime: string | null
  endTime: string | null
  startLocationText: string | null
  endLocationText: string | null
  budgetCents: number | null
  interests: string[]
  mustVisit: string[]
  avoidPlaces: string[]
}
type ConversationResult = { state: { tripId: string; expectedParticipants: number; participants: Array<{ participantId: string; status: string }> } | null; parse: { parsed: Parsed; canPlan: boolean; confirmationItems: Array<{ message: string }>; trip: null }; organizerAccessToken: string | null }
type Invitation = { invitationUrl: string }
type CollaborationState = {
  tripId: string
  status: string
  expectedParticipants: number
  currentRevision: number
  collaborationVersion: number
  participants: Array<{ participantId: string; status: string; isOrganizer: boolean }>
  conflicts: Array<{ conflictId: string; message: string; suggestion: string; allowedRelaxations: Array<{ id: string; label: string }> }>
}
function toCollaborationState(value: any): CollaborationState { return { tripId: value.tripId, status: value.status, expectedParticipants: value.progress.expectedCount, currentRevision: value.currentRevision, collaborationVersion: value.collaborationVersion, participants: value.participants.map((item: any) => ({ participantId: item.participantId, status: item.confirmationStatus, isOrganizer: item.role === 'ORGANIZER' })), conflicts: value.confirmationItems.map((item: any) => ({ conflictId: item.itemId, message: item.reason, suggestion: item.candidates.join('、'), allowedRelaxations: item.relaxations.map((choice: any) => ({ id: choice.relaxationId, label: choice.label })) })) } }

function idempotencyKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`
}

export function ConversationPlannerPage() {
  const [description, setDescription] = useState('')
  const [answers, setAnswers] = useState<string[]>(Array(questions.length).fill(''))
  const [tripFields, setTripFields] = useState({ city: '', date: '', startTime: '', endTime: '' })
  const [routeFields, setRouteFields] = useState({ start: '', end: '', budget: '' })
  const [entryMode, setEntryMode] = useState<'single' | 'group' | null>(null)
  const [inviteLink, setInviteLink] = useState('')
  const [step, setStep] = useState(0)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ConversationResult | null>(null)
  const [links, setLinks] = useState<string[]>([])
  const [collaboration, setCollaboration] = useState<CollaborationState | null>(null)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const cardAnswersReady = Boolean(tripFields.city.trim() && tripFields.date.trim() && tripFields.startTime.trim() && tripFields.endTime.trim() && routeFields.start.trim() && routeFields.end.trim() && routeFields.budget.trim())
  const isReady = description.trim().length > 0 && cardAnswersReady && answers.every((answer) => answer.trim().length > 0)
  const currentStepReady = step === 0
    ? Boolean(tripFields.city.trim() && tripFields.date.trim() && tripFields.startTime.trim() && tripFields.endTime.trim())
    : step === 2
      ? Boolean(routeFields.start.trim() && routeFields.end.trim() && routeFields.budget.trim())
      : Boolean(answers[step].trim())
  const currentQuestion = questions[step]
  const preview = useMemo(() => result?.parse.parsed, [result])
  const organizerToken = result?.state ? window.sessionStorage.getItem(`organizer-token:${result.state.tripId}`) : null

  useEffect(() => {
    if (!result?.state || !organizerToken) return
    let active = true
    const refresh = async () => {
      try {
        const state = await request<CollaborationState>(`/api/v2/trips/${result.state?.tripId}/collaboration`)
        if (active) setCollaboration(toCollaborationState(state.data))
      } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : '无法刷新成员状态。') }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 8000)
    return () => { active = false; window.clearInterval(timer) }
  }, [result?.state, organizerToken])

  function updateAnswer(value: string) {
    setAnswers((current) => current.map((answer, index) => index === step ? value : answer))
  }

  function updateTripField(field: keyof typeof tripFields, value: string) {
    setTripFields((current) => {
      const next = { ...current, [field]: value }
      updateAnswer(`目的城市：${next.city}；出行日期：${next.date}；可用时间：${next.startTime}到${next.endTime}`)
      return next
    })
  }

  function updateRouteField(field: keyof typeof routeFields, value: string) {
    setRouteFields((current) => {
      const next = { ...current, [field]: value }
      updateAnswer(`从${next.start}出发；结束地：${next.end}；共享预算：${next.budget}`)
      return next
    })
  }

  function begin(mode: 'single' | 'group') {
    setEntryMode(mode)
    if (mode === 'single') {
      setAnswers((current) => current.map((answer, index) => index === 1 ? '1个人出行，我是组织者。' : answer))
    }
  }

  function joinExistingTrip() {
    const token = inviteLink.trim().split('/').filter(Boolean).at(-1)
    if (!token) { setError('请粘贴完整邀请链接或链接末尾的邀请码。'); return }
    navigate(`/join/${token}`)
  }

  async function analyze() {
    if (!isReady) return
    setLoading(true); setError('')
    try {
      const created = await request<any>('/api/v2/trips/conversations', {
        method: 'POST', headers: { 'Idempotency-Key': idempotencyKey('organizer-conversation') },
        body: JSON.stringify({ schemaVersion: '1.0', referenceDate: new Date().toISOString().slice(0, 10), naturalLanguageRequest: description, answers: questions.map(([questionId], index) => ({ questionId, answer: answers[index] })) }),
      })
      if (!created.data.revision || !created.data.organizerAccess?.organizerToken) {
        throw new Error('需求尚未被解析为可创建的行程，请补全六个问题后重试。')
      }
      const revision = created.data.revision
      const organizerToken = created.data.organizerAccess.organizerToken as string
      const stateResponse = await request<any>(`/api/v2/trips/${revision.tripId}/collaboration`, { headers: { 'X-Organizer-Token': organizerToken } })
      const collaborationState = stateResponse.data
      const trip = revision.understanding.trip
      const parsed: Parsed = { cityName: trip.cityName, travelDate: trip.travelDate, startTime: trip.startTime, endTime: trip.endTime, startLocationText: trip.startLocationText, endLocationText: trip.endLocationText, budgetCents: trip.budgetCents, interests: revision.understanding.participants.flatMap((item: any) => item.interests ?? []), mustVisit: revision.understanding.participants.flatMap((item: any) => item.mustVisit ?? []), avoidPlaces: revision.understanding.participants.flatMap((item: any) => item.avoidPlaces ?? []) }
      const compatible: ConversationResult = { state: { tripId: revision.tripId, expectedParticipants: collaborationState.progress.expectedCount, participants: collaborationState.participants }, parse: { parsed, canPlan: false, confirmationItems: [], trip: null }, organizerAccessToken: organizerToken }
      setResult(compatible)
      window.sessionStorage.setItem(`organizer-token:${revision.tripId}`, organizerToken)
      setCollaboration(toCollaborationState(collaborationState))
      const invitations = await Promise.all(collaborationState.participants.filter((item: any) => item.participantId !== collaborationState.organizerParticipantId).map((item: any) => request<Invitation>(`/api/v2/trips/${revision.tripId}/participants/${item.participantId}/invitations`, { method: 'POST', headers: { 'X-Organizer-Token': organizerToken, 'Idempotency-Key': idempotencyKey('participant-invitation') }, body: JSON.stringify({ schemaVersion: '1.0', expectedVersion: collaborationState.collaborationVersion }) })))
      setLinks(invitations.map((item) => `${window.location.origin}${item.data.invitationUrl ?? ''}`))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '对话解析失败，请稍后重试。')
    } finally { setLoading(false) }
  }

  async function resolveConflict(conflictId: string, relaxation: string) {
    if (!result?.state || !organizerToken) return
    setLoading(true); setError('')
    try {
      const updated = await request<any>(`/api/v2/trips/${result.state.tripId}/confirmation-items/${conflictId}/resolve`, {
        method: 'POST', headers: { 'X-Organizer-Token': organizerToken, 'Idempotency-Key': idempotencyKey('organizer-resolve') }, body: JSON.stringify({ schemaVersion: '1.0', baseRevision: collaboration?.currentRevision, expectedVersion: collaboration?.collaborationVersion, relaxationId: relaxation }),
      })
      setCollaboration(toCollaborationState(updated.data))
    } catch (caught) { setError(caught instanceof Error ? caught.message : '冲突处理失败。') }
    finally { setLoading(false) }
  }

  function editAnswer(index: number) {
    setResult(null)
    setCollaboration(null)
    setLinks([])
    setStep(index)
    setError('')
  }

  return <AppShell compact>
    <main className="planner-layout">
      <aside className="planner-sidebar">
        <div><span className="eyebrow">S2 · 对话建行程</span><h1>把旅行，<br />说给我听。</h1><p>我们会用六个小问题收集完整信息，再一次性整理为可确认的行程需求。</p></div>
        <ol className="step-list">{questions.map(([, label], index) => <li key={label} className={index < step || result ? 'is-complete' : index === step ? 'is-current' : ''}><span>{index < step || result ? <Check size={14} /> : index + 1}</span><div><strong>问题 {index + 1}</strong><small>{label.slice(0, 16)}…</small></div></li>)}</ol>
        <div className="privacy-note"><LockKeyhole size={17} /><span>你的回答仅用于整理行程偏好。成员资料各自独立确认。</span></div>
      </aside>
      <section className="planner-panel conversation-panel" data-reveal="panel">
      <header className="planner-panel__header"><div><span className="section-kicker">CONVERSATIONAL TRIP</span><h2>{result ? '确认你的旅行需求' : '从一句期待开始'}</h2></div><span className="save-state"><span className="status-dot" /> 已自动保存当前回答</span></header>
      {!result && entryMode === null && <section className="entry-mode-card"><div><span className="section-kicker">CHOOSE YOUR WAY</span><h3>这次，怎么出发？</h3><p>单人行程直接开始；多人由组织者创建后发送邀请链接，成员各自填写自己的资料。</p></div><div className="entry-mode-grid"><button type="button" onClick={() => begin('single')}><UserRound size={21} /><strong>单人创建</strong><small>我自己规划一趟行程</small><ArrowRight size={17} /></button><button type="button" onClick={() => begin('group')}><UsersRound size={21} /><strong>多人创建</strong><small>我是组织者，邀请同行成员</small><ArrowRight size={17} /></button></div><div className="join-entry"><span><Link2 size={16} />已有多人邀请？</span><input value={inviteLink} onChange={(event) => setInviteLink(event.target.value)} placeholder="粘贴邀请链接" /><button className="button button--soft" type="button" onClick={joinExistingTrip}>加入行程</button></div></section>}
      {!result && entryMode !== null && <>
        <section className="conversation-card"><div className="conversation-intro"><span><Sparkles size={18} /></span><div><strong>先写一句总体期待</strong><p>它会和六个问题的回答一起交给 Agent，不会提前调用模型。</p></div></div>
        <label className="field-label" htmlFor="goal">这趟旅行，你最希望得到什么？</label>
        <textarea id="goal" className="conversation-textarea" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="例如：和朋友去驻马店玩一天，想轻松一点，也想吃当地特色。" />
        <section className="question-bubble"><div className="question-bubble__meta"><span>问题 {step + 1} / {questions.length}</span><span>{Math.round(((step + 1) / questions.length) * 100)}%</span></div><h3>{currentQuestion[1]}</h3>
          {step === 0 ? <div className="question-field-cards question-field-cards--trip"><label><span><MapPin size={16} />目的城市</span><input value={tripFields.city} onChange={(event) => updateTripField('city', event.target.value)} placeholder="例如：杭州、驻马店" /></label><label><span><CalendarDays size={16} />出行日期</span><input type="date" value={tripFields.date} onChange={(event) => updateTripField('date', event.target.value)} /></label><fieldset className="time-picker-card"><legend><Clock3 size={16} />可用时间</legend><div><label>开始<input type="time" value={tripFields.startTime} onChange={(event) => updateTripField('startTime', event.target.value)} /></label><span>—</span><label>结束<input type="time" value={tripFields.endTime} onChange={(event) => updateTripField('endTime', event.target.value)} /></label></div></fieldset></div> : step === 2 ? <div className="question-field-cards question-field-cards--route"><label><span><MapPin size={16} />出发地</span><input value={routeFields.start} onChange={(event) => updateRouteField('start', event.target.value)} placeholder="例如：杭州东站" /></label><label><span><MapPin size={16} />结束地</span><input value={routeFields.end} onChange={(event) => updateRouteField('end', event.target.value)} placeholder="例如：晚上回杭州东站" /></label><label><span><WalletCards size={16} />共享预算</span><input value={routeFields.budget} onChange={(event) => updateRouteField('budget', event.target.value)} placeholder="例如：总共 500 元" /></label></div> : <textarea className="conversation-textarea conversation-textarea--answer" value={answers[step]} onChange={(event) => updateAnswer(event.target.value)} placeholder="用自然语言回答即可，不用填表。" />}
          {step === 1 && entryMode === 'group' && <div className="party-picker"><span>同行人数</span><div>{[2, 3].map((count) => <button key={count} type="button" className={answers[1].startsWith(String(count)) ? 'is-selected' : ''} onClick={() => updateAnswer(`${count}个人出行，我是组织者。`)}><UsersRound size={18} />{count} 人</button>)}</div></div>}
          <div className="planner-actions"><button className="button button--ghost" type="button" disabled={step === 0} onClick={() => setStep((value) => value - 1)}>上一个问题</button>{step < questions.length - 1 ? <button className="button button--primary" type="button" disabled={!currentStepReady} onClick={() => setStep((value) => value + 1)}>下一个问题 <ArrowRight size={18} /></button> : <button className="button button--primary" type="button" disabled={!isReady || loading} onClick={analyze}>{loading ? '正在整理需求…' : '完成问答并智能整理'} <ArrowRight size={18} /></button>}</div>
        </section></section></>}
      {error && <p className="form-error">{error}</p>}
      {result && <section className="confirmation-card"><div className="confirmation-card__head"><span><Check size={20} /></span><div><strong>Agent 解析确认卡</strong><p>{result.parse.canPlan ? '已整理完成。核对无误后，把邀请链接发给同行成员。' : '仍有需要补充的信息，请回到对应问题修正。'}</p></div></div>
        <ul className="confirmation-grid">{[['城市', preview?.cityName], ['日期', preview?.travelDate], ['时间', `${preview?.startTime ?? '未识别'} 至 ${preview?.endTime ?? '未识别'}`], ['起终点', `${preview?.startLocationText ?? '未识别'} → ${preview?.endLocationText ?? '未识别'}`], ['预算', preview?.budgetCents === null || preview?.budgetCents === undefined ? '未识别' : `¥${preview.budgetCents / 100}`], ['兴趣', preview?.interests.join('、') || '未识别']].map(([label, value]) => <li key={label}><strong>{label}</strong><span>{value}</span></li>)}</ul>
        {result.parse.confirmationItems.map((item) => <p className="form-error" key={item.message}>{item.message}</p>)}
        <div><strong>需要更正？</strong><p>{questions.map(([, question], index) => <button className="button button--soft" type="button" key={question} onClick={() => editAnswer(index)}>修改第 {index + 1} 问</button>)}</p></div>
        {links.length > 0 && <div className="invite-card"><strong>成员邀请链接</strong><p>每个链接只对应一名成员，资料确认后自动失效。</p>{links.map((link, index) => <div className="invite-row" key={link}><span>成员 {index + 1}</span><code>{link}</code><button type="button" className="button button--soft" onClick={() => navigator.clipboard.writeText(link)}><Copy size={14} />复制</button></div>)}</div>}
        {collaboration && <div className="draft-confirmation"><div className="draft-confirmation__heading"><span><UsersRound size={18} /></span><div><strong>协作进度</strong><p>{collaboration.participants.filter((item) => item.status === 'CONFIRMED').length} / {collaboration.expectedParticipants} 位成员已确认 · {collaboration.status}</p></div></div>
          {collaboration.conflicts.map((conflict) => <div key={conflict.conflictId}><p className="form-error">{conflict.message}。{conflict.suggestion}</p>{conflict.allowedRelaxations.map((relaxation) => <button className="button button--soft" disabled={loading} key={relaxation.id} onClick={() => void resolveConflict(conflict.conflictId, relaxation.id)}>采用：{relaxation.label}</button>)}</div>)}
          {collaboration.status === 'READY_TO_PLAN' && <button className="button button--primary" onClick={() => navigate(`/recommendation/${collaboration.tripId}`)}>查看唯一推荐 <ArrowRight size={18} /></button>}
        </div>}
      </section>}
    </section></main>
  </AppShell>
}
