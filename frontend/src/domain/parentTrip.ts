export type ParentTripDay = {
  dayIndex: number; date: string; budgetCents: number; childTripId: string | null
  childBudgetCents: number | null; plannedCostCents: number | null
  actualSpentCents: number | null; remainingBudgetCents: number | null
  childStatus: string; costStatus: 'NOT_AVAILABLE' | 'PLANNED' | 'ACTUAL_RECORDED'
}

const parentTripChildStatusLabels: Record<string, string> = {
  NOT_CREATED: '尚未创建',
  DRAFT: '草稿整理中',
  CONSTRAINT_CONFIRMED: '行程信息已确认',
  PLANNING: '正在生成方案',
  PLAN_REVIEW: '方案待确认',
  CONFIRMED: '行程已确认',
  EXECUTING: '行程进行中',
  REPLAN_REVIEW: '调整方案待确认',
  COMPLETED: '已完成',
}

export function parentTripChildStatusLabel(status: string): string {
  return parentTripChildStatusLabels[status] ?? '状态待确认'
}

export type ParentTripPlaceMemoryItem = {
  dayIndex: number
  date: string
  childTripId: string
  planId: string
  planStatus: 'PROPOSED' | 'CURRENT'
  placeId: string
  placeName: string
}

export type ParentTrip = {
  schemaVersion: '1.0'; parentTripId: string; title: string; cityName: string
  startDate: string; endDate: string; totalBudgetCents: number
  plannedCostCents: number | null; actualSpentCents: number | null; days: ParentTripDay[]
  placeMemory: ParentTripPlaceMemoryItem[]
}

export type ParentTripMemberProfile = {
  participantId: string
  role: 'ORGANIZER' | 'MEMBER'
  accessStatus: 'ORGANIZER_ACTIVE' | 'INVITED' | 'MEMBER_ACTIVE'
  nickname: string
  interests: string[]
  budgetCapCents: number | null
  profileVersion: number
  updatedAt: string
}

export type ParentTripSyncView = {
  schemaVersion: '1.0'
  parentTrip: ParentTrip
  syncVersion: number
  viewerRole: 'ORGANIZER' | 'MEMBER'
  viewerParticipantId: string
  visibleProfiles: ParentTripMemberProfile[]
  pollAfterSeconds: 5
  changedAt: string
}

export type ParentTripInvitationCreated = {
  invitationId: string
  parentTripId: string
  participantId: string
  invitationUrl: string | null
  expiresAt: string
  linkAvailable: boolean
  syncVersion: number
}

export type ParentTripInvitationRedeemed = {
  sessionId: string
  parentTripId: string
  participantId: string
  memberSessionToken: string | null
  expiresAt: string
  sessionTokenAvailable: boolean
  syncVersion: number
}
