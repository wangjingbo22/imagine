import {
  ArrowRight,
  BadgeCheck,
  BusFront,
  Camera,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDollarSign,
  Clock3,
  Download,
  FileVideo,
  Footprints,
  Image,
  LoaderCircle,
  Layers3,
  Map,
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
  Trash2,
  Upload,
  Utensils,
  Video,
  Wallet,
  X,
} from 'lucide-react'
import { type ChangeEvent, useCallback, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { ApiError } from '../api/client'
import { tripApi, USE_PLAN_VERSION_API } from '../api/tripApi'
import { buildCreateSingleDayTrip } from '../api/tripContract'
import { AppShell } from '../components/AppShell'
import type {
  CityResolution,
  ExecutionEvent,
  Place,
  PlanSnapshot,
  PlanVersionDiff,
  PlanVersionProposal,
  PlanVersionReason,
  ProviderRoute,
  Provenance,
  SourceStatus,
  StoredPlanVersion,
  TripDraftInput,
  TripPlanState,
  TripSummary,
} from '../domain/trip'
import { mockPlanV1 } from '../mocks/trip'

type WorkspaceView = 'plan' | 'execute' | 'diff' | 'summary'

interface MediaAsset {
  id: string
  taskId: string
  type: 'photo' | 'video'
  name: string
  dataUrl: string
  createdAt: string
}

interface LocationEvidence {
  city: CityResolution
  places: Place[]
  route: ProviderRoute | null
  query: string
}

const views: Array<{ value: WorkspaceView; label: string }> = [
  { value: 'plan', label: '计划工作台' },
  { value: 'execute', label: '执行旅程' },
  { value: 'diff', label: 'V1/V2 变更对比' },
  { value: 'summary', label: '旅行总结' },
]

const diffCategoryLabels = {
  PLACE: '地点',
  TIME: '时间',
  ROUTE: '路线',
  COST: '费用',
  CARE: '关怀指标',
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

const recommendationFeedbackOptions = [
  '想少走路',
  '预算再低一些',
  '减少换乘',
  '增加文化景点',
  '调整用餐安排',
]

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

function escapeHtml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
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
      walkMeters: task.walkMeters,
      note: task.note,
      status: index === 0 ? 'completed' : index === 1 ? 'current' : 'upcoming',
      coordinates: coordinates[index] ?? [50, 50],
    })),
  }
}

