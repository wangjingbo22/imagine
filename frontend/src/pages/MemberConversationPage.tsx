import { ArrowRight, CalendarDays, Check, Clock3, MapPin, Sparkles, UsersRound, WalletCards } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import {
  confirmMemberSession,
  createMemberChangeProposal,
  getMemberSession,
  isFixedQuestionFallback,
  newIdempotencyKey,
  redeemParticipantInvitation,
  submitMemberConversation,
} from '../api/collaborationApi'
import { ApiError } from '../api/client'
import { AppShell } from '../components/AppShell'
import type {
  FixedQuestionFallbackResponse,
  MemberSessionView,
  SharedTripProposalField,
} from '../domain/collaboration'
import { invitationTokenFromText } from '../services/collaborationDraft'
import { userFacingErrorMessage } from '../utils/userFacingError'

const questions = [
  ['trip', '这次行程的目标、城市、日期和出行时间是什么？'],
  ['party', '同行人数和组织者是谁？'],
  ['endpoints_budget', '起点、终点与共享预算安排是什么？'],
  ['preferences', '你喜欢什么、必去哪里、希望避开什么？'],
  ['assistance', '你的预算上限、步行、换乘、休息或关怀限制是什么？'],
  ['confirm', '请确认以上描述；还有什么不能妥协的限制？'],
] as const

// 下拉项与服务端白名单一一对应；标签面向成员，路径只用于接口传输。
const proposalFields: Array<{ value: SharedTripProposalField; label: string }> = [
  { value: 'trip.cityName', label: '目的城市' },
  { value: 'trip.travelDate', label: '出行日期' },
  { value: 'trip.startTime', label: '开始时间' },
  { value: 'trip.endTime', label: '结束时间' },
  { value: 'trip.startLocationText', label: '出发地' },
  { value: 'trip.endLocationText', label: '结束地' },
  { value: 'trip.budgetCents', label: '同行行程总预算' },
]

function proposalFieldLabel(fieldPath: string): string {
  return proposalFields.find((field) => field.value === fieldPath)?.label ?? '共同安排信息'
}

type LocalChangeProposal = {
  fieldPath: SharedTripProposalField
  proposedValue: string | number
  reason: string
}

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

