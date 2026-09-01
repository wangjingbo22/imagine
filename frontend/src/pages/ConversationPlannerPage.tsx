import { ArrowRight, CalendarDays, Check, ChevronDown, Clock3, Copy, HeartHandshake, Link2, LockKeyhole, MapPin, RefreshCw, Sparkles, UserRound, UsersRound, WalletCards } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  confirmOrganizerParticipant,
  createOrganizerConversation,
  createParticipantInvitation,
  getOrganizerCollaboration,
  isFixedQuestionFallback,
  newIdempotencyKey,
  resolveOrganizerConfirmationItem,
  reviewMemberChangeProposal,
} from '../api/collaborationApi'
import { linkParentTripDay } from '../api/parentTripApi'
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
  collaborationPlanningDraft,
  invitationTokenFromText,
} from '../services/collaborationDraft'
import { getStoredOrganizerToken, setStoredOrganizerToken, setStoredPlanContext } from '../services/organizerStorage'
import {
  clearPlannerLocalDraft,
  createPlannerLocalDraftWriteGate,
  loadPlannerLocalDraft,
  plannerLocalDraftScope,
  persistPlannerFallbackDraft,
  savePlannerLocalDraft,
} from '../services/plannerLocalDraft'
import { clearRecommendationSession } from '../services/recommendationSelection'
import {
  DEFAULT_PLANNING_END_TIME,
  DEFAULT_PLANNING_START_TIME,
  defaultPlanningTimeWindow,
  localDateValue,
  localTimeValue,
  type PlanningTimeWindow,
  tripDateRangeDayCount,
  validateTripDateRange,
  validateTripSchedule,
} from '../services/tripTimeConstraints'
import { useAccountSession } from '../session/useAccountSession'

// 20 人是当前协作会话、邀请链接和公平评分共同支持的安全上限。
// 前端校验与服务端模型使用同一上限，避免界面可填但提交后被拒绝。
const MAX_PARTICIPANT_COUNT = 20

const questions = [
  ['trip', '这次想去哪里、哪天出发、哪天结束？'],
  ['party', '一共几个人出行？谁是组织者？'],
  ['endpoints_budget', '从哪里出发、最终回到哪里？同行行程总预算大约是多少？'],
  ['preferences', '每个人喜欢什么、必去哪里、希望避开什么？'],
  ['assistance', '是否有预算上限、步行、换乘、休息或关怀需求？'],
  ['confirm', '请确认以上描述；还需要补充什么不可妥协的限制吗？'],
] as const

// 确认页使用短标题代替“修改第 N 问”，让组织者一眼看出将返回哪类信息。
const questionEditLabels = ['城市与日期', '同行成员', '起终点与预算', '兴趣与必去', '预算与关怀', '最终限制'] as const

function collaborationStatusLabel(status: CollaborationAggregate['status']): string {
  const labels: Record<CollaborationAggregate['status'], string> = {
    MIGRATION_REQUIRED: '需要重新创建行程',
    DRAFT_CONVERSATION: '正在整理资料',
    INVITING: '正在邀请成员',
    COLLECTING_MEMBERS: '等待成员确认',
    CONFLICT_REVIEW: '需要处理确认项',
    READY_TO_PLAN: '可以进入下一步',
  }
  return labels[status]
}

type EntryMode = 'single' | 'group'
type TripFields = { city: string; startDate: string; endDate: string }

function tripAnswer(fields: TripFields, window: PlanningTimeWindow): string {
  // Keep the existing machine-readable travelDate marker for the strict
  // single-day understanding contract while presenting a date range in UI.
  return `目的城市：${fields.city}；出行日期：${fields.startDate}；出行时间：${window.startTime}到${window.endTime}；出发日期：${fields.startDate}；结束日期：${fields.endDate}`
}

const groupQuestionIndexes: readonly number[] = [0, 1, 2, 3, 4, 5]
const singleQuestionIndexes: readonly number[] = [0, 2, 3, 4, 5]

