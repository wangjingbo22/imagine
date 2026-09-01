export const PARENT_TRIP_POLL_INTERVAL_MS = 5000

const PENDING_INVITATION_KEY = 'parent-trip:pending-invitation'

type PendingInvitation = {
  invitationToken: string
  idempotencyKey: string
}

export function parentTripOrganizerTokenKey(parentTripId: string): string {
  return `parent-trip-token:${parentTripId}`
}

export function parentTripMemberSessionKey(parentTripId: string): string {
  return `parent-trip-member-session:${parentTripId}`
}

export function parseParentInvitationToken(value?: string): string | null {
  const normalized = value?.trim() ?? ''
  return /^[A-Za-z0-9_-]{43}$/.test(normalized) ? normalized : null
}

export function createParentIdempotencyKey(scope: 'invite' | 'redeem'): string {
  return `parent-${scope}-${crypto.randomUUID()}`
}

export function capturePendingInvitation(
  invitationToken: string,
): PendingInvitation {
  const existing = readPendingInvitation()
  if (existing?.invitationToken === invitationToken) return existing
  const pending = {
    invitationToken,
    idempotencyKey: createParentIdempotencyKey('redeem'),
  }
  window.sessionStorage.setItem(PENDING_INVITATION_KEY, JSON.stringify(pending))
  return pending
}

export function readPendingInvitation(): PendingInvitation | null {
  const value = window.sessionStorage.getItem(PENDING_INVITATION_KEY)
  if (!value) return null
  try {
    const parsed = JSON.parse(value) as Partial<PendingInvitation>
    if (
      parseParentInvitationToken(parsed.invitationToken) &&
      typeof parsed.idempotencyKey === 'string' &&
      parsed.idempotencyKey.length >= 16
    ) {
      return parsed as PendingInvitation
    }
  } catch {
    // Invalid pending state is cleared below.
  }
  window.sessionStorage.removeItem(PENDING_INVITATION_KEY)
  return null
}

export function clearPendingInvitation(): void {
  window.sessionStorage.removeItem(PENDING_INVITATION_KEY)
}

export function storeParentMemberSession(
  parentTripId: string,
  memberSessionToken: string,
): void {
  window.sessionStorage.setItem(
    parentTripMemberSessionKey(parentTripId),
    memberSessionToken,
  )
}

export function readParentMemberSession(parentTripId: string): string | null {
  return window.sessionStorage.getItem(parentTripMemberSessionKey(parentTripId))
}

export function clearParentMemberSession(parentTripId: string): void {
  window.sessionStorage.removeItem(parentTripMemberSessionKey(parentTripId))
}
