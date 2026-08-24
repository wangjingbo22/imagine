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
import { tripApi } from '../api/tripApi'
import { AppShell } from '../components/AppShell'
import type { TripDraftInput } from '../domain/trip'

const processSteps = [
  {
    title: '理解你的真实需求',
    detail: '已识别北京、单日、预算 ¥350、历史文化、特色餐饮与低体力需求。',
    icon: BrainCircuit,
  },
  {
    title: '检索同城地点',
    detail: '正在筛选历史文化、餐饮与轻松漫步类候选地点，并核对来源时间。',
    icon: MapPinned,
  },
  {
    title: '分析路线与关怀风险',
    detail: '逐段检查步行距离、换乘次数、休息间隔和已知阶梯路线。',
    icon: Route,
  },
  {
    title: '计算预算和时间',
    detail: '金额按整数分复算，并预留交通波动与临时消费缓冲。',
    icon: CircleDollarSign,
  },
  {
    title: '执行确定性校验',
    detail: '预算、时间、路线连续性、步行、换乘、休息和返程规则全部检查。',
    icon: ShieldCheck,
  },
]

export function AgentProcessPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const navigationState = location.state as { tripId?: string; draft?: TripDraftInput } | null
  const tripId = navigationState?.tripId ?? 'trip-demo-2026'
  const draft = navigationState?.draft
  const [completedSteps, setCompletedSteps] = useState(0)
  const [isPlanReady, setIsPlanReady] = useState(false)

  useEffect(() => {
    let currentStep = 0
    const timer = window.setInterval(() => {
      currentStep += 1
      setCompletedSteps(currentStep)
      if (currentStep === processSteps.length) {
        window.clearInterval(timer)
        void tripApi.generatePlan(tripId).then(() => setIsPlanReady(true))
      }
    }, 650)

    return () => window.clearInterval(timer)
  }, [tripId])

  useEffect(() => {
    if (!isPlanReady) {
      return
    }

    const redirectTimer = window.setTimeout(
      () => navigate('/workspace', { state: { draft } }),
      1200,
    )
    return () => window.clearTimeout(redirectTimer)
  }, [draft, isPlanReady, navigate])

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
    '找到 8 个候选点',
    '排除 2 条高负担路线',
    `预估剩余 ¥${Math.max(0, Math.round(((draft?.budgetCents ?? 35000) - 29800) / 100))}`,
    '8 项硬约束通过',
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
            <span><Clock3 size={15} /> 数据时间 15:58</span>
            <span><BadgeCheck size={15} /> Mock 演示环境</span>
          </div>
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
              onClick={() => navigate('/workspace', { state: { draft } })}
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
