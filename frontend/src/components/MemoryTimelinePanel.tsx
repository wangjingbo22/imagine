/* oxlint-disable react/only-export-components */
import {
  Activity,
  Camera,
  CheckCircle2,
  Clock3,
  HeartHandshake,
  RefreshCw,
  Route,
  WalletCards,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { request } from '../api/client'
import type { AssistanceProfile } from '../domain/trip'
import { MemoryPhotoStrip, type MemoryPhoto } from './MemoryPhotoStrip'

export type MemoryTimelineItemKind =
  | 'PLAN_VERSION'
  | 'CARE_CONFIRMED'
  | 'TASK_STARTED'
  | 'TASK_COMPLETED'
  | 'TASK_SKIPPED'
  | 'EXPENSE'
  | 'PHOTO'

export type MemoryTimelineItem = {
  itemId: string
  kind: MemoryTimelineItemKind
  occurredAt: string
  title: string
  taskId: string | null
  eventId: string | null
  eventType: 'START' | 'COMPLETE' | 'SKIP' | 'EXPENSE' | null
  planVersionId: string | null
  planVersion: number | null
  planStatus: string | null
  amountCents: number | null
  cumulativeActualCostCents: number | null
  completionRatePercent: number | null
  assistanceProfile: AssistanceProfile | null
  photo: (MemoryPhoto & {
    mediaId: string
    mimeType: string
    createdAt: string
  }) | null
}

export type MemoryTimeline = {
  schemaVersion: '1.0'
  tripId: string
  summary: {
    completedTaskCount: number
    skippedTaskCount: number
    totalTaskCount: number
    completionRatePercent: number
    plannedCostCents: number
    actualCostCents: number
    costDifferenceCents: number
    currency: 'CNY'
    currentPlanVersion: number
    planChangeCount: number
    photoCount: number
    participantCareResults?: Array<{
      participantId: string
      nickname: string
      assistanceProfile: AssistanceProfile | null
    }>
    assistanceProfile: AssistanceProfile | null
  }
  items: MemoryTimelineItem[]
}

type TaskReference = { id: string; order: number; title: string }

type BoundPhotoResult = {
  photos: MemoryPhoto[]
  invalidItemIds: string[]
}

const timelineRequests = new Map<string, Promise<MemoryTimeline>>()

const timelineKindLabels: Record<MemoryTimelineItemKind, string> = {
  PLAN_VERSION: '计划版本',
  CARE_CONFIRMED: '关怀确认',
  TASK_STARTED: '任务开始',
  TASK_COMPLETED: '任务完成',
  TASK_SKIPPED: '任务跳过',
  EXPENSE: '实际费用',
  PHOTO: '任务照片',
}

const assistanceTypeLabels: Record<AssistanceProfile['type'], string> = {
  ORDINARY: '普通出行',
  PARENT_CHILD: '亲子关怀',
  LOW_STAMINA: '低体力关怀',
  MOBILITY_ASSISTANCE_BETA: '行动辅助',
}

function loadMemoryTimeline(tripId: string): Promise<MemoryTimeline> {
  const existing = timelineRequests.get(tripId)
  if (existing) return existing

  const operation = request<MemoryTimeline>(
    `/api/v1/trips/${encodeURIComponent(tripId)}/memory-timeline`,
  ).then((response) => response.data)
  timelineRequests.set(tripId, operation)
  void operation.then(
    () => timelineRequests.delete(tripId),
    () => timelineRequests.delete(tripId),
  )
  return operation
}

export const orderMemoryTimelineItems = (
  items: readonly MemoryTimelineItem[],
): MemoryTimelineItem[] => items
  .map((item, sourceIndex) => ({ item, sourceIndex }))
  .sort((left, right) => {
    const leftTime = Date.parse(left.item.occurredAt)
    const rightTime = Date.parse(right.item.occurredAt)
    const normalizedLeft = Number.isFinite(leftTime) ? leftTime : Number.MAX_SAFE_INTEGER
    const normalizedRight = Number.isFinite(rightTime) ? rightTime : Number.MAX_SAFE_INTEGER
    return normalizedLeft - normalizedRight || left.sourceIndex - right.sourceIndex
  })
  .map(({ item }) => item)

export const extractBoundTimelinePhotos = (
  items: readonly MemoryTimelineItem[],
): BoundPhotoResult => {
  const result: BoundPhotoResult = { photos: [], invalidItemIds: [] }
  for (const item of items) {
    if (item.kind !== 'PHOTO') continue
    if (!item.photo || !item.taskId || item.photo.taskId !== item.taskId) {
      result.invalidItemIds.push(item.itemId)
      continue
    }
    result.photos.push(item.photo)
  }
  return result
}

export const assistanceProfileDetails = (
  profile: AssistanceProfile | null,
): string[] => {
  if (!profile) return ['未提供单一关怀档案；多人行程请查看各成员确认卡']
  const details = [assistanceTypeLabels[profile.type]]
  if (profile.childAge !== null) details.push(`儿童年龄 ${profile.childAge} 岁`)
  if (profile.walkLimits.maxContinuousMeters !== null) {
    details.push(`单段步行不超过 ${profile.walkLimits.maxContinuousMeters} 米`)
  }
  if (profile.walkLimits.maxDailyMeters !== null) {
    details.push(`全天步行不超过 ${profile.walkLimits.maxDailyMeters} 米`)
  }
  if (profile.maxTransfers !== null) details.push(`单程换乘不超过 ${profile.maxTransfers} 次`)
  if (profile.restInterval !== null) details.push(`每 ${profile.restInterval} 分钟安排休息`)
  if (profile.napWindow) {
    details.push(`午休窗口 ${profile.napWindow.start.slice(0, 5)}-${profile.napWindow.end.slice(0, 5)}`)
  }
  if (profile.avoidStairs) details.push('路线避开楼梯')
  return details
}

function formatMoney(cents: number): string {
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    minimumFractionDigits: 2,
  }).format(cents / 100)
}

