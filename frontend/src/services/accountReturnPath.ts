const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const recommendationPathPattern = /^\/recommendation\/([0-9a-f-]+)$/i
const planPathPattern = /^\/plan$/

function hasOnlySingleValues(params: URLSearchParams, allowedKeys: Set<string>): boolean {
  return ![...params.keys()].some((key) => !allowedKeys.has(key)) &&
    ![...allowedKeys].some((key) => params.getAll(key).length > 1)
}

function isSafePlanReturnPath(returnTo: string, pathname: string, query: string): boolean {
  if (!planPathPattern.test(pathname)) return false
  const params = new URLSearchParams(query)
  const allowedKeys = new Set(['mode', 'parentTripId', 'dayIndex', 'city', 'date', 'budget'])
  if (!hasOnlySingleValues(params, allowedKeys)) return false

  const mode = params.get('mode')
  if (mode !== null && mode !== 'single' && mode !== 'group') return false
  const parentTripId = params.get('parentTripId')
  const dayIndex = params.get('dayIndex')
  if ((parentTripId === null) !== (dayIndex === null)) return false
  if (parentTripId && !uuidPattern.test(parentTripId)) return false
  if (dayIndex !== null && !/^(0|[1-9]\d*)$/.test(dayIndex)) return false
  const city = params.get('city')
  if (city !== null && (!city.trim() || city.length > 80)) return false
  const date = params.get('date')
  if (date !== null && !/^\d{4}-\d{2}-\d{2}$/.test(date)) return false
  const budget = params.get('budget')
  if (budget !== null && !/^\d+$/.test(budget)) return false
  return !returnTo.includes('#')
}

export function safeReturnPath(search: string): string | null {
  const returnTo = new URLSearchParams(search).get('returnTo')
  if (returnTo === '/parent-join' || returnTo === '/model-settings') return returnTo
  if (!returnTo || returnTo.includes('#')) return null

  const separatorIndex = returnTo.indexOf('?')
  const pathname = separatorIndex === -1 ? returnTo : returnTo.slice(0, separatorIndex)
  const query = separatorIndex === -1 ? '' : returnTo.slice(separatorIndex + 1)
  if (isSafePlanReturnPath(returnTo, pathname, query)) return returnTo
  const match = recommendationPathPattern.exec(pathname)
  if (!match || !uuidPattern.test(match[1])) return null

  const params = new URLSearchParams(query)
  const allowedKeys = new Set(['parentTripId', 'dayIndex'])
  if (!hasOnlySingleValues(params, allowedKeys)) return null

  const parentTripId = params.get('parentTripId')
  if (parentTripId && !uuidPattern.test(parentTripId)) return null
  const dayIndex = params.get('dayIndex')
  if (dayIndex !== null && !/^(0|[1-9]\d*)$/.test(dayIndex)) return null
  return returnTo
}
