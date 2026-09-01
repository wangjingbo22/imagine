export const S1_REPLAN_LIMIT_MESSAGE = '当前迭代仅支持一次 V2 调整。'

export function canRequestS1PlanV2(
  currentVersion: number | null,
  completedV2Decisions: number,
) {
  return currentVersion === 1 && completedV2Decisions === 0
}

export function executionAdjustmentBlockReason(input: {
  currentVersion: number | null
  completedV2Decisions: number
  hasPendingCandidate: boolean
  hasCurrentTask: boolean
  hasAdjustableSuffix: boolean
  hasOrganizerToken: boolean
}): string | null {
  if (input.currentVersion === null) return '正在恢复当前计划，请稍后再调整。'
  if (input.currentVersion !== 1) {
    return `当前正在执行 Plan V${input.currentVersion}。本版本仅支持一次 V1 → V2 调整，暂不支持继续生成 V3；仍可记录消费并完成任务。`
  }
  if (input.hasPendingCandidate) return '已有待确认的 Plan V2，请先查看变更并接受或拒绝。'
  if (input.completedV2Decisions > 0) return `${S1_REPLAN_LIMIT_MESSAGE}本次调整已处理，请继续执行当前计划。`
  if (!input.hasOrganizerToken) return '当前浏览器没有组织者凭证，只能查看，不能发起调整。'
  if (!input.hasCurrentTask) return '当前没有正在执行的任务，不能发起调整。'
  if (!input.hasAdjustableSuffix) return '当前已经是最后一个任务，没有后续安排可生成 Plan V2。'
  return null
}