function sharedAnswerTexts(view: MemberSessionView): [string, string, string] {
  /**
   * 前三个固定问题来自共同安排。集中生成文本可以保证组织者批准建议后，
   * 页面展示与提交给后端的答案同时更新，不会继续携带旧修订中的时间或地点。
   */
  const shared = view.sharedTrip
  return [
    `城市：${shared.cityName ?? ''}；日期：${shared.travelDate ?? ''}；时间：${shared.startTime ?? ''}到${shared.endTime ?? ''}`,
    '同行信息由组织者管理；我是通过成员邀请链接加入的成员。',
    `从${shared.startLocationText ?? ''}出发；结束地：${shared.endLocationText ?? ''}；同行行程总预算：${shared.budgetCents === null ? '' : `${shared.budgetCents / 100}元`}`,
  ]
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
  // 把原来一整段难编辑的自然语言拆成三个明确字段。提交时仍会重新组装成
  // 固定六问协议所需的答案文本，因此不会改变既有服务端接口。
  const [preferenceFields, setPreferenceFields] = useState({ interests: '', mustVisit: '', avoidPlaces: '' })
  const [memberBudget, setMemberBudget] = useState('')
  const [careNeeds, setCareNeeds] = useState('')
  const [finalConfirmation, setFinalConfirmation] = useState('我已查看共同信息，并确认这里填写的是我本人的需求。')
  // 共同城市、日期、时间和起终点已经在页面顶部集中展示；成员直接从
  // 第 4 个协议问题开始填写自己的兴趣，避免重复翻阅三个只读步骤。
  const [step, setStep] = useState(3)
  const [reviewing, setReviewing] = useState(false)
  const [fallback, setFallback] = useState<FixedQuestionFallbackResponse | null>(null)
  const [reviewedFallbackAnswers, setReviewedFallbackAnswers] = useState<boolean[]>(Array(questions.length).fill(false))
  const [fallbackReviewNotice, setFallbackReviewNotice] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [proposalField, setProposalField] = useState<SharedTripProposalField>('trip.cityName')
  const [proposalValue, setProposalValue] = useState('')
  const [proposalReason, setProposalReason] = useState('')
  const [proposalNotice, setProposalNotice] = useState('')
  const [proposalDrafts, setProposalDrafts] = useState<LocalChangeProposal[]>([])
  const [proposalPanelOpen, setProposalPanelOpen] = useState(false)

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
        const nextPreferences = {
          interests: participant.interests.join('、'),
          mustVisit: participant.mustVisit.join('、'),
          avoidPlaces: participant.avoidPlaces.join('、'),
        }
        const nextBudget = participant.budgetCapCents === null ? '' : String(participant.budgetCapCents / 100)
        const nextCare = careSummary(current)
        setPreferenceFields(nextPreferences)
        setMemberBudget(nextBudget)
        setCareNeeds(nextCare)
        setDescription(`参加组织者创建的${shared.cityName ?? ''}行程，并独立确认我的个人偏好与关怀限制。`)
        setAnswers([
          ...sharedAnswerTexts(current),
          `兴趣：${nextPreferences.interests}；必去：${nextPreferences.mustVisit}；避开：${nextPreferences.avoidPlaces}`,
          `个人预算上限：${nextBudget ? `${nextBudget}元` : '未设置'}；${nextCare}`,
          finalConfirmation,
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

  useEffect(() => {
    if (!sessionToken) return
    let active = true

    const refresh = async () => {
      try {
        const latest = await getMemberSession(sessionToken)
        if (!active) return
        setView(latest)
        // 只同步共同信息对应的前三项，绝不覆盖成员正在输入的个人偏好。
        setAnswers((items) => items.map((item, index) => (
          index < 3 ? sharedAnswerTexts(latest)[index] : item
        )))
      } catch {
        // 后台刷新失败时保留当前页面；真正提交时仍会再次强制刷新并给出中文提示。
      }
    }

    const timer = window.setInterval(() => void refresh(), 5_000)
    const handleFocus = () => void refresh()
    window.addEventListener('focus', handleFocus)
    return () => {
      active = false
      window.clearInterval(timer)
      window.removeEventListener('focus', handleFocus)
    }
  }, [sessionToken])

  const ready = Boolean(description.trim() && answers.every((answer) => answer.trim()))
  const currentStepReady = Boolean(answers[step].trim())
  const hasBlockingIssue = view?.confirmationItems.some((item) => item.code !== 'CONFLICT') ?? false
  const reviewedFallbackCount = reviewedFallbackAnswers.filter(Boolean).length
  const fallbackReviewComplete = reviewedFallbackCount === questions.length
  const hasCurrentProposalInput = Boolean(proposalValue.trim() && proposalReason.trim())
  // 当前输入若与清单中的字段相同，发送时会覆盖旧草稿，因此总数不能重复计算。
  const proposalSendCount = proposalDrafts.length + (
    hasCurrentProposalInput && !proposalDrafts.some((item) => item.fieldPath === proposalField) ? 1 : 0
  )

  function updatePreferences(field: keyof typeof preferenceFields, value: string) {
    // 每次输入都同步生成第 4 问的协议文本，让“下一步”和最终提交始终读取最新值。
    setPreferenceFields((current) => {
      const next = { ...current, [field]: value }
      setAnswers((items) => items.map((item, index) => index === 3
        ? `兴趣：${next.interests}；必去：${next.mustVisit}；避开：${next.avoidPlaces}`
        : item))
      return next
    })
  }

  function updateMemberLimits(budget: string, care: string) {
    // 空预算明确序列化为“未设置”，避免后端把空字符串误判为格式错误。
    setMemberBudget(budget)
    setCareNeeds(care)
    setAnswers((items) => items.map((item, index) => index === 4
      ? `个人预算上限：${budget.trim() ? `${budget}元` : '未设置'}；${care.trim() || '没有额外关怀限制。'}`
      : item))
  }

  function updateConfirmation(value: string) {
    // 第 6 问保留自由补充能力，但使用完整尺寸的输入卡而不是浏览器默认小文本框。
    setFinalConfirmation(value)
    setAnswers((items) => items.map((item, index) => index === 5 ? value : item))
  }

  async function submit(reviewedFallback = false) {
    if (!ready || !view || !sessionToken) return
    setLoading(true); setError('')
    try {
      const submitAgainst = async (latest: MemberSessionView) => {
        const latestSharedAnswers = sharedAnswerTexts(latest)
        const synchronizedAnswers = answers.map((answer, index) => (
          index < 3 ? latestSharedAnswers[index] : answer
        ))
        setView(latest)
        setAnswers(synchronizedAnswers)
        return submitMemberConversation({
          participantSessionToken: sessionToken,
          baseRevision: latest.currentRevision,
          expectedVersion: latest.collaborationVersion,
          naturalLanguageRequest: description,
          answers: questions.map(([questionId], index) => ({ questionId, answer: synchronizedAnswers[index] })),
          reviewedFallback,
        })
      }

      // 点击提交时不相信页面缓存，始终基于组织者最新审批结果整理成员资料。
      let latest = await getMemberSession(sessionToken)
      let outcome
      try {
        outcome = await submitAgainst(latest)
      } catch (caught) {
        if (!(caught instanceof ApiError) || !['COLLABORATION_VERSION_STALE', 'DRAFT_REVISION_STALE'].includes(String(caught.code))) {
          throw caught
        }
        // 审批可能恰好发生在“读取最新状态”和“提交”之间；重新读取后安全重试一次。
        latest = await getMemberSession(sessionToken)
        outcome = await submitAgainst(latest)
      }
      if (isFixedQuestionFallback(outcome)) {
        setFallback(outcome)
        setReviewing(false)
        if (reviewedFallback) {
          setFallbackReviewNotice('智能整理服务暂不可用。已保留 6 / 6 核对结果，可以再次提交。')
        } else {
          setReviewedFallbackAnswers(Array(questions.length).fill(false))
          setFallbackReviewNotice('')
        }
      } else {
        setFallback(null)
        setView(outcome)
        setReviewing(true)
      }
    } catch (caught) {
      if (caught instanceof ApiError && ['COLLABORATION_VERSION_STALE', 'DRAFT_REVISION_STALE'].includes(String(caught.code))) {
        setError('共同安排刚刚发生变化，页面已刷新，请重新点击“整理并查看确认”。')
      } else {
        setError(caught instanceof Error ? caught.message : '资料整理失败。')
      }
    }
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

  function currentSharedValue(field: SharedTripProposalField): string {
    if (!view) return ''
    // 预算在页面使用“元”，提交时再转换为服务端统一保存的“分”。
    const values: Record<SharedTripProposalField, string> = {
      'trip.cityName': view.sharedTrip.cityName ?? '',
      'trip.travelDate': view.sharedTrip.travelDate ?? '',
      'trip.startTime': view.sharedTrip.startTime ?? '',
      'trip.endTime': view.sharedTrip.endTime ?? '',
      'trip.startLocationText': view.sharedTrip.startLocationText ?? '',
      'trip.endLocationText': view.sharedTrip.endLocationText ?? '',
      'trip.budgetCents': view.sharedTrip.budgetCents === null ? '' : String(view.sharedTrip.budgetCents / 100),
    }
    return values[field]
  }

  function currentProposalDraft(): LocalChangeProposal {
    const reason = proposalReason.trim()
    if (!proposalValue.trim()) throw new Error('请填写希望修改成什么内容。')
    if (!reason) throw new Error('请简单填写修改原因，一个字也可以。')
    // 预算必须以整数分传给后端，避免多条建议依次提交时产生浮点金额误差。
    const budgetCents = Math.round(Number(proposalValue) * 100)
    if (proposalField === 'trip.budgetCents' && (!Number.isFinite(budgetCents) || budgetCents < 0)) {
      throw new Error('请填写有效的非负预算金额。')
    }
    return {
      fieldPath: proposalField,
      proposedValue: proposalField === 'trip.budgetCents' ? budgetCents : proposalValue.trim(),
      reason,
    }
  }

  function queueCurrentProposal() {
    setError(''); setProposalNotice('')
    try {
      const draft = currentProposalDraft()
      // 同一个字段再次加入时替换旧草稿，避免组织者收到互相矛盾的重复建议。
      setProposalDrafts((items) => [...items.filter((item) => item.fieldPath !== draft.fieldPath), draft])
      setProposalValue('')
      setProposalReason('')
      setProposalNotice('已加入修改清单，可以继续选择其他内容。')
    } catch (caught) { setError(caught instanceof Error ? caught.message : '建议内容不完整。') }
  }

  async function submitChangeProposals() {
    if (!view || !sessionToken) return
    setLoading(true); setError(''); setProposalNotice('')
    let queue = [...proposalDrafts]
    try {
      // 输入框中尚未“加入清单”的最后一条也会一并发送，减少一次额外点击。
      if (hasCurrentProposalInput) {
        const current = currentProposalDraft()
        queue = [...queue.filter((item) => item.fieldPath !== current.fieldPath), current]
      }
      // 已有完整清单时，忽略表单里尚未写完的残留内容；没有清单时才提示
      // 当前输入不完整，从而保证“发送清单”按钮一定会产生可见结果。
      if (queue.length === 0 && (proposalValue.trim() || proposalReason.trim())) {
        currentProposalDraft()
      }
      if (queue.length === 0) throw new Error('请至少填写一条修改建议。')
      let latestView = view
      for (let index = 0; index < queue.length; index += 1) {
        const draft = queue[index]
        latestView = await createMemberChangeProposal({
          participantSessionToken: sessionToken,
          baseRevision: latestView.currentRevision,
          expectedVersion: latestView.collaborationVersion,
          ...draft,
        })
        setView(latestView)
        // 每成功发送一条就从本地清单移除；即使后续网络失败也不会重复提交成功项。
        setProposalDrafts(queue.slice(index + 1))
      }
      setProposalDrafts([])
      setProposalValue('')
      setProposalReason('')
      setProposalNotice(`已发送 ${queue.length} 条建议，组织者可以逐条批准或拒绝。`)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '修改建议提交失败。') }
    finally { setLoading(false) }
  }

  if (loading && !view && !error) return <AppShell compact><main className="planner-layout member-planner-layout"><section className="planner-panel member-loading-panel"><Sparkles size={24} /><h1>正在进入成员行程</h1><p role="status">正在建立仅属于你的成员会话，请稍候…</p></section></main></AppShell>
  if (!view) return <AppShell compact><main className="planner-layout member-planner-layout"><section className="planner-panel invitation-error-panel"><h1>此邀请不可用</h1><p className="form-error" role="alert">{userFacingErrorMessage(error, '链接已过期或被组织者撤销。')}</p><div className="invitation-error-help"><strong>怎么继续？</strong><ol><li>同一个成员邀请链接可以重复打开。</li><li>再次打开后请使用最新标签页；旧标签页的会话会自动失效。</li><li>若链接已过期或被撤销，请联系组织者。</li></ol><a className="button button--soft" href="/plan">返回行程创建页</a></div></section></main></AppShell>

  return <AppShell compact><main className="planner-layout member-planner-layout"><section className="planner-panel motion-enter">
    <span className="section-kicker">成员行程问答</span>
    <h1>填写你的旅行偏好</h1>
    <p>你只能读取和修改自己的成员资料；组织者和其他成员的资料不会暴露在此会话中。{expiresAt && ` 会话有效至 ${new Date(expiresAt).toLocaleString('zh-CN')}。`}</p>
    <section className="shared-trip-card shared-trip-card--overview"><div className="shared-trip-card__head"><span><UsersRound size={18} /></span><div><strong>本次行程信息</strong><p>先查看城市、日期、时间、起终点和同行行程总预算。</p></div></div><div className="shared-trip-card__grid"><article><MapPin size={15} /><span>目的城市</span><strong>{view.sharedTrip.cityName || '待补充'}</strong></article><article><CalendarDays size={15} /><span>出行日期</span><strong>{view.sharedTrip.travelDate || '待补充'}</strong></article><article><Clock3 size={15} /><span>出行时间</span><strong>{view.sharedTrip.startTime && view.sharedTrip.endTime ? `${view.sharedTrip.startTime} — ${view.sharedTrip.endTime}` : '待补充'}</strong></article><article><MapPin size={15} /><span>出发地</span><strong>{view.sharedTrip.startLocationText || '待补充'}</strong></article><article><MapPin size={15} /><span>结束地</span><strong>{view.sharedTrip.endLocationText || '待补充'}</strong></article><article><WalletCards size={15} /><span>同行行程总预算</span><strong>{view.sharedTrip.budgetCents === null ? '待补充' : `¥${view.sharedTrip.budgetCents / 100}`}</strong></article></div></section>
    <button className={`proposal-panel-toggle${proposalPanelOpen ? ' is-open' : ''}`} type="button" aria-expanded={proposalPanelOpen} onClick={() => setProposalPanelOpen((open) => !open)}><span><strong>共同安排有异议？</strong><small>可一次提交多条修改建议，由组织者逐条审核</small></span><em>{view.changeProposals.filter((item) => item.status === 'PENDING').length > 0 ? `${view.changeProposals.filter((item) => item.status === 'PENDING').length} 条待审核` : proposalPanelOpen ? '收起' : '展开填写'}</em></button>
    {proposalPanelOpen && <section className="change-proposal-card" aria-labelledby="change-proposal-title">
      <div className="change-proposal-card__head"><div><span>共同安排有问题？</span><h2 id="change-proposal-title">向组织者提出修改建议</h2><p>可连续加入多条修改，再一次发送。组织者会逐条批准或拒绝。</p></div><strong>{view.changeProposals.filter((item) => item.status === 'PENDING').length} 条待审核</strong></div>
      <div className="change-proposal-form">
        <label><span>希望修改</span><select value={proposalField} onChange={(event) => { const field = event.target.value as SharedTripProposalField; setProposalField(field); setProposalValue(currentSharedValue(field)) }}>{proposalFields.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        <label><span>建议改为</span><input type={proposalField === 'trip.travelDate' ? 'date' : proposalField === 'trip.startTime' || proposalField === 'trip.endTime' ? 'time' : proposalField === 'trip.budgetCents' ? 'number' : 'text'} min={proposalField === 'trip.budgetCents' ? '0' : undefined} value={proposalValue} onChange={(event) => setProposalValue(event.target.value)} placeholder={currentSharedValue(proposalField) || '填写你的建议'} /></label>
        <label className="change-proposal-form__reason"><span>为什么需要修改（至少填写 1 个字）</span><textarea value={proposalReason} onChange={(event) => setProposalReason(event.target.value)} placeholder="例如：我当天 10:00 才能到达，希望把开始时间改为 10:30。" /></label>
        <div className="change-proposal-form__actions"><button className="button button--soft" type="button" disabled={loading || !hasCurrentProposalInput} onClick={queueCurrentProposal}>加入修改清单</button><button className="button button--primary" type="button" disabled={loading || proposalSendCount === 0} onClick={() => void submitChangeProposals()}>发送 {proposalSendCount} 条建议 <ArrowRight size={17} /></button></div>
      </div>
      {proposalDrafts.length > 0 && <div className="proposal-draft-list"><strong>待发送修改清单</strong><ol>{proposalDrafts.map((item) => <li key={item.fieldPath}><span>{proposalFieldLabel(item.fieldPath)}：{item.fieldPath === 'trip.budgetCents' && typeof item.proposedValue === 'number' ? `¥${item.proposedValue / 100}` : String(item.proposedValue)}</span><small>{item.reason}</small><button type="button" aria-label="从修改清单移除" onClick={() => setProposalDrafts((items) => items.filter((draft) => draft.fieldPath !== item.fieldPath))}>移除</button></li>)}</ol></div>}
      {proposalNotice && <p className="proposal-notice" role="status">{proposalNotice}</p>}
      {view.changeProposals.length > 0 && <ol className="change-proposal-list">{[...view.changeProposals].reverse().map((item) => <li key={item.proposalId}><div><strong>{proposalFieldLabel(item.fieldPath)}</strong><span>建议值：{item.fieldPath === 'trip.budgetCents' && typeof item.proposedValue === 'number' ? `¥${item.proposedValue / 100}` : String(item.proposedValue)}</span><p>{item.reason}</p>{item.organizerNote && <small>组织者说明：{item.organizerNote}</small>}</div><em className={`proposal-status proposal-status--${item.status.toLowerCase()}`}>{item.status === 'PENDING' ? '待组织者审核' : item.status === 'APPROVED' ? '已批准并执行' : '已拒绝，保留原计划'}</em></li>)}</ol>}
    </section>}
    {error && <p className="form-error" role="alert">{userFacingErrorMessage(error, '当前操作失败，请稍后重试。')}</p>}
    {fallback && <section className="fallback-review-card member-fallback-review"><div className="fallback-review-card__head"><span><Sparkles size={18} /></span><div><strong>成员固定问题核对</strong><p>智能整理不可用时，请逐项确认；6 / 6 后会使用你核对过的答案生成成员草稿。</p></div></div><ol className="fallback-review-list">{fallback.fallback.items.map((item, index) => <li key={item.questionId} className={reviewedFallbackAnswers[index] ? 'is-reviewed' : ''}><div className="fallback-review-item__content"><span>问题 {index + 1}</span><strong>{questions[index][1]}</strong><p>{item.answer}</p></div><div className="fallback-review-item__actions"><button className="button button--soft" type="button" onClick={() => editFallbackAnswer(index)}>修改此项</button><label><input type="checkbox" checked={reviewedFallbackAnswers[index] ?? false} onChange={() => toggleFallbackReview(index)} /><span><Check size={15} />答案准确</span></label></div></li>)}</ol><div className="fallback-review-footer"><div><p role="status" aria-live="polite">已核对 {reviewedFallbackCount} / {questions.length} 项。</p>{fallbackReviewNotice && <p className="fallback-review-notice" role="alert">{userFacingErrorMessage(fallbackReviewNotice, '智能整理暂不可用，请稍后重试。')}</p>}</div><button className="button button--primary" type="button" disabled={loading} onClick={() => void retryReviewedFallback()}>{loading ? '正在生成成员草稿…' : fallbackReviewComplete ? '六项已核对，生成成员草稿' : `先勾选剩余 ${questions.length - reviewedFallbackCount} 项`} <ArrowRight size={18} /></button></div></section>}
    {!fallback && !reviewing && view.confirmationStatus !== 'CONFIRMED' && <>
      <label className="field-label" htmlFor="member-goal">先说说你对这趟旅行的期待</label>
      <div className="member-answer-card member-answer-card--goal"><Sparkles size={20} /><textarea id="member-goal" className="member-answer-textarea" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="例如：我更喜欢慢节奏，也不想走太久。" /></div>
      <section className="draft-confirmation member-question-card"><div className="draft-confirmation__heading"><span><Sparkles size={18} /></span><div><strong>{step < 3 ? `共同信息 ${step + 1} / 3` : `个人问题 ${step - 2} / 3`}</strong><p>{questions[step][1]}</p></div></div>
        {step < 3 ? <div className="shared-trip-card__grid" role="group" aria-label="组织者已确认的共享行程，只读">
          {step === 0 && <><article><MapPin size={15} /><span>目的城市</span><strong>{view.sharedTrip.cityName || '待组织者补充'}</strong></article><article><CalendarDays size={15} /><span>出行日期</span><strong>{view.sharedTrip.travelDate || '待组织者补充'}</strong></article><article><Clock3 size={15} /><span>出行时间</span><strong>{view.sharedTrip.startTime && view.sharedTrip.endTime ? `${view.sharedTrip.startTime} — ${view.sharedTrip.endTime}` : '待组织者补充'}</strong></article></>}
          {step === 1 && <article><UsersRound size={15} /><span>成员权限</span><strong>同行人数与组织者由创建者管理</strong></article>}
          {step === 2 && <><article><MapPin size={15} /><span>起终点</span><strong>{view.sharedTrip.startLocationText || '待补充'} → {view.sharedTrip.endLocationText || '待补充'}</strong></article><article><WalletCards size={15} /><span>共享预算</span><strong>{view.sharedTrip.budgetCents === null ? '待补充' : `¥${view.sharedTrip.budgetCents / 100}`}</strong></article></>}
        </div> : step === 3 ? <div className="member-preference-grid"><label><span>兴趣偏好</span><input value={preferenceFields.interests} onChange={(event) => updatePreferences('interests', event.target.value)} placeholder="例如：历史文化、美食" /><small>多个内容可用顿号分隔</small></label><label><span>硬性必去地点</span><input value={preferenceFields.mustVisit} onChange={(event) => updatePreferences('mustVisit', event.target.value)} placeholder="例如：故宫、天坛" /><small>生成方案时必须全部纳入</small></label><label><span>希望避开的地点</span><input value={preferenceFields.avoidPlaces} onChange={(event) => updatePreferences('avoidPlaces', event.target.value)} placeholder="例如：酒吧、拥挤商场" /><small>这些地点不会进入候选</small></label></div> : step === 4 ? <div className="member-limits-grid"><label><span><WalletCards size={16} />个人预算上限（元，可不填）</span><input type="number" min="0" inputMode="decimal" value={memberBudget} onChange={(event) => updateMemberLimits(event.target.value, careNeeds)} placeholder="例如：500" /></label><label><span>步行、换乘、休息或其他关怀需求</span><textarea className="member-answer-textarea" value={careNeeds} onChange={(event) => updateMemberLimits(memberBudget, event.target.value)} placeholder="例如：连续步行不超过 800 米，每 60 分钟休息一次" /></label></div> : <div className="member-answer-card"><textarea className="member-answer-textarea" value={finalConfirmation} onChange={(event) => updateConfirmation(event.target.value)} placeholder="请确认信息，或补充不能妥协的限制" /></div>}
        <div className="planner-actions"><button className="button button--ghost" type="button" disabled={step <= 3 || loading} onClick={() => setStep((value) => Math.max(3, value - 1))}>上一个问题</button>{step < 5 ? <button className="button button--primary" type="button" disabled={!currentStepReady || loading} onClick={() => setStep((value) => value + 1)}>下一个问题 <ArrowRight size={18} /></button> : <button className="button button--primary" type="button" disabled={!ready || loading} onClick={() => void submit()}>整理并查看确认 <ArrowRight size={18} /></button>}</div>
      </section>
    </>}
    {reviewing && <section className="draft-confirmation"><div className="draft-confirmation__heading"><span><Check size={18} /></span><div><strong>资料确认卡</strong><p>{view.sharedTrip.cityName || '行程城市待确认'} · {view.sharedTrip.travelDate || '日期待确认'} · {view.participant.interests.join('、') || '偏好待确认'}</p></div></div>{view.confirmationItems.map((item) => <p className="form-error" key={item.itemId}>{userFacingErrorMessage(item.reason, '此项资料需要补充或更正。')}</p>)}<div className="planner-actions"><button className="button button--ghost" type="button" disabled={loading} onClick={() => setReviewing(false)}>返回修改</button><button className="button button--primary" type="button" disabled={loading || hasBlockingIssue} onClick={() => void confirm()}>确认我的资料</button></div></section>}
    {view.confirmationStatus === 'CONFIRMED' && <section className="draft-confirmation" role="status" aria-live="polite"><strong>你的资料已确认，正在等待组织者和其他成员完成确认。</strong>{view.confirmationItems.map((item) => <p className="form-error" key={item.itemId}>{userFacingErrorMessage(item.reason, '此项资料需要补充或更正。')}</p>)}</section>}
  </section></main></AppShell>
}
