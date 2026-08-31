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
  ['endpoints_budget', '起点、终点与共享预算安排是什么？'],
  ['preferences', '你喜欢什么、必去哪里、希望避开什么？'],
  ['assistance', '你的预算上限、步行、换乘、休息或关怀限制是什么？'],
  ['confirm', '请确认以上描述；还有什么不能妥协的限制？'],
] as const

function careSummary(view: MemberSessionView): string {
  const care = view.participant.careDraft
  if (!care) return '没有额外关怀限制。'
  const walkLimits = care.walkLimits ?? { maxContinuousMeters: null, maxDailyMeters: null }
  return [
    care.assistanceTypeHint ? `关怀类型：${care.assistanceTypeHint}` : null,
    walkLimits.maxContinuousMeters === null ? null : `连续步行不超过${walkLimits.maxContinuousMeters}米`,
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
  const [step, setStep] = useState(0)
  const [reviewing, setReviewing] = useState(false)
  const [fallback, setFallback] = useState<FixedQuestionFallbackResponse | null>(null)
  const [reviewedFallbackAnswers, setReviewedFallbackAnswers] = useState<boolean[]>(Array(questions.length).fill(false))
  const [fallbackReviewNotice, setFallbackReviewNotice] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    const timeout = window.setTimeout(() => {
      if (!active) return
      setError('成员会话加载超时，请重新打开邀请链接。')
      setLoading(false)
    }, 15_000)
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
        if (!capability) throw new Error('缺少有效的成员邀请或成员会话。')
        const current = await getMemberSession(capability)
        if (!active) return
        setSessionToken(capability)
        setView(current)
        const shared = current.sharedTrip
        const participant = current.participant
        setDescription(`参加组织者创建的${shared.cityName ?? ''}行程，并独立确认我的个人偏好与关怀限制。`)
        setAnswers([
          `城市：${shared.cityName ?? ''}；日期：${shared.travelDate ?? ''}；时间：${shared.startTime ?? ''}到${shared.endTime ?? ''}`,
          '同行信息由组织者管理；我是通过成员邀请链接加入的成员。',
          `从${shared.startLocationText ?? ''}出发；结束地：${shared.endLocationText ?? ''}；共享预算：${shared.budgetCents === null ? '' : `${shared.budgetCents / 100}元`}`,
          `兴趣：${participant.interests.join('、')}；必去：${participant.mustVisit.join('、')}；避开：${participant.avoidPlaces.join('、')}`,
          `个人预算上限：${participant.budgetCapCents === null ? '未设置' : `${participant.budgetCapCents / 100}元`}；${careSummary(current)}`,
          '我已查看共同信息，并确认这里填写的是我本人的需求。',
        ])
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : '邀请链接无效。')
      } finally {
        if (active) {
          window.clearTimeout(timeout)
          setLoading(false)
        }
      }
    }
    void initialize()
    return () => { active = false; window.clearTimeout(timeout) }
  }, [token])

  const ready = Boolean(description.trim() && answers.every((answer) => answer.trim()))
  const currentStepReady = Boolean(answers[step].trim())
  const hasBlockingIssue = view?.confirmationItems.some((item) => item.code !== 'CONFLICT') ?? false
  const reviewedFallbackCount = reviewedFallbackAnswers.filter(Boolean).length
  const fallbackReviewComplete = reviewedFallbackCount === questions.length

  function updateAnswer(value: string) {
    setAnswers((items) => items.map((item, index) => index === step ? value : item))
  }

  async function submit(reviewedFallback = false) {
    if (!ready || !view || !sessionToken) return
    setLoading(true); setError('')
    try {
      const outcome = await submitMemberConversation({
        participantSessionToken: sessionToken,
        baseRevision: view.currentRevision,
        expectedVersion: view.collaborationVersion,
        naturalLanguageRequest: description,
        answers: questions.map(([questionId], index) => ({ questionId, answer: answers[index] })),
        reviewedFallback,
      })
      if (isFixedQuestionFallback(outcome)) {
        setFallback(outcome)
        setReviewing(false)
        if (reviewedFallback) {
          setFallbackReviewNotice(`服务仍未返回模型提案（${outcome.recognition.failureCode}）。已保留 6 / 6 核对结果，可以再次提交。`)
        } else {
          setReviewedFallbackAnswers(Array(questions.length).fill(false))
          setFallbackReviewNotice('')
        }
      } else {
        setFallback(null)
        setView(outcome)
        setReviewing(true)
      }
    } catch (caught) { setError(caught instanceof Error ? caught.message : '资料整理失败。') }
    finally { setLoading(false) }
  }

  function editFallbackAnswer(index: number) {
    setFallback(null)
    setFallbackReviewNotice('')
    setStep(index)
  }

  function toggleFallbackReview(index: number) {
    setFallbackReviewNotice('')
    setReviewedFallbackAnswers((current) => current.map((checked, itemIndex) => (
      itemIndex === index ? !checked : checked
    )))
  }

  async function retryReviewedFallback() {
    if (loading) return
    if (!fallbackReviewComplete) {
      const remaining = questions.length - reviewedFallbackCount
      setFallbackReviewNotice(`还需勾选 ${remaining} 项“答案准确”，才能继续。`)
      window.requestAnimationFrame(() => {
        document.querySelector<HTMLInputElement>('.member-fallback-review li:not(.is-reviewed) input')?.focus()
      })
      return
    }
    setFallbackReviewNotice('')
    await submit(true)
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

  if (loading && !view && !error) return <AppShell compact><main className="planner-layout member-planner-layout"><section className="planner-panel member-loading-panel"><Sparkles size={24} /><h1>正在进入成员行程</h1><p role="status">正在建立仅属于你的成员会话，请稍候…</p></section></main></AppShell>
  if (!view) return <AppShell compact><main className="planner-layout member-planner-layout"><section className="planner-panel invitation-error-panel"><h1>此邀请不可用</h1><p className="form-error" role="alert">{error || '链接已过期或被组织者撤销。'}</p><div className="invitation-error-help"><strong>怎么继续？</strong><ol><li>同一个成员邀请链接可以重复打开。</li><li>再次打开后请使用最新标签页；旧标签页的会话会自动失效。</li><li>若链接已过期或被撤销，请联系组织者。</li></ol><a className="button button--soft" href="/plan">返回行程创建页</a></div></section></main></AppShell>

  return <AppShell compact><main className="planner-layout member-planner-layout"><section className="planner-panel motion-enter">
    <span className="section-kicker">MEMBER CONVERSATION</span>
    <h1>填写你的旅行偏好</h1>
    <p>你只能读取和修改自己的成员资料；组织者和其他成员的资料不会暴露在此会话中。{expiresAt && ` 会话有效至 ${new Date(expiresAt).toLocaleString('zh-CN')}。`}</p>
    <section className="shared-trip-card"><div className="shared-trip-card__head"><span><UsersRound size={18} /></span><div><strong>组织者共享的行程范围</strong><p>下面是共同安排；你的个人偏好和关怀限制独立确认。</p></div></div><div className="shared-trip-card__grid"><article><MapPin size={15} /><span>目的城市</span><strong>{view.sharedTrip.cityName || '待补充'}</strong></article><article><CalendarDays size={15} /><span>出行日期</span><strong>{view.sharedTrip.travelDate || '待补充'}</strong></article><article><Clock3 size={15} /><span>可用时间</span><strong>{view.sharedTrip.startTime && view.sharedTrip.endTime ? `${view.sharedTrip.startTime} — ${view.sharedTrip.endTime}` : '待补充'}</strong></article><article><MapPin size={15} /><span>起终点</span><strong>{view.sharedTrip.startLocationText || '待补充'} → {view.sharedTrip.endLocationText || '待补充'}</strong></article><article><WalletCards size={15} /><span>共享预算</span><strong>{view.sharedTrip.budgetCents === null ? '待补充' : `¥${view.sharedTrip.budgetCents / 100}`}</strong></article></div></section>
    {error && <p className="form-error" role="alert">{error}</p>}
    {fallback && <section className="fallback-review-card member-fallback-review"><div className="fallback-review-card__head"><span><Sparkles size={18} /></span><div><strong>成员固定问题核对</strong><p>智能整理不可用时，请逐项确认；6 / 6 后会使用你核对过的答案生成成员草稿。</p></div></div><ol className="fallback-review-list">{fallback.fallback.items.map((item, index) => <li key={item.questionId} className={reviewedFallbackAnswers[index] ? 'is-reviewed' : ''}><div className="fallback-review-item__content"><span>问题 {index + 1}</span><strong>{questions[index][1]}</strong><p>{item.answer}</p></div><div className="fallback-review-item__actions"><button className="button button--soft" type="button" onClick={() => editFallbackAnswer(index)}>修改此项</button><label><input type="checkbox" checked={reviewedFallbackAnswers[index] ?? false} onChange={() => toggleFallbackReview(index)} /><span><Check size={15} />答案准确</span></label></div></li>)}</ol><div className="fallback-review-footer"><div><p role="status" aria-live="polite">已核对 {reviewedFallbackCount} / {questions.length} 项。</p>{fallbackReviewNotice && <p className="fallback-review-notice" role="alert">{fallbackReviewNotice}</p>}</div><button className="button button--primary" type="button" disabled={loading} onClick={() => void retryReviewedFallback()}>{loading ? '正在生成成员草稿…' : fallbackReviewComplete ? '六项已核对，生成成员草稿' : `先勾选剩余 ${questions.length - reviewedFallbackCount} 项`} <ArrowRight size={18} /></button></div></section>}
    {!fallback && !reviewing && view.confirmationStatus !== 'CONFIRMED' && <>
      <label className="field-label" htmlFor="member-goal">先说说你对这趟旅行的期待</label>
      <textarea id="member-goal" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="例如：我更喜欢慢节奏，也不想走太久。" />
      <section className="draft-confirmation"><div className="draft-confirmation__heading"><span><Sparkles size={18} /></span><div><strong>问题 {step + 1} / 6</strong><p>{questions[step][1]}</p></div></div>
        {step < 3 ? <div className="shared-trip-card__grid" role="group" aria-label="组织者已确认的共享行程，只读">
          {step === 0 && <><article><MapPin size={15} /><span>目的城市</span><strong>{view.sharedTrip.cityName || '待组织者补充'}</strong></article><article><CalendarDays size={15} /><span>出行日期</span><strong>{view.sharedTrip.travelDate || '待组织者补充'}</strong></article><article><Clock3 size={15} /><span>可用时间</span><strong>{view.sharedTrip.startTime && view.sharedTrip.endTime ? `${view.sharedTrip.startTime} — ${view.sharedTrip.endTime}` : '待组织者补充'}</strong></article></>}
          {step === 1 && <article><UsersRound size={15} /><span>成员权限</span><strong>同行人数与组织者由创建者管理</strong></article>}
          {step === 2 && <><article><MapPin size={15} /><span>起终点</span><strong>{view.sharedTrip.startLocationText || '待补充'} → {view.sharedTrip.endLocationText || '待补充'}</strong></article><article><WalletCards size={15} /><span>共享预算</span><strong>{view.sharedTrip.budgetCents === null ? '待补充' : `¥${view.sharedTrip.budgetCents / 100}`}</strong></article></>}
        </div> : <textarea value={answers[step]} onChange={(event) => updateAnswer(event.target.value)} placeholder="请输入你的回答" />}
        {step < 3 && <p className="field-help" role="status">这是组织者确认的共同安排。成员会话只能核对，不能改写共享事实。</p>}
        <div className="planner-actions"><button className="button button--ghost" type="button" disabled={step === 0 || loading} onClick={() => setStep((value) => value - 1)}>上一个问题</button>{step < 5 ? <button className="button button--primary" type="button" disabled={!currentStepReady || loading} onClick={() => setStep((value) => value + 1)}>下一个问题 <ArrowRight size={18} /></button> : <button className="button button--primary" type="button" disabled={!ready || loading} onClick={() => void submit()}>整理并查看确认 <ArrowRight size={18} /></button>}</div>
      </section>
    </>}
    {reviewing && <section className="draft-confirmation"><div className="draft-confirmation__heading"><span><Check size={18} /></span><div><strong>资料确认卡</strong><p>{view.sharedTrip.cityName || '行程城市待确认'} · {view.sharedTrip.travelDate || '日期待确认'} · {view.participant.interests.join('、') || '偏好待确认'}</p></div></div>{view.confirmationItems.map((item) => <p className="form-error" key={item.itemId}>规则 {item.ruleId}：{item.reason}</p>)}<div className="planner-actions"><button className="button button--ghost" type="button" disabled={loading} onClick={() => setReviewing(false)}>返回修改</button><button className="button button--primary" type="button" disabled={loading || hasBlockingIssue} onClick={() => void confirm()}>确认我的资料</button></div></section>}
    {view.confirmationStatus === 'CONFIRMED' && <section className="draft-confirmation" role="status" aria-live="polite"><strong>你的资料已确认，正在等待组织者和其他成员完成确认。</strong>{view.confirmationItems.map((item) => <p className="form-error" key={item.itemId}>规则 {item.ruleId}：{item.reason}</p>)}</section>}
  </section></main></AppShell>
}
