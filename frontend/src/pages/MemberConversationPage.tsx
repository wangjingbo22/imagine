import { ArrowRight, CalendarDays, Check, Clock3, MapPin, Sparkles, UsersRound, WalletCards } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
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

type Invitation = { tripId: string; participantId: string; expiresAt: string; status: string; sharedTrip: { cityName: string | null; travelDate: string | null; startTime: string | null; endTime: string | null; startLocationText: string | null; endLocationText: string | null; budgetCents: number | null; interests: string[]; mustVisit: string[]; avoidPlaces: string[] } }
type State = { status: string; conflicts: Array<{ message: string; suggestion: string }> }
type Parse = { parsed: { cityName: string | null; travelDate: string | null; interests: string[]; mustVisit: string[]; avoidPlaces: string[] }; canPlan: boolean; confirmationItems: Array<{ message: string }> }
type SubmittedMember = { state: State; parse: Parse }

export function MemberConversationPage() {
  const { token = '' } = useParams()
  const [invitation, setInvitation] = useState<Invitation | null>(null)
  const [description, setDescription] = useState('')
  const [answers, setAnswers] = useState<string[]>(Array(questions.length).fill(''))
  const [step, setStep] = useState(0)
  const [parse, setParse] = useState<Parse | null>(null)
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    request<Invitation>(`/api/v2/participant-invitations/${token}`)
      .then((result) => {
        setInvitation(result.data)
        const shared = result.data.sharedTrip
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
  }, [token])

  const ready = description.trim() && answers.every((answer) => answer.trim())
  const body = () => ({
    naturalLanguageRequest: description,
    answers: questions.map(([questionId], index) => ({ questionId, answer: answers[index] })),
  })

  async function submit() {
    if (!ready) return
    setLoading(true); setError('')
    try {
      const result = await request<SubmittedMember>(`/api/v2/participant-invitations/${token}/conversation`, { method: 'PUT', body: JSON.stringify(body()) })
      setState(result.data.state)
      setParse(result.data.parse)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '资料整理失败。') }
    finally { setLoading(false) }
  }

  async function confirm() {
    setLoading(true); setError('')
    try {
      const result = await request<State>(`/api/v2/participant-invitations/${token}/confirm`, { method: 'POST' })
      setState(result.data)
      setParse(null)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '确认失败。') }
    finally { setLoading(false) }
  }

  if (loading && !invitation && !error) return <AppShell compact><main className="planner-layout"><section className="planner-panel"><p>正在验证邀请链接…</p></section></main></AppShell>
  if (!invitation) return <AppShell compact><main className="planner-layout"><section className="planner-panel"><h1>此邀请不可用</h1><p className="form-error">{error || '链接已失效、撤销，或已被确认使用。'}</p></section></main></AppShell>

  return <AppShell compact><main className="planner-layout"><section className="planner-panel" data-reveal="panel">
    <span className="section-kicker">MEMBER CONVERSATION</span>
    <h1>填写你的旅行偏好</h1>
    <p>已复制组织者填写的共同信息，你可以逐项改成自己的需求；你的修改不会影响其他成员。邀请有效至 {new Date(invitation.expiresAt).toLocaleString('zh-CN')}。</p>
    <section className="shared-trip-card"><div className="shared-trip-card__head"><span><UsersRound size={18} /></span><div><strong>已从组织者复制共同信息</strong><p>下面内容是草稿，你仍可在问答中改动。</p></div></div><div className="shared-trip-card__grid"><article><MapPin size={15} /><span>目的城市</span><strong>{invitation.sharedTrip.cityName || '待补充'}</strong></article><article><CalendarDays size={15} /><span>出行日期</span><strong>{invitation.sharedTrip.travelDate || '待补充'}</strong></article><article><Clock3 size={15} /><span>可用时间</span><strong>{invitation.sharedTrip.startTime && invitation.sharedTrip.endTime ? `${invitation.sharedTrip.startTime} — ${invitation.sharedTrip.endTime}` : '待补充'}</strong></article><article><MapPin size={15} /><span>起终点</span><strong>{invitation.sharedTrip.startLocationText || '待补充'} → {invitation.sharedTrip.endLocationText || '待补充'}</strong></article><article><WalletCards size={15} /><span>共享预算</span><strong>{invitation.sharedTrip.budgetCents === null ? '待补充' : `¥${invitation.sharedTrip.budgetCents / 100}`}</strong></article></div></section>
    {error && <p className="form-error">{error}</p>}
    {!parse && state?.status !== 'READY_TO_PLAN' && <>
      <label className="field-label" htmlFor="member-goal">先说说你对这趟旅行的期待</label>
      <textarea id="member-goal" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="例如：我更喜欢慢节奏，也不想走太久。" />
      <section className="draft-confirmation"><div className="draft-confirmation__heading"><span><Sparkles size={18} /></span><div><strong>问题 {step + 1} / 6</strong><p>{questions[step][1]}</p></div></div>
        <textarea value={answers[step]} onChange={(event) => setAnswers((items) => items.map((item, index) => index === step ? event.target.value : item))} placeholder="请输入你的回答" />
        <div className="planner-actions"><button className="button button--ghost" disabled={step === 0 || loading} onClick={() => setStep((value) => value - 1)}>上一个问题</button>{step < 5 ? <button className="button button--primary" disabled={!answers[step].trim() || loading} onClick={() => setStep((value) => value + 1)}>下一个问题 <ArrowRight size={18} /></button> : <button className="button button--primary" disabled={!ready || loading} onClick={submit}>整理并查看确认 <ArrowRight size={18} /></button>}</div>
      </section>
    </>}
    {parse && <section className="draft-confirmation"><div className="draft-confirmation__heading"><span><Check size={18} /></span><div><strong>资料确认卡</strong><p>{parse.parsed.cityName || '行程城市待确认'} · {parse.parsed.travelDate || '日期待确认'} · {parse.parsed.interests.join('、') || '偏好待确认'}</p></div></div>{parse.confirmationItems.map((item) => <p className="form-error" key={item.message}>{item.message}</p>)}<div className="planner-actions"><button className="button button--ghost" disabled={loading} onClick={() => setParse(null)}>返回修改</button><button className="button button--primary" disabled={loading || !parse.canPlan} onClick={confirm}>确认我的资料</button></div></section>}
    {state && !parse && <section className="draft-confirmation"><strong>{state.status === 'READY_TO_PLAN' ? '所有成员已确认，可以由组织者继续规划。' : '你的资料已确认，正在等待其他成员。'}</strong>{state.conflicts.map((conflict) => <p className="form-error" key={conflict.message}>{conflict.message}。{conflict.suggestion}</p>)}</section>}
  </section></main></AppShell>
}
