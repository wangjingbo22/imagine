import type {
  ApiResponse,
  TripSchemaErrorResponse,
  ValidationIssue,
} from '../domain/trip'

export function resolveApiBaseUrl(configuredValue?: string): string {
  const normalized = configuredValue?.trim().replace(/\/+$/, '')
  return normalized || ''
}

// Production requests must use the web service's same-origin proxy so the
// account session cookie is sent consistently. Development may opt into a
// separate API target when Vite is not proxying it.
const API_BASE_URL = import.meta.env?.PROD
  ? ''
  : resolveApiBaseUrl(import.meta.env?.VITE_API_BASE_URL)

export class ApiError extends Error {
  readonly code: number | string
  readonly issues: ValidationIssue[]
  readonly details: Array<Record<string, unknown>>

  constructor(
    code: number | string,
    message: string,
    issues: ValidationIssue[] = [],
    details: Array<Record<string, unknown>> = [],
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.issues = issues
    this.details = details
  }
}

function isTripSchemaError(body: unknown): body is TripSchemaErrorResponse {
  if (!body || typeof body !== 'object') {
    return false
  }
  const candidate = body as Partial<TripSchemaErrorResponse>
  return (
    (candidate.code === 'TRIP_SCHEMA_INVALID' ||
      candidate.code === 'TRIP_CONFIRMATION_REQUIRED') &&
    candidate.schemaVersion === '1.0' &&
    Array.isArray(candidate.errors)
  )
}

type ErrorBody = {
  code?: number | string
  message?: string
  errors?: Array<Record<string, unknown>>
}

function isObject(body: unknown): body is Record<string, unknown> {
  return body !== null && typeof body === 'object'
}

async function readResponseBody(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) {
    return undefined
  }
  try {
    return JSON.parse(text) as unknown
  } catch {
    if (!response.ok) {
      throw new ApiError(
        response.status,
        `服务端请求失败（HTTP ${response.status}）`,
      )
    }
    throw new ApiError('API_RESPONSE_INVALID', '服务端返回了无法识别的数据')
  }
}

export async function requestBare<T>(
  path: string,
  init?: RequestInit,
): Promise<{ data: T; headers: Headers }> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  const body = await readResponseBody(response)
  if (isTripSchemaError(body)) {
    throw new ApiError(
      body.code,
      body.errors.map((issue) => `${issue.path}: ${issue.message}`).join('; '),
      body.errors,
      body.errors as unknown as Array<Record<string, unknown>>,
    )
  }
  if (!response.ok) {
    const error = (isObject(body) ? body : {}) as ErrorBody
    throw new ApiError(
      error.code ?? response.status,
      error.message || `HTTP ${response.status}`,
      [],
      Array.isArray(error.errors) ? error.errors : [],
    )
  }
  return { data: body as T, headers: response.headers }
}

export async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<ApiResponse<T>> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  const body = await readResponseBody(response)
  if (isTripSchemaError(body)) {
    throw new ApiError(
      body.code,
      body.errors.map((issue) => `${issue.path}: ${issue.message}`).join('; '),
      body.errors,
      body.errors as unknown as Array<Record<string, unknown>>,
    )
  }

  if (!isObject(body)) {
    if (!response.ok) {
      throw new ApiError(response.status, `服务端请求失败（HTTP ${response.status}）`)
    }
    throw new ApiError('API_RESPONSE_INVALID', '服务端返回了无法识别的数据')
  }

  const error = body as ErrorBody
  if (!response.ok || error.code !== 200) {
    const details = Array.isArray(error.errors) ? error.errors : []
    throw new ApiError(error.code ?? response.status, error.message || `HTTP ${response.status}`, [], details)
  }

  return body as unknown as ApiResponse<T>
}
