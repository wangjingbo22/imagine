import type {
  EventDrivenReplanRequest,
  ExecutionEvent,
  TripSummary,
} from '../domain/trip'

type ExecutionPlan = {
  days: Array<{
    tasks: Array<{ taskId: string }>
  }>
}

type ExecutionEventLike = Pick<ExecutionEvent, 'taskId' | 'eventType'>

type IdentifiedExecutionPlan = ExecutionPlan & { planId: string }

type ContinuationActions<TPlan extends IdentifiedExecutionPlan> = {
  startTask: (plan: TPlan, taskIndex: number) => Promise<void> | void
  showSummary: () => void
}

type PlanDecision = 'accept' | 'reject'

type DecisionContinuationActions<
  TPlan extends IdentifiedExecutionPlan,
  TState extends {
    currentPlan: TPlan | null
    events: ReadonlyArray<ExecutionEventLike>
  },
> = ContinuationActions<TPlan> & {
  acceptPlan: (candidatePlanId: string) => Promise<unknown>
  rejectPlan: (candidatePlanId: string) => Promise<unknown>
  restoreTrip: () => Promise<TState>
  applyRestoredState: (state: TState) => void
}

type CompletionEventType = Extract<ExecutionEvent['eventType'], 'EXPENSE' | 'COMPLETE'>

export function firstUnfinishedTaskIndex(
  plan: ExecutionPlan,
  events: ReadonlyArray<ExecutionEventLike>,
): number | null {
  const terminalTaskIds = new Set(
    events
      .filter((event) => event.eventType === 'COMPLETE' || event.eventType === 'SKIP')
      .map((event) => event.taskId),
  )
  const index = plan.days[0]?.tasks.findIndex((task) => !terminalTaskIds.has(task.taskId)) ?? -1
  return index >= 0 ? index : null
}

export function executionEventIdempotencyKey(
  planId: string,
  taskId: string,
  eventType: ExecutionEvent['eventType'],
  _amountCents?: number | null,
): string {
  return `${planId}:${taskId}:${eventType}`
}

export async function continueExecutionFromRestoredState<
  TPlan extends IdentifiedExecutionPlan,
>(
  restored: {
    currentPlan: TPlan
    events: ReadonlyArray<ExecutionEventLike>
  },
  actions: ContinuationActions<TPlan>,
): Promise<number | null> {
  const nextIndex = firstUnfinishedTaskIndex(restored.currentPlan, restored.events)
  if (nextIndex === null) {
    actions.showSummary()
    return null
  }
  await actions.startTask(restored.currentPlan, nextIndex)
  return nextIndex
}

export async function decideAndContinueExecution<
  TPlan extends IdentifiedExecutionPlan,
  TState extends {
    currentPlan: TPlan | null
    events: ReadonlyArray<ExecutionEventLike>
  },
>(
  decision: PlanDecision,
  candidatePlanId: string,
  actions: DecisionContinuationActions<TPlan, TState>,
): Promise<{
  restoredState: TState
  nextTaskIndex: number | null
  adjustmentCount: 1
}> {
  if (decision === 'accept') {
    await actions.acceptPlan(candidatePlanId)
  } else {
    await actions.rejectPlan(candidatePlanId)
  }

  const restoredState = await actions.restoreTrip()
  if (!restoredState.currentPlan) {
    throw new Error('决策完成后未找到当前使用的方案。')
  }
  actions.applyRestoredState(restoredState)
  const nextTaskIndex = await continueExecutionFromRestoredState(
    {
      currentPlan: restoredState.currentPlan,
      events: restoredState.events,
    },
    actions,
  )
  return { restoredState, nextTaskIndex, adjustmentCount: 1 }
}

export function plannedPlusFiftyYuan(plannedCostCents: number): string {
  return String((plannedCostCents + 5_000) / 100)
}

export async function submitTaskCompletionEvents(
  actualCostYuan: string,
  recordEvent: (
    eventType: CompletionEventType,
    amountCents?: number | null,
  ) => Promise<unknown>,
): Promise<number> {
  const amountCents = parseYuanAmountToCents(actualCostYuan)
  if (amountCents === null) {
    throw new Error('实际消费金额必须是非负数字。')
  }
  await recordEvent('EXPENSE', amountCents)
  await recordEvent('COMPLETE', null)
  return amountCents
}

export function sprint1SummaryView(
  summary: TripSummary,
  formatMoney: (cents: number) => string,
) {
  const differencePrefix = summary.differenceCents >= 0 ? '+' : '-'
  return {
    completion: {
      completed: summary.completedTaskIds.length,
      total: summary.totalTasks,
      progressPercent: summary.totalTasks > 0
        ? (summary.completedTaskIds.length / summary.totalTasks) * 100
        : 0,
    },
    cost: {
      actual: formatMoney(summary.actualCostCents),
      detail: `计划 ${formatMoney(summary.plannedCostCents)} · ${differencePrefix}${formatMoney(Math.abs(summary.differenceCents))}`,
    },
    eventCount: summary.events.length,
    version: {
      current: `V${summary.currentPlanVersion}`,
      historyCount: summary.planHistory.length,
    },
    visibleSections: ['metrics', 'history'] as const,
    actions: [] as const,
  }
}

export function createExpenseChangeReplanRequest(): EventDrivenReplanRequest {
  return {
    schemaVersion: '1.0',
    reason: 'EXPENSE_CHANGE',
  }
}

export function parseYuanAmountToCents(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null

  const yuan = Number(trimmed)
  if (!Number.isFinite(yuan) || yuan < 0) return null

  return Math.round(yuan * 100)
}
