import { request } from './client'
import type { ParentTrip } from '../domain/parentTrip'

const headers = (parentToken: string) => ({ 'X-Parent-Trip-Token': parentToken })

export async function createParentTrip(input: {
  parentTripId: string; title: string; cityName: string; startDate: string
  dayBudgetCents: number[]; parentToken: string
}): Promise<ParentTrip> {
  return (await request<ParentTrip>('/api/v3/parent-trips', { method: 'POST',
    headers: headers(input.parentToken), body: JSON.stringify({ schemaVersion: '1.0', ...input, parentToken: undefined }) })).data
}

export async function getParentTrip(parentTripId: string, parentToken: string): Promise<ParentTrip> {
  return (await request<ParentTrip>(`/api/v3/parent-trips/${parentTripId}`, { headers: headers(parentToken) })).data
}

export async function linkParentTripDay(input: { parentTripId: string; dayIndex: number
  childTripId: string; parentToken: string; organizerToken: string }): Promise<ParentTrip> {
  return (await request<ParentTrip>(`/api/v3/parent-trips/${input.parentTripId}/days/${input.dayIndex}/child`, {
    method: 'PUT', headers: { ...headers(input.parentToken), 'X-Organizer-Token': input.organizerToken },
    body: JSON.stringify({ schemaVersion: '1.0', childTripId: input.childTripId }),
  })).data
}
