import { ArrowRight, CalendarDays, Check, Clock3, MapPin, Sparkles, UsersRound, WalletCards } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { request } from '../api/client'
import { AppShell } from '../components/AppShell'

const questions = [
  ['trip', '这次行程的目标、城市、日期和可用时间是什么？'],
  ['party', '同行人数和组织者是谁？'],
  ['endpoints_budget', '你的出发/结束地点，以及共享预算安排是什么？'],
  ['preferences', '你喜欢什么、必去哪里、希望避开什么？'],
  ['assistance', '你的预算上限、步行、换乘、休息或关怀限制是什么？'],
  ['confirm', '请确认以上描述；还有什么不能妥协的限制？'],
] as const

type Invitation = { tripId: string; participantId: string; currentRevision: number; collaborationVersion: number; sharedTrip: { cityName: string | null; travelDate: string | null; startTime: string | null; endTime: string | null; startLocationText: string | null; endLocationText: string | null; budgetCents: number | null; interests: string[]; mustVisit: string[]; avoidPlaces: string[] } }
type State = { status: string; conflicts: Array<{ message: string; suggestion: string }> }
type Parse = { parsed: { cityName: string | null; travelDate: string | null; interests: string[]; mustVisit: string[]; avoidPlaces: string[] }; canPlan: boolean; confirmationItems: Array<{ message: string }> }

