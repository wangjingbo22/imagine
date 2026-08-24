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
  GitCompareArrows,
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
  Utensils,
  Wallet,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { AppShell } from '../components/AppShell'
import type { TripDraftInput } from '../domain/trip'
import { mockPlanV1, mockPlanV2 } from '../mocks/trip'

type WorkspaceView = 'plan' | 'execute' | 'diff' | 'summary'

const views: Array<{ value: WorkspaceView; label: string }> = [
  { value: 'plan', label: '计划工作台' },
  { value: 'execute', label: '执行旅程' },
  { value: 'diff', label: '版本对比' },
  { value: 'summary', label: '旅行总结' },
]

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

export function WorkspacePage() {
  const location = useLocation()
  const draft = (location.state as { draft?: TripDraftInput } | null)?.draft
  const [view, setView] = useState<WorkspaceView>('plan')
  const [actualCost, setActualCost] = useState('188')
  const [currentTaskIndex, setCurrentTaskIndex] = useState(1)
  const [currentPlanVersion, setCurrentPlanVersion] = useState<1 | 2>(1)
  const [completedTaskIds, setCompletedTaskIds] = useState<string[]>(['task-1'])
  const [skippedTaskIds, setSkippedTaskIds] = useState<string[]>([])
  const [replanExpenseDeltaCents, setReplanExpenseDeltaCents] = useState<number | null>(null)
  const [actualSpentCents, setActualSpentCents] = useState(600)
  const [isFeedbackOpen, setIsFeedbackOpen] = useState(false)
  const [recommendationFeedback, setRecommendationFeedback] = useState('')
  const [selectedFeedbackOptions, setSelectedFeedbackOptions] = useState<string[]>([])
  const [recommendationRound, setRecommendationRound] = useState(1)
  const [isRegenerating, setIsRegenerating] = useState(false)
  const [appliedFeedback, setAppliedFeedback] = useState<string[]>([])
  const budgetCents = draft?.budgetCents ?? 35000
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
  const remainingBudgetCents = Math.max(0, budgetCents - displayPlanV1.totalCostCents)
  const displayPlanV2 = {
    ...mockPlanV2,
    cityName: draft?.cityName ?? mockPlanV2.cityName,
    tasks: mockPlanV2.tasks.map((task, index) => ({
      ...task,
      title: index === 2 && draft?.cityName && draft.cityName !== '北京'
        ? `${draft.cityName}湖畔公园`
        : displayPlanV1.tasks[index]?.title ?? task.title,
    })),
  }
  const activePlan = currentPlanVersion === 2 ? displayPlanV2 : displayPlanV1
  const currentTask = activePlan.tasks[currentTaskIndex]
  const nextTask = activePlan.tasks[currentTaskIndex + 1]
  const actualExpenseCents = Math.max(0, Number(actualCost) || 0) * 100
  const expenseDeltaCents = actualExpenseCents - (currentTask?.costCents ?? 0)
  const effectiveReplanDeltaCents = replanExpenseDeltaCents ?? expenseDeltaCents
  const projectedCostCents = displayPlanV1.totalCostCents + effectiveReplanDeltaCents
  const projectedBufferCents = budgetCents - projectedCostCents
  const expenseDifferenceLabel =
    expenseDeltaCents === 0
      ? '实际消费与计划一致'
      : `比计划${expenseDeltaCents > 0 ? '多花' : '少花'} ${formatMoney(Math.abs(expenseDeltaCents))}`
  const executionProgress = Math.round(
    ((completedTaskIds.length + skippedTaskIds.length) / activePlan.tasks.length) * 100,
  )
  const isJourneyComplete =
    completedTaskIds.length + skippedTaskIds.length >= activePlan.tasks.length

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

  function moveToNextTask() {
    const nextIndex = currentTaskIndex + 1
    const task = activePlan.tasks[nextIndex]
    if (!task) {
      setView('summary')
      return
    }
    setCurrentTaskIndex(nextIndex)
    setActualCost(String(task.costCents / 100))
    setView('execute')
  }

  function handleSkipTask() {
    if (!currentTask) {
      return
    }
    setSkippedTaskIds((current) =>
      current.includes(currentTask.id) ? current : [...current, currentTask.id],
    )
    moveToNextTask()
  }

  function handleCompleteTask() {
    if (!currentTask) {
      return
    }
    setCompletedTaskIds((current) =>
      current.includes(currentTask.id) ? current : [...current, currentTask.id],
    )
    setActualSpentCents((current) => current + actualExpenseCents)
    if (currentPlanVersion === 1 && currentTaskIndex === 1 && expenseDeltaCents !== 0) {
      setReplanExpenseDeltaCents(expenseDeltaCents)
      setView('diff')
      return
    }
    moveToNextTask()
  }

  function handlePlanDecision(decision: 'ACCEPT' | 'REJECT') {
    if (decision === 'ACCEPT') {
      setCurrentPlanVersion(2)
    }
    const nextIndex = Math.max(currentTaskIndex + 1, 2)
    const nextPlan = decision === 'ACCEPT' ? displayPlanV2 : displayPlanV1
    setCurrentTaskIndex(nextIndex)
    setActualCost(String((nextPlan.tasks[nextIndex]?.costCents ?? 0) / 100))
    setView('execute')
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
                (item.value === 'diff' && replanExpenseDeltaCents === null)
              }
              key={item.value}
              onClick={() => setView(item.value)}
              type="button"
            >
              {item.label}
              {item.value === 'diff' && <span>1</span>}
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
                {displayPlanV1.tasks.map((task) => (
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
                  {displayPlanV1.tasks.map((task) => (
                    <span className="map-pin" key={task.id} style={{ left: `${task.coordinates[0]}%`, top: `${task.coordinates[1]}%` }}>{task.order}</span>
                  ))}
                </div>
              </section>
              <section className="metric-card">
                <div className="metric-card__head"><span>预算使用</span><strong>{formatMoney(mockPlanV1.totalCostCents)} / {formatMoney(budgetCents)}</strong></div>
                <div className="progress-bar"><i style={{ width: '85%' }} /></div>
                <div className="metric-grid">
                  <div><Wallet size={18} /><span>剩余缓冲<strong>{formatMoney(remainingBudgetCents)}</strong></span></div>
                  <div><Footprints size={18} /><span>全天步行<strong>2.65 km</strong></span></div>
                  <div><BusFront size={18} /><span>公共交通<strong>2 次换乘</strong></span></div>
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
                  <button type="button">查看详情</button>
                </div>
                <div><Telescope size={15} /><span>地点与路线</span><strong>在线获取 · 15:58</strong></div>
                <div><CircleDollarSign size={15} /><span>价格参考</span><strong>估算区间</strong></div>
                <div><MapPin size={15} /><span>无障碍设施</span><strong className="needs-confirmation">待确认</strong></div>
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
                  <button className="button button--primary" onClick={() => setView('execute')} type="button">
                    接受推荐并确认 Plan V1 <ArrowRight size={18} />
                  </button>
                </div>
              )}
            </aside>
          </div>
        )}

        {view === 'execute' && (
          <section className="execution-web motion-enter">
            <div className="execution-web__main">
              <div className="execution-web__heading">
                <div>
                  <span className="section-kicker">LIVE EXECUTION · PLAN V{currentPlanVersion}</span>
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
                  <button className="button button--ghost" onClick={handleSkipTask} type="button">跳过此任务</button>
                  <button className="button button--primary" onClick={handleCompleteTask} type="button">
                    {currentTaskIndex === activePlan.tasks.length - 1
                      ? '完成行程并查看总结'
                      : currentPlanVersion === 1 && currentTaskIndex === 1 && expenseDeltaCents !== 0
                        ? '完成并重新规划'
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
                  <div><span>当前版本</span><strong>V{currentPlanVersion}</strong></div>
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

              <section className="execution-rules-card">
                <h3>执行保护规则</h3>
                <div><Check size={16} /><span><strong>完成项保持不变</strong><small>已发生的行程不会被重写</small></span></div>
                <div><Check size={16} /><span><strong>新版必须由你确认</strong><small>候选 V2 不自动覆盖 V1</small></span></div>
                <div><Check size={16} /><span><strong>事件和金额可追溯</strong><small>每条记录绑定具体任务</small></span></div>
              </section>
            </aside>
          </section>
        )}

        {view === 'diff' && (
          <section className="diff-stage motion-enter">
            <div className="agent-processing">
              <span className="agent-processing__orb"><LoaderCircle size={24} /></span>
              <div><strong>Agent 已完成最小扰动重规划</strong><p>保留 2 个已确认任务，仅调整下午路线。</p></div>
              <span className="pass-chip"><ShieldCheck size={13} /> V2 校验通过</span>
            </div>
            <div className="diff-heading">
              <div><span className="section-kicker">PLAN CHANGE REVIEW</span><h2>看看 Agent 改了什么</h2></div>
              <div className="diff-summary">
                <span>预算余量 <strong>{formatMoney(remainingBudgetCents)} → {formatMoney(projectedBufferCents)}</strong></span>
                <span>步行距离 <strong>2.65 → 1.88 km</strong></span>
              </div>
            </div>
            <div className="diff-columns">
              <article className="diff-plan">
                <header><span>当前版本</span><strong>Plan V1</strong></header>
                {displayPlanV1.tasks.map((task) => (
                  <div className={task.id === 'task-3' ? 'diff-task is-removed' : 'diff-task'} key={task.id}>
                    <span>{task.order}</span><div><strong>{task.title}</strong><small>{task.timeRange} · {formatMoney(task.costCents)}</small></div>
                    {task.id === 'task-3' ? <em>移除</em> : <em>保留</em>}
                  </div>
                ))}
              </article>
              <span className="diff-arrow"><GitCompareArrows size={24} /></span>
              <article className="diff-plan diff-plan--new">
                <header><span>候选版本</span><strong>Plan V2</strong></header>
                {displayPlanV2.tasks.map((task) => (
                  <div className={task.id === 'task-3' ? 'diff-task is-added' : 'diff-task'} key={task.id}>
                    <span>{task.order}</span><div><strong>{task.title}</strong><small>{task.timeRange} · {formatMoney(task.costCents)}</small></div>
                    {task.id === 'task-3' ? <em>新增</em> : <em>保留</em>}
                  </div>
                ))}
              </article>
            </div>
            <div className="diff-reason">
              <Sparkles size={20} />
              <p><strong>为什么这样调整？</strong> 午餐{expenseDifferenceLabel}后，Agent 重新检查了剩余预算与体力约束。替换为北海公园东岸可减少 400 米步行，并尽量保留返程缓冲。</p>
            </div>
            <div className="diff-actions">
              <button className="button button--ghost" onClick={() => handlePlanDecision('REJECT')} type="button">拒绝，继续 V1</button>
              <button className="button button--primary" onClick={() => handlePlanDecision('ACCEPT')} type="button">
                接受 Plan V2 <Check size={17} />
              </button>
            </div>
          </section>
        )}

        {view === 'summary' && (
          <section className="summary-stage motion-enter">
            <div className="summary-hero">
              <span className="summary-icon"><BadgeCheck size={34} /></span>
              <span className="section-kicker">JOURNEY COMPLETE</span>
              <h2>今天，你和{draft?.cityName ?? '北京'}认真地见了一面。</h2>
              <p>行程已经结束。每一次完成、跳过和版本变化都有记录，每一笔花费都有来处。</p>
            </div>
            <div className="summary-metrics">
              <article><span>任务完成</span><strong>{completedTaskIds.length}<small>/{activePlan.tasks.length}</small></strong><i style={{ width: `${(completedTaskIds.length / activePlan.tasks.length) * 100}%` }} /></article>
              <article><span>实际花费</span><strong>{formatMoney(actualSpentCents)}</strong><small>计划 {formatMoney(activePlan.totalCostCents)} · {actualSpentCents >= activePlan.totalCostCents ? '+' : '-'}{formatMoney(Math.abs(actualSpentCents - activePlan.totalCostCents))}</small></article>
              <article><span>关怀满足率</span><strong>100<small>%</small></strong><small>4 项硬约束全部满足</small></article>
              <article><span>最终版本</span><strong>V{currentPlanVersion}</strong><small>{currentPlanVersion === 2 ? '接受了 1 次最小扰动调整' : '继续执行原始计划'}</small></article>
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
          </section>
        )}
      </main>
    </AppShell>
  )
}
