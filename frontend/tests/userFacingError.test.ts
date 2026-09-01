import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiError } from '../src/api/client.ts'
import { userFacingErrorMessage } from '../src/utils/userFacingError.ts'

test('user-facing errors remove internal codes, ids, and field paths', () => {
  const error = new ApiError(
    'LLM_NOT_CONFIGURED',
    '本次模型服务不可用（LLM_NOT_CONFIGURED），participant.profile 缺少内容，行程 fe30839f-fdb3-4b2e-a1a3-e53cd2dc0774 未创建。',
  )
  const message = userFacingErrorMessage(error, '操作失败，请重试。')

  assert.equal(message, '本次模型服务不可用，缺少内容，行程 未创建。')
  assert.doesNotMatch(message, /LLM_NOT_CONFIGURED|participant\.profile|fe30839f/)
})

test('user-facing errors replace English-only and HTTP failures with contextual copy', () => {
  assert.equal(userFacingErrorMessage(new Error('Internal Server Error'), '保存失败，请重试。'), '保存失败，请重试。')
  assert.equal(userFacingErrorMessage(new Error('服务端请求失败（HTTP 500）'), '加载失败，请重试。'), '加载失败，请重试。')
  assert.equal(userFacingErrorMessage(new Error('网络连接中断，请稍后重试。'), '加载失败，请重试。'), '网络连接中断，请稍后重试。')
})
