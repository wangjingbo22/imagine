import { ArrowRight, CalendarDays, Check, Clock3, MapPin, Sparkles, UsersRound, WalletCards } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import {
  confirmMemberSession,
  getMemberSession,
  isFixedQuestionFallback,
  newIdempotencyKey,
  redeemParticipantInvitation,
  submitMemberConversation,
} from '../api/collaborationApi'
import { AppShell } from '../components/AppShell'
import type {
  FixedQuestionFallbackResponse,
  MemberSessionView,
} from '../domain/collaboration'
import { invitationTokenFromText } from '../services/collaborationDraft'

const questions = [
  ['trip', '这次行程的目标、城市、日期和可用时间是什么？'],
  ['party', '同行人数和组织者是谁？'],
  ['endpoints_budget', '你的出发/结束地点，以及共享预算安排是什么？'],
  ['preferences', '你喜欢什么、必去哪里、希望避开什么？'],
  ['assistance', '你的预算上限、步行、换乘、休息或关怀限制是什么？'],
  ['confirm', '请确认以上描述；还有什么不能妥协的限制？'],
] as const

function careSummary(view: MemberSessionView): string {
  const care = view.participant.careDraft
  if (!care) return '没有额外关怀限制。'
  return [
    care.assistanceTypeHint ? `关怀类型：${care.assistanceTypeHint}` : null,
    care.walkLimits.maxContinuousMeters === null ? null : `连续步行不超过${care.walkLimits.maxContinuousMeters}米`,
    care.maxTransfers === null ? null : `最多换乘${care.maxTransfers}次`,
    care.restIntervalMinutes === null ? null : `每${care.restIntervalMinutes}分钟休息`,
    care.avoidStairs ? '避开楼梯' : null,
  ].filter(Boolean).join('；') || '没有额外关怀限制。'
}

