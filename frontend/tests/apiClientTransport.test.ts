import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { resolveApiBaseUrl } from '../src/api/client.ts'

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
