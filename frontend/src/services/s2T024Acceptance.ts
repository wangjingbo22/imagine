export const S2_T024_MINIMUM_TARGET_PX = 44

export const S2_T024_VIEWPORTS = [
  { id: 'RESP-S2-001-375', width: 375, height: 812 },
  { id: 'RESP-S2-001-768', width: 768, height: 1024 },
] as const

export const S2_T024_GOLDEN_PHASES = [
  'SIX_QUESTION_CONFIRMATION',
  'UNIQUE_RECOMMENDATION',
  'EXECUTION_AND_GPS',
  'TASK_PHOTO',
  'LATE_OR_FATIGUE_V2',
  'ORGANIZER_DECISION',
  'MEMORY_TIMELINE',
] as const

export function hasNoHorizontalOverflow(clientWidth: number, scrollWidth: number) {
  return scrollWidth <= clientWidth + 1
}

export function isPrimaryTargetReachable(width: number, height: number) {
  return width >= S2_T024_MINIMUM_TARGET_PX && height >= S2_T024_MINIMUM_TARGET_PX
}

export function isT024AcceptanceScope(taskId: string) {
  return taskId === 'S2-T024'
}
