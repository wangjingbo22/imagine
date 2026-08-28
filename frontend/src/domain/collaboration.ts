export type CollaborationStatus =
  | 'MIGRATION_REQUIRED'
  | 'DRAFT_CONVERSATION'
  | 'INVITING'
  | 'COLLECTING_MEMBERS'
  | 'CONFLICT_REVIEW'
  | 'READY_TO_PLAN'

export type ConfirmationStatus =
  | 'MIGRATION_REQUIRED'
  | 'DRAFT'
  | 'CONFIRMED'
  | 'NEEDS_RECONFIRMATION'

export type ActorScope = 'ORGANIZER' | 'PARTICIPANT'

export type RelaxationOption = {
  relaxationId: string
  action: string
  actorScope: ActorScope
  participantId: string | null
  fieldPath: string
  proposedValue: unknown
  label: string
}

export type CollaborationIssue = {
  itemId: string
  fieldPath: string
  participantId: string | null
  relatedParticipantIds: string[]
  ruleId: string
  code: 'MISSING' | 'AMBIGUOUS' | 'INVALID' | 'CONFLICT'
  reason: string
  candidates: string[]
  allowedRelaxations: RelaxationOption[]
}

export type ParticipantProgress = {
  participantId: string
  memberKey: `member-${1 | 2 | 3}`
  role: 'ORGANIZER' | 'MEMBER'
  accessStatus: string
  confirmationStatus: ConfirmationStatus
  confirmedRevision: number | null
}

export type CollaborationAggregate = {
  schemaVersion: '1.0'
  tripId: string
  draftId: string
  currentRevision: number
  organizerParticipantId: string
  status: CollaborationStatus
  collaborationVersion: number
  policyVersion: 'S2-T003.1'
  readinessDigest: string | null
  canPlan: boolean
  progress: {
    expectedCount: number
    confirmedCount: number
    openIssueCount: number
  }
  participants: ParticipantProgress[]
  confirmationItems: CollaborationIssue[]
}

export function organizerRelaxations(issue: CollaborationIssue): RelaxationOption[] {
  return issue.allowedRelaxations.filter((option) => option.actorScope === 'ORGANIZER')
}

export function participantRelaxations(issue: CollaborationIssue): RelaxationOption[] {
  return issue.allowedRelaxations.filter((option) => option.actorScope === 'PARTICIPANT')
}

export function participantIdsForIssue(issue: CollaborationIssue): string[] {
  return Array.from(new Set([
    ...(issue.participantId ? [issue.participantId] : []),
    ...issue.relatedParticipantIds,
  ])).sort()
}

export function canEnterRecommendation(state: CollaborationAggregate): boolean {
  return state.status === 'READY_TO_PLAN' && state.canPlan && state.readinessDigest !== null
}
