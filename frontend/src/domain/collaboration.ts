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

export type ParticipantAccessStatus =
  | 'ORGANIZER_ACTIVE'
  | 'NOT_INVITED'
  | 'INVITED'
  | 'SESSION_ACTIVE'
  | 'REVOKED'
  | 'EXPIRED'

export type ConversationAnswer = {
  questionId: string
  answer: string
}

export type CareDraft = {
  assistanceTypeHint: 'ORDINARY' | 'PARENT_CHILD' | 'LOW_STAMINA' | 'MOBILITY_ASSISTANCE_BETA' | null
  childAge: number | null
  walkLimits: {
    maxContinuousMeters: number | null
    maxDailyMeters: number | null
  }
  maxTransfers: number | null
  restIntervalMinutes: number | null
  napWindow: { start: string | null; end: string | null } | null
  avoidStairs: boolean | null
}

export type TripUnderstandingTrip = {
  cityName: string | null
  travelDate: string | null
  startTime: string | null
  endTime: string | null
  startLocationText: string | null
  endLocationText: string | null
  budgetCents: number | null
}

export type ParticipantUnderstanding = {
  memberKey: `member-${1 | 2 | 3}`
  nickname: string | null
  budgetCapCents: number | null
  interests: string[]
  mustVisit: string[]
  avoidPlaces: string[]
  careDraft: CareDraft | null
}

export type TripUnderstandingProposal = {
  schemaVersion: '1.0'
  trip: TripUnderstandingTrip
  participants: ParticipantUnderstanding[]
  fieldEvidence: Array<{
    fieldPath: string
    memberKey: `member-${1 | 2 | 3}` | null
    sourceType: 'USER_TEXT' | 'EXPLICIT_FIELD'
    sourceText: string
  }>
  missingFields: Array<{
    fieldPath: string
    memberKey: `member-${1 | 2 | 3}` | null
    code: 'MISSING'
    questionKey: string
  }>
  ambiguities: Array<{
    fieldPath: string
    memberKey: `member-${1 | 2 | 3}` | null
    code: 'AMBIGUOUS'
    reason: string
    candidates: string[]
    questionKey: string
  }>
  confirmationQuestions: Array<{
    fieldPath: string
    memberKey: `member-${1 | 2 | 3}` | null
    questionKey: string
    prompt: string
    choices: string[]
  }>
}

export type TripDraftRevision = {
  schemaVersion: '1.0'
  draftId: string
  revision: number
  tripId: string
  understanding: TripUnderstandingProposal
  memberBindings: Partial<Record<`member-${1 | 2 | 3}`, string>>
  sourceDigest: string
  createdAt: string
}

export type FixedQuestionFallbackResponse = {
  answerRevision: number
  naturalLanguageRequest: string
  answers: ConversationAnswer[]
  recognition: {
    source: 'FIXED_QUESTIONS'
    model: string | null
    failureCode: string
    callCount: number
  }
  understanding: null
  fallback: {
    mode: 'FIXED_QUESTIONS'
    items: Array<{
      questionId: string
      answer: string
      code: 'REVIEW_REQUIRED'
      message: string
    }>
  }
  canPlan: false
}

export type OrganizerConversationCreated = {
  revision: TripDraftRevision
  organizerAccess: {
    tripId: string
    organizerParticipantId: string
    organizerToken: string | null
    organizerTokenAvailable: boolean
    collaborationVersion: number
  }
}

export type InvitationCreated = {
  invitationId: string
  tripId: string
  participantId: string
  invitationUrl: string | null
  expiresAt: string
  linkAvailable: boolean
  collaborationVersion: number
}

export type InvitationRedeemed = {
  sessionId: string
  participantSessionToken: string | null
  tripId: string
  participantId: string
  expiresAt: string
  sessionTokenAvailable: boolean
}

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
  accessStatus: ParticipantAccessStatus
  confirmationStatus: ConfirmationStatus
  confirmedRevision: number | null
}

export type MemberSessionView = {
  schemaVersion: '1.0'
  tripId: string
  participantId: string
  currentRevision: number
  collaborationVersion: number
  sharedTrip: TripUnderstandingTrip
  participant: ParticipantUnderstanding
  accessStatus: ParticipantAccessStatus
  confirmationStatus: ConfirmationStatus
  confirmationItems: CollaborationIssue[]
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
