const DRAFT_SCHEMA_VERSION = 1 as const
const MAX_DRAFT_AGE_MS = 30 * 24 * 60 * 60 * 1000

export function createPlannerLocalDraftWriteGate() {
  let persistenceAllowed = true
  return {
    canPersist: () => persistenceAllowed,
    blockAfterAuthoritativeCreation: () => { persistenceAllowed = false },
    allowAfterUserEdit: () => { persistenceAllowed = true },
  }
}

export type PlannerLocalDraftScope = 'standard' | `parent:${string}:day:${number}`

export interface PlannerLocalDraftData {
  entryMode: 'single' | 'group' | null
  questionnaireStarted: boolean
  step: number
  description: string
  answers: readonly string[]
  tripFields: { city: string; startDate: string; endDate: string }
  customTimeWindow: { startTime: string; endTime: string } | null
  routeFields: { start: string; end: string; budget: string }
  organizerNickname: string
  partyCount: number
  personalBudget: string
  assistanceMode: string
}

export interface PlannerLocalDraft extends Omit<PlannerLocalDraftData, 'answers'> {
  schemaVersion: typeof DRAFT_SCHEMA_VERSION
  savedAt: string
  answers: [string, string, string, string, string, string]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isStringRecord(value: unknown, keys: readonly string[]): value is Record<string, string> {
  return isRecord(value) && keys.every((key) => typeof value[key] === 'string')
}

function asDraft(value: unknown, now: Date): PlannerLocalDraft | null {
  if (!isRecord(value) || value.schemaVersion !== DRAFT_SCHEMA_VERSION) return null
  if (typeof value.savedAt !== 'string') return null
  const savedAt = new Date(value.savedAt)
  if (Number.isNaN(savedAt.getTime()) || now.getTime() - savedAt.getTime() > MAX_DRAFT_AGE_MS) return null
  if (value.entryMode !== 'single' && value.entryMode !== 'group' && value.entryMode !== null) return null
  if (typeof value.questionnaireStarted !== 'boolean' || typeof value.step !== 'number') return null
  if (!Number.isInteger(value.step) || value.step < 0 || value.step > 5) return null
  if (typeof value.description !== 'string' || typeof value.organizerNickname !== 'string' || typeof value.personalBudget !== 'string' || typeof value.assistanceMode !== 'string') return null
  if (!Array.isArray(value.answers) || value.answers.length !== 6 || value.answers.some((answer) => typeof answer !== 'string')) return null
  if (!isStringRecord(value.tripFields, ['city', 'startDate', 'endDate'])) return null
  if (!isStringRecord(value.routeFields, ['start', 'end', 'budget'])) return null
  if (typeof value.partyCount !== 'number') return null
  if (!Number.isInteger(value.partyCount) || value.partyCount < 1 || value.partyCount > 20) return null
  if (value.customTimeWindow !== null && !isStringRecord(value.customTimeWindow, ['startTime', 'endTime'])) return null

  return {
    schemaVersion: DRAFT_SCHEMA_VERSION,
    savedAt: value.savedAt,
    entryMode: value.entryMode,
    questionnaireStarted: value.questionnaireStarted,
    step: value.step,
    description: value.description,
    answers: [...value.answers] as PlannerLocalDraft['answers'],
    tripFields: { city: value.tripFields.city, startDate: value.tripFields.startDate, endDate: value.tripFields.endDate },
    customTimeWindow: value.customTimeWindow === null
      ? null
      : { startTime: value.customTimeWindow.startTime, endTime: value.customTimeWindow.endTime },
    routeFields: { start: value.routeFields.start, end: value.routeFields.end, budget: value.routeFields.budget },
    organizerNickname: value.organizerNickname,
    partyCount: value.partyCount,
    personalBudget: value.personalBudget,
    assistanceMode: value.assistanceMode,
  }
}

export function plannerLocalDraftScope(parentTripId: string | null, dayIndex: number | null): PlannerLocalDraftScope {
  return parentTripId && typeof dayIndex === 'number' && Number.isSafeInteger(dayIndex) && dayIndex >= 0
    ? `parent:${parentTripId}:day:${dayIndex}`
    : 'standard'
}

export function plannerLocalDraftKey(accountId: string, scope: PlannerLocalDraftScope): string {
  return `xingzhi:planner-local-draft:v1:${accountId}:${scope}`
}

export function savePlannerLocalDraft(
  storage: Storage,
  accountId: string,
  scope: PlannerLocalDraftScope,
  data: PlannerLocalDraftData,
  now = new Date(),
): boolean {
  const stored = asDraft({ schemaVersion: DRAFT_SCHEMA_VERSION, savedAt: now.toISOString(), ...data }, now)
  if (!stored) return false
  try {
    storage.setItem(plannerLocalDraftKey(accountId, scope), JSON.stringify(stored))
    return true
  } catch {
    return false
  }
}

export function persistPlannerFallbackDraft(
  storage: Storage,
  accountId: string,
  scope: PlannerLocalDraftScope,
  data: PlannerLocalDraftData,
  writeGate: ReturnType<typeof createPlannerLocalDraftWriteGate>,
): boolean {
  return writeGate.canPersist() && savePlannerLocalDraft(storage, accountId, scope, data)
}

export function loadPlannerLocalDraft(
  storage: Storage,
  accountId: string,
  scope: PlannerLocalDraftScope,
  now = new Date(),
): PlannerLocalDraft | null {
  const key = plannerLocalDraftKey(accountId, scope)
  try {
    const raw = storage.getItem(key)
    if (!raw) return null
    const draft = asDraft(JSON.parse(raw), now)
    if (draft) return draft
    storage.removeItem(key)
  } catch {
    try { storage.removeItem(key) } catch { /* Storage is unavailable. */ }
  }
  return null
}

export function clearPlannerLocalDraft(storage: Storage, accountId: string, scope: PlannerLocalDraftScope): void {
  try {
    storage.removeItem(plannerLocalDraftKey(accountId, scope))
  } catch {
    // Clearing a draft must never block the form flow when storage is unavailable.
  }
}

export function hasPlannerLocalDraft(storage: Storage, accountId: string): boolean {
  return loadPlannerLocalDraft(storage, accountId, 'standard') !== null
}
