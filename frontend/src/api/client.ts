import type {
  ApiResponse,
  TripSchemaErrorResponse,
  ValidationIssue,
} from '../domain/trip'

const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

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

export async function requestBare<T>(
  path: string,
  init?: RequestInit,
): Promise<{ data: T; headers: Headers }> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  const body = (await response.json()) as T | TripSchemaErrorResponse | {
    code?: number | string
    message?: string
    errors?: Array<Record<string, unknown>>
  }
  if (isTripSchemaError(body)) {
    throw new ApiError(
      body.code,
      body.errors.map((issue) => `${issue.path}: ${issue.message}`).join('; '),
      body.errors,
      body.errors as unknown as Array<Record<string, unknown>>,
    )
  }
  if (!response.ok) {
    const error = body as {
      code?: number | string
      message?: string
      errors?: Array<Record<string, unknown>>
    }
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
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  const body = (await response.json()) as ApiResponse<T> | TripSchemaErrorResponse | {
    code?: number | string
    message?: string
    errors?: Array<Record<string, unknown>>
  }
  if (isTripSchemaError(body)) {
    throw new ApiError(
      body.code,
      body.errors.map((issue) => `${issue.path}: ${issue.message}`).join('; '),
      body.errors,
      body.errors as unknown as Array<Record<string, unknown>>,
    )
  }

  if (!response.ok || body.code !== 200) {
    const details = 'errors' in body && Array.isArray(body.errors) ? body.errors : []
    throw new ApiError(body.code ?? response.status, body.message || `HTTP ${response.status}`, [], details)
  }

  return body as ApiResponse<T>
}
