import {
  ArrowRight,
  BadgeCheck,
  BusFront,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDollarSign,
  Clock3,
  Footprints,
  LoaderCircle,
  Layers3,
  MapPin,
  MessageSquareText,
  Navigation,
  ReceiptText,
  RefreshCw,
  Route,
  ShieldCheck,
  Send,
  Sparkles,
  Telescope,
  Wallet,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { ApiError } from '../api/client'
import { tripApi, USE_PLAN_VERSION_API } from '../api/tripApi'
import { AppShell } from '../components/AppShell'
import { MemoryTimelinePanel } from '../components/MemoryTimelinePanel'
import { RouteOverview } from '../components/RouteOverview'
import { TaskPhotoCard } from '../components/TaskPhotoCard'
import type {
  CandidatePlanRequest,
  CandidatePlanReview,
  CandidateReviewItem,
  CandidateReviewConfirmationInput,
  CreateSingleDayTrip,
  ExecutionEvent,
  PlanSnapshot,
  PlanningConstraint,
  PlanVersionDiff,
  Provenance,
  SourceStatus,
  StoredPlanVersion,
  TripDraftInput,
  TripPlanState,
  TripSummary,
} from '../domain/trip'
import type {
  ConfirmedExecutionAdjustmentEventInput,
  ExecutionAdjustmentReplanPreview,
  ExecutionAdjustmentType,
  ExecutionEventParseOutcome,
  FatigueLevel,
} from '../domain/executionAdjustment'
import {
  loadAmapPlan,
  type AmapPlanResult,
  type LocationEvidence,
} from '../services/amapPlan'
import {
  compileGroupAssistanceConstraints,
  planningCareFromConstraints,
} from '../services/assistanceConstraints'
import {
  decideAndContinueExecution,
  executionEventIdempotencyKey,
  firstUnfinishedTaskIndex,
  parseYuanAmountToCents,
  plannedPlusFiftyYuan,
  sprint1SummaryView,
  submitTaskCompletionEvents,
} from '../services/executionReplan'
import {
  buildConfirmedAdjustment,
  createAdjustmentIdempotencyKey,
} from '../services/executionAdjustment'
import { facilityEvidenceNeedsConfirmation } from '../services/routeRiskFacts'
import { restoreDraftFromPlanningFacts } from '../services/planningFacts'
import { getStoredOrganizerToken } from '../services/organizerStorage'
import {
  canRequestS1PlanV2,
  executionAdjustmentBlockReason,
  S1_REPLAN_LIMIT_MESSAGE,
} from '../services/replanPolicy'

const EXECUTION_REPLAN_HELP = '实际消费变化在完成当前任务时记录'

type WorkspaceView = 'plan' | 'execute' | 'diff' | 'summary'

const views: Array<{ value: WorkspaceView; label: string }> = [
  { value: 'plan', label: '计划工作台' },
  { value: 'execute', label: '执行旅程' },
  { value: 'diff', label: 'V1/V2 变更对比' },
  { value: 'summary', label: '旅行总结' },
]

const diffCategoryLabels = {
  TIME: '时间',
  CARE: '休息与关怀安排',
  ROUTE: '路线',
  COST: '费用',
  PLACE: '地点',
} as const

const diffChangeLabels = {
  RETAINED: '保留',
  REMOVED: '删除',
  ADDED: '新增',
  CHANGED: '变更',
} as const

const sourceStatusLabels: Record<SourceStatus, string> = {
  ONLINE: '在线获取',
  VERIFIED_CACHE: '已核验缓存',
  USER_CONFIRMED: '用户确认',
  ESTIMATED: '估算',
  UNKNOWN: '未知待确认',
}

const routeModeLabels = {
  WALKING: '步行',
  TRANSIT: '公共交通',
  DRIVING: '驾车',
  BICYCLING: '骑行',
} as const

const recommendationFeedbackOptions = [
  '想少走路',
  '预算再低一些',
  '减少换乘',
  '增加文化景点',
  '调整用餐安排',
]

const facilityTypeLabels: Record<string, string> = {
  ELEVATOR: '电梯',
  RAMP: '坡道',
  NURSING_ROOM: '母婴室',
  ACCESSIBLE_ENTRANCE: '无障碍入口',
}

function describePlanV2Error(error: unknown) {
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : '确认事件并生成 V2 失败'
  }
  const messages: Record<string, string> = {
    REPLAN_ADJUSTMENT_NO_CHANGE: '当前安排已满足本次限制，没有实际任务变化，已保留原计划，不生成空白 V2。',
    REPLAN_FATIGUE_ROUTE_TOO_LONG: '现有交通路段加必要停留时间超过疲劳休息间隔，需要核实更省力的路线；原计划未被替换。',
    REPLAN_FATIGUE_TIME_INSUFFICIENT: '加入真实休息后时间不足，请调整出行安排；原计划未被替换。',
    REPLAN_S1_VERSION_LIMIT: '当前已不再执行 Plan V1。本版本仅支持一次 V1 → V2 调整，请继续执行当前计划。',
    REPLAN_NO_FEASIBLE_CANDIDATE: '当前调整未通过服务端校验，原 Plan V1 保持不变。',
    S2_T021_EVENT_TASK_NOT_STARTED: '当前任务尚未正式开始。请刷新页面或先开始当前任务，再生成 V2。',
    S2_T021_SUFFIX_EMPTY: '当前已经是最后一个任务，没有后续安排可生成 Plan V2。',
    REPLAN_CANDIDATE_PENDING: '已有一个待决策的 Plan V2，请先在“V1/V2 变更对比”中接受或拒绝。',
    REPLAN_CURRENT_PLAN_REQUIRED: '没有可执行的当前 Plan V1，请先确认并开始 Plan V1。',
    REPLAN_EXECUTION_REQUIRED: '行程尚未进入执行状态，请先确认 Plan V1 并开始行程。',
    S2_T021_NO_FEASIBLE_CANDIDATE: '当前迟到或疲劳约束下没有安全可行的后续方案，原 Plan V1 保持不变。',
    T018_NO_FEASIBLE_CANDIDATE: '当前迟到或疲劳约束下没有安全可行的后续方案，原 Plan V1 保持不变。',
  }
  if (error.code === 'REPLAN_NO_FEASIBLE_CANDIDATE') {
    const ruleIds = error.details.flatMap((item) =>
      Array.isArray(item.affectedRuleIds) ? item.affectedRuleIds.filter((rule): rule is string => typeof rule === 'string') : [],
    )
    const explanations = [...new Set(ruleIds.map((rule) => {
      if (rule.startsWith('REPLAN.VALIDATION.COVERAGE.')) return '服务端校验报告不完整，请更新服务后重试'
      if (rule === 'REPLAN.PREFIX.IMMUTABLE') return '候选改变了已开始或已锁定的任务，不能替换当前计划'
      if (rule.includes('timeBudgetMinutes')) return '剩余时间不足，当前可信路线无法在截止时间前完成'
      if (rule.includes('walkBudgetMeters') || rule.includes('maxSegmentWalkMeters')) return '现有路线的步行量超过调整后的体力限制'
      if (rule.includes('restIntervalMinutes')) return '现有后续安排无法满足所需休息频率'
      if (rule.includes('BUDGET')) return '已消费金额加剩余费用超过预算，或仍有费用未确认'
      if (rule.includes('CARE')) return '关怀限制或设施事实尚未满足，请核对相关要求'
      return `未通过规则：${rule}`
    }))]
    return [messages.REPLAN_NO_FEASIBLE_CANDIDATE, ...explanations].join(' ')
  }
  return messages[String(error.code)] ?? `${error.message}（${String(error.code)}）`
}

function formatMoney(cents: number) {
  return `¥${Math.round(cents / 100)}`
}