function questionLabel(questionIndex: number, entryMode: EntryMode | null): string {
  if (entryMode === 'single' && questionIndex === 2) {
    return '从哪里出发、最终回到哪里？'
  }
  if (entryMode === 'single' && questionIndex === 3) {
    return '喜欢什么、必去哪里、希望避开什么？'
  }
  return questions[questionIndex]?.[1] ?? ''
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
  const [searchParams] = useSearchParams()
  const { user } = useAccountSession()
  const requestedMode = searchParams.get('mode')
  const parentTripId = searchParams.get('parentTripId')
  const parentDayIndexRaw = searchParams.get('dayIndex')
  const parsedParentDayIndex = parentDayIndexRaw !== null && /^(0|[1-9]\d*)$/.test(parentDayIndexRaw)
    ? Number(parentDayIndexRaw)
    : null
  const parentDayIndex = parsedParentDayIndex !== null && Number.isSafeInteger(parsedParentDayIndex)
    ? parsedParentDayIndex
    : null
  const parentCity = searchParams.get('city') ?? ''
  const parentDate = searchParams.get('date') ?? ''
  const parentBudgetCents = Number(searchParams.get('budget'))
  const isParentDay = Boolean(parentTripId && parentDayIndex !== null)
  const plannerDraftScope = plannerLocalDraftScope(
    isParentDay ? parentTripId : null,
    isParentDay ? parentDayIndex : null,
  )
  const initialEntryMode: EntryMode | null = requestedMode === 'group'
    ? 'group'
    : requestedMode === 'single' || isParentDay
      ? 'single'
      : null
  const [description, setDescription] = useState('')
  const [answers, setAnswers] = useState<string[]>(() => {
    const initial = Array<string>(questions.length).fill('')
    if (initialEntryMode === 'group') initial[1] = '2个人出行；组织者昵称：'
    if (initialEntryMode === 'single') initial[1] = '1个人出行；组织者昵称：旅行者'
    return initial
  })
  const [tripFields, setTripFields] = useState<TripFields>(() => ({
    city: parentCity,
    startDate: parentDate || localDateValue(),
    endDate: parentDate || localDateValue(),
  }))
  const [customTimeWindow, setCustomTimeWindow] = useState<PlanningTimeWindow | null>(null)
  const [timeDraft, setTimeDraft] = useState<PlanningTimeWindow>({
    startTime: DEFAULT_PLANNING_START_TIME,
    endTime: DEFAULT_PLANNING_END_TIME,
  })
  const [timeEditorOpen, setTimeEditorOpen] = useState(false)
  const [routeFields, setRouteFields] = useState({ start: '', end: '', budget: Number.isFinite(parentBudgetCents) ? String(parentBudgetCents / 100) : '' })
  const [organizerNickname, setOrganizerNickname] = useState(initialEntryMode === 'single' ? '旅行者' : '')
  const [partyCount, setPartyCount] = useState(initialEntryMode === 'group' ? 2 : 1)
  const [personalBudget, setPersonalBudget] = useState('')
  const [assistanceMode, setAssistanceMode] = useState('ORDINARY')
  const [entryMode, setEntryMode] = useState<EntryMode | null>(initialEntryMode)
  const [questionnaireStarted, setQuestionnaireStarted] = useState(false)
  const [inviteLink, setInviteLink] = useState('')
  const [step, setStep] = useState(isParentDay ? initialEntryMode === 'group' ? 1 : 2 : 0)
  const [loading, setLoading] = useState(false)
  const [refreshingCollaboration, setRefreshingCollaboration] = useState(false)
  const [result, setResult] = useState<OrganizerConversationCreated | null>(null)
  const [fallback, setFallback] = useState<FixedQuestionFallbackResponse | null>(null)
  const [reviewedFallbackAnswers, setReviewedFallbackAnswers] = useState<boolean[]>(Array(questions.length).fill(false))
  const [fallbackReviewNotice, setFallbackReviewNotice] = useState('')
  const [links, setLinks] = useState<Array<{ invitationId: string; participantId: string; link: string }>>([])
  const [collaboration, setCollaboration] = useState<CollaborationAggregate | null>(null)
  const [planningDraft, setPlanningDraft] = useState<TripDraftInput | null>(null)
  const [error, setError] = useState('')
  const [temporalNow, setTemporalNow] = useState(() => new Date())
  const [hydratedDraftScope, setHydratedDraftScope] = useState<string | null>(null)
  const [localDraftStatus, setLocalDraftStatus] = useState<'idle' | 'saved' | 'unavailable'>('idle')
  const conversationKey = useRef<string | null>(null)
  const localDraftWriteGate = useRef(createPlannerLocalDraftWriteGate())
  const outcomeRef = useRef<HTMLElement | null>(null)
  const navigate = useNavigate()

  const today = localDateValue(temporalNow)
  const dateRangeError = validateTripDateRange(tripFields, temporalNow)
  const dayCount = tripDateRangeDayCount(tripFields)
  const isMultiDayRange = (dayCount ?? 0) > 1
  const canContinueAsMultiDay = isMultiDayRange && !dateRangeError
  const generatedTimeWindow = defaultPlanningTimeWindow(tripFields.startDate, temporalNow)
  const planningTimeWindow = customTimeWindow ?? generatedTimeWindow
  const scheduleError = dateRangeError ?? (
    !isMultiDayRange && !planningTimeWindow
      ? '今天的默认规划时间已经结束，请选择明天或更晚日期。'
      : null
  )
  const timeDraftError = timeEditorOpen
    ? validateTripSchedule({
        date: tripFields.startDate,
        startTime: timeDraft.startTime,
        endTime: timeDraft.endTime,
      }, temporalNow)
    : null
  const modeQuestionIndexes = entryMode === 'single' ? singleQuestionIndexes : groupQuestionIndexes
  const visibleQuestionIndexes = isParentDay
    ? modeQuestionIndexes.filter((questionIndex) => questionIndex !== 0)
    : modeQuestionIndexes
  const visibleStepIndex = Math.max(visibleQuestionIndexes.indexOf(step), 0)
  const visibleQuestionCount = visibleQuestionIndexes.length
  const isLastQuestion = visibleStepIndex === visibleQuestionCount - 1
  const currentQuestionLabel = questionLabel(step, entryMode)
  const cardAnswersReady = Boolean(
    tripFields.city.trim()
    && tripFields.startDate.trim()
    && tripFields.endDate.trim()
    && routeFields.start.trim()
    && routeFields.end.trim()
    && (entryMode === 'single' || routeFields.budget.trim()),
  )
  const isReady = description.trim().length > 0 && cardAnswersReady && !scheduleError && answers.every((answer) => answer.trim().length > 0)
  const currentStepReady = step === 0
    ? Boolean(tripFields.city.trim() && tripFields.startDate.trim() && tripFields.endDate.trim() && !scheduleError)
    : step === 1
      ? Boolean(organizerNickname.trim() && (entryMode === 'single' || (Number.isInteger(partyCount) && partyCount >= 2 && partyCount <= MAX_PARTICIPANT_COUNT)))
    : step === 2
      ? Boolean(routeFields.start.trim() && routeFields.end.trim() && (entryMode === 'single' || routeFields.budget.trim()))
      : step === 4
        ? Boolean(personalBudget.trim())
      : Boolean(answers[step].trim())
  const revision = result?.revision ?? null
  const preview = useMemo(() => revision?.understanding.trip, [revision])
  const previewParticipant = revision?.understanding.participants[0]
  const organizerToken = revision
    ? result?.organizerAccess.organizerToken ?? getStoredOrganizerToken(revision.tripId)
    : null
  const organizerConfirmed = collaboration?.participants.some((item) => item.role === 'ORGANIZER' && item.confirmationStatus === 'CONFIRMED') ?? false
  const memberParticipants = collaboration?.participants.filter((item) => item.role === 'MEMBER') ?? []
  const hasMemberParticipants = memberParticipants.length > 0
  const allMembersConfirmed = hasMemberParticipants && memberParticipants.every((item) => item.confirmationStatus === 'CONFIRMED')
  const needsInvitations = collaboration?.participants.some((item) => item.role === 'MEMBER' && item.accessStatus === 'NOT_INVITED') ?? false
  const organizerCanUnlockNextStep = Boolean(
    collaboration
    && !organizerConfirmed
    && allMembersConfirmed
    && !needsInvitations
    && collaboration.progress.openIssueCount === 0,
  )
  const reviewedFallbackCount = visibleQuestionIndexes.filter((index) => reviewedFallbackAnswers[index]).length
  const fallbackReviewComplete = reviewedFallbackCount === visibleQuestionCount
  const hasOutcome = Boolean(result || fallback)

  const localDraftIdentity = user ? `${user.userId}:${plannerDraftScope}` : null

  useEffect(() => {
    const timer = window.setInterval(() => setTemporalNow(new Date()), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    setHydratedDraftScope(null)
    localDraftWriteGate.current.allowAfterUserEdit()
    if (!user || !localDraftIdentity) return

    let restored = null
    try {
      restored = loadPlannerLocalDraft(window.localStorage, user.userId, plannerDraftScope)
    } catch {
      setLocalDraftStatus('unavailable')
    }
    if (restored) {
      const restoredMode = restored.entryMode ?? initialEntryMode
      const restoredQuestionIndexes = restoredMode === 'single' ? singleQuestionIndexes : groupQuestionIndexes
      const restoredVisibleIndexes = isParentDay
        ? restoredQuestionIndexes.filter((questionIndex) => questionIndex !== 0)
        : restoredQuestionIndexes
      const restoredStep = restoredVisibleIndexes.includes(restored.step)
        ? restored.step
        : (restoredVisibleIndexes[0] ?? 0)
      setDescription(restored.description)
      setAnswers([...restored.answers])
      setTripFields(restored.tripFields)
      setCustomTimeWindow(restored.customTimeWindow)
      setTimeDraft(restored.customTimeWindow ?? {
        startTime: DEFAULT_PLANNING_START_TIME,
        endTime: DEFAULT_PLANNING_END_TIME,
      })
      setRouteFields(restored.routeFields)
      setOrganizerNickname(restored.organizerNickname)
      setPartyCount(restored.partyCount)
      setPersonalBudget(restored.personalBudget)
      setAssistanceMode(restored.assistanceMode)
      setEntryMode(restoredMode)
      setQuestionnaireStarted(restored.questionnaireStarted)
      setStep(restoredStep)
      setError('')
      setLocalDraftStatus('saved')
    } else {
      const defaultAnswers = Array<string>(questions.length).fill('')
      if (initialEntryMode === 'group') defaultAnswers[1] = '2个人出行；组织者昵称：'
      if (initialEntryMode === 'single') defaultAnswers[1] = '1个人出行；组织者昵称：旅行者'
      setDescription('')
      setAnswers(defaultAnswers)
      setTripFields({
        city: parentCity,
        startDate: parentDate || localDateValue(),
        endDate: parentDate || localDateValue(),
      })
      setCustomTimeWindow(null)
      setTimeDraft({ startTime: DEFAULT_PLANNING_START_TIME, endTime: DEFAULT_PLANNING_END_TIME })
      setTimeEditorOpen(false)
      setRouteFields({
        start: '',
        end: '',
        budget: Number.isFinite(parentBudgetCents) ? String(parentBudgetCents / 100) : '',
      })
      setOrganizerNickname(initialEntryMode === 'single' ? '旅行者' : '')
      setPartyCount(initialEntryMode === 'group' ? 2 : 1)
      setPersonalBudget('')
      setAssistanceMode('ORDINARY')
      setEntryMode(initialEntryMode)
      setQuestionnaireStarted(false)
      setStep(isParentDay ? initialEntryMode === 'group' ? 1 : 2 : 0)
      setResult(null)
      setFallback(null)
      setCollaboration(null)
      setPlanningDraft(null)
      setLinks([])
      setReviewedFallbackAnswers(Array(questions.length).fill(false))
      setFallbackReviewNotice('')
      conversationKey.current = null
      setLocalDraftStatus('idle')
    }
    setHydratedDraftScope(localDraftIdentity)
  }, [initialEntryMode, isParentDay, localDraftIdentity, plannerDraftScope, user])

  useEffect(() => {
    if (!user || !localDraftIdentity || hydratedDraftScope !== localDraftIdentity || hasOutcome || !localDraftWriteGate.current.canPersist()) return
    const hasMeaningfulInput = entryMode !== null || Boolean(
      description.trim() || answers.some((answer) => answer.trim()) || routeFields.start.trim() || routeFields.end.trim()
      || routeFields.budget.trim() || organizerNickname.trim() || personalBudget.trim(),
    )
    if (!hasMeaningfulInput) {
      setLocalDraftStatus('idle')
      return
    }
    const timer = window.setTimeout(() => {
      if (!localDraftWriteGate.current.canPersist()) return
      let saved = false
      try {
        saved = savePlannerLocalDraft(window.localStorage, user.userId, plannerDraftScope, {
          entryMode,
          questionnaireStarted,
          step,
          description,
          answers,
          tripFields,
          customTimeWindow,
          routeFields,
          organizerNickname,
          partyCount,
          personalBudget,
          assistanceMode,
        })
      } catch {
        saved = false
      }
      setLocalDraftStatus(saved ? 'saved' : 'unavailable')
    }, 500)
    return () => window.clearTimeout(timer)
  }, [answers, assistanceMode, customTimeWindow, description, entryMode, hasOutcome, hydratedDraftScope, localDraftIdentity, organizerNickname, partyCount, personalBudget, plannerDraftScope, questionnaireStarted, routeFields, step, tripFields, user])

  useEffect(() => {
    if (!hasOutcome) return
    const frame = window.requestAnimationFrame(() => {
      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      outcomeRef.current?.scrollIntoView({
        behavior: reducedMotion ? 'auto' : 'smooth',
        block: 'start',
      })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [hasOutcome])

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
    localDraftWriteGate.current.allowAfterUserEdit()
    setError('')
  }

  function updateAnswer(value: string) {
    answersChanged()
    setAnswers((current) => current.map((answer, index) => index === step ? value : answer))
  }

  function moveQuestion(offset: -1 | 1) {
    if (offset === 1 && step === 0 && canContinueAsMultiDay) {
      const params = new URLSearchParams({
        city: tripFields.city.trim(),
        startDate: tripFields.startDate,
        endDate: tripFields.endDate,
      })
      if (entryMode) params.set('mode', entryMode)
      if (description.trim()) params.set('title', description.trim().slice(0, 80))
      navigate(`/parent-trips/new?${params.toString()}`)
      return
    }
    const nextQuestionIndex = visibleQuestionIndexes[visibleStepIndex + offset]
    if (nextQuestionIndex !== undefined) setStep(nextQuestionIndex)
  }

  function updateTripField(field: keyof typeof tripFields, value: string) {
    answersChanged()
    setTripFields((current) => {
      const next = { ...current, [field]: value }
      if (field === 'startDate' && value && (!next.endDate || next.endDate < value)) {
        next.endDate = value
      }
      if (field === 'startDate' || field === 'endDate') setCustomTimeWindow(null)
      const window = field === 'startDate' || field === 'endDate'
        ? defaultPlanningTimeWindow(next.startDate, temporalNow)
        : planningTimeWindow
      setAnswers((items) => items.map((answer, index) => index === 0
        ? window ? tripAnswer(next, window) : ''
        : answer))
      return next
    })
  }

  function updateRouteField(field: keyof typeof routeFields, value: string) {
    answersChanged()
    setRouteFields((current) => {
      const next = { ...current, [field]: value }
      setAnswers((items) => items.map((answer, index) => index === 2
        ? entryMode === 'single'
          ? `从${next.start}出发；结束地：${next.end}${(parentTripId ? next.budget : personalBudget).trim() ? `；本次行程总预算：${parentTripId ? next.budget : personalBudget}` : ''}`
          : `从${next.start}出发；结束地：${next.end}；同行行程总预算：${next.budget}`
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
    setAnswers((items) => items.map((answer, index) => {
      if (index === 2 && entryMode === 'single') {
        const tripBudget = parentTripId && routeFields.budget.trim() ? routeFields.budget : budget
        return `从${routeFields.start}出发；结束地：${routeFields.end}；本次行程总预算：${tripBudget}`
      }
      return index === 4
        ? `组织者个人预算上限：${budget}元；关怀模式：${mode}（${labels[mode]}）。`
        : answer
    }))
  }

  function begin(mode: EntryMode) {
    answersChanged()
    setEntryMode(mode)
    setQuestionnaireStarted(false)
    setStep(0)
    if (mode === 'single') {
      setOrganizerNickname('旅行者')
      updateParty(1, '旅行者')
    } else {
      setOrganizerNickname('')
      updateParty(2, '')
    }
  }

  function joinExistingTrip() {
    const token = invitationTokenFromText(inviteLink)
    if (!token) { setError('请粘贴完整的成员邀请链接或 43 位邀请码。'); return }
    navigate(`/join/${encodeURIComponent(token)}`)
  }

  function startQuestionnaire() {
    if (!description.trim()) return
    setError('')
    if (planningTimeWindow) {
      setAnswers((current) => current.map((answer, index) => (
        index === 0 ? tripAnswer(tripFields, planningTimeWindow) : answer
      )))
    }
    setStep(visibleQuestionIndexes[0] ?? 0)
    setQuestionnaireStarted(true)
  }

  function openTimeEditor() {
    setError('')
    setTimeDraft({
      startTime: preview?.startTime ?? planningTimeWindow?.startTime ?? DEFAULT_PLANNING_START_TIME,
      endTime: preview?.endTime ?? planningTimeWindow?.endTime ?? DEFAULT_PLANNING_END_TIME,
    })
    setTimeEditorOpen(true)
  }

  async function applyAdjustedTime() {
    const currentError = validateTripSchedule({
      date: tripFields.startDate,
      startTime: timeDraft.startTime,
      endTime: timeDraft.endTime,
    }, new Date())
    if (currentError) {
      setTemporalNow(new Date())
      setError(currentError)
      return
    }
    // A time change affects the canonical Trip, so rerun understanding before
    // any organizer/member confirmation or Provider request uses the new window.
    conversationKey.current = null
    await analyze(false, timeDraft)
  }

  async function analyze(
    preserveReviewedFallback = false,
    timeWindowOverride?: PlanningTimeWindow,
  ) {
    const submittedAt = new Date()
    const submittedWindow = timeWindowOverride
      ?? customTimeWindow
      ?? defaultPlanningTimeWindow(tripFields.startDate, submittedAt)
    if (!submittedWindow) {
      setTemporalNow(submittedAt)
      setStep(0)
      setError('今天的默认规划时间已经结束，请选择明天或更晚日期。')
      return
    }
    const submittedScheduleError = validateTripSchedule({
      date: tripFields.startDate,
      startTime: submittedWindow.startTime,
      endTime: submittedWindow.endTime,
    }, submittedAt)
    if (submittedScheduleError) {
      setTemporalNow(submittedAt)
      setStep(0)
      setError(submittedScheduleError)
      return
    }
    if (!isReady) return
    const submittedAnswers = answers.map((answer, index) => (
      index === 0 ? tripAnswer(tripFields, submittedWindow) : answer
    ))
    setAnswers(submittedAnswers)
    setLoading(true); setError('')
    try {
      const key = conversationKey.current ?? newIdempotencyKey('s2-organizer-conversation')
      conversationKey.current = key
      const created = await createOrganizerConversation({
        naturalLanguageRequest: description,
        referenceDate: localDateValue(submittedAt),
        referenceTime: localTimeValue(submittedAt),
        answers: questions.map(([questionId], index) => ({ questionId, answer: submittedAnswers[index] })),
        reviewedFallback: preserveReviewedFallback,
      }, key)
      if (isFixedQuestionFallback(created)) {
        if (user) {
          let saved = false
          try {
            saved = persistPlannerFallbackDraft(window.localStorage, user.userId, plannerDraftScope, {
              entryMode,
              questionnaireStarted,
              step,
              description,
              answers: submittedAnswers,
              tripFields,
              customTimeWindow,
              routeFields,
              organizerNickname,
              partyCount,
              personalBudget,
              assistanceMode,
            }, localDraftWriteGate.current)
          } catch {
            saved = false
          }
          setLocalDraftStatus(saved ? 'saved' : 'unavailable')
        }
        setFallback(created)
        if (preserveReviewedFallback) {
          setFallbackReviewNotice(`智能整理服务暂不可用（${created.recognition.failureCode}），本次已自动尝试 ${created.recognition.callCount} 次。已保留 ${visibleQuestionCount} / ${visibleQuestionCount} 核对结果，请稍后再次尝试。`)
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
      localDraftWriteGate.current.blockAfterAuthoritativeCreation()
      if (user) {
        clearPlannerLocalDraft(window.localStorage, user.userId, plannerDraftScope)
      }
      setStoredOrganizerToken(created.revision.tripId, created.organizerAccess.organizerToken)
      const nextPlanningDraft = collaborationPlanningDraft(created.revision)
      const nextCollaboration = await getOrganizerCollaboration(
        created.revision.tripId,
        created.organizerAccess.organizerToken,
      )
      setFallback(null)
      setCustomTimeWindow(submittedWindow)
      setTimeDraft(submittedWindow)
      setTimeEditorOpen(false)
      setResult(created)
      setPlanningDraft(nextPlanningDraft)
      setCollaboration(nextCollaboration)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '对话解析失败，请稍后重试。')
    } finally { setLoading(false) }
  }

  async function retryAfterFallbackReview() {
    if (loading) return
    if (!fallbackReviewComplete) {
      const remaining = visibleQuestionCount - reviewedFallbackCount
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
      if (parentTripId && parentDayIndex !== null) {
        const parentToken = window.sessionStorage.getItem(`parent-trip-token:${parentTripId}`)
        if (!parentToken) throw new Error('父行程组织者凭证已丢失，不能绑定当日行程。')
        await linkParentTripDay({
          parentTripId,
          dayIndex: parentDayIndex,
          childTripId: revision.tripId,
          parentToken,
          organizerToken,
        })
      }
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
        ? collaborationPlanningDraft(revision)
        : null
      setPlanningDraft(draft)
      if (draft && canEnterRecommendation(current)) {
        setStoredPlanContext(revision.tripId, draft)
      }
      // 如果当前只差组织者确认，确认成功后立即进入方案页，不再要求用户寻找第二个按钮。
      if (canEnterRecommendation(current)) {
        enterRecommendation(current, draft)
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

  function enterRecommendation(state: CollaborationAggregate, draft: TripDraftInput | null = planningDraft) {
    // 规划页面以服务端 tripId 获取最新修订；本地草稿只在版本一致时作为补充上下文。
    if (draft) setStoredPlanContext(state.tripId, draft)
    // 保留远端新增的推荐会话清理逻辑，避免上一次行程的候选编辑状态串入新方案。
    clearRecommendationSession(window.sessionStorage, state.tripId)
    const parentQuery = parentTripId && Number.isInteger(parentDayIndex)
      ? `?parentTripId=${encodeURIComponent(parentTripId)}&dayIndex=${parentDayIndex}`
      : ''
    navigate(`/recommendation/${state.tripId}${parentQuery}`)
  }

  async function refreshCollaborationNow() {
    if (!revision || !organizerToken) return
    setRefreshingCollaboration(true); setError('')
    try {
      // 手动刷新直接读取服务端权威状态，用于成员刚确认但轮询尚未到达的场景。
      const state = await getOrganizerCollaboration(revision.tripId, organizerToken)
      setCollaboration(state)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '刷新协作状态失败。')
    } finally {
      setRefreshingCollaboration(false)
    }
  }

  async function reviewChangeProposal(proposalId: string, decision: 'APPROVE' | 'REJECT') {
    if (!collaboration || !organizerToken) return
    setLoading(true); setError('')
    try {
      // 接口返回的是审批后的完整协作快照。批准时 currentRevision 会增加，
      // 因而旧的前端规划草稿必须清除，防止后续误用审批前的数据。
      const state = await reviewMemberChangeProposal({
        state: collaboration,
        proposalId,
        decision,
        organizerToken,
      })
      setCollaboration(state)
      if (state.currentRevision !== revision?.revision) setPlanningDraft(null)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '成员建议审批失败。') }
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

  return <AppShell compact>
    <main className="planner-layout">
      <aside className="planner-sidebar">
        <div><span className="eyebrow">S2 · 对话建行程</span><h1>把旅行，<br />说给我听。</h1><p>我们会用 {visibleQuestionCount} 个小问题收集完整信息，再一次性整理为可确认的行程需求。</p></div>
        <ol className="step-list">{visibleQuestionIndexes.map((questionIndex, index) => {
          const label = questionLabel(questionIndex, entryMode)
          return <li key={questions[questionIndex][0]} aria-current={!hasOutcome && questionnaireStarted && questionIndex === step ? 'step' : undefined} className={index < visibleStepIndex || hasOutcome ? 'is-complete' : questionnaireStarted && questionIndex === step ? 'is-current' : ''}><span>{index < visibleStepIndex || hasOutcome ? <Check size={14} /> : index + 1}</span><div><strong>问题 {index + 1}</strong><small>{label.slice(0, 16)}…</small></div></li>
        })}</ol>
        <div className="privacy-note"><LockKeyhole size={17} /><span>{entryMode === 'group' ? '你的回答仅用于整理行程偏好。成员资料各自独立确认。' : '你的回答仅用于整理本次行程偏好。'}</span></div>
      </aside>
      <section className="planner-panel conversation-panel" data-reveal="panel">
        <header className="planner-panel__header"><div><span className="section-kicker">CONVERSATIONAL TRIP</span><h2>{hasOutcome ? '确认你的旅行需求' : isParentDay ? '从今天的期待开始' : '从一句期待开始'}</h2></div><span className="save-state"><span className="status-dot" /> {localDraftStatus === 'saved' ? '本地草稿已保存' : localDraftStatus === 'unavailable' ? '本地草稿未保存' : '填写后自动保存'}</span></header>
        {!hasOutcome && entryMode === null && <section className="entry-mode-card"><div><span className="section-kicker">CHOOSE YOUR WAY</span><h3>这次，怎么出发？</h3><p>单人行程直接开始；多人由组织者创建后发送邀请链接，成员各自填写自己的资料。</p></div><div className="entry-mode-grid"><button type="button" onClick={() => begin('single')}><UserRound size={21} /><strong>单人创建</strong><small>我自己规划一趟行程</small><ArrowRight size={17} /></button><button type="button" onClick={() => begin('group')}><UsersRound size={21} /><strong>多人创建</strong><small>我是组织者，邀请同行成员</small><ArrowRight size={17} /></button></div><div className="join-entry"><span><Link2 size={16} />已有多人邀请？</span><input value={inviteLink} onChange={(event) => setInviteLink(event.target.value)} placeholder="粘贴邀请链接" /><button className="button button--soft" type="button" onClick={joinExistingTrip}>加入行程</button></div></section>}
        {!hasOutcome && entryMode !== null && <section className="conversation-card"><div className="conversation-intro"><span><Sparkles size={18} /></span><div><strong>{questionnaireStarted ? isParentDay ? '今天的期待' : '总体期待' : isParentDay ? '先填写今天的期待' : '先填写总体期待'}</strong><p>{questionnaireStarted ? `这段${isParentDay ? '今天的' : ''}期待会和全部回答一起整理，你仍可以继续修改。` : `填写后才能开始回答 ${visibleQuestionCount} 个问题。`}</p></div></div>
          <label className="field-label" htmlFor="goal">{isParentDay ? '今天，你最希望得到什么？' : '这趟旅行，你最希望得到什么？'}</label>
          <textarea id="goal" className="conversation-textarea" required value={description} onChange={(event) => { answersChanged(); setDescription(event.target.value) }} placeholder={isParentDay ? '例如：今天想轻松逛历史景点，也想吃一顿当地特色。' : '例如：和朋友去驻马店玩一天，想轻松一点，也想吃当地特色。'} />
          {!questionnaireStarted && <div className="goal-start-actions"><span className={description.trim() ? 'is-ready' : ''} role="status">{description.trim() ? `${isParentDay ? '今天的' : '总体'}期待已填写，可以开始。` : `请先填写${isParentDay ? '今天的期待' : '总体期待'}。`}</span><button aria-controls="trip-questionnaire" className="button button--primary" disabled={!description.trim()} type="button" onClick={startQuestionnaire}>开始回答 {visibleQuestionCount} 个问题 <ArrowRight size={18} /></button></div>}
          {questionnaireStarted && <section className="question-bubble" id="trip-questionnaire"><div className="question-bubble__meta"><span>问题 {visibleStepIndex + 1} / {visibleQuestionCount}</span><span>{Math.round(((visibleStepIndex + 1) / visibleQuestionCount) * 100)}%</span></div><h3>{currentQuestionLabel}</h3>
            {step === 0 ? <><div className="question-field-cards question-field-cards--trip"><label><span><MapPin size={16} />目的城市</span><input value={tripFields.city} onChange={(event) => updateTripField('city', event.target.value)} /></label><label><span><CalendarDays size={16} />出发日期</span><input aria-invalid={Boolean(scheduleError)} disabled={Boolean(parentTripId)} min={today} type="date" value={tripFields.startDate} onFocus={() => setTemporalNow(new Date())} onChange={(event) => updateTripField('startDate', event.target.value)} />{parentTripId && <small>由多日行程统一设置</small>}</label><label><span><CalendarDays size={16} />结束日期</span><input aria-invalid={Boolean(scheduleError)} disabled={Boolean(parentTripId)} min={tripFields.startDate || today} type="date" value={tripFields.endDate} onFocus={() => setTemporalNow(new Date())} onChange={(event) => updateTripField('endDate', event.target.value)} />{parentTripId && <small>当前为单日子行程</small>}</label></div><p className="default-planning-window"><Clock3 size={16} /><span>{canContinueAsMultiDay ? `共 ${dayCount} 天，将进入多日行程并逐日规划。` : planningTimeWindow ? `系统默认按 ${planningTimeWindow.startTime}–${planningTimeWindow.endTime} 规划，整理完成后仍可调整。` : '今天的默认规划时间已经结束。'}</span></p>{scheduleError && <p className="form-error" role="alert">{scheduleError}</p>}</> : step === 1 ? <div className="question-field-cards"><label><span>组织者昵称</span><input value={organizerNickname} onChange={(event) => updateOrganizerName(event.target.value)} placeholder="例如：小明" /></label><label><span>同行人数</span><input type="number" min="2" max={MAX_PARTICIPANT_COUNT} step="1" inputMode="numeric" value={partyCount} onChange={(event) => updateParty(Number(event.target.value))} /><small>自定义填写，支持 2–20 人</small></label></div> : step === 2 ? <div className="question-field-cards question-field-cards--route"><label><span><MapPin size={16} />出发地</span><input value={routeFields.start} onChange={(event) => updateRouteField('start', event.target.value)} /></label><label><span><MapPin size={16} />结束地</span><input value={routeFields.end} onChange={(event) => updateRouteField('end', event.target.value)} /></label>{(entryMode === 'group' || Boolean(parentTripId)) && <label><span><WalletCards size={16} />{parentTripId ? '当日预算（多日行程已分配）' : '同行行程总预算'}</span><input type="number" min="0" inputMode="decimal" value={routeFields.budget} readOnly={Boolean(parentTripId)} onChange={(event) => updateRouteField('budget', event.target.value)} />{parentTripId && <small>自动沿用多日行程预算，无需重复填写</small>}</label>}</div> : step === 4 ? <div className="question-field-cards question-field-cards--assistance"><label><span><WalletCards size={16} />个人预算上限（元）</span><input inputMode="numeric" value={personalBudget} onChange={(event) => { setPersonalBudget(event.target.value); updateAssistance(assistanceMode, event.target.value) }} placeholder="例如：500" /></label><label className="care-mode-field"><span><HeartHandshake size={16} />关怀模式</span><div className="care-mode-select"><select value={assistanceMode} onChange={(event) => updateAssistance(event.target.value)}><option value="ORDINARY">普通出行</option><option value="PARENT_CHILD">亲子出行</option><option value="LOW_STAMINA">低体力出行</option><option value="MOBILITY_ASSISTANCE_BETA">行动辅助</option></select><ChevronDown aria-hidden="true" size={18} /></div></label></div> : <textarea className="conversation-textarea conversation-textarea--answer" value={answers[step]} onChange={(event) => updateAnswer(event.target.value)} placeholder="用自然语言回答即可，不用填表。" />}
            <div className="planner-actions"><button className="button button--ghost" type="button" disabled={visibleStepIndex === 0} onClick={() => moveQuestion(-1)}>上一个问题</button>{!isLastQuestion ? <button className="button button--primary" type="button" disabled={!currentStepReady} onClick={() => moveQuestion(1)}>{step === 0 && canContinueAsMultiDay ? '继续创建多日行程' : '下一个问题'} <ArrowRight size={18} /></button> : <button className="button button--primary" type="button" disabled={!isReady || loading} onClick={() => void analyze()}>{loading ? '正在整理需求…' : '完成问答并智能整理'} <ArrowRight size={18} /></button>}</div>
          </section>}
        </section>}
        {error && <p className="form-error" role="alert">{error}</p>}
        {fallback && <section ref={outcomeRef} className="confirmation-card fallback-review-card">
          <div className="confirmation-card__head"><span><Sparkles size={20} /></span><div><strong>逐项核对 {visibleQuestionCount} 个回答</strong><p>本次模型服务不可用（{fallback.recognition.failureCode}），服务端没有创建 Trip。请确认每项内容准确；需要更正就返回对应问题，全部核对后可重新智能整理。</p></div></div>
          <ol className="fallback-review-list">
            {visibleQuestionIndexes.map((questionIndex, index) => {
              const item = fallback.fallback.items[questionIndex]
              return <li key={item.questionId} className={reviewedFallbackAnswers[questionIndex] ? 'is-reviewed' : ''}>
              <div className="fallback-review-item__content"><span>问题 {index + 1}</span><strong>{questionLabel(questionIndex, entryMode)}</strong><p>{item.answer}</p></div>
              <div className="fallback-review-item__actions">
                <button className="button button--soft" type="button" onClick={() => editAnswer(questionIndex)}>修改此项</button>
                <label><input type="checkbox" checked={reviewedFallbackAnswers[questionIndex] ?? false} onChange={() => toggleFallbackReview(questionIndex)} /><span><Check size={15} />答案准确</span></label>
              </div>
            </li>})}
          </ol>
          <div className="fallback-review-footer">
            <div><p role="status" aria-live="polite">已核对 {reviewedFallbackCount} / {visibleQuestionCount} 项。重新整理成功后会显示整理结果，在确认资料前仍不会调用 Provider 或规划。</p>{fallbackReviewNotice && <p className="fallback-review-notice" role="alert">{fallbackReviewNotice}</p>}</div>
            <button className="button button--primary" type="button" disabled={loading} onClick={() => void retryAfterFallbackReview()}>{loading ? '正在重新整理…' : fallbackReviewComplete ? fallbackReviewNotice ? '再次尝试智能整理' : '全部已核对，重新智能整理' : `先勾选剩余 ${visibleQuestionCount - reviewedFallbackCount} 项`} <ArrowRight size={18} /></button>
          </div>
        </section>}
        {parentTripId && <button className="parent-trip-return" type="button" onClick={() => navigate(`/parent-trips/${parentTripId}`)}>← 返回多日父行程</button>}
        {result && revision && <section ref={outcomeRef} className="confirmation-card"><div className="confirmation-card__head"><span><Check size={20} /></span><div><strong>{result.recognition.source === 'REVIEWED_FIXED_QUESTIONS' ? `已核对 ${visibleQuestionCount} 项回答草稿` : '智能整理完成'}</strong><p>{result.recognition.source === 'REVIEWED_FIXED_QUESTIONS' ? `本次百炼未成功，草稿来自已核对的 ${visibleQuestionCount} 项回答（${result.recognition.degradedReason ?? '未知失败'}）。仍可继续确认资料。` : entryMode === 'group' ? '请核对组织者资料；确认后会为同行成员准备后续确认。' : '请核对今天的安排；确认后会直接生成推荐方案。'}</p></div></div>
          {collaboration && (!organizerConfirmed || needsInvitations) && <button className="button button--primary confirmation-primary-action" type="button" disabled={loading} onClick={() => void confirmAndPrepare()}>{organizerCanUnlockNextStep ? '确认最新安排并生成方案' : organizerConfirmed ? '生成成员邀请链接' : hasMemberParticipants ? needsInvitations ? '确认组织者资料并生成成员邀请链接' : '确认最新共同安排' : '确认并生成推荐方案'} <ArrowRight size={18} /></button>}
          {!collaboration && <button className="button button--primary confirmation-primary-action" type="button" disabled={refreshingCollaboration} onClick={() => void refreshCollaborationNow()}>{refreshingCollaboration ? '正在准备下一步…' : '继续准备推荐方案'} <RefreshCw className={refreshingCollaboration ? 'is-spinning' : ''} size={17} /></button>}
          <ul className="confirmation-grid">{[['城市', preview?.cityName], ['日期', preview?.travelDate], ['时间', `${preview?.startTime ?? '未识别'} 至 ${preview?.endTime ?? '未识别'}`], ['起终点', `${preview?.startLocationText ?? '未识别'} → ${preview?.endLocationText ?? '未识别'}`], ['预算', preview?.budgetCents === null || preview?.budgetCents === undefined ? '未识别' : `¥${preview.budgetCents / 100}`], ['兴趣', previewParticipant?.interests.join('、') || '未识别']].map(([label, value]) => <li key={label}><strong>{label}</strong><span>{value}</span></li>)}</ul>
          {!organizerConfirmed && <section className="planning-time-editor" aria-labelledby="planning-time-editor-title"><div className="planning-time-editor__summary"><span><Clock3 size={18} /></span><div><strong id="planning-time-editor-title">每日规划时间</strong><p>默认按 08:30–21:00 安排；当天临时创建时会避开已经过去的时间。</p></div>{!timeEditorOpen && <button className="button button--soft" type="button" disabled={loading} onClick={openTimeEditor}>调整时间</button>}</div>{timeEditorOpen && <div className="planning-time-editor__form"><label>开始时间<input aria-invalid={Boolean(timeDraftError)} type="time" value={timeDraft.startTime} onFocus={() => setTemporalNow(new Date())} onChange={(event) => setTimeDraft((current) => ({ ...current, startTime: event.target.value }))} /></label><span>至</span><label>结束时间<input aria-invalid={Boolean(timeDraftError)} min={timeDraft.startTime} type="time" value={timeDraft.endTime} onFocus={() => setTemporalNow(new Date())} onChange={(event) => setTimeDraft((current) => ({ ...current, endTime: event.target.value }))} /></label><div><button className="button button--ghost" type="button" disabled={loading} onClick={() => setTimeEditorOpen(false)}>取消</button><button className="button button--primary" type="button" disabled={loading || Boolean(timeDraftError)} onClick={() => void applyAdjustedTime()}>{loading ? '正在重新整理…' : '应用并重新整理'}</button></div>{timeDraftError && <p className="form-error" role="alert">{timeDraftError}</p>}</div>}</section>}
          {!organizerConfirmed && <section className="confirmation-edit-panel"><div><strong>需要调整信息？</strong><p>选择对应内容返回修改，其他已填写信息会保留。</p></div><div className="confirmation-edit-grid">{visibleQuestionIndexes.map((questionIndex, index) => <button type="button" key={questions[questionIndex][0]} onClick={() => editAnswer(questionIndex)}><span>{index + 1}</span><strong>{questionEditLabels[questionIndex]}</strong><small>点击修改</small></button>)}</div></section>}
          {collaboration && <div className="draft-confirmation"><div className="draft-confirmation__heading draft-confirmation__heading--with-action"><span>{hasMemberParticipants ? <UsersRound size={18} /> : <Check size={18} />}</span><div><strong>{hasMemberParticipants ? '协作进度' : '确认进度'}</strong><p role="status" aria-live="polite">{collaboration.progress.confirmedCount} / {collaboration.progress.expectedCount} 位成员已确认 · {collaborationStatusLabel(collaboration.status)}</p></div><button className="collaboration-refresh-button" type="button" disabled={refreshingCollaboration} onClick={() => void refreshCollaborationNow()}><RefreshCw className={refreshingCollaboration ? 'is-spinning' : ''} size={16} />{refreshingCollaboration ? '正在刷新' : '刷新状态'}</button></div>
            {collaboration.changeProposals.length > 0 && <section className="organizer-proposal-card"><div className="organizer-proposal-card__head"><div><strong>成员修改建议</strong><p>批准后立即形成新的共同安排并要求全员重新确认；拒绝后继续执行原计划。</p></div><span>{collaboration.changeProposals.filter((item) => item.status === 'PENDING').length} 条待审核</span></div><ol className="organizer-proposal-list">{[...collaboration.changeProposals].reverse().map((item) => { const member = collaboration.participants.find((participant) => participant.participantId === item.participantId); const labels: Record<string, string> = { 'trip.cityName': '目的城市', 'trip.travelDate': '出行日期', 'trip.startTime': '开始时间', 'trip.endTime': '结束时间', 'trip.startLocationText': '出发地', 'trip.endLocationText': '结束地', 'trip.budgetCents': '同行行程总预算' }; const displayValue = item.fieldPath === 'trip.budgetCents' && typeof item.proposedValue === 'number' ? `¥${item.proposedValue / 100}` : String(item.proposedValue); return <li key={item.proposalId}><div className="organizer-proposal-list__content"><span>{member?.memberKey ?? '成员'} 建议修改“{labels[item.fieldPath] ?? item.fieldPath}”</span><strong>{displayValue}</strong><p>{item.reason}</p></div>{item.status === 'PENDING' ? <div className="organizer-proposal-list__actions"><button className="button button--soft" type="button" disabled={loading} onClick={() => void reviewChangeProposal(item.proposalId, 'REJECT')}>拒绝并保留原计划</button><button className="button button--primary" type="button" disabled={loading} onClick={() => void reviewChangeProposal(item.proposalId, 'APPROVE')}>批准并执行</button></div> : <em className={`proposal-status proposal-status--${item.status.toLowerCase()}`}>{item.status === 'APPROVED' ? '已批准并执行' : '已拒绝，原计划不变'}</em>}</li>})}</ol></section>}
            <ConflictReviewPanel state={collaboration} busy={loading} onResolve={(itemId, relaxationId) => void resolveConflict(itemId, relaxationId)} />
          </div>}
          {collaboration && hasMemberParticipants && links.length === 0 && <div className="invite-card invite-card--pending"><strong>成员邀请入口</strong><p>{!organizerConfirmed ? '点击上方“确认组织者资料并生成成员邀请链接”，生成后成员可直接打开或复制自己的专属链接。' : needsInvitations ? '点击上方“生成成员邀请链接”，生成后成员可直接打开或复制自己的专属链接。' : '邀请已创建，但当前标签页没有可展示的链接密钥。请返回创建页面重新发起一趟多人行程。'}</p></div>}
          {links.length > 0 && <div className="invite-card"><strong>成员邀请链接</strong><p>每个链接只对应一名成员，在该成员确认资料前可以重复打开。再次打开会生成新会话，并让该成员上一次打开的旧标签页失效。</p>{links.map((item, index) => <div className="invite-row" key={item.invitationId}><span>成员 {index + 1}</span><code>{item.link}</code><div className="invite-row__actions"><a className="button button--soft" href={item.link}><ArrowRight size={14} />进入成员页</a><button type="button" className="button button--soft" onClick={() => void navigator.clipboard.writeText(item.link)}><Copy size={14} />复制</button></div></div>)}</div>}
          {collaboration && canEnterRecommendation(collaboration) && <button className="button button--primary" type="button" onClick={() => enterRecommendation(collaboration)}>生成并查看推荐方案 <ArrowRight size={18} /></button>}
        </section>}
      </section>
    </main>
  </AppShell>
}
