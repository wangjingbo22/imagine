const KEY_STORAGE = 'xingzhi:user-llm-key'
const MODEL_STORAGE = 'xingzhi:user-llm-model'

export const USER_MODEL_OPTIONS = [
  { id: 'qwen-turbo', name: 'Qwen Turbo', description: '更快，适合日常行程解析' },
  { id: 'qwen-plus', name: 'Qwen Plus', description: '均衡的理解与响应速度' },
  { id: 'qwen-max', name: 'Qwen Max', description: '更强的复杂需求理解' },
] as const

export function userLlmHeaders(): Record<string, string> {
  const apiKey = window.sessionStorage.getItem(KEY_STORAGE)?.trim()
  const model = window.sessionStorage.getItem(MODEL_STORAGE)?.trim()
  return apiKey && model ? { 'X-User-Llm-Key': apiKey, 'X-User-Llm-Model': model } : {}
}

export function getUserLlmSettings() {
  return {
    apiKey: window.sessionStorage.getItem(KEY_STORAGE) ?? '',
    model: window.sessionStorage.getItem(MODEL_STORAGE) ?? 'qwen-plus',
  }
}

export function saveUserLlmSettings(apiKey: string, model: string) {
  window.sessionStorage.setItem(KEY_STORAGE, apiKey.trim())
  window.sessionStorage.setItem(MODEL_STORAGE, model)
}

export function clearUserLlmSettings() {
  window.sessionStorage.removeItem(KEY_STORAGE)
  window.sessionStorage.removeItem(MODEL_STORAGE)
}