export function MemberConversationPage() {
  const { token = '' } = useParams()
  const location = useLocation()
  const [invitation, setInvitation] = useState<Invitation | null>(null)
  const [description, setDescription] = useState('')
  const [answers, setAnswers] = useState<string[]>(Array(questions.length).fill(''))
  const [tripFields, setTripFields] = useState({ city: '', date: '', startTime: '', endTime: '' })
  const [routeFields, setRouteFields] = useState({ start: '', end: '', budget: '' })
  const [step, setStep] = useState(0)
  const [parse, setParse] = useState<Parse | null>(null)
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const invitationToken = token || new URLSearchParams(location.hash.slice(1)).get('token') || ''
    request<any>('/api/v2/participant-invitations/redeem', { method: 'POST', headers: { 'Idempotency-Key': `redeem-${crypto.randomUUID()}` }, body: JSON.stringify({ schemaVersion: '1.0', token: invitationToken }) })
      .then((redeemed) => {
        const session = redeemed.data.participantSessionToken
        if (!session) throw new Error('邀请已被使用，请在原浏览器继续填写。')
        window.sessionStorage.setItem(`participant-session:${redeemed.data.tripId}`, session)
        return request<any>('/api/v2/member-session', { headers: { 'X-Participant-Session': session } })
      }).then((result) => {
        setInvitation(result.data)
        const shared = result.data.sharedTrip
        setTripFields({
          city: shared.cityName ?? '', date: shared.travelDate ?? '',
          startTime: shared.startTime ?? '', endTime: shared.endTime ?? '',
        })
        setRouteFields({
          start: shared.startLocationText ?? '', end: shared.endLocationText ?? '',
          budget: shared.budgetCents === null ? '' : String(shared.budgetCents / 100),
        })
        setDescription(`参加组织者创建的${shared.cityName ?? ''}行程。我会在共同安排基础上补充和修改自己的偏好。`)
        setAnswers([
          `城市：${shared.cityName ?? ''}；日期：${shared.travelDate ?? ''}；时间：${shared.startTime ?? ''}到${shared.endTime ?? ''}`,
          '沿用组织者创建的同行信息。',
          `从${shared.startLocationText ?? ''}出发；结束地：${shared.endLocationText ?? ''}；共享预算：${shared.budgetCents === null ? '' : `${shared.budgetCents / 100}元`}`,
          `兴趣：${shared.interests.join('、')}；必去：${shared.mustVisit.join('、')}；避开：${shared.avoidPlaces.join('、')}`,
          '沿用共同安排；我会补充自己的步行、休息和预算限制。',
          '我已查看组织者填写的共同信息，并确认或修改自己的需求。',
        ])
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : '邀请链接无效。'))
      .finally(() => setLoading(false))
  }, [location.hash, token])

  const ready = description.trim() && answers.every((answer) => answer.trim())
  const currentStepReady = step === 0
    ? Boolean(tripFields.city.trim() && tripFields.date.trim() && tripFields.startTime.trim() && tripFields.endTime.trim())
    : step === 2
      ? Boolean(routeFields.start.trim() && routeFields.end.trim() && routeFields.budget.trim())
      : Boolean(answers[step].trim())

  function updateAnswer(value: string) {
    setAnswers((items) => items.map((item, index) => index === step ? value : item))
  }

  function updateTripField(field: keyof typeof tripFields, value: string) {
    setTripFields((current) => {
      const next = { ...current, [field]: value }
      setAnswers((items) => items.map((item, index) => index === 0
        ? `目的城市：${next.city}；出行日期：${next.date}；可用时间：${next.startTime}到${next.endTime}` : item))
      return next
    })
  }

  function updateRouteField(field: keyof typeof routeFields, value: string) {
    setRouteFields((current) => {
      const next = { ...current, [field]: value }
      setAnswers((items) => items.map((item, index) => index === 2
        ? `从${next.start}出发；结束地：${next.end}；共享预算：${next.budget}元` : item))
      return next
    })
  }
  const body = () => ({
    naturalLanguageRequest: description,
    answers: questions.map(([questionId], index) => ({ questionId, answer: answers[index] })),
  })

  async function submit() {
    if (!ready) return
    setLoading(true); setError('')
    try {
      if (!invitation) return
      const session = window.sessionStorage.getItem(`participant-session:${invitation.tripId}`)
      const result = await request<any>('/api/v2/member-session/conversation', { method: 'PUT', headers: { 'X-Participant-Session': session ?? '', 'Idempotency-Key': `member-conversation-${crypto.randomUUID()}` }, body: JSON.stringify({ schemaVersion: '1.0', baseRevision: invitation.currentRevision, expectedVersion: invitation.collaborationVersion, ...body() }) })
      setInvitation(result.data)
      setParse({ parsed: { cityName: result.data.sharedTrip.cityName, travelDate: result.data.sharedTrip.travelDate, interests: result.data.participant.interests ?? [], mustVisit: result.data.participant.mustVisit ?? [], avoidPlaces: result.data.participant.avoidPlaces ?? [] }, canPlan: true, confirmationItems: result.data.confirmationItems.map((item: any) => ({ message: item.reason })) })
    } catch (caught) { setError(caught instanceof Error ? caught.message : '资料整理失败。') }
    finally { setLoading(false) }
  }

  async function confirm() {
    setLoading(true); setError('')
    try {
      if (!invitation) return
      const session = window.sessionStorage.getItem(`participant-session:${invitation.tripId}`)
      const result = await request<any>('/api/v2/member-session/confirm', { method: 'POST', headers: { 'X-Participant-Session': session ?? '', 'Idempotency-Key': `member-confirm-${crypto.randomUUID()}` }, body: JSON.stringify({ schemaVersion: '1.0', baseRevision: invitation.currentRevision, expectedVersion: invitation.collaborationVersion }) })
      setState({ status: result.data.status, conflicts: result.data.confirmationItems.map((item: any) => ({ message: item.reason, suggestion: '' })) })
      setParse(null)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '确认失败。') }
    finally { setLoading(false) }
  }

  if (loading && !invitation && !error) return <AppShell compact><main className="planner-layout"><section className="planner-panel"><p>正在验证邀请链接…</p></section></main></AppShell>
  if (!invitation) return <AppShell compact><main className="planner-layout"><section className="planner-panel"><h1>此邀请不可用</h1><p className="form-error">{error || '链接已失效、撤销，或已被确认使用。'}</p></section></main></AppShell>

  return <AppShell compact><main className="planner-layout"><section className="planner-panel" data-reveal="panel">
    <span className="section-kicker">MEMBER CONVERSATION</span>
    <h1>填写你的旅行偏好</h1>
    <p>已复制组织者填写的共同信息，你可以逐项改成自己的需求；你的修改不会影响其他成员。确认后邀请链接将失效。</p>
    <section className="shared-trip-card"><div className="shared-trip-card__head"><span><UsersRound size={18} /></span><div><strong>已从组织者复制共同信息</strong><p>下面内容是草稿，你仍可在问答中改动。</p></div></div><div className="shared-trip-card__grid"><article><MapPin size={15} /><span>目的城市</span><strong>{invitation.sharedTrip.cityName || '待补充'}</strong></article><article><CalendarDays size={15} /><span>出行日期</span><strong>{invitation.sharedTrip.travelDate || '待补充'}</strong></article><article><Clock3 size={15} /><span>可用时间</span><strong>{invitation.sharedTrip.startTime && invitation.sharedTrip.endTime ? `${invitation.sharedTrip.startTime} — ${invitation.sharedTrip.endTime}` : '待补充'}</strong></article><article><MapPin size={15} /><span>起终点</span><strong>{invitation.sharedTrip.startLocationText || '待补充'} → {invitation.sharedTrip.endLocationText || '待补充'}</strong></article><article><WalletCards size={15} /><span>共享预算</span><strong>{invitation.sharedTrip.budgetCents === null ? '待补充' : `¥${invitation.sharedTrip.budgetCents / 100}`}</strong></article></div></section>
    {error && <p className="form-error">{error}</p>}
    {!parse && state?.status !== 'READY_TO_PLAN' && <>
      <label className="field-label" htmlFor="member-goal">先说说你对这趟旅行的期待</label>
      <textarea id="member-goal" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="例如：我更喜欢慢节奏，也不想走太久。" />
      <section className="draft-confirmation"><div className="draft-confirmation__heading"><span><Sparkles size={18} /></span><div><strong>问题 {step + 1} / 6</strong><p>{questions[step][1]}</p></div></div>
        {step === 0 ? <div className="question-field-cards question-field-cards--trip"><label><span><MapPin size={16} />目的城市</span><input value={tripFields.city} onChange={(event) => updateTripField('city', event.target.value)} placeholder="例如：杭州" /></label><label><span><CalendarDays size={16} />出行日期</span><input type="date" value={tripFields.date} onChange={(event) => updateTripField('date', event.target.value)} /></label><fieldset className="time-picker-card"><legend><Clock3 size={16} />可用时间</legend><div><label>开始<input type="time" value={tripFields.startTime} onChange={(event) => updateTripField('startTime', event.target.value)} /></label><span>—</span><label>结束<input type="time" value={tripFields.endTime} onChange={(event) => updateTripField('endTime', event.target.value)} /></label></div></fieldset></div> : step === 2 ? <div className="question-field-cards question-field-cards--route"><label><span><MapPin size={16} />出发地</span><input value={routeFields.start} onChange={(event) => updateRouteField('start', event.target.value)} placeholder="例如：杭州东站" /></label><label><span><MapPin size={16} />结束地</span><input value={routeFields.end} onChange={(event) => updateRouteField('end', event.target.value)} placeholder="例如：回到杭州东站" /></label><label><span><WalletCards size={16} />共享预算</span><input inputMode="decimal" value={routeFields.budget} onChange={(event) => updateRouteField('budget', event.target.value)} placeholder="例如：500" /></label></div> : <textarea value={answers[step]} onChange={(event) => updateAnswer(event.target.value)} placeholder="请输入你的回答" />}
        <div className="planner-actions"><button className="button button--ghost" disabled={step === 0 || loading} onClick={() => setStep((value) => value - 1)}>上一个问题</button>{step < 5 ? <button className="button button--primary" disabled={!currentStepReady || loading} onClick={() => setStep((value) => value + 1)}>下一个问题 <ArrowRight size={18} /></button> : <button className="button button--primary" disabled={!ready || loading} onClick={submit}>整理并查看确认 <ArrowRight size={18} /></button>}</div>
      </section>
    </>}
    {parse && <section className="draft-confirmation"><div className="draft-confirmation__heading"><span><Check size={18} /></span><div><strong>资料确认卡</strong><p>{parse.parsed.cityName || '行程城市待确认'} · {parse.parsed.travelDate || '日期待确认'} · {parse.parsed.interests.join('、') || '偏好待确认'}</p></div></div>{parse.confirmationItems.map((item) => <p className="form-error" key={item.message}>{item.message}</p>)}<div className="planner-actions"><button className="button button--ghost" disabled={loading} onClick={() => setParse(null)}>返回修改</button><button className="button button--primary" disabled={loading || !parse.canPlan} onClick={confirm}>确认我的资料</button></div></section>}
    {state && !parse && <section className="draft-confirmation"><strong>{state.status === 'READY_TO_PLAN' ? '所有成员已确认，可以由组织者继续规划。' : '你的资料已确认，正在等待其他成员。'}</strong>{state.conflicts.map((conflict) => <p className="form-error" key={conflict.message}>{conflict.message}。{conflict.suggestion}</p>)}</section>}
  </section></main></AppShell>
}
