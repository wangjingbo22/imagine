import {
  ArrowRight,
  BadgeCheck,
  BrainCircuit,
  Check,
  CircleDollarSign,
  Clock3,
  Database,
  MapPinned,
  Route,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AppShell } from '../components/AppShell'
import type { CreateSingleDayTrip, TripDraftInput } from '../domain/trip'
import { loadAmapPlan, type AmapPlanResult } from '../services/amapPlan'
import { userFacingErrorMessage } from '../utils/userFacingError'

const processSteps = [
  {
    title: '理解你的真实需求',
    icon: BrainCircuit,
  },
  {
    title: '检索同城地点',
    icon: MapPinned,
  },
  {
    title: '分析路线与关怀风险',
    icon: Route,
  },
  {
    title: '计算预算和时间',
    icon: CircleDollarSign,
  },
  {
    title: '执行确定性校验',
    icon: ShieldCheck,
  },
]

const phaseDetails = {
  CITY: '正在确认本次行程的目的城市',
  PLACES: '正在检索符合偏好的同城地点',
  ROUTES: '正在规划地点之间的实际路线',
  PLAN: '正在核对预算、时间和关怀需求',
} as const

export function AgentProcessPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const navigationState = location.state as {
    tripId?: string
    draft?: TripDraftInput
    trip?: CreateSingleDayTrip
  } | null
  const tripId = navigationState?.tripId ?? null
  const draft = navigationState?.draft
  const confirmedTrip = navigationState?.trip
  const [completedSteps, setCompletedSteps] = useState(0)
  const [isPlanReady, setIsPlanReady] = useState(false)
  const [planningResult, setPlanningResult] = useState<AmapPlanResult | null>(null)
  const [planningError, setPlanningError] = useState(() => {
    if (!draft) return '缺少行程草稿，请返回新建行程页面重新提交。'
    if (!tripId || !confirmedTrip) return '行程信息不完整，请返回新建行程页面重新确认。'
    return ''
  })
  const [providerDetail, setProviderDetail] = useState('等待连接高德地图服务')
  const [retryToken, setRetryToken] = useState(0)
  const planningPromiseRef = useRef<Promise<AmapPlanResult> | null>(null)

  useEffect(() => {
    if (!draft || !tripId || !confirmedTrip) {
      return
    }
    let cancelled = false
    const phaseStep = { CITY: 0, PLACES: 1, ROUTES: 2, PLAN: 3 } as const
    const planningPromise = planningPromiseRef.current ?? loadAmapPlan(
      tripId,
      draft,
      (phase) => {
        if (cancelled) return
        setCompletedSteps(phaseStep[phase])
        setProviderDetail(phaseDetails[phase])
      },
      { confirmedTrip },
    )
    planningPromiseRef.current = planningPromise
    void planningPromise.then((result) => {
      if (cancelled) return
      setPlanningResult(result)
      setCompletedSteps(processSteps.length)
      setProviderDetail(
        result.planningIssue
          ? '地点与路线已返回，部分信息需要确认'
          : `高德返回 ${result.evidence.places.length} 个地点和 ${result.evidence.routes.length} 段路线`,
      )
      setIsPlanReady(true)
    }).catch((error: unknown) => {
      if (cancelled) return
      if (planningPromiseRef.current === planningPromise) {
        planningPromiseRef.current = null
      }
      setPlanningError(userFacingErrorMessage(error, '行程方案暂时生成失败，请稍后重试。'))
      setProviderDetail('本次生成未完成')
    })
    return () => {
      cancelled = true
    }
  }, [confirmedTrip, draft, retryToken, tripId])

  useEffect(() => {
    if (!isPlanReady || !tripId) {
      return
    }

    const redirectTimer = window.setTimeout(
      () => navigate(`/workspace?tripId=${tripId}`, {
        state: { draft, tripId, trip: confirmedTrip, amapPlanResult: planningResult },
      }),
      1200,
    )
    return () => window.clearTimeout(redirectTimer)
  }, [confirmedTrip, draft, isPlanReady, navigate, planningResult, tripId])

  const progress = useMemo(
    () => Math.round((completedSteps / processSteps.length) * 100),
    [completedSteps],
  )
  const routeConstraintDetail = draft?.assistanceMode === 'low-mobility'
    ? draft.assistanceProfile.maxSegmentWalkMeters === null
      ? '逐段检查步行距离、换乘次数与休息间隔；当前未冻结单段步行上限。'
      : `逐段检查步行距离、换乘次数与休息间隔。已确认单段步行上限 ${draft.assistanceProfile.maxSegmentWalkMeters} 米。`
    : draft?.assistanceMode === 'family'
      ? '逐段检查路线来源，并按已确认的午休时段和亲子返程规则排程。'
      : draft?.assistanceMode === 'assisted'
        ? '逐段检查路线与设施来源；楼梯规避证据未知时保持待确认。'
        : '逐段检查路线距离、换乘与来源事实；普通模式没有额外冻结步行或休息阈值。'

  const dynamicStepDetails = [
    `已识别${draft?.cityName ?? '北京'}、单日、预算 ¥${Math.round((draft?.budgetCents ?? 35000) / 100)}、${draft?.interests.join('、') ?? '历史文化、特色餐饮'}与关怀需求。`,
    `正在筛选${draft?.cityName ?? '北京'}的兴趣候选地点，并核对来源时间与同城缓存。`,
    routeConstraintDetail,
    `金额按整数分复算，并在 ¥${Math.round((draft?.budgetCents ?? 35000) / 100)} 总预算内预留交通波动与临时消费缓冲。`,
    `预算、${draft?.startTime ?? '09:00'}—${draft?.endTime ?? '20:00'} 时间窗与路线连续性全部检查，并仅执行已确认关怀画像中实际冻结的规则。`,
  ]
  const dynamicStepResults = [
    `${9 + (draft?.mustVisit.length ?? 0) + (draft?.avoidPlaces.length ?? 0)} 项结构化字段`,
    planningResult ? `${planningResult.evidence.places.length} 个高德地点` : '正在读取地点信息',
    planningResult ? `${planningResult.evidence.routes.length} 段真实路线` : '正在规划逐段路线',
    planningResult
      ? `已知费用 ¥${Math.round(planningResult.knownCostCents / 100)}，${planningResult.unknownPriceCount} 项待确认`
      : '等待价格信息',
    planningResult?.registeredPlan
      ? '服务端确定性校验通过'
      : planningResult?.planningIssue
        ? '发现未知事实，等待确认'
        : '等待服务端校验',
  ]

  return (
    <AppShell compact>
      <main className="agent-page">
        <section className="agent-page__intro" data-reveal="side">
          <span className="eyebrow"><Sparkles size={14} /> 智能行程规划</span>
          <h1>把一句愿望，变成<br />一条走得通的路线。</h1>
          <p>
            大模型负责理解和解释，确定性程序负责金额、路线与关怀约束。
            这里展示的每一步都对应一次真实的工具或规则检查。
          </p>
          <div className="agent-progress-card">
            <div>
              <span>生成进度</span>
              <strong>{progress}%</strong>
            </div>
            <div className="agent-progress-track"><i style={{ width: `${progress}%` }} /></div>
            <small>{isPlanReady ? '候选事实已处理，即将自动进入工作台' : '预计还需数秒'}</small>
          </div>
          <div className="agent-session-meta">
            <span><Database size={15} /> 城市缓存已隔离</span>
            <span><Clock3 size={15} /> {providerDetail}</span>
            <span><BadgeCheck size={15} /> 高德真实数据</span>
          </div>
          {planningError && (
            <div className="provider-retry">
              <p className="media-error">{userFacingErrorMessage(planningError, '行程方案暂时生成失败，请稍后重试。')}</p>
              <button
                className="button button--soft"
                onClick={() => {
                  setPlanningError('')
                  setCompletedSteps(0)
                  setProviderDetail('正在重新连接高德地图服务')
                  planningPromiseRef.current = null
                  setRetryToken((current) => current + 1)
                }}
                type="button"
              >
                重试高德真实数据
              </button>
            </div>
          )}
        </section>

        <section className="agent-console" data-reveal="panel">
          <div className="agent-console__header">
            <div>
              <span className="agent-console__pulse" />
              <strong>规划进度</strong>
            </div>
              <span>{isPlanReady ? '方案已生成' : '正在处理'}</span>
          </div>
          <div className="agent-step-list">
            {processSteps.map(({ title, icon: Icon }, index) => {
              const isComplete = index < completedSteps
              const isActive = index === completedSteps && !isPlanReady
              return (
                <article
                  className={`agent-step ${isComplete ? 'is-complete' : ''} ${isActive ? 'is-active' : ''}`}
                  key={title}
                >
                  <span className="agent-step__icon">
                    {isComplete ? <Check size={18} /> : <Icon size={18} />}
                  </span>
                  <div>
                    <div className="agent-step__title">
                      <strong>{title}</strong>
                      <span>{isComplete ? dynamicStepResults[index] : isActive ? '处理中…' : '等待中'}</span>
                    </div>
                    <p>{dynamicStepDetails[index]}</p>
                  </div>
                </article>
              )
            })}
          </div>
          <div className="agent-console__footer">
            <div>
              <ShieldCheck size={18} />
              <span>
                <strong>
                  {isPlanReady
                    ? planningResult?.registeredPlan
                      ? '服务端校验通过，1 秒后自动跳转'
                      : '发现待确认事实，1 秒后展示证据'
                    : '不会跳过硬约束校验'}
                </strong>
                <small>
                  {isPlanReady
                    ? planningResult?.registeredPlan
                      ? '也可以立即点击右侧按钮查看'
                      : '未知价格或设施不会被视为已通过，补齐前无法确认'
                    : '失败时将返回具体冲突，而不是生成看似合理的方案'}
                </small>
              </span>
            </div>
            <button
              className="button button--primary"
              disabled={!isPlanReady}
              onClick={() => {
                if (!tripId) return
                navigate(`/workspace?tripId=${tripId}`, {
                  state: { draft, tripId, trip: confirmedTrip, amapPlanResult: planningResult },
                })
              }}
              type="button"
            >
              查看推荐方案 <ArrowRight size={18} />
            </button>
          </div>
        </section>
      </main>
    </AppShell>
  )
}
