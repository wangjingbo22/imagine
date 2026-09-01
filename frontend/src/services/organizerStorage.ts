import type { TripDraftInput } from '../domain/trip'

const organizerTokenPrefix = 'organizer-token:'
const planContextPrefix = 's2-plan-context:'

function readStorage(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key)
  } catch {
    return null
  }
}

function writeStorage(storage: Storage, key: string, value: string): void {
  try {
    storage.setItem(key, value)
  } catch {
    // Storage may be disabled or quota-limited; the current page state still
    // carries the token while the user stays in the same flow.
  }
}

function removeStorage(storage: Storage, key: string): void {
  try {
    storage.removeItem(key)
  } catch {
    // Ignore storage cleanup failures.
  }
}

function readClientState(key: string): string | null {
  return readStorage(window.sessionStorage, key) ?? readStorage(window.localStorage, key)
}

function writeClientState(key: string, value: string): void {
  writeStorage(window.sessionStorage, key, value)
  writeStorage(window.localStorage, key, value)
}

export function getStoredOrganizerToken(tripId: string): string | null {
  const key = `${organizerTokenPrefix}${tripId}`
  const sessionToken = readStorage(window.sessionStorage, key)
  if (sessionToken) {
    writeStorage(window.localStorage, key, sessionToken)
    return sessionToken
  }
  return readStorage(window.localStorage, key)
}

export function setStoredOrganizerToken(tripId: string, token: string): void {
  writeClientState(`${organizerTokenPrefix}${tripId}`, token)
}

export function getStoredPlanContext(tripId: string): { draft: TripDraftInput } | null {
  const key = `${planContextPrefix}${tripId}`
  const raw = readClientState(key)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as { draft?: TripDraftInput }
    return parsed.draft ? { draft: parsed.draft } : null
  } catch {
    removeStorage(window.sessionStorage, key)
    removeStorage(window.localStorage, key)
    return null
  }
}

export function setStoredPlanContext(tripId: string, draft: TripDraftInput): void {
  writeClientState(`${planContextPrefix}${tripId}`, JSON.stringify({ draft }))
}
