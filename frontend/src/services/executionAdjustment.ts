import type {
  ConfirmedExecutionAdjustment,
  ExecutionAdjustmentType,
  ExecutionEventDraft,
  FatigueLevel,
} from '../domain/executionAdjustment'

export interface AdjustmentDraftOverrides {
  eventType?: ExecutionAdjustmentType
  lateMinutes?: number | null
  fatigueLevel?: FatigueLevel | null
}

export function buildConfirmedAdjustment(
  draft: ExecutionEventDraft,
  overrides: AdjustmentDraftOverrides = {},
): ConfirmedExecutionAdjustment {
  const eventType = overrides.eventType ?? draft.eventType
  if (!eventType) {
    throw new Error('请先确认这次调整是迟到还是疲劳。')
  }

  if (eventType === 'LATE') {
    const lateMinutes = overrides.lateMinutes === undefined
      ? draft.lateMinutes
      : overrides.lateMinutes
    if (
      lateMinutes === null ||
      !Number.isInteger(lateMinutes) ||
      lateMinutes < 1 ||
      lateMinutes > 240
    ) {
      throw new Error('迟到分钟数必须是 1–240 的整数。')
    }
    return {
      schemaVersion: '1.0',
      confirmationStatus: 'CONFIRMED',
      eventType,
      taskId: draft.taskId,
      lateMinutes,
      fatigueLevel: null,
    }
  }

  const fatigueLevel = overrides.fatigueLevel === undefined
    ? draft.fatigueLevel
    : overrides.fatigueLevel
  if (!fatigueLevel) {
    throw new Error('请先确认当前疲劳程度。')
  }
  return {
    schemaVersion: '1.0',
    confirmationStatus: 'CONFIRMED',
    eventType,
    taskId: draft.taskId,
    lateMinutes: null,
    fatigueLevel,
  }
}

export function canConfirmAdjustmentDraft(draft: ExecutionEventDraft): boolean {
  try {
    buildConfirmedAdjustment(draft)
    return true
  } catch {
    return false
  }
}

export function createAdjustmentIdempotencyKey(
  planId: string,
  taskId: string,
  eventType: ExecutionAdjustmentType,
  occurredAt: string,
): string {
  if (!/(?:Z|[+-]\d{2}:\d{2})$/i.test(occurredAt)) {
    throw new Error('occurredAt 必须包含明确时区。')
  }
  const instant = new Date(occurredAt)
  if (Number.isNaN(instant.getTime())) {
    throw new Error('occurredAt 必须是有效的带时区时间。')
  }
  const normalizedInstant = instant.toISOString().replace(/[-:.]/g, '')
  return `s2-adjust:${planId}:${taskId}:${eventType}:${normalizedInstant}`.slice(0, 160)
}
