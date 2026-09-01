export type ParentTripDay = {
  dayIndex: number; date: string; budgetCents: number; childTripId: string | null
  childBudgetCents: number | null; plannedCostCents: number | null
  actualSpentCents: number | null; remainingBudgetCents: number | null
  childStatus: string; costStatus: 'NOT_AVAILABLE' | 'PLANNED' | 'ACTUAL_RECORDED'
}

export type ParentTrip = {
  schemaVersion: '1.0'; parentTripId: string; title: string; cityName: string
  startDate: string; endDate: string; totalBudgetCents: number
  plannedCostCents: number | null; actualSpentCents: number | null; days: ParentTripDay[]
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
