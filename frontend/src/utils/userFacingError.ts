const parenthesizedCodePattern = /[（(]\s*[A-Z][A-Z0-9]*(?:[_.][A-Z0-9]+)+\s*[）)]/g
const internalCodePattern = /\b[A-Z][A-Z0-9]*(?:[_.][A-Z0-9]+)+\b/g
const uuidPattern = /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/gi
const fieldPathPattern = /\b[a-z][A-Za-z0-9]*(?:(?:\[\d+\])|(?:\.[A-Za-z][A-Za-z0-9]*))+\b/g

export function userFacingErrorMessage(error: unknown, fallback: string): string {
  const message = typeof error === 'string'
    ? error
    : error instanceof Error
      ? error.message
      : ''

  if (!message.trim()) return fallback

  const cleaned = message
    .replace(parenthesizedCodePattern, '')
    .replace(internalCodePattern, '')
    .replace(uuidPattern, '')
    .replace(fieldPathPattern, '')
    .replace(/[（(]\s*HTTP\s*\d{3}\s*[）)]/gi, '')
    .replace(/[（(]\s*[）)]/g, '')
    .replace(/\s+([，。；：！？])/g, '$1')
    .replace(/([，。；：！？])\s+/g, '$1')
    .replace(/([：；，])\s*([：；，])/g, '$1')
    .replace(/\s{2,}/g, ' ')
    .replace(/^[\s:：;；,，/.-]+|[\s:：;；,，/.-]+$/g, '')
    .trim()

  if (!/[\u3400-\u9fff]/.test(cleaned)) return fallback
  if (/^服务端请求失败[。.]?$/.test(cleaned)) return fallback
  return cleaned
}