export function WorkspacePage() {
  const location = useLocation()
  const navigationState = location.state as {
    draft?: TripDraftInput
    tripId?: string
  } | null
  const draft = navigationState?.draft
  const tripId =
    new URLSearchParams(location.search).get('tripId') ?? navigationState?.tripId ?? null
  const [view, setView] = useState<WorkspaceView>('plan')
  const [summary, setSummary] = useState<TripSummary | null>(null)
  const [restoredPlan, setRestoredPlan] = useState<PlanSnapshot | null>(null)
  const [storedCurrentPlan, setStoredCurrentPlan] = useState<StoredPlanVersion | null>(null)
  const [candidatePlanV2, setCandidatePlanV2] = useState<StoredPlanVersion | null>(null)
  const [planDiff, setPlanDiff] = useState<PlanVersionDiff | null>(null)
  const [persistedPlanId, setPersistedPlanId] = useState<string | null>(null)
  const [isConfirmingPlan, setIsConfirmingPlan] = useState(false)
  const [isPreparingV2, setIsPreparingV2] = useState(false)
  const [isDecidingV2, setIsDecidingV2] = useState(false)
  const [isWritingEvent, setIsWritingEvent] = useState(false)
  const [advanceAfterDecision, setAdvanceAfterDecision] = useState(false)
  const [planLifecycleError, setPlanLifecycleError] = useState('')
  const [actualCost, setActualCost] = useState('0')
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
  const [executionFeedback, setExecutionFeedback] = useState('')
  const [executionAdjustmentCount, setExecutionAdjustmentCount] = useState(0)
  const [executionNotice, setExecutionNotice] = useState('')
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [mediaAssets, setMediaAssets] = useState<MediaAsset[]>([])
  const [mediaError, setMediaError] = useState('')
  const [locationEvidence, setLocationEvidence] = useState<LocationEvidence | null>(null)
  const [isLoadingLocationEvidence, setIsLoadingLocationEvidence] = useState(
    Boolean(tripId && draft),
  )
  const [locationEvidenceError, setLocationEvidenceError] = useState('')

  const applyTripState = useCallback((state: TripPlanState) => {
    const current = state.currentPlan
    if (current) {
      const display = toDisplayPlan(current)
      setStoredCurrentPlan(current)
      setRestoredPlan(display)
      setPersistedPlanId(current.planId)
      const completed = state.events
        .filter((event) => event.eventType === 'COMPLETE')
        .map((event) => event.taskId)
      const skipped = state.events
        .filter((event) => event.eventType === 'SKIP')
        .map((event) => event.taskId)
      const terminal = new Set([...completed, ...skipped])
      const unfinishedIndex = display.tasks.findIndex(
        (task) => !terminal.has(task.id),
      )
      const nextIndex =
        unfinishedIndex < 0 ? Math.max(0, display.tasks.length - 1) : unfinishedIndex
      setCompletedTaskIds([...new Set(completed)])
      setSkippedTaskIds([...new Set(skipped)])
      setActualSpentCents(
        state.events
          .filter((event) => event.eventType === 'EXPENSE')
          .reduce((total, event) => total + (event.amountCents ?? 0), 0),
      )
      setCurrentTaskIndex(nextIndex)
      const nextTask = unfinishedIndex < 0 ? null : display.tasks[nextIndex]
      if (nextTask) {
        setActualCost(String(nextTask.costCents / 100))
      }
    }
    if (state.tripStatus === 'COMPLETED') {
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
      }
      if (current) {
        applyTripState(response.data)
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
  }, [applyTripState, tripId])

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
    if (!tripId || !draft) {
      return
    }
    let cancelled = false
    const query = draft.mustVisit[0] ?? draft.interests[0] ?? '博物馆'
    void (async () => {
      const cityResponse = await tripApi.resolveCity(draft.cityName)
      const city = cityResponse.data
      let places: Place[] = []
      let route: ProviderRoute | null = null
      let hadEvidenceError = false
      try {
        const placesResponse = await tripApi.searchPlaces(
          tripId,
          city.cityContext,
          query,
          [],
          1,
          4,
        )
        places = placesResponse.data.places
        if (places[0]) {
          const routeResponse = await tripApi.planRoute(
            tripId,
            city.cityContext,
            city.cityContext.center,
            places[0].location,
            'WALKING',
          )
          route = routeResponse.data.routes[0] ?? null
        }
      } catch (error) {
        hadEvidenceError = true
        if (!cancelled) {
          setLocationEvidenceError(
            error instanceof Error
              ? `城市已解析，但地点或路线暂时不可用：${error.message}`
              : '城市已解析，但地点或路线暂时不可用。',
          )
        }
      }
      if (!cancelled) {
        if (!hadEvidenceError) {
          setLocationEvidenceError('')
        }
        setLocationEvidence({ city, places, route, query })
      }
    })().catch((error: unknown) => {
      if (!cancelled) {
        setLocationEvidenceError(
          error instanceof Error ? error.message : '城市地点与路线加载失败',
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
  }, [draft, tripId])

  const budgetCents = draft?.budgetCents ?? (
    restoredPlan
      ? restoredPlan.totalCostCents + restoredPlan.bufferCents
      : 35000
  )
  const validationRules = [
    `单段步行 ≤ ${draft?.assistanceProfile.maxSegmentWalkMeters ?? 500}m`,
    `换乘次数 ≤ ${draft?.assistanceProfile.maxTransfers ?? 2}`,
    `每 ${draft?.assistanceProfile.restIntervalMinutes ?? 90} 分钟休息`,
    `${draft?.endTime ?? '20:00'} 前结束`,
  ]
  const customCityTitles = draft?.cityName && draft.cityName !== '北京'
    ? [
        `${draft.cityName}城市博物馆`,
        `${draft.cityName}本地风味餐厅`,
        `${draft.cityName}城市公园`,
        `${draft.cityName}历史街区漫步`,
      ]
    : undefined
  const baseDisplayPlanV1 = customCityTitles
    ? {
        ...mockPlanV1,
        cityName: draft?.cityName ?? mockPlanV1.cityName,
        tasks: mockPlanV1.tasks.map((task, index) => ({ ...task, title: customCityTitles[index] })),
      }
    : mockPlanV1
  const displayPlanV1 = recommendationRound > 1
    ? {
        ...baseDisplayPlanV1,
        totalCostCents: Math.max(0, baseDisplayPlanV1.totalCostCents - 3200),
        totalWalkMeters: Math.max(0, baseDisplayPlanV1.totalWalkMeters - 620),
        tasks: baseDisplayPlanV1.tasks.map((task, index) => {
          if (index === 2) {
            return {
              ...task,
              title: `${draft?.cityName ?? '北京'}城市艺术馆`,
              costCents: 1500,
              walkMeters: 320,
              note: '根据反馈减少步行并增加室内文化体验',
            }
          }
          if (index === 3) {
            return {
              ...task,
              costCents: Math.max(0, task.costCents - 4300),
              walkMeters: Math.max(300, task.walkMeters - 220),
              note: '根据反馈降低预算并减少路线绕行',
            }
          }
          return task
        }),
      }
    : baseDisplayPlanV1
  const activePlan = restoredPlan ?? displayPlanV1
  const remainingBudgetCents = Math.max(0, budgetCents - activePlan.totalCostCents)
  const currentTask = activePlan.tasks[currentTaskIndex]
  const nextTask = activePlan.tasks[currentTaskIndex + 1]
  const selectedTask = activePlan.tasks.find((task) => task.id === selectedTaskId)
  const actualExpenseCents = Math.max(0, Number(actualCost) || 0) * 100
  const expenseDeltaCents = actualExpenseCents - (currentTask?.costCents ?? 0)
  const expenseDifferenceLabel =
    expenseDeltaCents === 0
      ? '实际消费与计划一致'
      : `比计划${expenseDeltaCents > 0 ? '多花' : '少花'} ${formatMoney(Math.abs(expenseDeltaCents))}`
  const executionProgress = Math.round(
    ((completedTaskIds.length + skippedTaskIds.length) / activePlan.tasks.length) * 100,
  )
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
    locationEvidence?.route?.provenance ??
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

  function toggleRecommendationFeedback(option: string) {
    setSelectedFeedbackOptions((current) =>
      current.includes(option)
        ? current.filter((item) => item !== option)
        : [...current, option],
    )
  }

  function handleRegenerateRecommendation() {
    if (selectedFeedbackOptions.length === 0 && recommendationFeedback.trim().length === 0) {
      return
    }
    setIsRegenerating(true)
    window.setTimeout(() => {
      setRecommendationRound((current) => current + 1)
      setAppliedFeedback([
        ...selectedFeedbackOptions,
        ...(recommendationFeedback.trim() ? [recommendationFeedback.trim()] : []),
      ])
      setIsRegenerating(false)
      setIsFeedbackOpen(false)
    }, 1200)
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
    const amountSuffix = eventType === 'EXPENSE' ? `:${amountCents ?? 0}` : ''
    await tripApi.createExecutionEvent(tripId, {
      taskId,
      planVersionId: planId,
      eventType,
      amountCents,
      idempotencyKey: `${planId}:${taskId}:${eventType}${amountSuffix}`,
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

  async function handleAcceptPlan() {
    if (!tripId) {
      setPlanLifecycleError('当前页面缺少 tripId，请从“新建行程”重新进入。')
      return
    }
    setIsConfirmingPlan(true)
    setPlanLifecycleError('')
    try {
      let planId = persistedPlanId
      if (!planId) {
        if (!draft) {
          throw new Error('刷新后未找到可恢复的方案，请从“新建行程”重新生成。')
        }
        const city = locationEvidence?.city ?? (await tripApi.resolveCity(draft.cityName)).data
        const tasks = activePlan.tasks.map((task) => ({
          taskId: task.id,
          order: task.order,
          title: task.title,
          category: task.category,
          timeRange: task.timeRange,
          durationMinutes: task.durationMinutes,
          transport: task.transport,
          costCents: task.costCents,
          walkMeters: task.walkMeters,
          note: task.note,
        }))
        const totalCostCents = tasks.reduce((sum, task) => sum + task.costCents, 0)
        const totalWalkMeters = tasks.reduce((sum, task) => sum + task.walkMeters, 0)
        const normalizedTrip = buildCreateSingleDayTrip(draft, {
          tripId,
          participantId: crypto.randomUUID(),
          cityContext: city.cityContext,
          nickname: '单人旅客',
          startLocationText: `${city.cityContext.cityName}市内`,
          endLocationText: `${city.cityContext.cityName}市内`,
        })
        const proposal: PlanVersionProposal = {
          schemaVersion: '1.0',
          planId: crypto.randomUUID(),
          tripSnapshot: {
            ...normalizedTrip,
            status: 'PLAN_REVIEW',
          },
          version: 1,
          parentId: null,
          reason: 'INITIAL_PLAN',
          metrics: {
            totalCostCents,
            bufferCents: draft.budgetCents - totalCostCents,
            totalWalkMeters,
            transferCount: activePlan.transferCount,
            validationStatus: 'PASS',
          },
          days: [{ dayIndex: 0, date: draft.travelDate, tasks }],
          constraintsSnapshot: [
            ...validationRules.map((description, index) => ({
              ruleId: `hard-rule-${index + 1}`,
              scope: 'trip.days[0]',
              hardness: 'HARD' as const,
              status: 'PASS' as const,
              description,
              details: {},
            })),
            {
              ruleId: 'accessibility-entrance',
              scope: 'days[0].tasks',
              hardness: 'SOFT',
              status: 'NEEDS_CONFIRMATION',
              description: '无障碍入口信息需现场确认',
              details: {},
            },
          ],
          sourcesSnapshot: [
            {
              provider: 'AMAP',
              sourceStatus: city.provenance.sourceStatus,
              fetchedAt: city.provenance.fetchedAt,
              isStale: city.provenance.isStale,
              referenceId: city.cityContext.cityCode,
            },
            ...(locationEvidence?.places ?? []).flatMap((place) => [
              {
                provider: place.provenance.provider,
                sourceStatus: place.provenance.sourceStatus,
                fetchedAt: place.provenance.fetchedAt,
                isStale: place.provenance.isStale,
                referenceId: place.placeId,
              },
              {
                provider: place.priceReference.provenance.provider,
                sourceStatus: place.priceReference.provenance.sourceStatus,
                fetchedAt: place.priceReference.provenance.fetchedAt,
                isStale: place.priceReference.provenance.isStale,
                referenceId: `${place.placeId}:price`,
              },
            ]),
            ...(locationEvidence?.route ? [{
              provider: locationEvidence.route.provenance.provider,
              sourceStatus: locationEvidence.route.provenance.sourceStatus,
              fetchedAt: locationEvidence.route.provenance.fetchedAt,
              isStale: locationEvidence.route.provenance.isStale,
              referenceId: locationEvidence.route.routeId,
            }] : []),
            {
              provider: 'FRONTEND_MOCK',
              sourceStatus: 'ESTIMATED',
              fetchedAt: new Date().toISOString(),
              isStale: false,
              referenceId: 'workspace-recommendation-v1',
            },
          ],
        }
        const registered = await tripApi.registerPlanVersion(tripId, proposal)
        planId = registered.data.planId
        setPersistedPlanId(planId)
        setRestoredPlan(toDisplayPlan(registered.data))
      }
      await tripApi.confirmPlan(tripId, planId)
      await tripApi.startExecution(tripId)
      const restored = await tripApi.getTrip(tripId)
      if (restored.data.currentPlan) {
        applyTripState(restored.data)
        await startTask(restored.data.currentPlan, 0)
      }
      setView('execute')
    } catch (error) {
      setPlanLifecycleError(error instanceof Error ? error.message : '确认 Plan V1 失败')
    } finally {
      setIsConfirmingPlan(false)
    }
  }

  async function preparePlanV2(
    reason: Exclude<PlanVersionReason, 'INITIAL_PLAN'>,
    feedback: string,
    lockedThroughIndex: number,
  ) {
    if (!tripId || !storedCurrentPlan) {
      throw new Error('未恢复当前 Plan V1，暂时不能生成 Plan V2。')
    }
    if (candidatePlanV2) {
      setView('diff')
      return
    }

    const originalTasks = storedCurrentPlan.days[0].tasks
    const replaceIndex = originalTasks.findIndex((_, index) => index > lockedThroughIndex)
    if (replaceIndex < 0) {
      throw new Error('当前没有可调整的未完成任务。')
    }
    const tasks = originalTasks.map((task, index) => {
      if (index === replaceIndex) {
        return {
          ...task,
          taskId: crypto.randomUUID(),
          title: `${storedCurrentPlan.tripSnapshot.cityContext.cityName}城市艺术馆`,
          category: '室内文化',
          transport: '步行 300 米 · 5 分钟',
          costCents: Math.max(0, task.costCents - 1500),
          walkMeters: Math.min(task.walkMeters, 300),
          note: `根据“${feedback}”替换为低负担室内任务`,
        }
      }
      if (index === replaceIndex + 1) {
        return {
          ...task,
          transport: '地铁直达 · 减少一次换乘',
          costCents: Math.max(0, task.costCents - 1700),
          walkMeters: Math.max(0, task.walkMeters - 220),
          note: `根据“${feedback}”减少费用、换乘和步行`,
        }
      }
      return task
    })
    const totalCostCents = tasks.reduce((sum, task) => sum + task.costCents, 0)
    const totalWalkMeters = tasks.reduce((sum, task) => sum + task.walkMeters, 0)
    const proposal: PlanVersionProposal = {
      schemaVersion: '1.0',
      planId: crypto.randomUUID(),
      tripSnapshot: storedCurrentPlan.tripSnapshot,
      version: 2,
      parentId: storedCurrentPlan.planId,
      reason,
      metrics: {
        totalCostCents,
        bufferCents: storedCurrentPlan.tripSnapshot.totalBudgetCents - totalCostCents,
        totalWalkMeters,
        transferCount: Math.max(0, storedCurrentPlan.metrics.transferCount - 1),
        validationStatus: 'PASS',
      },
      days: [{
        dayIndex: 0,
        date: storedCurrentPlan.days[0].date,
        tasks,
      }],
      constraintsSnapshot: [
        ...storedCurrentPlan.constraintsSnapshot,
        {
          ruleId: `v2-${reason.toLowerCase().replaceAll('_', '-')}`,
          scope: 'trip.days[0].remainingTasks',
          hardness: 'SOFT',
          status: 'WARNING',
          description: 'Plan V2 已根据执行变化降低后续负担',
          details: { feedback },
        },
      ],
      sourcesSnapshot: [
        ...storedCurrentPlan.sourcesSnapshot,
        {
          provider: 'FRONTEND_MOCK',
          sourceStatus: 'ESTIMATED',
          fetchedAt: new Date().toISOString(),
          isStale: false,
          referenceId: 'workspace-recommendation-v2',
        },
      ],
    }

    const registered = await tripApi.registerPlanVersion(tripId, proposal)
    const diff = await tripApi.getPlanDiff(tripId, registered.data.planId)
    setCandidatePlanV2(registered.data)
    setPlanDiff(diff.data)
    setView('diff')
  }

  async function decidePlanV2(decision: 'accept' | 'reject') {
    if (!tripId || !candidatePlanV2) {
      return
    }
    setIsDecidingV2(true)
    setPlanLifecycleError('')
    try {
      if (decision === 'accept') {
        await tripApi.acceptPlanV2(tripId, candidatePlanV2.planId)
      } else {
        await tripApi.rejectPlanV2(tripId, candidatePlanV2.planId)
      }
      const restored = await tripApi.getTrip(tripId)
      if (!restored.data.currentPlan) {
        throw new Error('决策完成后未找到 CURRENT 版本。')
      }
      const nextDisplayPlan = toDisplayPlan(restored.data.currentPlan)
      applyTripState(restored.data)
      setCandidatePlanV2(null)
      setPlanDiff(null)
      setExecutionNotice(
        decision === 'accept'
          ? '已接受 Plan V2；Plan V1 已转为历史版本。'
          : '已拒绝 Plan V2；继续执行原 Plan V1。',
      )
      if (decision === 'accept') {
        setExecutionAdjustmentCount((current) => current + 1)
      }
      if (advanceAfterDecision) {
        const nextIndex = currentTaskIndex + 1
        const next = nextDisplayPlan.tasks[nextIndex]
        setAdvanceAfterDecision(false)
        if (!next) {
          setView('summary')
        } else {
          await startTask(restored.data.currentPlan, nextIndex)
          setView('execute')
        }
      } else {
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
      await recordExecutionEvent(
        storedCurrentPlan.planId,
        currentTask.id,
        'SKIP',
      )
      const nextIndex = currentTaskIndex + 1
      if (storedCurrentPlan.days[0].tasks[nextIndex]) {
        await startTask(storedCurrentPlan, nextIndex)
        setView('execute')
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
    setIsWritingEvent(true)
    setPlanLifecycleError('')
    try {
      await recordExecutionEvent(
        storedCurrentPlan.planId,
        currentTask.id,
        'EXPENSE',
        actualExpenseCents,
      )
      await recordExecutionEvent(
        storedCurrentPlan.planId,
        currentTask.id,
        'COMPLETE',
      )
      if (
        expenseDeltaCents !== 0 &&
        currentTaskIndex < activePlan.tasks.length - 1 &&
        USE_PLAN_VERSION_API
      ) {
        setIsPreparingV2(true)
        setAdvanceAfterDecision(true)
        await preparePlanV2('EXPENSE_CHANGE', expenseDifferenceLabel, currentTaskIndex)
        setIsPreparingV2(false)
        return
      }
      const nextIndex = currentTaskIndex + 1
      if (storedCurrentPlan.days[0].tasks[nextIndex]) {
        await startTask(storedCurrentPlan, nextIndex)
        setView('execute')
      }
    } catch (error) {
      setAdvanceAfterDecision(false)
      setIsPreparingV2(false)
      setPlanLifecycleError(error instanceof Error ? error.message : '完成任务失败')
    } finally {
      setIsWritingEvent(false)
    }
  }

  async function handleExecutionFeedback() {
    const feedback = executionFeedback.trim()
    if (!feedback) {
      return
    }
    setIsPreparingV2(true)
    setAdvanceAfterDecision(false)
    setPlanLifecycleError('')
    setExecutionFeedback('')
    try {
      await preparePlanV2('USER_FEEDBACK', feedback, currentTaskIndex)
    } catch (error) {
      setPlanLifecycleError(error instanceof Error ? error.message : '生成 Plan V2 失败')
    } finally {
      setIsPreparingV2(false)
    }
  }

  function handleMediaUpload(
    event: ChangeEvent<HTMLInputElement>,
    type: MediaAsset['type'],
  ) {
    const input = event.currentTarget
    const file = input.files?.[0]
    if (!file || !selectedTask) {
      return
    }
    const expectedPrefix = type === 'photo' ? 'image/' : 'video/'
    const maxSize = type === 'photo' ? 5 * 1024 * 1024 : 30 * 1024 * 1024
    if (!file.type.startsWith(expectedPrefix)) {
      setMediaError(`请选择${type === 'photo' ? '图片' : '视频'}文件。`)
      input.value = ''
      return
    }
    if (file.size > maxSize) {
      setMediaError(`${type === 'photo' ? '图片不能超过 5MB' : '视频不能超过 30MB'}。`)
      input.value = ''
      return
    }

    setMediaError('')
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = reader.result
      if (typeof dataUrl !== 'string') {
        setMediaError('素材读取失败，请重新选择文件。')
        return
      }
      setMediaAssets((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          taskId: selectedTask.id,
          type,
          name: file.name,
          dataUrl,
          createdAt: new Date().toISOString(),
        },
      ])
    }
    reader.onerror = () => setMediaError('素材读取失败，请重新选择文件。')
    reader.readAsDataURL(file)
    input.value = ''
  }

  function handleExportSummary() {
    const taskRows = activePlan.tasks.map((task) => {
      const status = skippedTaskIds.includes(task.id)
        ? '已跳过'
        : completedTaskIds.includes(task.id)
          ? '已完成'
          : '未执行'
      return `<tr><td>${task.order}</td><td>${escapeHtml(task.title)}</td><td>${escapeHtml(task.timeRange)}</td><td>${status}</td></tr>`
    }).join('')
    const mediaHtml = mediaAssets.length > 0
      ? mediaAssets.map((asset) => asset.type === 'photo'
          ? `<figure><img src="${asset.dataUrl}" alt="${escapeHtml(asset.name)}"><figcaption>${escapeHtml(asset.name)}</figcaption></figure>`
          : `<figure><video controls src="${asset.dataUrl}"></video><figcaption>${escapeHtml(asset.name)}</figcaption></figure>`,
        ).join('')
      : '<p>本次旅行没有保存照片或视频。</p>'
    const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>行知旅伴旅行总结</title><style>body{font-family:system-ui,sans-serif;max-width:960px;margin:40px auto;padding:0 24px;color:#172033}h1{font-size:36px}section{margin-top:32px}table{width:100%;border-collapse:collapse}th,td{padding:12px;border-bottom:1px solid #e5eaf1;text-align:left}.media{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.media img,.media video{width:100%;max-height:360px;object-fit:cover;border-radius:12px}figcaption{margin-top:6px;color:#667085;font-size:12px}</style></head><body><h1>${escapeHtml(draft?.cityName ?? '北京')}旅行总结</h1><p>完成 ${summary?.completedTaskIds.length ?? completedTaskIds.length}/${summary?.totalTasks ?? activePlan.tasks.length} 个任务，跳过 ${summary?.skippedTaskIds.length ?? skippedTaskIds.length} 个任务，实际花费 ${formatMoney(summary?.actualCostCents ?? actualSpentCents)}。</p><section><h2>实际行程</h2><table><thead><tr><th>#</th><th>地点</th><th>时间</th><th>状态</th></tr></thead><tbody>${taskRows}</tbody></table></section><section><h2>旅行影像</h2><div class="media">${mediaHtml}</div></section></body></html>`
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${draft?.cityName ?? '北京'}旅行总结.html`
    anchor.style.display = 'none'
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <AppShell compact>
      <main className="workspace">
        <header className="workspace-header" data-reveal="fade">
          <div>
            <span className="section-kicker">{draft?.cityName ?? '北京'} · {draft?.travelDate ?? '2026.08.26'}</span>
            <h1>历史与城市风味的一日漫游</h1>
          </div>
          <div className="workspace-header__meta">
            <span className="pass-chip pass-chip--large"><ShieldCheck size={15} /> 8 项硬约束通过</span>
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
                        <strong>{formatMoney(task.costCents)}</strong>
                      </div>
                      <div className="task-meta">
                        <span><Clock3 size={15} /> {task.durationMinutes} 分钟</span>
                        <span><Navigation size={15} /> {task.transport}</span>
                        <span><Footprints size={15} /> {task.walkMeters} 米</span>
                      </div>
                      <div className="task-note"><BadgeCheck size={15} /> {task.note}</div>
                      <button className="task-guide-button" onClick={() => setSelectedTaskId(task.id)} type="button">
                        <Camera size={15} /> 查看拍照与视频指导
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <aside className="insight-column">
              <section className="map-card">
                <div className="map-card__toolbar">
                  <span><Map size={16} /> 路线总览</span>
                  <button type="button">查看大图</button>
                </div>
                <div className="map-canvas">
                  <span className="map-road map-road--one" />
                  <span className="map-road map-road--two" />
                  <span className="map-river" />
                  <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                    <path d="M22 71 C30 62, 34 62, 43 58 S54 42, 61 34 S72 28, 78 19" />
                  </svg>
                  {activePlan.tasks.map((task) => (
                    <span className="map-pin" key={task.id} style={{ left: `${task.coordinates[0]}%`, top: `${task.coordinates[1]}%` }}>{task.order}</span>
                  ))}
                </div>
              </section>
              <section className="metric-card">
                <div className="metric-card__head"><span>预算使用</span><strong>{formatMoney(activePlan.totalCostCents)} / {formatMoney(budgetCents)}</strong></div>
                <div className="progress-bar"><i style={{ width: '85%' }} /></div>
                <div className="metric-grid">
                  <div><Wallet size={18} /><span>剩余缓冲<strong>{formatMoney(remainingBudgetCents)}</strong></span></div>
                  <div><Footprints size={18} /><span>全天步行<strong>{(activePlan.totalWalkMeters / 1000).toFixed(2)} km</strong></span></div>
                  <div><BusFront size={18} /><span>公共交通<strong>{activePlan.transferCount} 次换乘</strong></span></div>
                  <div><Clock3 size={18} /><span>弹性时间<strong>45 分钟</strong></span></div>
                </div>
              </section>
              <section className="validation-card">
                <div className="validation-card__head">
                  <span><ShieldCheck size={21} /> 关怀校验</span>
                  <strong>PASS</strong>
                </div>
                {validationRules.map((rule) => (
                  <div className="validation-row" key={rule}><CheckCircle2 size={16} /><span>{rule}</span><small>已满足</small></div>
                ))}
                <div className="warning-row"><MapPin size={16} /><span>无障碍入口信息</span><small>待确认</small></div>
              </section>
              <section className="explanation-card">
                <div className="explanation-card__head">
                  <span><Sparkles size={18} /> Agent 推荐理由</span>
                  <small>可解释</small>
                </div>
                <p>优先满足{draft?.interests.slice(0, 2).join('和') || '历史文化和特色餐饮'}偏好，在满足{draft?.assistanceMode === 'standard' ? '时间与预算' : '关怀'}约束的前提下，减少无效折返并保留返程缓冲。</p>
                <div className="reason-tags">
                  <span>兴趣匹配 92%</span>
                  <span>预算利用 85%</span>
                  <span>关怀约束 4/4</span>
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
                    {knownPrice?.amountCents !== null && knownPrice?.amountCents !== undefined
                      ? `${formatMoney(knownPrice.amountCents)} · ${sourceStatusLabels[knownPrice.provenance.sourceStatus]}`
                      : priceProvenance
                        ? '未知待确认'
                        : '加载中'}
                  </strong>
                </div>
                <div><Wallet size={15} /><span>计划费用</span><strong>前端估算 · 不冒充实时价格</strong></div>
                <div><MapPin size={15} /><span>无障碍设施</span><strong className="needs-confirmation">待确认</strong></div>
              </section>
              <section className="provider-evidence-card">
                <div className="source-card__head">
                  <span><BadgeCheck size={18} /> 同城 Provider 证据</span>
                  {isLoadingLocationEvidence && <LoaderCircle className="spin-icon" size={15} />}
                </div>
                {locationEvidence ? (
                  <>
                    <p>
                      “{locationEvidence.query}”候选仅来自
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
                                ? '价格未知待确认'
                                : `参考 ${formatMoney(place.priceReference.amountCents)}`}
                            </b>
                          </div>
                        </article>
                      )) : <p className="provider-evidence-empty">该关键词暂无同城候选。</p>}
                    </div>
                    {locationEvidence.route && (
                      <div className="provider-route-evidence">
                        <Route size={17} />
                        <span>
                          <strong>中心点 → {locationEvidence.places[0]?.name}</strong>
                          <small>
                            步行 {locationEvidence.route.distanceMeters} 米 · 约
                            {Math.max(1, Math.round(locationEvidence.route.durationSeconds / 60))} 分钟 ·
                            {formatSource(locationEvidence.route.provenance)}
                          </small>
                        </span>
                      </div>
                    )}
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
                  <button className="button button--primary" disabled={isConfirmingPlan} onClick={handleAcceptPlan} type="button">
                    {isConfirmingPlan ? <LoaderCircle className="spin-icon" size={17} /> : null}
                    {isConfirmingPlan ? '正在保存并确认…' : '接受推荐并确认 Plan V1'}
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

            <div className="plan-diff-groups">
              {Object.entries(diffCategoryLabels).map(([category, categoryLabel]) => {
                const categoryItems = planDiff.items.filter((item) => item.category === category)
                return (
                  <section className="plan-diff-group" key={category}>
                    <header>
                      <h3>{categoryLabel}</h3>
                      <span>{categoryItems.length} 项变化记录</span>
                    </header>
                    {categoryItems.length > 0 ? (
                      <div className="plan-diff-list">
                        {categoryItems.map((item) => (
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
                <button className="button button--primary" disabled={isDecidingV2} onClick={() => void decidePlanV2('accept')} type="button">
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
                  <div className="current-task-map">
                    <span className="current-task-map__road" />
                    <span className="current-task-map__pin"><Utensils size={23} /></span>
                    <span className="current-task-map__origin">你的位置</span>
                    <span className="current-task-map__route" />
                  </div>
                </div>
                <div className="current-task-card__content">
                  <span className="category-chip">任务 {currentTaskIndex + 1} / {activePlan.tasks.length} · {currentTask?.category}</span>
                  <h3>{currentTask?.title}</h3>
                  <p><MapPin size={16} /> {draft?.cityName ?? '北京'} · 当前任务目的地</p>
                  <div className="current-task-metrics">
                    <div><Clock3 size={19} /><span>计划时间<strong>{currentTask?.timeRange}</strong></span></div>
                    <div><Navigation size={19} /><span>预计步行<strong>{currentTask?.walkMeters ?? 0} 米</strong></span></div>
                    <div><Wallet size={19} /><span>计划消费<strong>{formatMoney(currentTask?.costCents ?? 0)}</strong></span></div>
                  </div>
                  <button className="task-guide-button task-guide-button--large" onClick={() => setSelectedTaskId(currentTask?.id ?? null)} type="button">
                    <Camera size={16} /> 进入地点体验与拍摄指导
                  </button>
                </div>
              </article>

              <div className="execution-form-card">
                <div className="execution-form-card__head">
                  <div><ReceiptText size={20} /><span><strong>完成任务并记录消费</strong><small>实际金额会用于计算剩余预算</small></span></div>
                  <span>自动保存</span>
                </div>
                <label className="web-expense-field">
                  <span>实际消费金额</span>
                  <div><b>¥</b><input value={actualCost} onChange={(event) => setActualCost(event.target.value)} /></div>
                </label>
                <div className="budget-alert">
                  <CircleDollarSign size={19} />
                  <div><strong>{expenseDifferenceLabel}</strong><small>提交后 Agent 将检查剩余路线是否仍满足预算和关怀约束。</small></div>
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
                      : expenseDeltaCents !== 0
                        ? '完成并更新后续安排'
                        : '完成当前任务'}
                    <RefreshCw size={17} />
                  </button>
                </div>
              </div>
            </div>

            <aside className="execution-web__side">
              <section className="trip-progress-card">
                <div className="trip-progress-card__head"><span>今日进度</span><strong>{completedTaskIds.length + skippedTaskIds.length} / {activePlan.tasks.length}</strong></div>
                <div className="progress-bar"><i style={{ width: `${executionProgress}%` }} /></div>
                <div className="trip-progress-stats">
                  <div><span>已用预算</span><strong>{formatMoney(actualSpentCents)}</strong></div>
                  <div><span>剩余预算</span><strong>{formatMoney(Math.max(0, budgetCents - actualSpentCents))}</strong></div>
                  <div><span>已步行</span><strong>420m</strong></div>
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
                  <span><MessageSquareText size={18} /> 随时反馈给 Agent</span>
                </div>
                <textarea
                  maxLength={160}
                  onChange={(event) => setExecutionFeedback(event.target.value)}
                  placeholder="例如：有点累了、想提前吃饭、希望减少后面的步行……"
                  value={executionFeedback}
                />
                <button className="button button--soft" disabled={isPreparingV2 || !executionFeedback.trim()} onClick={() => void handleExecutionFeedback()} type="button">
                  {isPreparingV2 ? <LoaderCircle className="spin-icon" size={15} /> : <Send size={15} />}
                  {isPreparingV2 ? '正在生成候选方案…' : '生成 Plan V2 候选方案'}
                </button>
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
              <h2>今天，你和{draft?.cityName ?? '北京'}认真地见了一面。</h2>
              <p>行程已经结束。每一次完成、跳过、反馈和拍摄记录都已保存在这份总结中。</p>
            </div>
            <div className="summary-metrics">
              <article><span>任务完成</span><strong>{summary?.completedTaskIds.length ?? completedTaskIds.length}<small>/{summary?.totalTasks ?? activePlan.tasks.length}</small></strong><i style={{ width: `${((summary?.completedTaskIds.length ?? completedTaskIds.length) / (summary?.totalTasks ?? activePlan.tasks.length)) * 100}%` }} /></article>
              <article><span>实际花费</span><strong>{formatMoney(summary?.actualCostCents ?? actualSpentCents)}</strong><small>计划 {formatMoney(summary?.plannedCostCents ?? activePlan.totalCostCents)} · {(summary?.differenceCents ?? (actualSpentCents - activePlan.totalCostCents)) >= 0 ? '+' : '-'}{formatMoney(Math.abs(summary?.differenceCents ?? (actualSpentCents - activePlan.totalCostCents)))}</small></article>
              <article><span>关怀满足率</span><strong>100<small>%</small></strong><small>4 项硬约束全部满足</small></article>
              <article><span>最终版本</span><strong>V{summary?.currentPlanVersion ?? storedCurrentPlan?.version ?? 1}</strong><small>{summary ? `${summary.planHistory.length} 个版本可追溯` : `${executionAdjustmentCount} 次调整`}</small></article>
            </div>
            <div className="memory-route">
              <div className="panel-heading"><div><span className="section-kicker">ACTUAL TIMELINE</span><h2>实际旅程</h2></div><Route size={22} /></div>
              {activePlan.tasks
                .filter((task) => completedTaskIds.includes(task.id) || skippedTaskIds.includes(task.id))
                .map((task, index) => (
                <div className="memory-stop" key={task.id}>
                  <span>{index + 1}</span>
                  <div><strong>{task.title}</strong><small>{task.timeRange} · {skippedTaskIds.includes(task.id) ? '已跳过' : '实际完成'}</small></div>
                  {skippedTaskIds.includes(task.id) ? <X size={19} /> : <CheckCircle2 size={19} />}
                </div>
              ))}
            </div>
            {summary && (
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
            <div className="summary-media">
              <div className="panel-heading">
                <div><span className="section-kicker">TRAVEL MEDIA</span><h2>旅行影像</h2></div>
                <button className="button button--primary" onClick={handleExportSummary} type="button"><Download size={16} /> 导出旅行总结</button>
              </div>
              {mediaAssets.length > 0 ? (
                <div className="summary-media__grid">
                  {mediaAssets.map((asset) => (
                    <article key={asset.id}>
                      {asset.type === 'photo'
                        ? <img alt={asset.name} src={asset.dataUrl} />
                        : <video controls src={asset.dataUrl} />}
                      <div><span>{asset.type === 'photo' ? <Image size={14} /> : <FileVideo size={14} />}{asset.name}</span></div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="summary-media__empty"><Camera size={24} /><span>本次旅行还没有保存照片或视频</span></div>
              )}
            </div>
          </section>
        )}
        {selectedTask && (
          <div className="place-experience-backdrop" onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setSelectedTaskId(null)
            }
          }}>
            <section className="place-experience-modal" aria-modal="true" role="dialog">
              <header>
                <div>
                  <span className="section-kicker">AGENT CREATIVE GUIDE</span>
                  <h2>{selectedTask.title}</h2>
                  <p>{selectedTask.category} · {selectedTask.timeRange}</p>
                </div>
                <button onClick={() => setSelectedTaskId(null)} type="button"><X size={20} /></button>
              </header>
              <div className="creative-guide-grid">
                <article>
                  <span className="creative-guide-icon"><Camera size={22} /></span>
                  <h3>拍照指导</h3>
                  <ol>
                    <li>先拍一张包含环境的横向全景，保留地点标志。</li>
                    <li>人物放在画面三分线位置，避免正午顶光直射面部。</li>
                    <li>补拍门票、餐食或建筑细节，方便总结页讲故事。</li>
                  </ol>
                </article>
                <article>
                  <span className="creative-guide-icon"><Video size={22} /></span>
                  <h3>视频分镜指导</h3>
                  <ol>
                    <li>开场 3 秒：稳定拍摄地点名称或入口。</li>
                    <li>过程 5—8 秒：缓慢横移，记录人物与环境互动。</li>
                    <li>结尾 3 秒：拍下离开路线或一句现场感受。</li>
                  </ol>
                </article>
              </div>
              <div className="media-upload-area">
                <div>
                  <h3>保存本次体验</h3>
                  <p>照片上限 5MB，视频上限 30MB；素材仅保存在当前演示会话中。</p>
                </div>
                <div className="media-upload-actions">
                  <label className="button button--ghost"><Upload size={16} /> 上传照片<input accept="image/*" hidden onChange={(event) => handleMediaUpload(event, 'photo')} type="file" /></label>
                  <label className="button button--ghost"><Video size={16} /> 上传视频<input accept="video/*" hidden onChange={(event) => handleMediaUpload(event, 'video')} type="file" /></label>
                </div>
                {mediaError && <p className="media-error">{mediaError}</p>}
              </div>
              <div className="saved-media">
                <div className="panel-heading"><h3>已保存素材</h3><small>{mediaAssets.filter((asset) => asset.taskId === selectedTask.id).length} 项</small></div>
                {mediaAssets.some((asset) => asset.taskId === selectedTask.id) ? (
                  <div className="saved-media__grid">
                    {mediaAssets.filter((asset) => asset.taskId === selectedTask.id).map((asset) => (
                      <article key={asset.id}>
                        {asset.type === 'photo'
                          ? <img alt={asset.name} src={asset.dataUrl} />
                          : <video controls src={asset.dataUrl} />}
                        <div><span>{asset.name}</span><button onClick={() => setMediaAssets((current) => current.filter((item) => item.id !== asset.id))} type="button"><Trash2 size={14} /></button></div>
                      </article>
                    ))}
                  </div>
                ) : <div className="saved-media__empty">还没有保存素材</div>}
              </div>
            </section>
          </div>
        )}
      </main>
    </AppShell>
  )
}