function formatSourceTime(provenance: Provenance) {
  const fetchedAt = new Date(provenance.fetchedAt)
  if (Number.isNaN(fetchedAt.getTime())) {
    return '时间未知'
  }
  return fetchedAt.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function formatSource(provenance: Provenance) {
  const staleSuffix = provenance.isStale ? ' · 已过期' : ''
  return `${sourceStatusLabels[provenance.sourceStatus]} · ${formatSourceTime(provenance)}${staleSuffix}`
}

function formatDiffValue(value: string | number | null, category: keyof typeof diffCategoryLabels) {
  if (value === null || value === '') {
    return '—'
  }
  if (category === 'COST' && typeof value === 'number') {
    return formatMoney(value)
  }
  if (category === 'CARE' && typeof value === 'string') {
    return value
      .replace(/^PASS｜/, '通过｜')
      .replace(/^WARNING｜/, '警告｜')
      .replace(/^NEEDS_CONFIRMATION｜/, '待确认｜')
      .replace(/^FAIL｜/, '未通过｜')
  }
  return String(value)
}

function describePlanningConstraint(constraint: PlanningConstraint) {
  switch (constraint.field) {
    case 'walkLimits.maxContinuousMeters':
      return `单段步行 ≤ ${constraint.value}m`
    case 'walkLimits.maxDailyMeters':
      return `全天步行 ≤ ${constraint.value}m`
    case 'maxTransfers':
      return `每段路线换乘次数 ≤ ${constraint.value}`
    case 'restInterval':
      return `连续活动不超过 ${constraint.value} 分钟`
    case 'napWindow': {
      const window = constraint.value as { start: string; end: string }
      return `${window.start.slice(0, 5)}—${window.end.slice(0, 5)} 午休时段不安排活动`
    }
    case 'return':
      return '亲子行程返程地点与截止时间已锁定'
    case 'avoidStairs':
      return '路线避免楼梯'
    default:
      return `${constraint.field} ${constraint.operator} ${String(constraint.value)}`
  }
}

function toDisplayPlan(plan: StoredPlanVersion): PlanSnapshot {
  const coordinates: Array<[number, number]> = [
    [22, 71],
    [43, 58],
    [61, 34],
    [78, 19],
  ]
  return {
    id: plan.planId,
    version: plan.version,
    cityName: plan.tripSnapshot.cityContext.cityName,
    totalCostCents: plan.metrics.totalCostCents,
    bufferCents: plan.metrics.bufferCents,
    totalWalkMeters: plan.metrics.totalWalkMeters,
    transferCount: plan.metrics.transferCount,
    validationStatus: plan.metrics.validationStatus,
    tasks: plan.days[0].tasks.map((task, index) => ({
      id: task.taskId,
      order: task.order,
      title: task.title,
      category: task.category,
      timeRange: task.timeRange,
      durationMinutes: task.durationMinutes,
      transport: task.transport,
      costCents: task.costCents,
      priceKnown: true,
      walkMeters: task.walkMeters,
      note: task.note.replace(
        '仅累计 Provider 已返回的金额，未知价格仍需确认',
        '费用已由用户确认并经服务端复算',
      ),
      status: index === 0 ? 'completed' : index === 1 ? 'current' : 'upcoming',
      coordinates: coordinates[index] ?? [50, 50],
    })),
  }
}

function planningFactsRecoveryMessage(error: unknown) {
  if (!(error instanceof ApiError)) {
    return '服务端规划事实恢复失败；请返回“新建行程”重新生成可信计划。'
  }
  switch (error.code) {
    case 'TRIP_NOT_FOUND':
      return '服务端未找到该行程；请返回“新建行程”重新创建。'
    case 'PLANNING_PLAN_NOT_ISSUED':
      return '当前计划没有服务端签发记录，已禁止重规划；请返回“新建行程”重新生成。'
    case 'PLANNING_FACTS_NOT_FOUND':
      return '当前计划缺少可恢复的 Provider 事实，已禁止重规划；请返回“新建行程”重新生成。'
    case 'PLANNING_PROPOSAL_DIGEST_MISMATCH':
      return '服务端规划事实摘要校验不一致，已禁止重规划；请重新生成计划或联系维护人员。'
    default:
      return `服务端规划事实恢复失败（${String(error.code)}）：${error.message}`
  }
}

export function WorkspacePage() {
  const location = useLocation()
  const navigationState = location.state as {
    draft?: TripDraftInput
    tripId?: string
    trip?: CreateSingleDayTrip
    amapPlanResult?: AmapPlanResult | null
  } | null
  const draft = navigationState?.draft
  const confirmedTrip = navigationState?.trip
  const tripId =
    new URLSearchParams(location.search).get('tripId') ?? navigationState?.tripId ?? null
  const parentTripId = new URLSearchParams(location.search).get('parentTripId')
  const organizerToken = tripId
    ? getStoredOrganizerToken(tripId)
    : null
  const [view, setView] = useState<WorkspaceView>('plan')
  const [summary, setSummary] = useState<TripSummary | null>(null)
  const [restoredPlan, setRestoredPlan] = useState<PlanSnapshot | null>(null)
  const [storedCurrentPlan, setStoredCurrentPlan] = useState<StoredPlanVersion | null>(null)
  const [candidatePlanV2, setCandidatePlanV2] = useState<StoredPlanVersion | null>(null)
  const [planDiff, setPlanDiff] = useState<PlanVersionDiff | null>(null)
  const [persistedPlanId, setPersistedPlanId] = useState<string | null>(
    navigationState?.amapPlanResult?.registeredPlan?.planId ?? null,
  )
  const [isConfirmingPlan, setIsConfirmingPlan] = useState(false)
  const [isPreparingV2, setIsPreparingV2] = useState(false)
  const [isDecidingV2, setIsDecidingV2] = useState(false)
  const [isWritingEvent, setIsWritingEvent] = useState(false)
  const [planLifecycleError, setPlanLifecycleError] = useState('')
  const [actualCost, setActualCost] = useState('0')
  const [arrivalMessage, setArrivalMessage] = useState('')
  const [isLocating, setIsLocating] = useState(false)
  const [currentTaskIndex, setCurrentTaskIndex] = useState(0)
  const [completedTaskIds, setCompletedTaskIds] = useState<string[]>([])
  const [skippedTaskIds, setSkippedTaskIds] = useState<string[]>([])
  const [actualSpentCents, setActualSpentCents] = useState(0)
  const [isFeedbackOpen, setIsFeedbackOpen] = useState(false)
  const [recommendationFeedback, setRecommendationFeedback] = useState('')
  const [selectedFeedbackOptions, setSelectedFeedbackOptions] = useState<string[]>([])
  const [recommendationRound, setRecommendationRound] = useState(1)
  const [isRegenerating, setIsRegenerating] = useState(false)
  const [appliedFeedback, setAppliedFeedback] = useState<string[]>([])
  const [executionAdjustmentCount, setExecutionAdjustmentCount] = useState(0)
  const [executionNotice, setExecutionNotice] = useState('')
  const [adjustmentText, setAdjustmentText] = useState('')
  const [adjustmentParse, setAdjustmentParse] = useState<ExecutionEventParseOutcome | null>(null)
  const [adjustmentEventType, setAdjustmentEventType] = useState<ExecutionAdjustmentType | ''>('')
  const [adjustmentLateMinutes, setAdjustmentLateMinutes] = useState('')
  const [adjustmentFatigueLevel, setAdjustmentFatigueLevel] = useState<FatigueLevel | ''>('')
  const [pendingAdjustmentEvent, setPendingAdjustmentEvent] = useState<
    ConfirmedExecutionAdjustmentEventInput | null
  >(null)
  const [adjustmentPreview, setAdjustmentPreview] = useState<
    ExecutionAdjustmentReplanPreview | null
  >(null)
  const [isParsingAdjustment, setIsParsingAdjustment] = useState(false)
  const [isConfirmingAdjustment, setIsConfirmingAdjustment] = useState(false)
  const [providerPlan, setProviderPlan] = useState<PlanSnapshot | null>(
    navigationState?.amapPlanResult?.plan ?? null,
  )
  const [candidateRequest, setCandidateRequest] = useState<CandidatePlanRequest | null>(
    navigationState?.amapPlanResult?.candidateRequest ?? null,
  )
  const planningDraft = draft ?? (
    candidateRequest ? restoreDraftFromPlanningFacts(candidateRequest) : null
  )
  const [planningIssue, setPlanningIssue] = useState(
    navigationState?.amapPlanResult?.planningIssue ?? null,
  )
  const [candidateReview, setCandidateReview] = useState<CandidatePlanReview | null>(
    navigationState?.amapPlanResult?.planningIssue?.review ?? null,
  )
  const [reviewValues, setReviewValues] = useState<Record<string, string>>({})
  const [isConfirmingEvidence, setIsConfirmingEvidence] = useState(false)
  const [planningTripSnapshot, setPlanningTripSnapshot] = useState<
    CandidatePlanRequest['trip'] | StoredPlanVersion['tripSnapshot'] | null
  >(
    navigationState?.amapPlanResult?.candidateRequest.trip ??
    navigationState?.amapPlanResult?.registeredPlan?.tripSnapshot ??
    null,
  )
  const [locationEvidence, setLocationEvidence] = useState<LocationEvidence | null>(
    navigationState?.amapPlanResult?.evidence ?? null,
  )
  const [isLoadingLocationEvidence, setIsLoadingLocationEvidence] = useState(
    Boolean(tripId && draft && confirmedTrip && !navigationState?.amapPlanResult),
  )
  const [locationEvidenceError, setLocationEvidenceError] = useState(
    tripId && draft && !confirmedTrip && !navigationState?.amapPlanResult
      ? '缺少 T004 已确认 Trip，不能猜测起点、终点或参与者；请返回新建行程重新确认。'
      : '',
  )

  const applyTripState = useCallback((state: TripPlanState) => {
    const current = state.currentPlan
    if (current) {
      const display = toDisplayPlan(current)
      setStoredCurrentPlan(current)
      setPlanningTripSnapshot(current.tripSnapshot)
      setRestoredPlan(display)
      setPersistedPlanId(current.planId)
      if (current.version === 2) {
        setExecutionAdjustmentCount(1)
      }
      const completed = state.events
        .filter((event) => event.eventType === 'COMPLETE')
        .map((event) => event.taskId)
      const skipped = state.events
        .filter((event) => event.eventType === 'SKIP')
        .map((event) => event.taskId)
      const unfinishedIndex = firstUnfinishedTaskIndex(current, state.events)
      const nextIndex =
        unfinishedIndex === null ? Math.max(0, display.tasks.length - 1) : unfinishedIndex
      setCompletedTaskIds([...new Set(completed)])
      setSkippedTaskIds([...new Set(skipped)])
      setActualSpentCents(
        state.actualBudget?.actualSpentCents ?? state.events
          .filter((event) => event.eventType === 'EXPENSE')
          .reduce((total, event) => total + (event.amountCents ?? 0), 0),
      )
      setCurrentTaskIndex(nextIndex)
      const nextTask = unfinishedIndex === null ? null : display.tasks[nextIndex]
      if (nextTask) {
        setActualCost(String(nextTask.costCents / 100))
      }
    }
    if (state.tripStatus === 'COMPLETED' ||
        (state.currentPlan && firstUnfinishedTaskIndex(state.currentPlan, state.events) === null)) {
      setView('summary')
    }
  }, [])

  useEffect(() => {
    if (!USE_PLAN_VERSION_API || !tripId) {
      return
    }
    let cancelled = false
    void tripApi.getTrip(tripId).then((response) => {
      if (cancelled) return
      const current = response.data.currentPlan
      const candidate = response.data.proposedPlans.find((plan) => plan.version === 2)
      const stored = current ?? response.data.proposedPlans[0]
      if (stored) {
        setRestoredPlan(toDisplayPlan(stored))
        setPersistedPlanId(stored.planId)
        setPlanningTripSnapshot(stored.tripSnapshot)
        void tripApi.getPlanningFacts(tripId, organizerToken).then((factsResponse) => {
          if (cancelled) return
          setCandidateRequest(factsResponse.data)
          setPlanningTripSnapshot(factsResponse.data.trip)
        }).catch((error: unknown) => {
          if (cancelled) return
          setCandidateRequest(null)
          setPlanLifecycleError(planningFactsRecoveryMessage(error))
        })
      }
      if (current) {
        applyTripState(response.data)
      }
      const completed = response.data.events
        .filter((event) => event.eventType === 'COMPLETE')
        .map((event) => event.taskId)
      const skipped = response.data.events
        .filter((event) => event.eventType === 'SKIP')
        .map((event) => event.taskId)
      setCompletedTaskIds([...new Set(completed)])
      setSkippedTaskIds([...new Set(skipped)])
      setActualSpentCents(response.data.actualBudget?.actualSpentCents ?? 0)
      if (stored) {
        const nextIndex = firstUnfinishedTaskIndex(stored, response.data.events)
        const restoredIndex = nextIndex !== null
          ? nextIndex
          : Math.max(0, stored.days[0].tasks.length - 1)
        setCurrentTaskIndex(restoredIndex)
        setActualCost(String(stored.days[0].tasks[restoredIndex].costCents / 100))
      }
      if (candidate) {
        setCandidatePlanV2(candidate)
        void tripApi.getPlanDiff(tripId, candidate.planId).then((diffResponse) => {
          if (cancelled) return
          setPlanDiff(diffResponse.data)
          setView('diff')
        }).catch((error: unknown) => {
          if (cancelled) return
          setPlanLifecycleError(error instanceof Error ? error.message : '恢复 Plan V2 Diff 失败')
        })
      } else if (response.data.tripStatus === 'EXECUTING') {
        setView('execute')
      }
    }).catch((error: unknown) => {
      if (cancelled || (error instanceof ApiError && error.code === 'TRIP_NOT_FOUND')) {
        return
      }
      setPlanLifecycleError(error instanceof Error ? error.message : '恢复 Plan V1 失败')
    })
    return () => {
      cancelled = true
    }
  }, [applyTripState, organizerToken, tripId])

  useEffect(() => {
    if (view !== 'summary' || !tripId) {
      return
    }
    let cancelled = false
    void tripApi.getSummary(tripId).then((response) => {
      if (!cancelled) {
        setSummary(response.data)
      }
    }).catch((error: unknown) => {
      if (!cancelled) {
        setPlanLifecycleError(error instanceof Error ? error.message : '加载总结失败')
      }
    })
    return () => {
      cancelled = true
    }
  }, [tripId, view])

  useEffect(() => {
    if (!tripId || !draft || !confirmedTrip || locationEvidence) {
      return
    }
    let cancelled = false
    void loadAmapPlan(tripId, draft, undefined, { confirmedTrip }).then((result) => {
      if (cancelled) return
      setProviderPlan(result.plan)
      setLocationEvidence(result.evidence)
      setCandidateRequest(result.candidateRequest)
      setPlanningTripSnapshot(result.candidateRequest.trip)
      setPlanningIssue(result.planningIssue)
      setCandidateReview(result.planningIssue?.review ?? null)
      setPersistedPlanId(result.registeredPlan?.planId ?? null)
      setLocationEvidenceError('')
    }).catch((error: unknown) => {
      if (!cancelled) {
        setLocationEvidenceError(
          error instanceof Error ? error.message : '高德真实地点与路线加载失败',
        )
      }
    }).finally(() => {
      if (!cancelled) {
        setIsLoadingLocationEvidence(false)
      }
    })

    return () => {
      cancelled = true
    }
  }, [confirmedTrip, draft, locationEvidence, tripId])

  const budgetCents = planningDraft?.budgetCents ?? (
    restoredPlan
      ? restoredPlan.totalCostCents + restoredPlan.bufferCents
      : 35000
  )
  const planningConstraints = planningTripSnapshot
    ? compileGroupAssistanceConstraints(
        planningTripSnapshot.participants.map((participant) => participant.assistanceProfile),
      )
    : []
  const validationRules = [
    ...planningConstraints.map(describePlanningConstraint),
    `${planningTripSnapshot?.days[0].timeWindow.end.slice(0, 5) ?? planningDraft?.endTime ?? '20:00'} 前结束`,
  ]
  const executionMapEvidence = useMemo<LocationEvidence | null>(() => {
    if (locationEvidence) return locationEvidence
    if (!candidateRequest) return null
    return {
      city: { cityContext: candidateRequest.trip.cityContext },
      places: candidateRequest.taskFacts.map((fact) => fact.place),
      routes: candidateRequest.taskFacts.map((fact) => fact.route),
      queries: [],
    } as unknown as LocationEvidence
  }, [candidateRequest, locationEvidence])
  const availablePlan = restoredPlan ?? providerPlan
  if (!availablePlan) {
    return (
      <AppShell compact>
        <main className="workspace provider-plan-loading">
          <section className="provider-evidence-card motion-enter">
            <div className="source-card__head">
              <span><LoaderCircle className={isLoadingLocationEvidence ? 'spin-icon' : ''} size={18} /> 高德真实数据计划</span>
            </div>
            <p>
              {isLoadingLocationEvidence
                ? '正在通过后端读取高德 Web 服务：解析城市、检索同城 POI，并逐段规划路线。'
                : locationEvidenceError || '没有可恢复的真实计划，请从“新建行程”重新进入。'}
            </p>
            {locationEvidenceError && <p className="media-error">不会使用固定数据或 Mock 自动回退。</p>}
          </section>
        </main>
      </AppShell>
    )
  }
  const activePlan = availablePlan
  const serverPlanReady = Boolean(persistedPlanId) &&
    activePlan.validationStatus === 'PASS' &&
    !planningIssue
  const hasIssuedPassPlan = serverPlanReady
  const remainingBudgetCents = Math.max(0, budgetCents - activePlan.totalCostCents)
  const budgetUsagePercent = budgetCents > 0
    ? Math.min(100, Math.round(activePlan.totalCostCents / budgetCents * 100))
    : 0
  const unknownPriceCount = hasIssuedPassPlan ? 0 : locationEvidence
    ? locationEvidence.places.filter((place) => place.priceReference.amountCents === null).length +
      locationEvidence.routes.filter((route) => route.priceReference.amountCents === null).length
    : activePlan.tasks.filter((task) => task.priceKnown === false).length
  const currentTask = activePlan.tasks[currentTaskIndex]
  const nextTask = activePlan.tasks.find(
    (task) => task.order > (currentTask?.order ?? 0),
  )
  const parsedActualExpenseCents = parseYuanAmountToCents(actualCost)
  const actualExpenseCents = parsedActualExpenseCents ?? 0
  const expenseDeltaCents = actualExpenseCents - (currentTask?.costCents ?? 0)
  const expenseDifferenceLabel =
    expenseDeltaCents === 0
      ? '实际消费与计划一致'
      : `比计划${expenseDeltaCents > 0 ? '多花' : '少花'} ${formatMoney(Math.abs(expenseDeltaCents))}`
  const summaryView = summary ? sprint1SummaryView(summary, formatMoney) : null
  const executionProgress = Math.round(
    ((completedTaskIds.length + skippedTaskIds.length) / activePlan.tasks.length) * 100,
  )
  const completedWalkMeters = activePlan.tasks
    .filter((task) => completedTaskIds.includes(task.id))
    .reduce((total, task) => total + task.walkMeters, 0)
  const isJourneyComplete =
    completedTaskIds.length + skippedTaskIds.length >= activePlan.tasks.length
  const storedProviderSources = storedCurrentPlan?.sourcesSnapshot.filter(
    (source) => source.provider === 'AMAP',
  ) ?? []
  const storedLocationSource = storedProviderSources.find(
    (source) => !source.referenceId?.endsWith(':price'),
  )
  const storedPriceSource = storedProviderSources.find(
    (source) => source.referenceId?.endsWith(':price'),
  )
  const locationProvenance =
    locationEvidence?.routes[0]?.provenance ??
    locationEvidence?.places[0]?.provenance ??
    locationEvidence?.city.provenance ??
    (storedLocationSource ? {
      provider: 'AMAP' as const,
      sourceStatus: storedLocationSource.sourceStatus,
      fetchedAt: storedLocationSource.fetchedAt,
      isStale: storedLocationSource.isStale,
    } : null) ??
    null
  const knownPrice = locationEvidence?.places.find(
    (place) => place.priceReference.amountCents !== null,
  )?.priceReference
  const priceProvenance =
    knownPrice?.provenance ??
    locationEvidence?.places[0]?.priceReference.provenance ??
    (storedPriceSource ? {
      provider: 'AMAP' as const,
      sourceStatus: storedPriceSource.sourceStatus,
      fetchedAt: storedPriceSource.fetchedAt,
      isStale: storedPriceSource.isStale,
    } : null)
  const displayedCityCode =
    locationEvidence?.city.cityContext.cityCode ??
    storedCurrentPlan?.tripSnapshot.cityContext.cityCode ??
    null
  const routeFacilityEvidence = locationEvidence?.routes.flatMap(
    (route) => route.facilityEvidence,
  ) ?? []
  const facilityEvidence = routeFacilityEvidence
  const facilityNeedsConfirmation = !hasIssuedPassPlan && Boolean(locationEvidence) && (
    facilityEvidence.length === 0 ||
    facilityEvidence.some(facilityEvidenceNeedsConfirmation)
  )
  const reviewItems = candidateReview?.items ?? []
  const priceReviewItems = reviewItems.filter((item) => item.valueType === 'PRICE_CENTS')
  const sourceReviewItems = reviewItems.filter((item) => item.valueType === 'SOURCE_CONFIRMATION')
  const facilityReviewGroups = [...reviewItems
    .filter((item) => item.valueType === 'FACILITY_STATUS')
    .reduce((groups, item) => {
      const key = item.facilityType ?? item.field
      const current = groups.get(key) ?? []
      current.push(item)
      groups.set(key, current)
      return groups
    }, new Map<string, CandidateReviewItem[]>())
    .entries()]
    .map(([key, items]) => ({
      key,
      label: facilityTypeLabels[key] ?? items[0]?.label ?? '路线设施',
      items,
    }))
  const completedReviewCount = reviewItems.filter(
    (item) => Boolean(reviewValues[item.itemId]?.trim()),
  ).length
  const reviewProgress = reviewItems.length > 0
    ? Math.round(completedReviewCount / reviewItems.length * 100)
    : 0
  const canCreatePlanV2 = canRequestS1PlanV2(
    storedCurrentPlan?.version ?? null,
    executionAdjustmentCount,
  )
  const hasAdjustableSuffix = currentTaskIndex < activePlan.tasks.length - 1
  const adjustmentBlockReason = executionAdjustmentBlockReason({
    currentVersion: storedCurrentPlan?.version ?? null,
    completedV2Decisions: executionAdjustmentCount,
    hasPendingCandidate: candidatePlanV2 !== null,
    hasCurrentTask: Boolean(currentTask),
    hasAdjustableSuffix,
    hasOrganizerToken: Boolean(organizerToken),
  })
  const adjustmentDetailsComplete = adjustmentEventType === 'LATE'
    ? Number.isInteger(Number(adjustmentLateMinutes)) && Number(adjustmentLateMinutes) >= 1 && Number(adjustmentLateMinutes) <= 240
    : adjustmentEventType === 'FATIGUE' && Boolean(adjustmentFatigueLevel)
  const changedExecutionTasks = candidatePlanV2?.days[0].tasks.filter((task) => {
    const previous = storedCurrentPlan?.days[0].tasks.find((item) => item.taskId === task.taskId)
    return !previous || previous.timeRange !== task.timeRange || previous.note !== task.note ||
      previous.title !== task.title || previous.transport !== task.transport ||
      previous.durationMinutes !== task.durationMinutes || previous.costCents !== task.costCents ||
      previous.walkMeters !== task.walkMeters
  }) ?? []

  function setReviewItems(
    items: CandidateReviewItem[],
    value: string,
  ) {
    setReviewValues((current) => ({
      ...current,
      ...Object.fromEntries(items.map((item) => [item.itemId, value])),
    }))
    setPlanLifecycleError('')
  }
  function toggleRecommendationFeedback(option: string) {
    setSelectedFeedbackOptions((current) =>
      current.includes(option)
        ? current.filter((item) => item !== option)
        : [...current, option],
    )
  }

  async function handleRegenerateRecommendation() {
    if (
      selectedFeedbackOptions.length === 0 &&
      recommendationFeedback.trim().length === 0
    ) {
      return
    }
    if (!tripId || !planningDraft) {
      setPlanLifecycleError('缺少原始行程草稿，无法重新请求高德真实数据。')
      return
    }
    if (persistedPlanId) {
      setPlanLifecycleError('当前 Plan V1 已由服务端签发；不可在客户端覆盖，请确认后通过 Plan V2 调整。')
      setIsFeedbackOpen(false)
      return
    }
    const planningTrip = candidateRequest?.trip ?? confirmedTrip
    if (!planningTrip) {
      setPlanLifecycleError('缺少 T004 已确认 Trip，不能猜测起终点；请返回新建行程重新确认。')
      return
    }
    setIsRegenerating(true)
    setPlanLifecycleError('')
    const feedback = [
      ...selectedFeedbackOptions,
      ...(recommendationFeedback.trim() ? [recommendationFeedback.trim()] : []),
    ]
    const interests = [...planningDraft.interests]
    if (selectedFeedbackOptions.includes('增加文化景点') && !interests.includes('博物馆')) {
      interests.unshift('博物馆')
    }
    if (selectedFeedbackOptions.includes('调整用餐安排') && !interests.includes('特色餐饮')) {
      interests.unshift('特色餐饮')
    }
    try {
      const currentCare = planningCareFromConstraints(
        compileGroupAssistanceConstraints(
          planningTrip.participants.map((participant) => participant.assistanceProfile),
        ),
      )
      const currentWalkLimit = currentCare.maxContinuousMeters ??
        planningDraft.assistanceProfile.maxSegmentWalkMeters
      const preferredMaxWalkMeters = selectedFeedbackOptions.includes('想少走路')
        ? Math.max(100, Math.round((currentWalkLimit ?? 500) * 0.7))
        : undefined
      const result = await loadAmapPlan(tripId, {
        ...planningDraft,
        interests,
        naturalLanguageRequest: `${planningDraft.naturalLanguageRequest}；补充反馈：${feedback.join('、')}`,
      }, undefined, { preferredMaxWalkMeters, confirmedTrip: planningTrip })
      setProviderPlan(result.plan)
      setLocationEvidence(result.evidence)
      setCandidateRequest(result.candidateRequest)
      setPlanningTripSnapshot(result.candidateRequest.trip)
      setPlanningIssue(result.planningIssue)
      setCandidateReview(result.planningIssue?.review ?? null)
      setPersistedPlanId(result.registeredPlan?.planId ?? null)
      setRecommendationRound((current) => current + 1)
      setAppliedFeedback(feedback)
      setLocationEvidenceError('')
      setPlanLifecycleError(result.planningIssue?.message ?? '')
      setIsFeedbackOpen(false)
    } catch (error) {
      setPlanLifecycleError(
        error instanceof Error ? error.message : '高德真实数据重新推荐失败',
      )
    } finally {
      setIsRegenerating(false)
    }
  }

  async function recordExecutionEvent(
    planId: string,
    taskId: string,
    eventType: ExecutionEvent['eventType'],
    amountCents: number | null = null,
  ) {
    if (!tripId) {
      throw new Error('当前页面缺少 tripId。')
    }
    await tripApi.createExecutionEvent(tripId, {
      schemaVersion: '1.0',
      taskId,
      planVersionId: planId,
      eventType,
      amountCents,
      idempotencyKey: executionEventIdempotencyKey(planId, taskId, eventType, amountCents),
      occurredAt: new Date().toISOString(),
    })
    const restored = await tripApi.getTrip(tripId)
    applyTripState(restored.data)
    return restored.data
  }

  async function startTask(
    plan: StoredPlanVersion,
    taskIndex: number,
  ) {
    const task = plan.days[0].tasks[taskIndex]
    if (!task) {
      return
    }
    await recordExecutionEvent(plan.planId, task.taskId, 'START')
  }

  async function checkArrival() {
    const target = candidateRequest?.taskFacts.find((item) => item.taskId === currentTask?.id)?.place.location
    if (!tripId || !currentTask || !target || !navigator.geolocation) {
      setArrivalMessage('当前任务缺少可信目的地坐标，暂不能自动定位；你仍可手动完成任务。')
      return
    }
    setIsLocating(true); setArrivalMessage('正在进行一次定位…')
    const attempt = await new Promise<{ position: GeolocationPosition | null; outcome: 'EVIDENCE' | 'PERMISSION_DENIED' | 'TIMEOUT' }>((resolve) => navigator.geolocation.getCurrentPosition((position) => resolve({ position, outcome: 'EVIDENCE' }), (error) => resolve({ position: null, outcome: error.code === error.TIMEOUT ? 'TIMEOUT' : 'PERMISSION_DENIED' }), { enableHighAccuracy: true, timeout: 10_000, maximumAge: 0 }))
    try {
      if (!attempt.position) {
        const decision = await tripApi.decideArrival(tripId, { schemaVersion: '1.0', taskId: currentTask.id, targetLocation: target, attemptOutcome: attempt.outcome, source: 'WEB_GEOLOCATION' })
        setArrivalMessage(decision.data.message)
        return
      }
      const evidence = await tripApi.saveArrivalEvidence(tripId, { schemaVersion: '1.0', taskId: currentTask.id, locationEvidence: { longitude: attempt.position.coords.longitude, latitude: attempt.position.coords.latitude, accuracy: attempt.position.coords.accuracy, capturedAt: new Date(attempt.position.timestamp).toISOString(), source: 'WEB_GEOLOCATION' }, idempotencyKey: `arrival-${crypto.randomUUID()}` })
      const decision = await tripApi.decideArrival(tripId, { schemaVersion: '1.0', taskId: currentTask.id, targetLocation: target, attemptOutcome: 'EVIDENCE', source: 'WEB_GEOLOCATION', arrivalEvidenceId: evidence.data.evidenceId })
      setArrivalMessage(decision.data.message)
    } catch (error) { setArrivalMessage(error instanceof Error ? error.message : '定位判断失败，可改为手动确认。') }
    finally { setIsLocating(false) }
  }

  async function handleAcceptPlan() {
    if (!tripId) {
      setPlanLifecycleError('当前页面缺少 tripId，请从“新建行程”重新进入。')
      return
    }
    setIsConfirmingPlan(true)
    setPlanLifecycleError('')
    try {
      if (planningIssue) {
        throw new Error(planningIssue.message)
      }
      if (activePlan.validationStatus !== 'PASS') {
        throw new Error('候选事实尚未获得服务端 T011 的完整 PASS，当前计划不能确认。')
      }
      if (activePlan.tasks.length < 3) {
        throw new Error('真实 Provider 地点不足 3 个，当前计划不能确认。')
      }
      if (!persistedPlanId) {
        throw new Error('服务端尚未签发可信 Plan V1；请先补齐未知价格、设施或来源证据。')
      }
      await tripApi.confirmPlan(tripId, persistedPlanId, organizerToken)
      await tripApi.startExecution(tripId)
      const restored = await tripApi.getTrip(tripId)
      if (restored.data.currentPlan) {
        applyTripState(restored.data)
        const firstIndex = firstUnfinishedTaskIndex(
          restored.data.currentPlan,
          restored.data.events,
        )
        if (firstIndex !== null) {
          await startTask(restored.data.currentPlan, firstIndex)
        }
      }
      setView('execute')
    } catch (error) {
      setPlanLifecycleError(error instanceof Error ? error.message : '确认 Plan V1 失败')
    } finally {
      setIsConfirmingPlan(false)
    }
  }

  async function handleConfirmEvidence() {
    if (!tripId || !candidateReview) return
    const confirmations: CandidateReviewConfirmationInput[] = []
    for (const item of candidateReview.items) {
      const raw = reviewValues[item.itemId]?.trim() ?? ''
      if (!raw) {
        setPlanLifecycleError(`请先完成“${item.label}”的确认。`)
        return
      }
      if (item.valueType === 'PRICE_CENTS') {
        const amountYuan = Number(raw)
        if (!Number.isFinite(amountYuan) || amountYuan < 0) {
          setPlanLifecycleError(`“${item.label}”金额必须是不小于 0 的数字。`)
          return
        }
        confirmations.push({
          itemId: item.itemId,
          amountCents: Math.round(amountYuan * 100),
          facilityStatus: null,
          sourceConfirmed: null,
          note: amountYuan === 0 ? '用户确认为免费或无额外费用' : '用户确认金额',
        })
      } else if (item.valueType === 'FACILITY_STATUS') {
        if (raw !== 'PASS' && raw !== 'FAIL') {
          setPlanLifecycleError(`请确认“${item.label}”存在或不存在。`)
          return
        }
        confirmations.push({
          itemId: item.itemId,
          amountCents: null,
          facilityStatus: raw,
          sourceConfirmed: null,
          note: raw === 'PASS' ? '用户确认设施存在' : '用户确认设施不存在',
        })
      } else {
        confirmations.push({
          itemId: item.itemId,
          amountCents: null,
          facilityStatus: null,
          sourceConfirmed: raw === 'CONFIRMED',
          note: '用户确认数据来源',
        })
      }
    }

    setIsConfirmingEvidence(true)
    setPlanLifecycleError('')
    try {
      const response = await tripApi.confirmPlanReview(
        tripId,
        candidateReview.reviewId,
        confirmations,
        organizerToken,
      )
      const stored = response.data
      setProviderPlan(toDisplayPlan(stored))
      setPersistedPlanId(stored.planId)
      setPlanningTripSnapshot(stored.tripSnapshot)
      setPlanningIssue(null)
      setCandidateReview(null)
      const facts = await tripApi.getPlanningFacts(tripId, organizerToken)
      setCandidateRequest(facts.data)
      setPlanLifecycleError('价格、设施与来源事实已由服务端重新校验，Plan V1 已获得 PASS。')
    } catch (error) {
      setPlanLifecycleError(error instanceof Error ? error.message : '候选事实确认失败')
    } finally {
      setIsConfirmingEvidence(false)
    }
  }

  async function preparePlanV2() {
    if (!tripId || !storedCurrentPlan) {
      throw new Error('未恢复当前 Plan V1，暂时不能生成 Plan V2。')
    }
    if (!canCreatePlanV2) {
      throw new Error(S1_REPLAN_LIMIT_MESSAGE)
    }
    if (candidatePlanV2) {
      setView('diff')
      return
    }

    const selected = await tripApi.replanFromEvents(tripId)
    const diff = await tripApi.getPlanDiff(tripId, selected.data.plan.planId)
    setCandidatePlanV2(selected.data.plan)
    setPlanDiff(diff.data)
    setView('diff')
  }

  function prepareQuickAdjustment(
    eventType: ExecutionAdjustmentType,
    value: number | FatigueLevel,
  ) {
    if (adjustmentBlockReason || isParsingAdjustment || isConfirmingAdjustment) {
      if (adjustmentBlockReason) setPlanLifecycleError(adjustmentBlockReason)
      return
    }
    if (!currentTask) {
      setPlanLifecycleError('当前页面缺少正在执行的任务。')
      return
    }
    if (!hasAdjustableSuffix) {
      setPlanLifecycleError('当前已经是最后一个任务，没有后续安排可生成 Plan V2。')
      return
    }
    const lateMinutes = eventType === 'LATE' ? Number(value) : null
    const fatigueLevel = eventType === 'FATIGUE' ? value as FatigueLevel : null
    const draft: ExecutionEventParseOutcome['draft'] = {
      schemaVersion: '1.0',
      eventType,
      taskId: currentTask.id,
      lateMinutes,
      fatigueLevel,
      clarificationQuestions: [],
    }
    setAdjustmentParse({
      draft,
      recognition: {
        source: 'DETERMINISTIC_FORM',
        model: null,
        degradedReason: null,
      },
    })
    setAdjustmentEventType(eventType)
    setAdjustmentLateMinutes(lateMinutes === null ? '' : String(lateMinutes))
    setAdjustmentFatigueLevel(fatigueLevel ?? '')
    setAdjustmentText(
      eventType === 'LATE'
        ? `迟到了 ${lateMinutes} 分钟`
        : `当前为${fatigueLevel === 'MILD' ? '轻度' : fatigueLevel === 'MODERATE' ? '中度' : '重度'}疲劳`,
    )
    setPendingAdjustmentEvent(null)
    setPlanLifecycleError('')
  }

  async function parseExecutionAdjustment() {
    if (adjustmentBlockReason || isParsingAdjustment || isConfirmingAdjustment) {
      if (adjustmentBlockReason) setPlanLifecycleError(adjustmentBlockReason)
      return
    }
    if (!tripId || !currentTask) {
      setPlanLifecycleError('当前页面缺少正在执行的任务，无法解析调整。')
      return
    }
    if (!organizerToken) {
      setPlanLifecycleError('当前浏览器没有组织者凭证，不能提交迟到或疲劳调整。')
      return
    }
    if (!hasAdjustableSuffix) {
      setPlanLifecycleError('当前已经是最后一个任务，没有后续安排可生成 Plan V2。')
      return
    }
    const rawText = adjustmentText.trim()
    if (!rawText) {
      setPlanLifecycleError('请先说明迟到或疲劳情况。')
      return
    }
    setIsParsingAdjustment(true)
    setPlanLifecycleError('')
    try {
      const parsed = await tripApi.parseExecutionAdjustment(
        {
          schemaVersion: '1.0',
          rawText,
          taskId: currentTask.id,
          currentTask: { taskId: currentTask.id, title: currentTask.title },
        },
        organizerToken,
      )
      setAdjustmentParse(parsed)
      setAdjustmentEventType(parsed.draft.eventType ?? '')
      setAdjustmentLateMinutes(
        parsed.draft.lateMinutes === null ? '' : String(parsed.draft.lateMinutes),
      )
      setAdjustmentFatigueLevel(parsed.draft.fatigueLevel ?? '')
      setPendingAdjustmentEvent(null)
    } catch (error) {
      setPlanLifecycleError(error instanceof Error ? error.message : '解析迟到或疲劳反馈失败')
    } finally {
      setIsParsingAdjustment(false)
    }
  }

  async function confirmExecutionAdjustment() {
    if (adjustmentBlockReason || isParsingAdjustment || isConfirmingAdjustment) {
      if (adjustmentBlockReason) setPlanLifecycleError(adjustmentBlockReason)
      return
    }
    if (!tripId || !storedCurrentPlan || !adjustmentParse) {
      setPlanLifecycleError('请先解析并确认当前任务的迟到或疲劳情况。')
      return
    }
    if (!organizerToken) {
      setPlanLifecycleError('当前浏览器没有组织者凭证，只有组织者可以发起重规划。')
      return
    }
    if (adjustmentParse.draft.taskId !== currentTask?.id) {
      setAdjustmentParse(null)
      setPendingAdjustmentEvent(null)
      setPlanLifecycleError('当前任务已变化，请重新选择迟到或疲劳情况。')
      return
    }
    setIsConfirmingAdjustment(true)
    setPlanLifecycleError('')
    try {
      const adjustment = buildConfirmedAdjustment(adjustmentParse.draft, {
        eventType: adjustmentEventType || undefined,
        lateMinutes: adjustmentLateMinutes.trim()
          ? Number(adjustmentLateMinutes)
          : null,
        fatigueLevel: adjustmentFatigueLevel || null,
      })
      const pendingMatches = pendingAdjustmentEvent !== null &&
        pendingAdjustmentEvent.planVersionId === storedCurrentPlan.planId &&
        pendingAdjustmentEvent.taskId === adjustment.taskId &&
        pendingAdjustmentEvent.eventType === adjustment.eventType &&
        pendingAdjustmentEvent.lateMinutes === adjustment.lateMinutes &&
        pendingAdjustmentEvent.fatigueLevel === adjustment.fatigueLevel
      const occurredAt = pendingMatches
        ? pendingAdjustmentEvent.occurredAt
        : new Date().toISOString()
      const eventInput: ConfirmedExecutionAdjustmentEventInput = pendingMatches
        ? pendingAdjustmentEvent
        : {
            ...adjustment,
            planVersionId: storedCurrentPlan.planId,
            occurredAt,
            idempotencyKey: createAdjustmentIdempotencyKey(
              storedCurrentPlan.planId,
              adjustment.taskId,
              adjustment.eventType,
              occurredAt,
            ),
          }
      setPendingAdjustmentEvent(eventInput)

      const persisted = await tripApi.confirmExecutionAdjustment(
        tripId,
        eventInput,
        organizerToken,
      )
      const preview = await tripApi.previewExecutionReplan(
        tripId,
        {
          schemaVersion: '1.0',
          adjustmentEventId: persisted.data.eventId,
          adjustment,
          lockedTaskIds: [...new Set([...completedTaskIds, ...skippedTaskIds])],
          explainDifferences: true,
        },
        organizerToken,
      )
      if (
        preview.data.currentPlanChanged ||
        preview.data.currentPlanId !== storedCurrentPlan.planId
      ) {
        throw new Error('服务端候选预览违反 CURRENT 不变约束，已停止展示。')
      }
      setAdjustmentPreview(preview.data)
      setCandidatePlanV2(preview.data.candidatePlan)
      setPlanDiff(preview.data.diff)
      setExecutionNotice(
        preview.data.explanation.status === 'UNAVAILABLE'
          ? '结构化 V2 与 Diff 已生成；文字解释暂不可用，不影响组织者决策。'
          : '迟到或疲劳事件已确认，候选 V2 尚未替换当前计划。',
      )
      setView('diff')
    } catch (error) {
      setPlanLifecycleError(describePlanV2Error(error))
    } finally {
      setIsConfirmingAdjustment(false)
    }
  }

  async function decidePlanV2(decision: 'accept' | 'reject') {
    if (!tripId || !candidatePlanV2) {
      return
    }
    setIsDecidingV2(true)
    setPlanLifecycleError('')
    try {
      const requiresAdjustmentDecision =
        candidatePlanV2.reason === 'DELAY' || candidatePlanV2.reason === 'FATIGUE'
      if (requiresAdjustmentDecision && !organizerToken) {
        throw new Error('当前浏览器没有组织者凭证，不能接受或拒绝此 V2。')
      }
      const continuation = await decideAndContinueExecution(
        decision,
        candidatePlanV2.planId,
        {
          acceptPlan: (planId) => requiresAdjustmentDecision
            ? tripApi.decideExecutionReplan(tripId, planId, 'ACCEPT', organizerToken as string)
            : tripApi.acceptPlanV2(tripId, planId),
          rejectPlan: (planId) => requiresAdjustmentDecision
            ? tripApi.decideExecutionReplan(tripId, planId, 'REJECT', organizerToken as string)
            : tripApi.rejectPlanV2(tripId, planId),
          restoreTrip: async () => (await tripApi.getTrip(tripId)).data,
          applyRestoredState: applyTripState,
          startTask,
          showSummary: () => setView('summary'),
        },
      )
      setCandidatePlanV2(null)
      setPlanDiff(null)
      setAdjustmentPreview(null)
      setPendingAdjustmentEvent(null)
      setAdjustmentParse(null)
      setAdjustmentText('')
      setAdjustmentEventType('')
      setAdjustmentLateMinutes('')
      setAdjustmentFatigueLevel('')
      setExecutionNotice(
        decision === 'accept'
          ? '已接受 Plan V2；Plan V1 已转为历史版本。'
          : '已拒绝 Plan V2；继续执行原 Plan V1。',
      )
      setExecutionAdjustmentCount(continuation.adjustmentCount)
      if (continuation.nextTaskIndex !== null) {
        setView('execute')
      }
    } catch (error) {
      setPlanLifecycleError(error instanceof Error ? error.message : 'Plan V2 决策失败')
    } finally {
      setIsDecidingV2(false)
    }
  }

  async function handleSkipTask() {
    if (!currentTask || !storedCurrentPlan) {
      return
    }
    setIsWritingEvent(true)
    setPlanLifecycleError('')
    try {
      const restored = await recordExecutionEvent(
        storedCurrentPlan.planId,
        currentTask.id,
        'SKIP',
      )
      const nextIndex = restored.currentPlan
        ? firstUnfinishedTaskIndex(restored.currentPlan, restored.events)
        : null
      if (restored.currentPlan && nextIndex !== null) {
        await startTask(restored.currentPlan, nextIndex)
        setView('execute')
      } else {
        setView('summary')
      }
    } catch (error) {
      setPlanLifecycleError(error instanceof Error ? error.message : '跳过任务失败')
    } finally {
      setIsWritingEvent(false)
    }
  }

  async function handleCompleteTask() {
    if (!currentTask || !storedCurrentPlan) {
      return
    }
    if (parsedActualExpenseCents === null) {
      setPlanLifecycleError('实际消费金额必须是非负数字。')
      return
    }
    setIsWritingEvent(true)
    setPlanLifecycleError('')
    try {
      const completionStates: TripPlanState[] = []
      await submitTaskCompletionEvents(
        actualCost,
        async (eventType, amountCents = null) => {
          const restored = await recordExecutionEvent(
            storedCurrentPlan.planId,
            currentTask.id,
            eventType,
            amountCents,
          )
          completionStates.push(restored)
        },
      )
      const completedState = completionStates.at(-1)
      if (!completedState) {
        throw new Error('完成任务事件没有返回服务端状态。')
      }
      const nextIndex = completedState.currentPlan
        ? firstUnfinishedTaskIndex(completedState.currentPlan, completedState.events)
        : null
      if (
        expenseDeltaCents !== 0 &&
        nextIndex !== null &&
        USE_PLAN_VERSION_API &&
        canCreatePlanV2
      ) {
        setIsPreparingV2(true)
        try {
          await preparePlanV2()
          setIsPreparingV2(false)
          return
        } catch (error) {
          setIsPreparingV2(false)
          setPlanLifecycleError(error instanceof Error ? error.message : '生成 Plan V2 失败')
          setExecutionNotice('费用变化已记录；Plan V2 暂不可行，继续执行当前 Plan V1。')
          if (tripId) {
            const restored = await tripApi.getTrip(tripId)
            applyTripState(restored.data)
            const restoredIndex = restored.data.currentPlan
              ? firstUnfinishedTaskIndex(restored.data.currentPlan, restored.data.events)
              : null
            if (restored.data.currentPlan && restoredIndex !== null) {
              await startTask(restored.data.currentPlan, restoredIndex)
              setView('execute')
            } else {
              setView('summary')
            }
          }
        }
        return
      }
      if (expenseDeltaCents !== 0 && !canCreatePlanV2) {
        setExecutionNotice(`费用变化已记录；${S1_REPLAN_LIMIT_MESSAGE} 将继续执行当前计划。`)
      }
      if (completedState.currentPlan && nextIndex !== null) {
        await startTask(completedState.currentPlan, nextIndex)
        setView('execute')
      } else {
        setView('summary')
      }
    } catch (error) {
      setIsPreparingV2(false)
      setPlanLifecycleError(error instanceof Error ? error.message : '完成任务失败')
    } finally {
      setIsWritingEvent(false)
    }
  }

  return (
    <AppShell compact>
      {parentTripId && <button className="parent-trip-return" type="button" onClick={() => { window.location.href = `/parent-trips/${parentTripId}` }}>← 返回多日行程规划</button>}
      <main className="workspace">
        <header className="workspace-header" data-reveal="fade">
          <div>
            <span className="section-kicker">
              {activePlan.cityName} · {planningDraft?.travelDate ?? storedCurrentPlan?.days[0].date ?? '日期已保存'}
            </span>
            <h1>{activePlan.cityName}高德真实数据一日计划</h1>
          </div>
          <div className="workspace-header__meta">
            <span className="pass-chip pass-chip--large">
              <ShieldCheck size={15} />
              {serverPlanReady
                ? `${validationRules.length} 项约束已由服务端复算`
                : '候选事实等待服务端确认'}
            </span>
            <button className="button button--soft" type="button"><Sparkles size={17} /> 问问 Agent</button>
          </div>
        </header>

        <nav className="workspace-tabs" data-reveal="fade" aria-label="行程视图">
          {views.map((item) => (
            <button
              className={view === item.value ? 'is-active' : ''}
              disabled={
                (item.value === 'summary' && !isJourneyComplete) ||
                (item.value === 'diff' && !planDiff)
              }
              key={item.value}
              onClick={() => setView(item.value)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </nav>

        {view === 'plan' && (
          <div className="workspace-grid motion-enter">
            <section className="timeline-panel">
              <div className="panel-heading">
                <div><span className="section-kicker">RECOMMENDATION #{recommendationRound}</span><h2>今天的路线</h2></div>
                <button className="mini-action" type="button">按时间 <ChevronDown size={15} /></button>
              </div>
              {recommendationRound > 1 && (
                <div className="recommendation-updated">
                  <CheckCircle2 size={17} />
                  <span><strong>已根据反馈重新推荐</strong><small>{appliedFeedback.join(' · ')}</small></span>
                </div>
              )}
              <div className="timeline">
                {activePlan.tasks.map((task) => (
                  <article className={`timeline-item timeline-item--${task.status}`} key={task.id}>
                    <div className="timeline-item__rail"><span>{task.order}</span></div>
                    <div className="timeline-item__time">{task.timeRange}</div>
                    <div className="timeline-item__card">
                      <div className="timeline-item__top">
                        <div>
                          <span className="category-chip">{task.category}</span>
                          <h3>{task.title}</h3>
                        </div>
                        <strong className={task.priceKnown === false ? 'needs-confirmation' : ''}>
                          {task.priceKnown === false
                            ? `${formatMoney(task.costCents)} 已知 · 另有待确认`
                            : formatMoney(task.costCents)}
                        </strong>
                      </div>
                      <div className="task-meta">
                        <span><Clock3 size={15} /> {task.durationMinutes} 分钟</span>
                        <span><Navigation size={15} /> {task.transport}</span>
                        <span><Footprints size={15} /> {task.walkMeters} 米</span>
                      </div>
                      <div className="task-note"><BadgeCheck size={15} /> {task.note}</div>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <aside className="insight-column">
              <RouteOverview
                cityName={activePlan.cityName}
                evidence={locationEvidence}
                startLocationText={candidateRequest?.trip.days[0].startLocationText ?? null}
              />
              <section className="metric-card">
                <div className="metric-card__head"><span>Provider 已知费用</span><strong>{formatMoney(activePlan.totalCostCents)} / {formatMoney(budgetCents)}</strong></div>
                <div className="progress-bar"><i style={{ width: `${budgetUsagePercent}%` }} /></div>
                <div className="metric-grid">
                  <div><Wallet size={18} /><span>剩余缓冲<strong>{formatMoney(remainingBudgetCents)}</strong></span></div>
                  <div><Footprints size={18} /><span>全天步行<strong>{(activePlan.totalWalkMeters / 1000).toFixed(2)} km</strong></span></div>
                  <div><BusFront size={18} /><span>公共交通<strong>{activePlan.transferCount} 次换乘</strong></span></div>
                  <div><Clock3 size={18} /><span>弹性时间<strong>45 分钟</strong></span></div>
                </div>
              </section>
              {candidateReview && (
                <section className="evidence-review-card" aria-live="polite">
                  <div className="source-card__head">
                    <span><ShieldCheck size={18} /> 行前事实核对</span>
                    <strong>{completedReviewCount}/{reviewItems.length} 已完成</strong>
                  </div>
                  <div className="evidence-review-progress" aria-label={`事实核对进度 ${reviewProgress}%`}>
                    <i style={{ width: `${reviewProgress}%` }} />
                  </div>
                  <p>只确认你实际知道的情况。相同设施已按类型合并，不再要求逐路线重复填写；“按未发现处理”表示规划时不依赖该设施。</p>

                  {priceReviewItems.length > 0 && (
                    <section className="evidence-review-group">
                      <header><span>费用</span><small>{priceReviewItems.length} 项</small></header>
                      <p>填写现场价或可靠估价；只有明确免费时才选“免费”。</p>
                      {priceReviewItems.map((item) => (
                        <div className="evidence-review-row" key={item.itemId}>
                          <label htmlFor={`review-${item.itemId}`}>{item.label}</label>
                          <div className="evidence-price-input">
                            <span>¥</span>
                            <input
                              id={`review-${item.itemId}`}
                              min="0"
                              placeholder="实际或可靠估价"
                              step="0.01"
                              type="number"
                              value={reviewValues[item.itemId] ?? ''}
                              onChange={(event) => setReviewValues((current) => ({
                                ...current,
                                [item.itemId]: event.target.value,
                              }))}
                            />
                            <button onClick={() => setReviewItems([item], '0')} type="button">
                              明确免费
                            </button>
                          </div>
                        </div>
                      ))}
                    </section>
                  )}

                  {facilityReviewGroups.length > 0 && (
                    <section className="evidence-review-group">
                      <header><span>路线设施</span><small>{facilityReviewGroups.length} 类</small></header>
                      <p>按设施类型一次选择，自动应用到涉及的全部路线段。</p>
                      <div className="facility-review-grid">
                        {facilityReviewGroups.map((group) => {
                          const values = group.items.map((item) => reviewValues[item.itemId])
                          const selected = values.every((value) => value === 'PASS')
                            ? 'PASS'
                            : values.every((value) => value === 'FAIL') ? 'FAIL' : ''
                          return (
                            <article className="facility-review-item" key={group.key}>
                              <div>
                                <strong>{group.label}</strong>
                                <small>影响 {group.items.length} 段路线</small>
                              </div>
                              <div className="facility-review-actions">
                                <button
                                  className={selected === 'PASS' ? 'is-selected is-pass' : ''}
                                  onClick={() => setReviewItems(group.items, 'PASS')}
                                  type="button"
                                >已核实存在</button>
                                <button
                                  className={selected === 'FAIL' ? 'is-selected is-fail' : ''}
                                  onClick={() => setReviewItems(group.items, 'FAIL')}
                                  type="button"
                                >按未发现处理</button>
                              </div>
                              <details>
                                <summary>查看并逐段修正</summary>
                                <ul>{group.items.map((item) => (
                                  <li key={item.itemId}>
                                    <span>{item.label}</span>
                                    <div>
                                      <button
                                        className={reviewValues[item.itemId] === 'PASS' ? 'is-selected is-pass' : ''}
                                        onClick={() => setReviewItems([item], 'PASS')}
                                        type="button"
                                      >有</button>
                                      <button
                                        className={reviewValues[item.itemId] === 'FAIL' ? 'is-selected is-fail' : ''}
                                        onClick={() => setReviewItems([item], 'FAIL')}
                                        type="button"
                                      >未发现</button>
                                    </div>
                                  </li>
                                ))}</ul>
                              </details>
                            </article>
                          )
                        })}
                      </div>
                    </section>
                  )}

                  {sourceReviewItems.length > 0 && (
                    <section className="evidence-review-group evidence-review-group--source">
                      <header><span>数据来源</span><small>{sourceReviewItems.length} 项</small></header>
                      <p>确认这些信息来自你本人、现场标识或可靠商家信息。</p>
                      <button
                        className={sourceReviewItems.every((item) => reviewValues[item.itemId] === 'CONFIRMED') ? 'is-confirmed' : ''}
                        onClick={() => setReviewItems(sourceReviewItems, 'CONFIRMED')}
                        type="button"
                      >
                        {sourceReviewItems.every((item) => reviewValues[item.itemId] === 'CONFIRMED')
                          ? '来源已统一确认'
                          : '确认上述来源可信'}
                      </button>
                    </section>
                  )}
                  <button
                    className="button button--primary evidence-review-submit"
                    disabled={isConfirmingEvidence || completedReviewCount !== reviewItems.length}
                    onClick={() => void handleConfirmEvidence()}
                    type="button"
                  >
                    {isConfirmingEvidence
                      ? <><LoaderCircle className="spin-icon" size={16} /> 服务端重新校验中…</>
                      : completedReviewCount === reviewItems.length
                        ? <><Check size={16} /> 提交并由服务端重新校验</>
                        : <><Check size={16} /> 还需确认 {reviewItems.length - completedReviewCount} 项</>}
                  </button>
                </section>
              )}
              <section className="explanation-card">
                <div className="explanation-card__head">
                  <span><Sparkles size={18} /> Agent 推荐理由</span>
                  <small>可解释</small>
                </div>
                <p>优先满足{planningDraft?.interests.slice(0, 2).join('和') || '历史文化和特色餐饮'}偏好，在满足{planningDraft?.assistanceMode === 'standard' ? '时间与预算' : '关怀'}约束的前提下，减少无效折返并保留返程缓冲。</p>
                <div className="reason-tags">
                  <span>高德地点 {locationEvidence?.places.length ?? activePlan.tasks.length} 个</span>
                  <span>真实路线 {locationEvidence?.routes.length ?? activePlan.tasks.length} 段</span>
                  <span>未知价格 {unknownPriceCount} 项</span>
                </div>
              </section>
              <section className="source-card">
                <div className="source-card__head">
                  <span><Layers3 size={18} /> 数据可信状态</span>
                  <strong className="city-code-chip">
                    {displayedCityCode ? `cityCode ${displayedCityCode}` : '正在核验城市'}
                  </strong>
                </div>
                <div>
                  <Telescope size={15} />
                  <span>地点与路线</span>
                  <strong>{locationProvenance ? formatSource(locationProvenance) : '加载中'}</strong>
                </div>
                <div>
                  <CircleDollarSign size={15} />
                  <span>Provider 价格</span>
                  <strong className={priceProvenance?.sourceStatus === 'UNKNOWN' ? 'needs-confirmation' : ''}>
                    {serverPlanReady
                      ? 'Provider 原值 + 用户确认 · 已完整'
                      : knownPrice?.amountCents !== null && knownPrice?.amountCents !== undefined
                      ? `${formatMoney(knownPrice.amountCents)} · ${sourceStatusLabels[knownPrice.provenance.sourceStatus]}`
                      : priceProvenance
                        ? '未知待确认'
                        : '加载中'}
                  </strong>
                </div>
                <div>
                  <Wallet size={15} />
                  <span>计划费用</span>
                  <strong className={unknownPriceCount > 0 ? 'needs-confirmation' : ''}>
                    高德已知 {formatMoney(activePlan.totalCostCents)} · {unknownPriceCount} 项未知
                  </strong>
                </div>
                <div>
                  <MapPin size={15} />
                  <span>路线设施证据</span>
                  <strong className={facilityNeedsConfirmation ? 'needs-confirmation' : ''}>
                    {serverPlanReady
                      ? '用户确认后服务端已复算'
                      : facilityNeedsConfirmation
                      ? `${Math.max(1, facilityEvidence.filter(facilityEvidenceNeedsConfirmation).length)} 项待确认`
                      : '已核验'}
                  </strong>
                </div>
              </section>
              <section className="provider-evidence-card">
                <div className="source-card__head">
                  <span><BadgeCheck size={18} /> 同城 Provider 证据</span>
                  {isLoadingLocationEvidence && <LoaderCircle className="spin-icon" size={15} />}
                </div>
                {locationEvidence ? (
                  <>
                    <p>
                      “{locationEvidence.queries.join(' / ')}”候选仅来自
                      {locationEvidence.city.cityContext.cityName}（{locationEvidence.city.cityContext.cityCode}），
                      不会读取其他城市缓存。
                    </p>
                    <div className="provider-place-list">
                      {locationEvidence.places.length > 0 ? locationEvidence.places.slice(0, 3).map((place) => (
                        <article key={place.placeId}>
                          <div>
                            <strong>{place.name}</strong>
                            <small>{place.address || '地址待 Provider 补充'}</small>
                          </div>
                          <div>
                            <span>{formatSource(place.provenance)}</span>
                            <b className={place.priceReference.amountCents === null ? 'needs-confirmation' : ''}>
                              {place.priceReference.amountCents === null
                                ? serverPlanReady
                                  ? '用户已确认并复算'
                                  : '价格未知待确认'
                                : `参考 ${formatMoney(place.priceReference.amountCents)}`}
                            </b>
                          </div>
                        </article>
                      )) : <p className="provider-evidence-empty">该关键词暂无同城候选。</p>}
                    </div>
                    {locationEvidence.routes.map((route, index) => (
                      <div className="provider-route-evidence" key={route.routeId}>
                        <Route size={17} />
                        <span>
                          <strong>
                            {index === 0
                              ? candidateRequest?.trip.days[0].startLocationText ?? '行程起点'
                              : locationEvidence.places[index - 1]?.name}
                            {' → '}{locationEvidence.places[index]?.name}
                          </strong>
                          <small>
                            {routeModeLabels[route.mode]} {route.distanceMeters} 米 · 约
                            {Math.max(1, Math.round(route.durationSeconds / 60))} 分钟 ·
                            {formatSource(route.provenance)}
                          </small>
                        </span>
                      </div>
                    ))}
                  </>
                ) : storedCurrentPlan ? (
                  <>
                    <p>
                      已从不可变 PlanVersion 恢复 {storedProviderSources.length} 条 AMAP 来源快照；
                      cityCode 为 {storedCurrentPlan.tripSnapshot.cityContext.cityCode}。
                    </p>
                    <div className="provider-route-evidence">
                      <Layers3 size={17} />
                      <span>
                        <strong>来源快照已恢复</strong>
                        <small>页面刷新不会把 Provider 来源改写为 Mock；重新搜索需要从新建行程页进入。</small>
                      </span>
                    </div>
                  </>
                ) : isLoadingLocationEvidence ? (
                  <p>正在向高德 Web 服务核验城市、地点候选和路线……</p>
                ) : (
                  <p>当前页面没有可恢复的城市输入，请从“新建行程”重新进入。</p>
                )}
                {locationEvidenceError && <p className="media-error">{locationEvidenceError}</p>}
              </section>
              {isFeedbackOpen ? (
                <section className="recommendation-feedback motion-enter">
                  <div className="recommendation-feedback__head">
                    <span><MessageSquareText size={18} /> 告诉 Agent 哪里不合适</span>
                    <button onClick={() => setIsFeedbackOpen(false)} type="button"><X size={16} /></button>
                  </div>
                  <div className="recommendation-feedback__options">
                    {recommendationFeedbackOptions.map((option) => (
                      <button
                        className={selectedFeedbackOptions.includes(option) ? 'is-selected' : ''}
                        key={option}
                        onClick={() => toggleRecommendationFeedback(option)}
                        type="button"
                      >
                        {selectedFeedbackOptions.includes(option) && <Check size={12} />}
                        {option}
                      </button>
                    ))}
                  </div>
                  <textarea
                    maxLength={200}
                    onChange={(event) => setRecommendationFeedback(event.target.value)}
                    placeholder="也可以具体说明，例如：希望下午安排室内景点，减少打车费用……"
                    value={recommendationFeedback}
                  />
                  <div className="recommendation-feedback__actions">
                    <small>{recommendationFeedback.length}/200</small>
                    <button
                      className="button button--primary"
                      disabled={
                        isRegenerating ||
                        (selectedFeedbackOptions.length === 0 && recommendationFeedback.trim().length === 0)
                      }
                      onClick={handleRegenerateRecommendation}
                      type="button"
                    >
                      {isRegenerating ? <LoaderCircle className="spin-icon" size={16} /> : <Send size={16} />}
                      {isRegenerating ? '正在重新推荐…' : '提交反馈并重新推荐'}
                    </button>
                  </div>
                </section>
              ) : (
                <div className="plan-decision-actions">
                  <button className="button button--ghost" onClick={() => setIsFeedbackOpen(true)} type="button">
                    <MessageSquareText size={17} /> 不满意，重新推荐
                  </button>
                  <button
                    className="button button--primary"
                    disabled={isConfirmingPlan || !serverPlanReady}
                    onClick={handleAcceptPlan}
                    type="button"
                  >
                    {isConfirmingPlan ? <LoaderCircle className="spin-icon" size={17} /> : null}
                    {isConfirmingPlan
                      ? '正在确认…'
                      : serverPlanReady
                        ? '接受推荐并确认 Plan V1'
                        : '证据待确认，暂不可接受'}
                    {!isConfirmingPlan && <ArrowRight size={18} />}
                  </button>
                  {planLifecycleError && <p className="media-error">{planLifecycleError}</p>}
                </div>
              )}
            </aside>
          </div>
        )}

        {view === 'diff' && planDiff && (
          <section className="plan-diff-stage motion-enter">
            <div className="plan-diff-hero">
              <div>
                <span className="section-kicker">候选方案审核 · 等待你的决定</span>
                <h2>V1/V2 变更对比</h2>
                <p>候选 Plan V2 尚未覆盖当前计划。只有接受后，V2 才会成为唯一的 CURRENT 版本。</p>
              </div>
              <span className="plan-diff-version">V1 <ArrowRight size={16} /> V2</span>
            </div>

            {adjustmentPreview && (
              <section className="explanation-card" aria-live="polite">
                <div className="explanation-card__head">
                  <span><Sparkles size={18} /> 本次执行调整</span>
                  <small>{adjustmentPreview.explanation.status}</small>
                </div>
                <p>
                  {adjustmentPreview.explanation.status === 'GENERATED'
                    ? adjustmentPreview.explanation.summary
                    : adjustmentPreview.explanation.status === 'UNAVAILABLE'
                      ? '文字解释暂不可用；下方结构化 Diff、HARD 校验和决策仍然有效。'
                      : '本次未请求文字解释；请以结构化 Diff 为准。'}
                </p>
                <div className="reason-tags">
                  {adjustmentPreview.eventConstraints.reasons.map((reason) => (
                    <span key={reason.reasonCode}>{reason.message}</span>
                  ))}
                  <span>冻结任务 {adjustmentPreview.frozenTaskIds.length} 个</span>
                  <span>
                    HARD 校验 {
                      adjustmentPreview.validationReport.checks.every(
                        (check) => check.hardness !== 'HARD' || check.status === 'PASS',
                      ) ? '通过' : '未通过'
                    }
                  </span>
                </div>
              </section>
            )}

            <div className="plan-diff-summary" aria-label="计划指标变化">
              <article>
                <span>预计费用</span>
                <strong className={planDiff.metricsDelta.totalCostCents <= 0 ? 'is-lower' : 'is-higher'}>
                  {planDiff.metricsDelta.totalCostCents >= 0 ? '+' : '-'}
                  {formatMoney(Math.abs(planDiff.metricsDelta.totalCostCents))}
                </strong>
              </article>
              <article>
                <span>步行距离</span>
                <strong className={planDiff.metricsDelta.totalWalkMeters <= 0 ? 'is-lower' : 'is-higher'}>
                  {planDiff.metricsDelta.totalWalkMeters >= 0 ? '+' : ''}{planDiff.metricsDelta.totalWalkMeters} 米
                </strong>
              </article>
              <article>
                <span>换乘次数</span>
                <strong className={planDiff.metricsDelta.transferCount <= 0 ? 'is-lower' : 'is-higher'}>
                  {planDiff.metricsDelta.transferCount >= 0 ? '+' : ''}{planDiff.metricsDelta.transferCount} 次
                </strong>
              </article>
            </div>
            <p className="plan-diff-change-count" role="status">
              {changedExecutionTasks.length > 0
                ? `实际调整 ${changedExecutionTasks.length} 个任务；请重点查看下方时间和休息安排。地点、费用不一定需要改变。`
                : '此候选没有实际任务变化，请拒绝此旧候选并继续原计划。'}
            </p>

            <div className="plan-diff-groups">
              {Object.entries(diffCategoryLabels).map(([category, categoryLabel]) => {
                const categoryItems = planDiff.items.filter((item) => item.category === category)
                const changedItems = categoryItems.filter((item) => item.changeType !== 'RETAINED')
                const retainedItems = categoryItems.filter((item) => item.changeType === 'RETAINED')
                return (
                  <section className="plan-diff-group" key={category}>
                    <header>
                      <h3>{categoryLabel}</h3>
                      <span>{changedItems.length} 项变更 · {retainedItems.length} 项保留</span>
                    </header>
                    {categoryItems.length > 0 ? (
                      <div className="plan-diff-list">
                        {changedItems.map((item) => (
                          <article
                            className={`plan-diff-row plan-diff-row--${item.changeType.toLowerCase()}`}
                            key={`${item.category}-${item.key}-${item.changeType}`}
                          >
                            <div className="plan-diff-row__title">
                              <span>{diffChangeLabels[item.changeType]}</span>
                              <strong>{item.label}</strong>
                            </div>
                            <div className="plan-diff-values">
                              <div><small>V1 当前值</small><p>{formatDiffValue(item.before, item.category)}</p></div>
                              <ArrowRight aria-hidden="true" size={16} />
                              <div><small>V2 候选值</small><p>{formatDiffValue(item.after, item.category)}</p></div>
                            </div>
                          </article>
                        ))}
                        {retainedItems.length > 0 && <details className="plan-diff-retained">
                          <summary>查看 {retainedItems.length} 项未变化的内容</summary>
                          {retainedItems.map((item) => <p key={item.key}><strong>{item.label}</strong>：{formatDiffValue(item.after, item.category)}</p>)}
                        </details>}
                      </div>
                    ) : (
                      <p className="plan-diff-empty">此类别没有变化。</p>
                    )}
                  </section>
                )
              })}
            </div>

            <div className="plan-diff-actions">
              <div>
                <ShieldCheck size={19} />
                <span><strong>状态守卫已启用</strong><small>接受和拒绝均由服务端原子处理，可安全重试。</small></span>
              </div>
              <div>
                <button className="button button--ghost" disabled={isDecidingV2} onClick={() => void decidePlanV2('reject')} type="button">
                  <X size={17} /> 拒绝 V2，继续执行 V1
                </button>
                <button className="button button--primary" disabled={isDecidingV2 || changedExecutionTasks.length === 0} onClick={() => void decidePlanV2('accept')} type="button">
                  {isDecidingV2 ? <LoaderCircle className="spin-icon" size={17} /> : <Check size={17} />}
                  {isDecidingV2 ? '正在处理决策…' : '接受 V2 并继续执行'}
                </button>
              </div>
              {planLifecycleError && <p className="media-error">{planLifecycleError}</p>}
            </div>
          </section>
        )}

        {view === 'execute' && (
          <section className="execution-web motion-enter">
            <div className="execution-web__main">
              <div className="execution-web__heading">
                <div>
                  <span className="section-kicker">LIVE EXECUTION · CONTINUOUS PLAN</span>
                  <h2>当前任务</h2>
                </div>
                <span className="execution-status"><span className="status-dot" /> 行程执行中</span>
              </div>

              <article className="current-task-card">
                <div className="current-task-card__visual">
                  <RouteOverview
                    cityName={activePlan.cityName}
                    evidence={executionMapEvidence}
                    startLocationText={candidateRequest?.trip.days[0].startLocationText ?? null}
                  />
                </div>
                <div className="current-task-card__content">
                  <span className="category-chip">任务 {currentTask?.order ?? 0} / {activePlan.tasks.length} · {currentTask?.category}</span>
                  <h3>{currentTask?.title}</h3>
                  <p><MapPin size={16} /> {planningDraft?.cityName ?? activePlan.cityName} · 当前任务目的地</p>
                  <div className="current-task-metrics">
                    <div><Clock3 size={19} /><span>计划时间<strong>{currentTask?.timeRange}</strong></span></div>
                    <div><Navigation size={19} /><span>预计步行<strong>{currentTask?.walkMeters ?? 0} 米</strong></span></div>
                    <div><Wallet size={19} /><span>计划消费<strong>{formatMoney(currentTask?.costCents ?? 0)}</strong></span></div>
                  </div>
                </div>
              </article>

              <div className="execution-form-card">
                <div className="execution-form-card__head">
                  <div><ReceiptText size={20} /><span><strong>完成任务并记录消费</strong><small>实际金额会用于计算剩余预算</small></span></div>
                  <span>自动保存</span>
                </div>
                <div className="planner-actions">
                  <button className="button button--soft" disabled={isLocating || isWritingEvent} onClick={() => void checkArrival()} type="button">
                    <Navigation size={16} />{isLocating ? '正在定位…' : '一次定位确认到达'}
                  </button>
                  {arrivalMessage && <span className="save-state">{arrivalMessage}</span>}
                </div>
                <label className="web-expense-field">
                  <span>实际消费金额</span>
                  <div><b>¥</b><input value={actualCost} onChange={(event) => setActualCost(event.target.value)} /></div>
                </label>
                <button
                  className="button button--soft"
                  disabled={!currentTask || isPreparingV2 || isWritingEvent}
                  onClick={() => setActualCost(plannedPlusFiftyYuan(currentTask?.costCents ?? 0))}
                  type="button"
                >
                  按计划 + ¥50
                </button>
                <div className="budget-alert">
                  <CircleDollarSign size={19} />
                  <div>
                    <strong>{expenseDifferenceLabel}</strong>
                    <small>
                      {canCreatePlanV2
                        ? '提交后 Agent 将检查剩余路线是否仍满足预算和关怀约束。'
                        : `提交后只记录实际费用；${S1_REPLAN_LIMIT_MESSAGE}`}
                    </small>
                  </div>
                </div>
                <div className="execution-form-actions">
                  <button
                    className="button button--ghost"
                    disabled={isPreparingV2 || isWritingEvent}
                    onClick={() => void handleSkipTask()}
                    type="button"
                  >
                    {isWritingEvent ? '正在保存…' : '跳过此任务'}
                  </button>
                  <button
                    className="button button--primary"
                    disabled={isPreparingV2 || isWritingEvent}
                    onClick={() => void handleCompleteTask()}
                    type="button"
                  >
                    {isWritingEvent
                      ? '正在保存事件…'
                      : isPreparingV2
                      ? '正在生成 Plan V2…'
                      : currentTaskIndex === activePlan.tasks.length - 1
                      ? '完成行程并查看总结'
                      : expenseDeltaCents !== 0 && canCreatePlanV2
                        ? '完成并更新后续安排'
                        : '完成当前任务'}
                    <RefreshCw size={17} />
                  </button>
                </div>
                {tripId && currentTask && <TaskPhotoCard tripId={tripId} taskId={currentTask.id} />}
              </div>
            </div>

            <aside className="execution-web__side">
              <section className="trip-progress-card">
                <div className="trip-progress-card__head"><span>今日进度</span><strong>{completedTaskIds.length + skippedTaskIds.length} / {activePlan.tasks.length}</strong></div>
                <div className="progress-bar"><i style={{ width: `${executionProgress}%` }} /></div>
                <div className="trip-progress-stats">
                  <div><span>已用预算</span><strong>{formatMoney(actualSpentCents)}</strong></div>
                  <div><span>剩余预算</span><strong>{formatMoney(budgetCents - actualSpentCents)}</strong></div>
                  <div><span>已步行</span><strong>{completedWalkMeters}m</strong></div>
                  <div><span>计划调整</span><strong>{executionAdjustmentCount} 次</strong></div>
                </div>
              </section>

              {nextTask && (
                <section className="next-task-card">
                  <span className="section-kicker">UP NEXT · {nextTask.timeRange.split('—')[0]}</span>
                  <h3>{nextTask.title}</h3>
                  <p>{nextTask.transport} · 预计步行 {nextTask.walkMeters} 米</p>
                  <div><Route size={18} /><span>{nextTask.note}</span></div>
                </section>
              )}

              <section className="execution-feedback-card">
                <div className="source-card__head">
                  <span><MessageSquareText size={18} /> 迟到 / 疲劳调整</span>
                </div>
                {adjustmentBlockReason && (
                  <p className="adjustment-unavailable" role="status">{adjustmentBlockReason}</p>
                )}
                {candidatePlanV2 && (
                  <button className="button button--soft" onClick={() => setView('diff')} type="button">查看已有 Plan V2</button>
                )}
                {!adjustmentBlockReason && <>
                {hasAdjustableSuffix ? (
                  <div className="adjustment-quick-actions">
                    <span>直接选择常见情况</span>
                    <div>
                      <button disabled={isParsingAdjustment || isConfirmingAdjustment} onClick={() => prepareQuickAdjustment('LATE', 15)} type="button">迟到 15 分钟</button>
                      <button disabled={isParsingAdjustment || isConfirmingAdjustment} onClick={() => prepareQuickAdjustment('LATE', 30)} type="button">迟到 30 分钟</button>
                      <button disabled={isParsingAdjustment || isConfirmingAdjustment} onClick={() => prepareQuickAdjustment('FATIGUE', 'MILD')} type="button">有点累</button>
                      <button disabled={isParsingAdjustment || isConfirmingAdjustment} onClick={() => prepareQuickAdjustment('FATIGUE', 'SEVERE')} type="button">需要明显减负</button>
                    </div>
                  </div>
                ) : (
                  <p className="adjustment-unavailable">当前已经是最后一个任务，没有后续安排需要生成 Plan V2。</p>
                )}
                <textarea
                  aria-label="说明迟到或疲劳情况"
                  disabled={isParsingAdjustment || isConfirmingAdjustment || !organizerToken || !hasAdjustableSuffix}
                  maxLength={160}
                  onChange={(event) => {
                    setAdjustmentText(event.target.value)
                    setAdjustmentParse(null)
                    setPendingAdjustmentEvent(null)
                  }}
                  placeholder="例如：迟到了 25 分钟；或者：我现在很累"
                  value={adjustmentText}
                />
                <button
                  className="button button--soft"
                  disabled={
                    isParsingAdjustment ||
                    isConfirmingAdjustment ||
                    !organizerToken ||
                    !hasAdjustableSuffix ||
                    !adjustmentText.trim()
                  }
                  onClick={() => void parseExecutionAdjustment()}
                  type="button"
                >
                  {isParsingAdjustment
                    ? <LoaderCircle className="spin-icon" size={15} />
                    : <Send size={15} />}
                  {isParsingAdjustment ? '正在识别…' : '识别自定义描述'}
                </button>
                {!organizerToken && (
                  <p className="media-error">当前浏览器没有组织者凭证，只能查看行程，不能发起重规划。</p>
                )}
                <p>{EXECUTION_REPLAN_HELP}；迟到或疲劳可在这里确认后立即生成 Plan V2 预览。</p>
                <p>这里只支持真实的迟到或疲劳情况；“想先吃东西”等用餐顺序调整暂不支持，不要选择疲劳来代替。</p>
                {adjustmentParse && (
                  <div className="evidence-review-list adjustment-confirmation" aria-live="polite">
                    <p>
                      确认当前情况
                      {adjustmentParse.recognition.degradedReason
                        ? '（智能识别暂不可用，已切换为固定选项）'
                        : ''}
                    </p>
                    {adjustmentParse.draft.clarificationQuestions.map((question) => (
                      <p key={question.questionKey}>{question.prompt}</p>
                    ))}
                    {!adjustmentParse.draft.eventType && <p>尚未识别到迟到或疲劳。只有确实发生这些情况时，才填写下方选项。</p>}
                    <label htmlFor="execution-adjustment-type">调整类型</label>
                    <select
                      id="execution-adjustment-type"
                      disabled={isParsingAdjustment || isConfirmingAdjustment}
                      onChange={(event) => {
                        setAdjustmentEventType(event.target.value as ExecutionAdjustmentType | '')
                        setPendingAdjustmentEvent(null)
                      }}
                      value={adjustmentEventType}
                    >
                      <option value="">请选择</option>
                      <option value="LATE">迟到</option>
                      <option value="FATIGUE">疲劳</option>
                    </select>
                    {adjustmentEventType === 'LATE' && (
                      <label htmlFor="execution-adjustment-late-minutes">
                        迟到分钟数（1–240）
                        <input
                          id="execution-adjustment-late-minutes"
                          disabled={isParsingAdjustment || isConfirmingAdjustment}
                          inputMode="numeric"
                          max="240"
                          min="1"
                          onChange={(event) => {
                            setAdjustmentLateMinutes(event.target.value)
                            setPendingAdjustmentEvent(null)
                          }}
                          type="number"
                          value={adjustmentLateMinutes}
                        />
                      </label>
                    )}
                    {adjustmentEventType === 'FATIGUE' && (
                      <label htmlFor="execution-adjustment-fatigue-level">
                        疲劳程度
                        <select
                          id="execution-adjustment-fatigue-level"
                          disabled={isParsingAdjustment || isConfirmingAdjustment}
                          onChange={(event) => {
                            setAdjustmentFatigueLevel(event.target.value as FatigueLevel | '')
                            setPendingAdjustmentEvent(null)
                          }}
                          value={adjustmentFatigueLevel}
                        >
                          <option value="">请选择</option>
                          <option value="MILD">轻度</option>
                          <option value="MODERATE">中度</option>
                          <option value="SEVERE">重度</option>
                        </select>
                      </label>
                    )}
                    <button
                      className="button button--primary"
                      disabled={
                        isConfirmingAdjustment ||
                        isParsingAdjustment ||
                        Boolean(adjustmentBlockReason) ||
                        !hasAdjustableSuffix ||
                        !adjustmentDetailsComplete
                      }
                      onClick={() => void confirmExecutionAdjustment()}
                      type="button"
                    >
                      {isConfirmingAdjustment
                        ? <LoaderCircle className="spin-icon" size={15} />
                        : <Check size={15} />}
                      {isConfirmingAdjustment ? '正在重新计算后续安排…' : '确认并生成 Plan V2 预览'}
                    </button>
                  </div>
                )}
                </>}
                {executionNotice && <p><CheckCircle2 size={14} /> {executionNotice}</p>}
                {planLifecycleError && <p className="media-error">{planLifecycleError}</p>}
              </section>

              <section className="execution-rules-card">
                <h3>执行保护规则</h3>
                <div><Check size={16} /><span><strong>完成项保持不变</strong><small>已发生的行程不会被重写</small></span></div>
                <div><Check size={16} /><span><strong>确认后才更新</strong><small>候选 V2 接受前不会覆盖当前计划</small></span></div>
                <div><Check size={16} /><span><strong>事件和金额可追溯</strong><small>每条记录绑定具体任务</small></span></div>
              </section>
            </aside>
          </section>
        )}

        {view === 'summary' && (
          <section className="summary-stage motion-enter">
            <div className="summary-hero">
              <span className="summary-icon"><BadgeCheck size={34} /></span>
              <span className="section-kicker">JOURNEY COMPLETE</span>
              <h2>今天，你和{planningDraft?.cityName ?? activePlan.cityName}认真地见了一面。</h2>
              <p>行程已经结束。以下数字和版本历史均来自服务端总结。</p>
            </div>
            {summaryView?.visibleSections.includes('metrics') && <div className="summary-metrics">
              <article><span>任务完成</span><strong>{summaryView ? summaryView.completion.completed : '—'}<small>{summaryView ? `/${summaryView.completion.total}` : ''}</small></strong><i style={{ width: `${summaryView?.completion.progressPercent ?? 0}%` }} /></article>
              <article><span>实际花费</span><strong>{summaryView?.cost.actual ?? '—'}</strong><small>{summaryView?.cost.detail ?? '等待服务端总结'}</small></article>
              <article><span>事件记录</span><strong>{summaryView?.eventCount ?? '—'}</strong><small>服务端事件流</small></article>
              <article><span>最终版本</span><strong>{summaryView?.version.current ?? '—'}</strong><small>{summaryView ? `${summaryView.version.historyCount} 个版本可追溯` : '等待服务端总结'}</small></article>
            </div>}
            {summaryView?.visibleSections.includes('history') && summary && (
              <div className="summary-history">
                <div className="panel-heading">
                  <div><span className="section-kicker">PLAN HISTORY</span><h2>版本变化</h2></div>
                </div>
                {summary.planHistory.map((item) => (
                  <div className="summary-history__row" key={item.planId}>
                    <span>Plan V{item.version}</span>
                    <strong>{item.status}</strong>
                    <small>{item.reason}</small>
                  </div>
                ))}
              </div>
            )}
            <MemoryTimelinePanel
              tripId={tripId}
              tasks={activePlan.tasks.map((task) => ({
                id: task.id,
                order: task.order,
                title: task.title,
              }))}
            />
          </section>
        )}
      </main>
    </AppShell>
  )
}
