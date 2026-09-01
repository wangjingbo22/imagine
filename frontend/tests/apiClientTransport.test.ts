import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import {
  ApiError,
  request,
  requestBare,
  resolveApiBaseUrl,
} from '../src/api/client.ts'

test('local API requests use the same-origin Vite proxy by default', async () => {
  assert.equal(resolveApiBaseUrl(undefined), '')
  assert.equal(resolveApiBaseUrl(''), '')
  assert.equal(resolveApiBaseUrl('   '), '')

  const viteConfig = await readFile(
    new URL('../vite.config.ts', import.meta.url),
    'utf8',
  )
  assert.match(viteConfig, /['"]\/api['"]\s*:\s*\{/)
  assert.match(viteConfig, /VITE_DEV_PROXY_TARGET/)
  assert.match(viteConfig, /['"]http:\/\/127\.0\.0\.1:8000['"]/)
})

test('an explicit deployment API origin is normalized without changing it', () => {
  assert.equal(
    resolveApiBaseUrl(' https://api.example.test/// '),
    'https://api.example.test',
  )
})

test('plain-text server errors become readable API errors', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response('Internal Server Error', { status: 500 })
  try {
    for (const operation of [request('/broken'), requestBare('/broken')]) {
      await assert.rejects(operation, (error: unknown) => {
        assert.ok(error instanceof ApiError)
        assert.equal(error.code, 500)
        assert.equal(error.message, '服务端请求失败（HTTP 500）')
        return true
      })
    }
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('invalid successful responses are reported without JSON parser details', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response('not-json', { status: 200 })
  try {
    await assert.rejects(request('/broken'), (error: unknown) => {
      assert.ok(error instanceof ApiError)
      assert.equal(error.code, 'API_RESPONSE_INVALID')
      assert.equal(error.message, '服务端返回了无法识别的数据')
      return true
    })
  } finally {
    globalThis.fetch = originalFetch
  }
})
