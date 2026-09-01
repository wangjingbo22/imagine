import { request } from './client'
import type {
  CollaborationAggregate,
  ConversationAnswer,
  FixedQuestionFallbackResponse,
  InvitationCreated,
  InvitationRedeemed,
  MemberSessionView,
  SharedTripProposalField,
  OrganizerConversationCreated,
} from '../domain/collaboration'

type ResolveOrganizerInput = {
  state: CollaborationAggregate
  itemId: string
  relaxationId: string
  organizerToken: string
}

export function newIdempotencyKey(prefix: string): string {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`
  return `${prefix}-${suffix}`
}

const idempotencyKey = newIdempotencyKey

export function isFixedQuestionFallback(
  value: unknown,
): value is FixedQuestionFallbackResponse {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<FixedQuestionFallbackResponse>
  return candidate.understanding === null && candidate.canPlan === false && candidate.fallback?.mode === 'FIXED_QUESTIONS'
}

export async function createOrganizerConversation(
  input: {
    naturalLanguageRequest: string
    answers: ConversationAnswer[]
    referenceDate: string
    referenceTime?: string
    reviewedFallback?: boolean
  },
  idempotencyKey: string,
): Promise<OrganizerConversationCreated | FixedQuestionFallbackResponse> {
  const response = await request<OrganizerConversationCreated | FixedQuestionFallbackResponse>(
    '/api/v2/trips/conversations',
    {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ schemaVersion: '1.0', ...input }),
    },
  )
  return response.data
}

export async function confirmOrganizerParticipant(input: {
  tripId: string
  participantId: string
  baseRevision: number
  expectedVersion: number
  organizerToken: string
}): Promise<CollaborationAggregate> {
  const response = await request<CollaborationAggregate>(
    `/api/v2/trips/${encodeURIComponent(input.tripId)}/participants/${encodeURIComponent(input.participantId)}/confirm`,
    {
      method: 'POST',
      headers: {
        'X-Organizer-Token': input.organizerToken,
        'Idempotency-Key': newIdempotencyKey('s2-organizer-confirm'),
      },
      body: JSON.stringify({
        schemaVersion: '1.0',
        baseRevision: input.baseRevision,
        expectedVersion: input.expectedVersion,
      }),
    },
  )
  return response.data
}

export async function createParticipantInvitation(input: {
  tripId: string
  participantId: string
  expectedVersion: number
  organizerToken: string
}): Promise<InvitationCreated> {
  const response = await request<InvitationCreated>(
    `/api/v2/trips/${encodeURIComponent(input.tripId)}/participants/${encodeURIComponent(input.participantId)}/invitations`,
    {
      method: 'POST',
      headers: {
        'X-Organizer-Token': input.organizerToken,
        'Idempotency-Key': newIdempotencyKey('s2-participant-invite'),
      },
      body: JSON.stringify({
        schemaVersion: '1.0',
        expectedVersion: input.expectedVersion,
        expiresInHours: 72,
      }),
    },
  )
  return response.data
}

const invitationRedemptions = new Map<string, Promise<InvitationRedeemed>>()

export function redeemParticipantInvitation(
  token: string,
  idempotencyKey: string,
): Promise<InvitationRedeemed> {
  const inFlight = invitationRedemptions.get(token)
  if (inFlight) return inFlight
  const operation = request<InvitationRedeemed>('/api/v2/participant-invitations/redeem', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ schemaVersion: '1.0', token }),
  }).then((response) => response.data)
  invitationRedemptions.set(token, operation)
  void operation.then(
    () => invitationRedemptions.delete(token),
    () => invitationRedemptions.delete(token),
  )
  return operation
}

export async function getMemberSession(
  participantSessionToken: string,
): Promise<MemberSessionView> {
  const response = await request<MemberSessionView>('/api/v2/member-session', {
    headers: { 'X-Participant-Session': participantSessionToken },
  })
  return response.data
}

export async function submitMemberConversation(input: {
  participantSessionToken: string
  baseRevision: number
  expectedVersion: number
  naturalLanguageRequest: string
  answers: ConversationAnswer[]
  reviewedFallback?: boolean
}): Promise<MemberSessionView | FixedQuestionFallbackResponse> {
  const response = await request<MemberSessionView | FixedQuestionFallbackResponse>(
    '/api/v2/member-session/conversation',
    {
      method: 'PUT',
      headers: {
        'X-Participant-Session': input.participantSessionToken,
        'Idempotency-Key': newIdempotencyKey('s2-member-conversation'),
      },
      body: JSON.stringify({
        schemaVersion: '1.0',
        baseRevision: input.baseRevision,
        expectedVersion: input.expectedVersion,
        naturalLanguageRequest: input.naturalLanguageRequest,
        answers: input.answers,
        reviewedFallback: input.reviewedFallback ?? false,
      }),
    },
  )
  return response.data
}

export async function confirmMemberSession(input: {
  participantSessionToken: string
  baseRevision: number
  expectedVersion: number
}): Promise<MemberSessionView> {
  const response = await request<MemberSessionView>('/api/v2/member-session/confirm', {
    method: 'POST',
    headers: {
      'X-Participant-Session': input.participantSessionToken,
      'Idempotency-Key': newIdempotencyKey('s2-member-confirm'),
    },
    body: JSON.stringify({
      schemaVersion: '1.0',
      baseRevision: input.baseRevision,
      expectedVersion: input.expectedVersion,
    }),
  })
  return response.data
}

/**
 * 把成员异议保存为“待审批建议”。这个接口不会直接修改共享行程，
 * 所以即使成员误操作，组织者原计划也不会被覆盖。
 */
export async function createMemberChangeProposal(input: {
  participantSessionToken: string
  baseRevision: number
  expectedVersion: number
  fieldPath: SharedTripProposalField
  proposedValue: string | number
  reason: string
}): Promise<MemberSessionView> {
  const response = await request<MemberSessionView>('/api/v2/member-session/change-proposals', {
    method: 'POST',
    headers: { 'X-Participant-Session': input.participantSessionToken },
    body: JSON.stringify({
      schemaVersion: '1.0',
      baseRevision: input.baseRevision,
      expectedVersion: input.expectedVersion,
      fieldPath: input.fieldPath,
      proposedValue: input.proposedValue,
      reason: input.reason,
    }),
  })
  return response.data
}

export async function getOrganizerCollaboration(
  tripId: string,
  organizerToken: string,
): Promise<CollaborationAggregate> {
  const response = await request<CollaborationAggregate>(
    `/api/v2/trips/${encodeURIComponent(tripId)}/collaboration`,
    { headers: { 'X-Organizer-Token': organizerToken } },
  )
  return response.data
}

export async function resolveOrganizerConfirmationItem({
  state,
  itemId,
  relaxationId,
  organizerToken,
}: ResolveOrganizerInput): Promise<CollaborationAggregate> {
  const response = await request<CollaborationAggregate>(
    `/api/v2/trips/${encodeURIComponent(state.tripId)}/confirmation-items/${encodeURIComponent(itemId)}/resolve`,
    {
      method: 'POST',
      headers: {
        'X-Organizer-Token': organizerToken,
        'Idempotency-Key': idempotencyKey('s2-t029-organizer-resolve'),
      },
      body: JSON.stringify({
        schemaVersion: '1.0',
        baseRevision: state.currentRevision,
        expectedVersion: state.collaborationVersion,
        relaxationId,
      }),
    },
  )
  return response.data
}

/** 组织者的审批动作：批准会生成新修订，拒绝只记录结论并保留原计划。 */
export async function reviewMemberChangeProposal(input: {
  state: CollaborationAggregate
  proposalId: string
  decision: 'APPROVE' | 'REJECT'
  organizerToken: string
  organizerNote?: string
}): Promise<CollaborationAggregate> {
  const response = await request<CollaborationAggregate>(
    `/api/v2/trips/${encodeURIComponent(input.state.tripId)}/change-proposals/${encodeURIComponent(input.proposalId)}/review`,
    {
      method: 'POST',
      headers: {
        'X-Organizer-Token': input.organizerToken,
        'Idempotency-Key': newIdempotencyKey('member-proposal-review'),
      },
      body: JSON.stringify({
        schemaVersion: '1.0',
        baseRevision: input.state.currentRevision,
        expectedVersion: input.state.collaborationVersion,
        decision: input.decision,
        organizerNote: input.organizerNote?.trim() || null,
      }),
    },
  )
  return response.data
}
