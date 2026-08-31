import { ArrowRight, CalendarDays, Check, Clock3, Copy, Link2, LockKeyhole, MapPin, Sparkles, UserRound, UsersRound, WalletCards } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  confirmOrganizerParticipant,
  createOrganizerConversation,
  createParticipantInvitation,
  getOrganizerCollaboration,
  isFixedQuestionFallback,
  newIdempotencyKey,
  resolveOrganizerConfirmationItem,
} from '../api/collaborationApi'
import { ApiError } from '../api/client'
import { AppShell } from '../components/AppShell'
import { ConflictReviewPanel } from '../components/ConflictReviewPanel'
import {
  canEnterRecommendation,
  type CollaborationAggregate,
  type FixedQuestionFallbackResponse,
  type OrganizerConversationCreated,
} from '../domain/collaboration'
import type { TripDraftInput } from '../domain/trip'
import {
  invitationTokenFromText,
  singleParticipantPlanningDraft,
} from '../services/collaborationDraft'

const questions = [
  ['trip', '这次想去哪里、哪天出发、当天大约什么时间可用？'],
  ['party', '一共几个人出行？谁是组织者？'],
  ['endpoints_budget', '从哪里出发、最终回到哪里？共享预算大约是多少？'],
  ['preferences', '每个人喜欢什么、必去哪里、希望避开什么？'],
  ['assistance', '是否有人有预算上限、步行、换乘、休息或关怀需求？'],
  ['confirm', '请确认以上描述；还需要补充什么不可妥协的限制吗？'],
] as const

