const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const recommendationPathPattern = /^\/recommendation\/([0-9a-f-]+)$/i

export function safeReturnPath(search: string): string | null {
  const returnTo = new URLSearchParams(search).get('returnTo')
  if (returnTo === '/parent-join' || returnTo === '/model-settings') return returnTo
  if (!returnTo || returnTo.includes('#')) return null

  const separatorIndex = returnTo.indexOf('?')
  const pathname = separatorIndex === -1 ? returnTo : returnTo.slice(0, separatorIndex)
  const query = separatorIndex === -1 ? '' : returnTo.slice(separatorIndex + 1)
  const match = recommendationPathPattern.exec(pathname)
  if (!match || !uuidPattern.test(match[1])) return null

  const params = new URLSearchParams(query)
  const allowedKeys = new Set(['parentTripId', 'dayIndex'])
  if ([...params.keys()].some((key) => !allowedKeys.has(key))) return null
  if ([...allowedKeys].some((key) => params.getAll(key).length > 1)) return null

  const parentTripId = params.get('parentTripId')
  if (parentTripId && !uuidPattern.test(parentTripId)) return null
  const dayIndex = params.get('dayIndex')
  if (dayIndex !== null && !/^(0|[1-9]\d*)$/.test(dayIndex)) return null
  return returnTo
}
