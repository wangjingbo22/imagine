import { request } from './client'
import type {
  ParentTrip,
  ParentTripInvitationCreated,
  ParentTripInvitationRedeemed,
  ParentTripSyncView,
} from '../domain/parentTrip'

const organizerHeaders = (parentToken: string) => ({
  'X-Parent-Trip-Token': parentToken,
})
const memberHeaders = (memberSessionToken: string) => ({
  'X-Parent-Member-Session': memberSessionToken,
})

export async function createParentTrip(input: {
  parentTripId: string; title: string; cityName: string; startDate: string
  dayBudgetCents: number[]; parentToken: string
}): Promise<ParentTrip> {
  const { parentToken, ...payload } = input
  return (await request<ParentTrip>('/api/v3/parent-trips', {
    method: 'POST',
    headers: organizerHeaders(parentToken),
    body: JSON.stringify({ schemaVersion: '1.0', ...payload }),
  })).data
}

export async function getParentTrip(parentTripId: string, parentToken: string): Promise<ParentTrip> {
  return (await request<ParentTrip>(`/api/v3/parent-trips/${parentTripId}`, {
    headers: organizerHeaders(parentToken),
  })).data
}

export async function linkParentTripDay(input: { parentTripId: string; dayIndex: number
  childTripId: string; parentToken: string; organizerToken: string }): Promise<ParentTrip> {
  return (await request<ParentTrip>(`/api/v3/parent-trips/${input.parentTripId}/days/${input.dayIndex}/child`, {
    method: 'PUT', headers: { ...organizerHeaders(input.parentToken), 'X-Organizer-Token': input.organizerToken },
    body: JSON.stringify({ schemaVersion: '1.0', childTripId: input.childTripId }),
  })).data
}

export async function getParentTripSync(input: {
  parentTripId: string
  parentToken?: string
  memberSessionToken?: string
}): Promise<ParentTripSyncView> {
  if (Boolean(input.parentToken) === Boolean(input.memberSessionToken)) {
    throw new Error('父行程同步必须且只能提供一种身份凭证。')
  }
  const headers = input.parentToken
    ? organizerHeaders(input.parentToken)
    : memberHeaders(input.memberSessionToken ?? '')
  return (await request<ParentTripSyncView>(
    `/api/v3/parent-trips/${input.parentTripId}/sync`,
    { headers },
  )).data
}

export async function createParentTripInvitation(input: {
  parentTripId: string
  parentToken: string
  expectedSyncVersion: number
  idempotencyKey: string
  expiresInHours?: number
}): Promise<ParentTripInvitationCreated> {
  return (await request<ParentTripInvitationCreated>(
    `/api/v3/parent-trips/${input.parentTripId}/invitations`,
    {
      method: 'POST',
      headers: {
        ...organizerHeaders(input.parentToken),
        'Idempotency-Key': input.idempotencyKey,
      },
      body: JSON.stringify({
        schemaVersion: '1.0',
        expectedSyncVersion: input.expectedSyncVersion,
        expiresInHours: input.expiresInHours ?? 72,
      }),
    },
  )).data
}

export async function redeemParentTripInvitation(input: {
  invitationToken: string
  idempotencyKey: string
}): Promise<ParentTripInvitationRedeemed> {
  return (await request<ParentTripInvitationRedeemed>(
    '/api/v3/parent-trip-invitations/redeem',
    {
      method: 'POST',
      headers: { 'Idempotency-Key': input.idempotencyKey },
      body: JSON.stringify({
        schemaVersion: '1.0',
        token: input.invitationToken,
      }),
    },
  )).data
}

export async function updateParentTripMemberProfile(input: {
  parentTripId: string
  memberSessionToken: string
  expectedSyncVersion: number
  nickname: string
  interests: string[]
  budgetCapCents: number | null
}): Promise<ParentTripSyncView> {
  return (await request<ParentTripSyncView>(
    `/api/v3/parent-trips/${input.parentTripId}/member-profile`,
    {
      method: 'PUT',
      headers: memberHeaders(input.memberSessionToken),
      body: JSON.stringify({
        schemaVersion: '1.0',
        expectedSyncVersion: input.expectedSyncVersion,
        nickname: input.nickname,
        interests: input.interests,
        budgetCapCents: input.budgetCapCents,
      }),
    },
  )).data
}