function formatOccurredAt(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function itemDetails(item: MemoryTimelineItem): string[] {
  const details: string[] = []
  if (item.planVersion !== null) {
    details.push(`Plan V${item.planVersion}${item.planStatus ? ` · ${item.planStatus}` : ''}`)
  }
  if (item.amountCents !== null) details.push(formatMoney(item.amountCents))
  if (item.cumulativeActualCostCents !== null) {
    details.push(`累计实际 ${formatMoney(item.cumulativeActualCostCents)}`)
  }
  if (item.completionRatePercent !== null) {
    details.push(`完成率 ${item.completionRatePercent}%`)
  }
  if (item.taskId) details.push(`任务 ${item.taskId}`)
  return details
}

function TimelineIcon({ kind }: { kind: MemoryTimelineItemKind }) {
  if (kind === 'PLAN_VERSION') return <Route size={17} />
  if (kind === 'CARE_CONFIRMED') return <HeartHandshake size={17} />
  if (kind === 'PHOTO') return <Camera size={17} />
  if (kind === 'EXPENSE') return <WalletCards size={17} />
  if (kind === 'TASK_COMPLETED') return <CheckCircle2 size={17} />
  return <Activity size={17} />
}

export function MemoryTimelinePanel({
  tripId,
  tasks,
}: {
  tripId: string | null
  tasks: TaskReference[]
}) {
  const [loadResult, setLoadResult] = useState<{
    tripId: string
    attempt: number
    timeline: MemoryTimeline | null
    error: string
  } | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    if (!tripId) return () => { active = false }
    void loadMemoryTimeline(tripId).then((result) => {
      if (!active) return
      if (result.tripId !== tripId) {
        throw new Error('回忆时间线与当前行程不一致。')
      }
      setLoadResult({ tripId, attempt, timeline: result, error: '' })
    }).catch((caught: unknown) => {
      if (active) {
        setLoadResult({
          tripId,
          attempt,
          timeline: null,
          error: caught instanceof Error ? caught.message : '回忆时间线加载失败。',
        })
      }
    })
    return () => { active = false }
  }, [attempt, tripId])

  const hasCurrentResult = Boolean(
    tripId && loadResult?.tripId === tripId && loadResult.attempt === attempt,
  )
  const timeline = hasCurrentResult ? loadResult?.timeline ?? null : null
  const error = !tripId
    ? '缺少 tripId，无法读取旅行回忆时间线。'
    : hasCurrentResult
      ? loadResult?.error ?? ''
      : ''
  const loading = Boolean(tripId) && !hasCurrentResult

  const orderedItems = useMemo(
    () => orderMemoryTimelineItems(timeline?.items ?? []),
    [timeline],
  )
  const boundPhotos = useMemo(
    () => extractBoundTimelinePhotos(orderedItems),
    [orderedItems],
  )
  const careDetails = assistanceProfileDetails(timeline?.summary.assistanceProfile ?? null)
  const participantCareResults = timeline?.summary.participantCareResults ?? []
  const costDifference = timeline?.summary.costDifferenceCents ?? 0

  return <section className="memory-timeline-panel" aria-labelledby="memory-timeline-title">
    <header className="memory-timeline-panel__heading">
      <div>
        <span className="section-kicker">MEMORY TIMELINE</span>
        <h2 id="memory-timeline-title">真实旅程时间线</h2>
        <p>按实际发生时间汇总计划、执行、费用、关怀结果和仍然保留的任务照片。</p>
      </div>
      {timeline && <span className="memory-timeline-panel__count">{orderedItems.length} 条可追溯记录</span>}
    </header>

    {loading && <p className="memory-timeline-panel__loading" role="status" aria-live="polite">
      <Clock3 size={18} aria-hidden="true" />正在读取旅行回忆时间线…
    </p>}

    {error && <div className="memory-timeline-panel__error" role="alert">
      <div><strong>回忆聚合暂时不可用</strong><p>{error}</p></div>
      <button className="button button--soft" type="button" onClick={() => setAttempt((value) => value + 1)}>
        <RefreshCw size={17} aria-hidden="true" />重新加载
      </button>
    </div>}

    {timeline && <>
      <div className="memory-timeline-summary" aria-label="旅行回忆聚合指标">
        <article><span>任务完成</span><strong>{timeline.summary.completedTaskCount}/{timeline.summary.totalTaskCount}</strong><small>{timeline.summary.completionRatePercent}% 完成</small></article>
        <article><span>计划 / 实际费用</span><strong>{formatMoney(timeline.summary.plannedCostCents)}</strong><small>实际 {formatMoney(timeline.summary.actualCostCents)}</small></article>
        <article><span>费用差额</span><strong>{costDifference > 0 ? '+' : ''}{formatMoney(costDifference)}</strong><small>{costDifference > 0 ? '超出计划' : costDifference < 0 ? '低于计划' : '与计划一致'}</small></article>
        <article><span>最终版本</span><strong>Plan V{timeline.summary.currentPlanVersion}</strong><small>{timeline.summary.planChangeCount} 次版本变化</small></article>
      </div>

      <section className="memory-care-result" aria-labelledby="memory-care-title">
        <span aria-hidden="true"><HeartHandshake size={20} /></span>
        <div><h3 id="memory-care-title">关怀确认结果</h3><ul>{participantCareResults.length > 0
          ? participantCareResults.map((participant) => <li key={participant.participantId}><strong>{participant.nickname}</strong>：{assistanceProfileDetails(participant.assistanceProfile).join('；')}</li>)
          : careDetails.map((detail) => <li key={detail}>{detail}</li>)}</ul></div>
      </section>

      {boundPhotos.invalidItemIds.length > 0 && <p className="memory-timeline-panel__binding-error" role="alert">
        {boundPhotos.invalidItemIds.length} 条照片记录没有正确绑定任务，已停止展示这些照片。
      </p>}

      <ol className="memory-timeline-list" aria-label="按真实发生时间排列的旅程记录">
        {orderedItems.map((item) => {
          const details = itemDetails(item)
          return <li className={`memory-timeline-item memory-timeline-item--${item.kind.toLowerCase()}`} key={item.itemId}>
            <span className="memory-timeline-item__icon" aria-hidden="true"><TimelineIcon kind={item.kind} /></span>
            <div className="memory-timeline-item__body">
              <div><span>{timelineKindLabels[item.kind]}</span><time dateTime={item.occurredAt}>{formatOccurredAt(item.occurredAt)}</time></div>
              <strong>{item.title}</strong>
              {details.length > 0 && <p>{details.map((detail) => <span key={detail}>{detail}</span>)}</p>}
            </div>
          </li>
        })}
      </ol>

      <MemoryPhotoStrip
        heading="未删除的任务照片"
        photos={boundPhotos.photos}
        tripId={tripId}
        tasks={tasks}
      />
    </>}

    {!loading && !timeline && <MemoryPhotoStrip
      heading="旧版照片回忆（降级展示）"
      tripId={tripId}
      tasks={tasks}
    />}
  </section>
}
