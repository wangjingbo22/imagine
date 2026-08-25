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
import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AppShell } from '../components/AppShell'
import type { TripDraftInput } from '../domain/trip'
import { loadAmapPlan, type AmapPlanResult } from '../services/amapPlan'

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

export function AgentProcessPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const navigationState = location.state as { tripId?: string; draft?: TripDraftInput } | null
  const tripId = navigationState?.tripId ?? crypto.randomUUID()
  const draft = navigationState?.draft
  const [completedSteps, setCompletedSteps] = useState(0)
  const [isPlanReady, setIsPlanReady] = useState(false)
  const [planningResult, setPlanningResult] = useState<AmapPlanResult | null>(null)
  const [planningError, setPlanningError] = useState(
    draft ? '' : '缺少行程草稿，请返回新建行程页面重新提交。',
  )
  const [providerDetail, setProviderDetail] = useState('等待连接高德 Web 服务')
  const [retryToken, setRetryToken] = useState(0)

  useEffect(() => {
    if (!draft) {
      return
    }
    let cancelled = false
    const phaseStep = { CITY: 0, PLACES: 1, ROUTES: 2, PLAN: 3 } as const
    void loadAmapPlan(tripId, draft, (phase, detail) => {
      if (cancelled) return
      setCompletedSteps(phaseStep[phase])
      setProviderDetail(detail)
    }).then((result) => {
      if (cancelled) return
      setPlanningResult(result)
      setCompletedSteps(processSteps.length)
      setProviderDetail(
        `高德返回 ${result.evidence.places.length} 个地点和 ${result.evidence.routes.length} 段路线`,
      )
      setIsPlanReady(true)
    }).catch((error: unknown) => {
      if (cancelled) return
      setPlanningError(error instanceof Error ? error.message : '高德真实数据生成失败')
      setProviderDetail('未使用固定数据回退')
    })
    return () => {
      cancelled = true
    }
  }, [draft, retryToken, tripId])

  useEffect(() => {
    if (!isPlanReady) {
      return
    }

    const redirectTimer = window.setTimeout(
      () => navigate(`/workspace?tripId=${tripId}`, {
        state: { draft, tripId, amapPlanResult: planningResult },
      }),
      1200,
    )
    return () => window.clearTimeout(redirectTimer)
  }, [draft, isPlanReady, navigate, planningResult, tripId])

  const progress = useMemo(
    () => Math.round((completedSteps / processSteps.length) * 100),
    [completedSteps],
  )

  const dynamicStepDetails = [
    `已识别${draft?.cityName ?? '北京'}、单日、预算 ¥${Math.round((draft?.budgetCents ?? 35000) / 100)}、${draft?.interests.join('、') ?? '历史文化、特色餐饮'}与关怀需求。`,
    `正在筛选${draft?.cityName ?? '北京'}的兴趣候选地点，并核对来源时间与同城缓存。`,
    `逐段检查步行距离、换乘次数、休息间隔和已知阶梯路线。当前单段步行上限 ${draft?.assistanceProfile.maxSegmentWalkMeters ?? 500} 米。`,
    `金额按整数分复算，并在 ¥${Math.round((draft?.budgetCents ?? 35000) / 100)} 总预算内预留交通波动与临时消费缓冲。`,
    `预算、${draft?.startTime ?? '09:00'}—${draft?.endTime ?? '20:00'} 时间窗、路线连续性、步行、换乘、休息和返程规则全部检查。`,
  ]
  const dynamicStepResults = [
    `${9 + (draft?.mustVisit.length ?? 0) + (draft?.avoidPlaces.length ?? 0)} 项结构化字段`,
    planningResult ? `${planningResult.evidence.places.length} 个高德 POI` : '正在读取 Provider',
    planningResult ? `${planningResult.evidence.routes.length} 段真实路线` : '正在规划逐段路线',
    planningResult
      ? `已知费用 ¥${Math.round(planningResult.knownCostCents / 100)}，${planningResult.unknownPriceCount} 项待确认`
      : '等待 Provider 价格事实',
    planningResult?.plan.validationStatus === 'PASS' ? '确定性校验通过' : '等待校验',
  ]

  return (
    <AppShell compact>
      <main className="agent-page">
        <section className="agent-page__intro" data-reveal="side">
          <span className="eyebrow"><Sparkles size={14} /> AGENT PLANNING SESSION</span>
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
            <small>{isPlanReady ? '方案已生成，即将自动进入工作台' : '预计还需数秒'}</small>
          </div>
          <div className="agent-session-meta">
            <span><Database size={15} /> 城市缓存已隔离</span>
            <span><Clock3 size={15} /> {providerDetail}</span>
            <span><BadgeCheck size={15} /> 高德真实数据</span>
          </div>
          {planningError && (
            <div className="provider-retry">
              <p className="media-error">{planningError}</p>
              <button
                className="button button--soft"
                onClick={() => {
                  setPlanningError('')
                  setCompletedSteps(0)
                  setProviderDetail('正在重新连接高德 Web 服务')
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
              <strong>Planning graph</strong>
            </div>
            <span>{tripId}</span>
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
                <strong>{isPlanReady ? '计划校验通过，1 秒后自动跳转' : '不会跳过硬约束校验'}</strong>
                <small>{isPlanReady ? '也可以立即点击右侧按钮查看' : '失败时将返回具体冲突，而不是生成看似合理的方案'}</small>
              </span>
            </div>
            <button
              className="button button--primary"
              disabled={!isPlanReady}
              onClick={() => navigate(`/workspace?tripId=${tripId}`, {
                state: { draft, tripId, amapPlanResult: planningResult },
              })}
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