function referenceDate(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function questionIndexForConfirmationDetails(
  details: Array<Record<string, unknown>>,
): number {
  const fieldPath = details
    .map((item) => item.fieldPath)
    .find((value): value is string => typeof value === 'string')
  if (!fieldPath) return 5
  if (fieldPath.startsWith('trip.cityName') || fieldPath.startsWith('trip.travelDate') || fieldPath.startsWith('trip.startTime') || fieldPath.startsWith('trip.endTime')) return 0
  if (fieldPath === 'participants') return 1
  if (fieldPath.startsWith('trip.startLocationText') || fieldPath.startsWith('trip.endLocationText') || fieldPath.startsWith('trip.budgetCents')) return 2
  if (fieldPath.includes('.interests') || fieldPath.includes('.mustVisit') || fieldPath.includes('.avoidPlaces')) return 3
  if (fieldPath.includes('.careDraft') || fieldPath.includes('.budgetCapCents')) return 4
  return 5
}

export function ConversationPlannerPage() {
  const [description, setDescription] = useState('')
  const [answers, setAnswers] = useState<string[]>(Array(questions.length).fill(''))
  const [tripFields, setTripFields] = useState({ city: '', date: '', startTime: '', endTime: '' })
  const [routeFields, setRouteFields] = useState({ start: '', end: '', budget: '' })
  const [organizerNickname, setOrganizerNickname] = useState('')
  const [partyCount, setPartyCount] = useState(1)
  const [personalBudget, setPersonalBudget] = useState('')
  const [assistanceMode, setAssistanceMode] = useState('ORDINARY')
  const [entryMode, setEntryMode] = useState<'single' | 'group' | null>(null)
  const [inviteLink, setInviteLink] = useState('')
  const [step, setStep] = useState(0)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<OrganizerConversationCreated | null>(null)
  const [fallback, setFallback] = useState<FixedQuestionFallbackResponse | null>(null)
  const [reviewedFallbackAnswers, setReviewedFallbackAnswers] = useState<boolean[]>(Array(questions.length).fill(false))
  const [fallbackReviewNotice, setFallbackReviewNotice] = useState('')
  const [links, setLinks] = useState<Array<{ invitationId: string; participantId: string; link: string }>>([])
  const [collaboration, setCollaboration] = useState<CollaborationAggregate | null>(null)
  const [planningDraft, setPlanningDraft] = useState<TripDraftInput | null>(null)
  const [error, setError] = useState('')
  const conversationKey = useRef<string | null>(null)
  const navigate = useNavigate()

  const cardAnswersReady = Boolean(tripFields.city.trim() && tripFields.date.trim() && tripFields.startTime.trim() && tripFields.endTime.trim() && routeFields.start.trim() && routeFields.end.trim() && routeFields.budget.trim())
  const isReady = description.trim().length > 0 && cardAnswersReady && answers.every((answer) => answer.trim().length > 0)
  const currentStepReady = step === 0
    ? Boolean(tripFields.city.trim() && tripFields.date.trim() && tripFields.startTime.trim() && tripFields.endTime.trim())
    : step === 1
      ? Boolean(organizerNickname.trim())
    : step === 2
      ? Boolean(routeFields.start.trim() && routeFields.end.trim() && routeFields.budget.trim())
      : step === 4
        ? Boolean(personalBudget.trim())
      : Boolean(answers[step].trim())
  const currentQuestion = questions[step]
  const revision = result?.revision ?? null
  const preview = useMemo(() => revision?.understanding.trip, [revision])
  const previewParticipant = revision?.understanding.participants[0]
  const organizerToken = revision
    ? result?.organizerAccess.organizerToken ?? window.sessionStorage.getItem(`organizer-token:${revision.tripId}`)
    : null
  const organizerConfirmed = collaboration?.participants.some((item) => item.role === 'ORGANIZER' && item.confirmationStatus === 'CONFIRMED') ?? false
  const memberParticipants = collaboration?.participants.filter((item) => item.role === 'MEMBER') ?? []
  const hasMemberParticipants = memberParticipants.length > 0
  const needsInvitations = collaboration?.participants.some((item) => item.role === 'MEMBER' && item.accessStatus === 'NOT_INVITED') ?? false
  const reviewedFallbackCount = reviewedFallbackAnswers.filter(Boolean).length
  const fallbackReviewComplete = reviewedFallbackCount === questions.length

  useEffect(() => {
    if (!revision || !organizerToken) return
    let active = true
    const refresh = async () => {
      try {
        const state = await getOrganizerCollaboration(revision.tripId, organizerToken)
        if (active) setCollaboration(state)
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : '无法刷新成员状态。')
      }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 8000)
    return () => { active = false; window.clearInterval(timer) }
  }, [revision, organizerToken])

  useEffect(() => {
    if (!revision) {
      setLinks([])
      return
    }
    try {
      const stored = window.sessionStorage.getItem(`organizer-invitations:${revision.tripId}`)
      const candidates: unknown = stored ? JSON.parse(stored) : []
      if (!Array.isArray(candidates)) return
      setLinks(candidates.filter((item): item is { invitationId: string; participantId: string; link: string } => (
        typeof item === 'object' && item !== null
        && typeof item.invitationId === 'string'
        && typeof item.participantId === 'string'
        && typeof item.link === 'string'
      )))
    } catch {
      window.sessionStorage.removeItem(`organizer-invitations:${revision.tripId}`)
      setLinks([])
    }
  }, [revision])

  function answersChanged() {
    conversationKey.current = null
    setError('')
  }

  function updateAnswer(value: string) {
    answersChanged()
    setAnswers((current) => current.map((answer, index) => index === step ? value : answer))
  }

  function updateTripField(field: keyof typeof tripFields, value: string) {
    answersChanged()
    setTripFields((current) => {
      const next = { ...current, [field]: value }
      setAnswers((items) => items.map((answer, index) => index === 0
        ? `目的城市：${next.city}；出行日期：${next.date}；可用时间：${next.startTime}到${next.endTime}`
        : answer))
      return next
    })
  }

  function updateRouteField(field: keyof typeof routeFields, value: string) {
    answersChanged()
    setRouteFields((current) => {
      const next = { ...current, [field]: value }
      setAnswers((items) => items.map((answer, index) => index === 2
        ? `从${next.start}出发；结束地：${next.end}；共享预算：${next.budget}`
        : answer))
      return next
    })
  }

  function updateParty(count: number, nickname = organizerNickname) {
    answersChanged()
    setPartyCount(count)
    setAnswers((items) => items.map((answer, index) => index === 1
      ? `${count}个人出行；组织者昵称：${nickname}` : answer))
  }

  function updateOrganizerName(value: string) {
    setOrganizerNickname(value)
    updateParty(partyCount, value)
  }

  function updateAssistance(mode: string, budget = personalBudget) {
    answersChanged()
    setAssistanceMode(mode)
    const labels: Record<string, string> = { ORDINARY: '普通出行（无额外关怀限制）', PARENT_CHILD: '亲子出行', LOW_STAMINA: '低体力出行', MOBILITY_ASSISTANCE_BETA: '行动辅助' }
    setAnswers((items) => items.map((answer, index) => index === 4
      ? `组织者个人预算上限：${budget}元；关怀模式：${mode}（${labels[mode]}）。` : answer))
  }

  function begin(mode: 'single' | 'group') {
    answersChanged()
    setEntryMode(mode)
    if (mode === 'single') {
      updateParty(1)
    }
  }

  function applyTestPreset() {
    answersChanged()
    setEntryMode('single')
    setDescription('想在北京轻松玩一天，参观历史景点并品尝北京特色美食。')
    setTripFields({ city: '北京', date: '2026-09-06', startTime: '09:00', endTime: '18:00' })
    setRouteFields({ start: '北京站', end: '北京站', budget: '500' })
    setOrganizerNickname('测试用户')
    setPartyCount(1)
    setPersonalBudget('500')
    setAssistanceMode('ORDINARY')
    setAnswers([
      '目的城市：北京；出行日期：2026-09-06；可用时间：09:00到18:00',
      '1个人出行；组织者昵称：测试用户',
      '从北京站出发；结束地：北京站；共享预算：500',
      '喜欢历史文化和美食，必去故宫和天坛，不去酒吧。',
      '组织者个人预算上限：500元；关怀模式：ORDINARY（普通出行（无额外关怀限制））。',
      '请安排节奏舒适、路线顺畅的一日行程。',
    ])
    setStep(0)
  }

  function joinExistingTrip() {
    const token = invitationTokenFromText(inviteLink)
    if (!token) { setError('请粘贴完整的成员邀请链接或 43 位邀请码。'); return }
    navigate(`/join/${encodeURIComponent(token)}`)
  }

  async function analyze(preserveReviewedFallback = false) {
    if (!isReady) return
    setLoading(true); setError('')
    try {
      const key = conversationKey.current ?? newIdempotencyKey('s2-organizer-conversation')
      conversationKey.current = key
      const created = await createOrganizerConversation({
        naturalLanguageRequest: description,
        referenceDate: referenceDate(),
        answers: questions.map(([questionId], index) => ({ questionId, answer: answers[index] })),
        reviewedFallback: preserveReviewedFallback,
      }, key)
      if (isFixedQuestionFallback(created)) {
        setFallback(created)
        if (preserveReviewedFallback) {
          setFallbackReviewNotice(`智能整理服务暂不可用（${created.recognition.failureCode}），本次已自动尝试 ${created.recognition.callCount} 次。已保留 6 / 6 核对结果，请稍后再次尝试。`)
        } else {
          setReviewedFallbackAnswers(Array(questions.length).fill(false))
          setFallbackReviewNotice('')
        }
        setResult(null)
        setCollaboration(null)
        setPlanningDraft(null)
        return
      }
      if (!created.organizerAccess.organizerToken || !created.organizerAccess.organizerTokenAvailable) {
        throw new Error('组织者凭证未生成；为避免越权，当前行程不能继续。')
      }
      setFallback(null)
      setResult(created)
      window.sessionStorage.setItem(`organizer-token:${created.revision.tripId}`, created.organizerAccess.organizerToken)
      setPlanningDraft(singleParticipantPlanningDraft(created.revision))
      setCollaboration(await getOrganizerCollaboration(created.revision.tripId, created.organizerAccess.organizerToken))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '对话解析失败，请稍后重试。')
    } finally { setLoading(false) }
  }

  async function retryAfterFallbackReview() {
    if (loading) return
    if (!fallbackReviewComplete) {
      const remaining = questions.length - reviewedFallbackCount
      setFallbackReviewNotice(`还需勾选 ${remaining} 项“答案准确”，才能重新整理。`)
      window.requestAnimationFrame(() => {
        document.querySelector<HTMLInputElement>('.fallback-review-list li:not(.is-reviewed) input')?.focus()
      })
      return
    }
    setFallbackReviewNotice('')
    // A failed command is idempotently replayed by the server. An explicit user
    // review starts a new submission attempt while preserving the six answers.
    conversationKey.current = null
    await analyze(true)
  }

  function toggleFallbackReview(index: number) {
    setFallbackReviewNotice('')
    setReviewedFallbackAnswers((current) => current.map((checked, itemIndex) => (
      itemIndex === index ? !checked : checked
    )))
  }

  async function confirmAndPrepare() {
    if (!revision || !organizerToken || !collaboration) return
    setLoading(true); setError('')
    try {
      let state = collaboration
      if (!organizerConfirmed) {
        state = await confirmOrganizerParticipant({
          tripId: revision.tripId,
          participantId: state.organizerParticipantId,
          baseRevision: state.currentRevision,
          expectedVersion: state.collaborationVersion,
          organizerToken,
        })
        setCollaboration(state)
      }

      let expectedVersion = state.collaborationVersion
      for (const participant of state.participants.filter((item) => item.role === 'MEMBER' && item.accessStatus === 'NOT_INVITED')) {
        const invitation = await createParticipantInvitation({
          tripId: state.tripId,
          participantId: participant.participantId,
          expectedVersion,
          organizerToken,
        })
        expectedVersion = invitation.collaborationVersion
        if (!invitation.linkAvailable || !invitation.invitationUrl) {
          throw new Error(`成员 ${participant.memberKey} 的邀请密钥未生成，请重新创建邀请。`)
        }
        const link = new URL(invitation.invitationUrl, window.location.origin).toString()
        setLinks((current) => {
          const next = current.some((item) => item.link === link)
            ? current
            : [...current, { invitationId: invitation.invitationId, participantId: participant.participantId, link }]
          window.sessionStorage.setItem(`organizer-invitations:${state.tripId}`, JSON.stringify(next))
          return next
        })
        state = {
          ...state,
          collaborationVersion: invitation.collaborationVersion,
          participants: state.participants.map((item) => item.participantId === participant.participantId
            ? { ...item, accessStatus: 'INVITED' }
            : item),
        }
        setCollaboration(state)
      }
      const current = await getOrganizerCollaboration(revision.tripId, organizerToken)
      setCollaboration(current)

      const draft = current.currentRevision === revision.revision
        ? singleParticipantPlanningDraft(revision)
        : null
      setPlanningDraft(draft)
      if (draft && canEnterRecommendation(current)) {
        window.sessionStorage.setItem(`s2-plan-context:${revision.tripId}`, JSON.stringify({ draft }))
      }
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'PARTICIPANT_CONFIRMATION_REQUIRED') {
        const missingQuestion = questionIndexForConfirmationDetails(caught.details)
        editAnswer(missingQuestion)
        setError(`请先补充问题 ${missingQuestion + 1}，再重新提交确认。`)
        return
      }
      setError(caught instanceof Error ? caught.message : '确认或邀请成员失败。')
    } finally { setLoading(false) }
  }

  async function resolveConflict(itemId: string, relaxationId: string) {
    if (!collaboration || !organizerToken) return
    setLoading(true); setError('')
    try {
      const state = await resolveOrganizerConfirmationItem({ state: collaboration, itemId, relaxationId, organizerToken })
      setCollaboration(state)
      if (state.currentRevision !== revision?.revision) setPlanningDraft(null)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '冲突处理失败。') }
    finally { setLoading(false) }
  }

  function editAnswer(index: number) {
    setResult(null)
    setFallback(null)
    setCollaboration(null)
    setPlanningDraft(null)
    setLinks([])
    setReviewedFallbackAnswers(Array(questions.length).fill(false))
    setStep(index)
    answersChanged()
  }

  const hasOutcome = Boolean(result || fallback)

  return <AppShell compact>
    <main className="planner-layout">
      <aside className="planner-sidebar">
        <div><span className="eyebrow">S2 · 对话建行程</span><h1>把旅行，<br />说给我听。</h1><p>我们会用六个小问题收集完整信息，再一次性整理为可确认的行程需求。</p></div>
        <ol className="step-list">{questions.map(([, label], index) => <li key={label} aria-current={!hasOutcome && index === step ? 'step' : undefined} className={index < step || hasOutcome ? 'is-complete' : index === step ? 'is-current' : ''}><span>{index < step || hasOutcome ? <Check size={14} /> : index + 1}</span><div><strong>问题 {index + 1}</strong><small>{label.slice(0, 16)}…</small></div></li>)}</ol>
        <div className="privacy-note"><LockKeyhole size={17} /><span>你的回答仅用于整理行程偏好。成员资料各自独立确认。</span></div>
      </aside>
      <section className="planner-panel conversation-panel" data-reveal="panel">
        <header className="planner-panel__header"><div><span className="section-kicker">CONVERSATIONAL TRIP</span><h2>{hasOutcome ? '确认你的旅行需求' : '从一句期待开始'}</h2></div><span className="save-state"><span className="status-dot" /> 已自动保存当前回答</span></header>
        {!hasOutcome && entryMode === null && <section className="entry-mode-card"><div><span className="section-kicker">CHOOSE YOUR WAY</span><h3>这次，怎么出发？</h3><p>单人行程直接开始；多人由组织者创建后发送邀请链接，成员各自填写自己的资料。</p></div><div className="entry-mode-grid"><button type="button" onClick={() => begin('single')}><UserRound size={21} /><strong>单人创建</strong><small>我自己规划一趟行程</small><ArrowRight size={17} /></button><button type="button" onClick={() => begin('group')}><UsersRound size={21} /><strong>多人创建</strong><small>我是组织者，邀请同行成员</small><ArrowRight size={17} /></button></div><button className="button button--soft" type="button" onClick={applyTestPreset}>填入北京单人测试模板</button><div className="join-entry"><span><Link2 size={16} />已有多人邀请？</span><input value={inviteLink} onChange={(event) => setInviteLink(event.target.value)} placeholder="粘贴邀请链接" /><button className="button button--soft" type="button" onClick={joinExistingTrip}>加入行程</button></div></section>}
        {!hasOutcome && entryMode !== null && <section className="conversation-card"><div className="conversation-intro"><span><Sparkles size={18} /></span><div><strong>先写一句总体期待</strong><p>它会和六个问题的回答一起交给 Agent，不会提前调用模型。</p></div></div>
          <label className="field-label" htmlFor="goal">这趟旅行，你最希望得到什么？</label>
          <textarea id="goal" className="conversation-textarea" value={description} onChange={(event) => { answersChanged(); setDescription(event.target.value) }} placeholder="例如：和朋友去驻马店玩一天，想轻松一点，也想吃当地特色。" />
          <section className="question-bubble"><div className="question-bubble__meta"><span>问题 {step + 1} / {questions.length}</span><span>{Math.round(((step + 1) / questions.length) * 100)}%</span></div><h3>{currentQuestion[1]}</h3>
            {step === 0 ? <div className="question-field-cards question-field-cards--trip"><label><span><MapPin size={16} />目的城市</span><input value={tripFields.city} onChange={(event) => updateTripField('city', event.target.value)} /></label><label><span><CalendarDays size={16} />出行日期</span><input type="date" value={tripFields.date} onChange={(event) => updateTripField('date', event.target.value)} /></label><fieldset className="time-picker-card"><legend><Clock3 size={16} />可用时间</legend><div><label>开始<input type="time" value={tripFields.startTime} onChange={(event) => updateTripField('startTime', event.target.value)} /></label><span>—</span><label>结束<input type="time" value={tripFields.endTime} onChange={(event) => updateTripField('endTime', event.target.value)} /></label></div></fieldset></div> : step === 1 ? <div className="question-field-cards"><label><span>组织者昵称</span><input value={organizerNickname} onChange={(event) => updateOrganizerName(event.target.value)} placeholder="例如：小明" /></label>{entryMode === 'group' && <label><span>同行人数</span><select value={partyCount} onChange={(event) => updateParty(Number(event.target.value))}><option value={2}>2 人</option><option value={3}>3 人</option></select></label>}</div> : step === 2 ? <div className="question-field-cards question-field-cards--route"><label><span><MapPin size={16} />出发地</span><input value={routeFields.start} onChange={(event) => updateRouteField('start', event.target.value)} /></label><label><span><MapPin size={16} />结束地</span><input value={routeFields.end} onChange={(event) => updateRouteField('end', event.target.value)} /></label><label><span><WalletCards size={16} />共享预算</span><input value={routeFields.budget} onChange={(event) => updateRouteField('budget', event.target.value)} /></label></div> : step === 4 ? <div className="question-field-cards"><label><span>个人预算上限（元）</span><input inputMode="numeric" value={personalBudget} onChange={(event) => { setPersonalBudget(event.target.value); updateAssistance(assistanceMode, event.target.value) }} placeholder="例如：500" /></label><label><span>关怀模式</span><select value={assistanceMode} onChange={(event) => updateAssistance(event.target.value)}><option value="ORDINARY">普通出行</option><option value="PARENT_CHILD">亲子出行</option><option value="LOW_STAMINA">低体力出行</option><option value="MOBILITY_ASSISTANCE_BETA">行动辅助</option></select></label></div> : <textarea className="conversation-textarea conversation-textarea--answer" value={answers[step]} onChange={(event) => updateAnswer(event.target.value)} placeholder="用自然语言回答即可，不用填表。" />}
            <div className="planner-actions"><button className="button button--ghost" type="button" disabled={step === 0} onClick={() => setStep((value) => value - 1)}>上一个问题</button>{step < questions.length - 1 ? <button className="button button--primary" type="button" disabled={!currentStepReady} onClick={() => setStep((value) => value + 1)}>下一个问题 <ArrowRight size={18} /></button> : <button className="button button--primary" type="button" disabled={!isReady || loading} onClick={() => void analyze()}>{loading ? '正在整理需求…' : '完成问答并智能整理'} <ArrowRight size={18} /></button>}</div>
          </section>
        </section>}
        {error && <p className="form-error" role="alert">{error}</p>}
        {fallback && <section className="confirmation-card fallback-review-card">
          <div className="confirmation-card__head"><span><Sparkles size={20} /></span><div><strong>逐项核对六个回答</strong><p>本次模型服务不可用（{fallback.recognition.failureCode}），服务端没有创建 Trip。请确认每项内容准确；需要更正就返回对应问题，全部核对后可重新智能整理。</p></div></div>
          <ol className="fallback-review-list">
            {fallback.fallback.items.map((item, index) => <li key={item.questionId} className={reviewedFallbackAnswers[index] ? 'is-reviewed' : ''}>
              <div className="fallback-review-item__content"><span>问题 {index + 1}</span><strong>{questions[index]?.[1]}</strong><p>{item.answer}</p></div>
              <div className="fallback-review-item__actions">
                <button className="button button--soft" type="button" onClick={() => editAnswer(index)}>修改此项</button>
                <label><input type="checkbox" checked={reviewedFallbackAnswers[index] ?? false} onChange={() => toggleFallbackReview(index)} /><span><Check size={15} />答案准确</span></label>
              </div>
            </li>)}
          </ol>
          <div className="fallback-review-footer">
            <div><p role="status" aria-live="polite">已核对 {reviewedFallbackCount} / {questions.length} 项。重新整理成功后会显示“Agent 解析确认卡”，在确认资料前仍不会调用 Provider 或规划。</p>{fallbackReviewNotice && <p className="fallback-review-notice" role="alert">{fallbackReviewNotice}</p>}</div>
            <button className="button button--primary" type="button" disabled={loading} onClick={() => void retryAfterFallbackReview()}>{loading ? '正在重新整理…' : fallbackReviewComplete ? fallbackReviewNotice ? '再次尝试智能整理' : '六项已核对，重新智能整理' : `先勾选剩余 ${questions.length - reviewedFallbackCount} 项`} <ArrowRight size={18} /></button>
          </div>
        </section>}
        {result && revision && <section className="confirmation-card"><div className="confirmation-card__head"><span><Check size={20} /></span><div><strong>Agent 解析确认卡</strong><p>请先确认组织者资料；多人行程随后按成员逐个生成可重复打开的邀请链接。</p></div></div>
          <ul className="confirmation-grid">{[['城市', preview?.cityName], ['日期', preview?.travelDate], ['时间', `${preview?.startTime ?? '未识别'} 至 ${preview?.endTime ?? '未识别'}`], ['起终点', `${preview?.startLocationText ?? '未识别'} → ${preview?.endLocationText ?? '未识别'}`], ['预算', preview?.budgetCents === null || preview?.budgetCents === undefined ? '未识别' : `¥${preview.budgetCents / 100}`], ['兴趣', previewParticipant?.interests.join('、') || '未识别']].map(([label, value]) => <li key={label}><strong>{label}</strong><span>{value}</span></li>)}</ul>
          <div><strong>需要更正？</strong><p>{questions.map(([, question], index) => <button className="button button--soft" type="button" key={question} onClick={() => editAnswer(index)}>修改第 {index + 1} 问</button>)}</p></div>
          {collaboration && <div className="draft-confirmation"><div className="draft-confirmation__heading"><span><UsersRound size={18} /></span><div><strong>协作进度</strong><p role="status" aria-live="polite">{collaboration.progress.confirmedCount} / {collaboration.progress.expectedCount} 位成员已确认 · {collaboration.status}</p></div></div>
            {(!organizerConfirmed || needsInvitations) && <button className="button button--primary" type="button" disabled={loading} onClick={() => void confirmAndPrepare()}>{organizerConfirmed ? '生成成员邀请链接' : hasMemberParticipants ? '确认组织者资料并生成成员邀请链接' : '确认组织者资料'} <ArrowRight size={18} /></button>}
            <ConflictReviewPanel state={collaboration} busy={loading} onResolve={(itemId, relaxationId) => void resolveConflict(itemId, relaxationId)} />
          </div>}
          {collaboration && hasMemberParticipants && links.length === 0 && <div className="invite-card invite-card--pending"><strong>成员邀请入口</strong><p>{!organizerConfirmed ? '点击上方“确认组织者资料并生成成员邀请链接”，生成后成员可直接打开或复制自己的专属链接。' : needsInvitations ? '点击上方“生成成员邀请链接”，生成后成员可直接打开或复制自己的专属链接。' : '邀请已创建，但当前标签页没有可展示的链接密钥。请返回创建页面重新发起一趟多人行程。'}</p></div>}
          {links.length > 0 && <div className="invite-card"><strong>成员邀请链接</strong><p>每个链接只对应一名成员，在该成员确认资料前可以重复打开。再次打开会生成新会话，并让该成员上一次打开的旧标签页失效。</p>{links.map((item, index) => <div className="invite-row" key={item.invitationId}><span>成员 {index + 1}</span><code>{item.link}</code><div className="invite-row__actions"><a className="button button--soft" href={item.link}><ArrowRight size={14} />进入成员页</a><button type="button" className="button button--soft" onClick={() => void navigator.clipboard.writeText(item.link)}><Copy size={14} />复制</button></div></div>)}</div>}
          {collaboration && canEnterRecommendation(collaboration) && planningDraft && <button className="button button--primary" type="button" onClick={() => { window.sessionStorage.setItem(`s2-plan-context:${collaboration.tripId}`, JSON.stringify({ draft: planningDraft })); navigate(`/recommendation/${collaboration.tripId}`) }}>查看唯一推荐 <ArrowRight size={18} /></button>}
          {collaboration && canEnterRecommendation(collaboration) && !planningDraft && <p className="form-error" role="status">协作状态已就绪，但多人 Trip 尚不能无损转换到现有单人规划契约。为避免伪造参与者或关怀事实，当前不会进入推荐页。</p>}
        </section>}
      </section>
    </main>
  </AppShell>
}
