import { request } from './client'
import type { CollaborationAggregate } from '../domain/collaboration'

type ResolveOrganizerInput = {
  state: CollaborationAggregate
  itemId: string
  relaxationId: string
  organizerToken: string
}

function idempotencyKey(prefix: string): string {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`
  return `${prefix}-${suffix}`
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
