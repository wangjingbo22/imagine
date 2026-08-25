export const S1_REPLAN_LIMIT_MESSAGE = '当前迭代仅支持一次 V2 调整。'

export function canRequestS1PlanV2(
  currentVersion: number | null,
  completedV2Decisions: number,
) {
  return currentVersion === 1 && completedV2Decisions === 0
}