export function MemberConversationPage() {
  const { token: pathToken = '' } = useParams()
  const location = useLocation()
  const token = invitationTokenFromText(pathToken) ?? invitationTokenFromText(location.hash)
  const [sessionToken, setSessionToken] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [view, setView] = useState<MemberSessionView | null>(null)
  const [description, setDescription] = useState('')
  const [answers, setAnswers] = useState<string[]>(Array(questions.length).fill(''))
  const [tripFields, setTripFields] = useState({ city: '', date: '', startTime: '', endTime: '' })
  const [routeFields, setRouteFields] = useState({ start: '', end: '', budget: '' })
  const [step, setStep] = useState(0)
  const [reviewing, setReviewing] = useState(false)
  const [fallback, setFallback] = useState<FixedQuestionFallbackResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    const initialize = async () => {
      try {
        let capability = token
          ? window.sessionStorage.getItem(`participant-session:${token}`)
          : window.sessionStorage.getItem('participant-session:last')
        if (!capability && token) {
          const keyName = `participant-redeem-key:${token}`
          const key = window.sessionStorage.getItem(keyName) ?? newIdempotencyKey('s2-participant-redeem')
          window.sessionStorage.setItem(keyName, key)
          const redeemed = await redeemParticipantInvitation(token, key)
          if (!redeemed.participantSessionToken || !redeemed.sessionTokenAvailable) {
            throw new Error('邀请已兑换，但成员会话密钥不可再次显示。请在首次打开邀请的同一标签页继续。')
          }
          capability = redeemed.participantSessionToken
          if (active) setExpiresAt(redeemed.expiresAt)
          window.sessionStorage.setItem(`participant-session:${token}`, capability)
          window.sessionStorage.setItem('participant-session:last', capability)
          window.sessionStorage.removeItem(keyName)
          window.history.replaceState(null, '', '/join')
        }
        if (!capability) throw new Error('缺少有效的一次性邀请或成员会话。')
        const current = await getMemberSession(capability)
        if (!active) return
        setSessionToken(capability)
        setView(current)
        const shared = current.sharedTrip
        const participant = current.participant
        setTripFields({
          city: shared.cityName ?? '', date: shared.travelDate ?? '',
          startTime: shared.startTime ?? '', endTime: shared.endTime ?? '',
        })
        setRouteFields({
          start: shared.startLocationText ?? '', end: shared.endLocationText ?? '',
          budget: shared.budgetCents === null ? '' : String(shared.budgetCents / 100),
        })
        setDescription(`参加组织者创建的${shared.cityName ?? ''}行程，并独立确认我的个人偏好与关怀限制。`)
        setAnswers([
          `城市：${shared.cityName ?? ''}；日期：${shared.travelDate ?? ''}；时间：${shared.startTime ?? ''}到${shared.endTime ?? ''}`,
          '同行信息由组织者管理；我是通过一次性邀请加入的成员。',
          `从${shared.startLocationText ?? ''}出发；结束地：${shared.endLocationText ?? ''}；共享预算：${shared.budgetCents === null ? '' : `${shared.budgetCents / 100}元`}`,
          `兴趣：${participant.interests.join('、')}；必去：${participant.mustVisit.join('、')}；避开：${participant.avoidPlaces.join('、')}`,
          `个人预算上限：${participant.budgetCapCents === null ? '未设置' : `${participant.budgetCapCents / 100}元`}；${careSummary(current)}`,
          '我已查看共同信息，并确认这里填写的是我本人的需求。',
        ])
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : '邀请链接无效。')
      } finally {
        if (active) setLoading(false)
      }
    }
    void initialize()
    return () => { active = false }
  }, [token])

  const ready = Boolean(description.trim() && answers.every((answer) => answer.trim()))
  const currentStepReady = step === 0
    ? Boolean(tripFields.city.trim() && tripFields.date.trim() && tripFields.startTime.trim() && tripFields.endTime.trim())
    : step === 2
      ? Boolean(routeFields.start.trim() && routeFields.end.trim() && routeFields.budget.trim())
      : Boolean(answers[step].trim())
  const hasBlockingIssue = view?.confirmationItems.some((item) => item.code !== 'CONFLICT') ?? false

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

  async function submit() {
    if (!ready || !view || !sessionToken) return
    setLoading(true); setError('')
    try {
      const outcome = await submitMemberConversation({
        participantSessionToken: sessionToken,
        baseRevision: view.currentRevision,
        expectedVersion: view.collaborationVersion,
        naturalLanguageRequest: description,
        answers: questions.map(([questionId], index) => ({ questionId, answer: answers[index] })),
      })
      if (isFixedQuestionFallback(outcome)) {
        setFallback(outcome)
        setReviewing(false)
      } else {
        setFallback(null)
        setView(outcome)
        setReviewing(true)
      }
    } catch (caught) { setError(caught instanceof Error ? caught.message : '资料整理失败。') }
    finally { setLoading(false) }
  }

  async function confirm() {
    if (!view || !sessionToken) return
    setLoading(true); setError('')
    try {
      setView(await confirmMemberSession({
        participantSessionToken: sessionToken,
        baseRevision: view.currentRevision,
        expectedVersion: view.collaborationVersion,
      }))
      setReviewing(false)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '确认失败。') }
    finally { setLoading(false) }
  }

  if (loading && !view && !error) return <AppShell compact><main className="planner-layout"><section className="planner-panel"><p role="status">正在兑换邀请并建立仅属于你的成员会话…</p></section></main></AppShell>
  if (!view) return <AppShell compact><main className="planner-layout"><section className="planner-panel"><h1>此邀请不可用</h1><p className="form-error" role="alert">{error || '链接已失效、撤销，或已被确认使用。'}</p></section></main></AppShell>

  return <AppShell compact><main className="planner-layout"><section className="planner-panel" data-reveal="panel">
    <span className="section-kicker">MEMBER CONVERSATION</span>
    <h1>填写你的旅行偏好</h1>
    <p>你只能读取和修改自己的成员资料；组织者和其他成员的资料不会暴露在此会话中。{expiresAt && ` 会话有效至 ${new Date(expiresAt).toLocaleString('zh-CN')}。`}</p>
    <section className="shared-trip-card"><div className="shared-trip-card__head"><span><UsersRound size={18} /></span><div><strong>组织者共享的行程范围</strong><p>下面是共同安排；你的个人偏好和关怀限制独立确认。</p></div></div><div className="shared-trip-card__grid"><article><MapPin size={15} /><span>目的城市</span><strong>{view.sharedTrip.cityName || '待补充'}</strong></article><article><CalendarDays size={15} /><span>出行日期</span><strong>{view.sharedTrip.travelDate || '待补充'}</strong></article><article><Clock3 size={15} /><span>可用时间</span><strong>{view.sharedTrip.startTime && view.sharedTrip.endTime ? `${view.sharedTrip.startTime} — ${view.sharedTrip.endTime}` : '待补充'}</strong></article><article><MapPin size={15} /><span>起终点</span><strong>{view.sharedTrip.startLocationText || '待补充'} → {view.sharedTrip.endLocationText || '待补充'}</strong></article><article><WalletCards size={15} /><span>共享预算</span><strong>{view.sharedTrip.budgetCents === null ? '待补充' : `¥${view.sharedTrip.budgetCents / 100}`}</strong></article></div></section>
    {error && <p className="form-error" role="alert">{error}</p>}
    {fallback && <section className="draft-confirmation"><div className="draft-confirmation__heading"><span><Sparkles size={18} /></span><div><strong>固定问题核对</strong><p>模型本次不可用，服务端没有推进草稿版本，也不能确认资料。</p></div></div>{fallback.fallback.items.map((item, index) => <p className="form-error" key={item.questionId}>第 {index + 1} 问：{item.message}</p>)}<button className="button button--ghost" type="button" onClick={() => { setFallback(null); setStep(0) }}>返回逐题修改</button></section>}
    {!fallback && !reviewing && view.confirmationStatus !== 'CONFIRMED' && <>
      <label className="field-label" htmlFor="member-goal">先说说你对这趟旅行的期待</label>
      <textarea id="member-goal" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="例如：我更喜欢慢节奏，也不想走太久。" />
      <section className="draft-confirmation"><div className="draft-confirmation__heading"><span><Sparkles size={18} /></span><div><strong>问题 {step + 1} / 6</strong><p>{questions[step][1]}</p></div></div>
        {step === 0 ? <div className="question-field-cards question-field-cards--trip"><label><span><MapPin size={16} />目的城市</span><input value={tripFields.city} onChange={(event) => updateTripField('city', event.target.value)} placeholder="例如：杭州" /></label><label><span><CalendarDays size={16} />出行日期</span><input type="date" value={tripFields.date} onChange={(event) => updateTripField('date', event.target.value)} /></label><fieldset className="time-picker-card"><legend><Clock3 size={16} />可用时间</legend><div><label>开始<input type="time" value={tripFields.startTime} onChange={(event) => updateTripField('startTime', event.target.value)} /></label><span>—</span><label>结束<input type="time" value={tripFields.endTime} onChange={(event) => updateTripField('endTime', event.target.value)} /></label></div></fieldset></div> : step === 2 ? <div className="question-field-cards question-field-cards--route"><label><span><MapPin size={16} />出发地</span><input value={routeFields.start} onChange={(event) => updateRouteField('start', event.target.value)} placeholder="例如：杭州东站" /></label><label><span><MapPin size={16} />结束地</span><input value={routeFields.end} onChange={(event) => updateRouteField('end', event.target.value)} placeholder="例如：回到杭州东站" /></label><label><span><WalletCards size={16} />共享预算</span><input inputMode="decimal" value={routeFields.budget} onChange={(event) => updateRouteField('budget', event.target.value)} placeholder="例如：500" /></label></div> : <textarea value={answers[step]} onChange={(event) => updateAnswer(event.target.value)} placeholder="请输入你的回答" />}
        <div className="planner-actions"><button className="button button--ghost" type="button" disabled={step === 0 || loading} onClick={() => setStep((value) => value - 1)}>上一个问题</button>{step < 5 ? <button className="button button--primary" type="button" disabled={!currentStepReady || loading} onClick={() => setStep((value) => value + 1)}>下一个问题 <ArrowRight size={18} /></button> : <button className="button button--primary" type="button" disabled={!ready || loading} onClick={() => void submit()}>整理并查看确认 <ArrowRight size={18} /></button>}</div>
      </section>
    </>}
    {reviewing && <section className="draft-confirmation"><div className="draft-confirmation__heading"><span><Check size={18} /></span><div><strong>资料确认卡</strong><p>{view.sharedTrip.cityName || '行程城市待确认'} · {view.sharedTrip.travelDate || '日期待确认'} · {view.participant.interests.join('、') || '偏好待确认'}</p></div></div>{view.confirmationItems.map((item) => <p className="form-error" key={item.itemId}>规则 {item.ruleId}：{item.reason}</p>)}<div className="planner-actions"><button className="button button--ghost" type="button" disabled={loading} onClick={() => setReviewing(false)}>返回修改</button><button className="button button--primary" type="button" disabled={loading || hasBlockingIssue} onClick={() => void confirm()}>确认我的资料</button></div></section>}
    {view.confirmationStatus === 'CONFIRMED' && <section className="draft-confirmation" role="status" aria-live="polite"><strong>你的资料已确认，正在等待组织者和其他成员完成确认。</strong>{view.confirmationItems.map((item) => <p className="form-error" key={item.itemId}>规则 {item.ruleId}：{item.reason}</p>)}</section>}
  </section></main></AppShell>
}
