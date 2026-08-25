import type { EventDrivenReplanRequest } from '../domain/trip'

export function createExpenseChangeReplanRequest(): EventDrivenReplanRequest {
  return {
    schemaVersion: '1.0',
    reason: 'EXPENSE_CHANGE',
  }
}

export function parseYuanAmountToCents(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null

  const yuan = Number(trimmed)
  if (!Number.isFinite(yuan) || yuan < 0) return null

  return Math.round(yuan * 100)
}
