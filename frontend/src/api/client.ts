import type {
  ApiResponse,
  TripSchemaErrorResponse,
  ValidationIssue,
} from '../domain/trip'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  readonly code: number | string
  readonly issues: ValidationIssue[]

  constructor(code: number | string, message: string, issues: ValidationIssue[] = []) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.issues = issues
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

  const body = (await response.json()) as ApiResponse<T> | TripSchemaErrorResponse
  if (isTripSchemaError(body)) {
    throw new ApiError(
      body.code,
      body.errors.map((issue) => `${issue.path}: ${issue.message}`).join('; '),
      body.errors,
    )
  }

  if (!response.ok || body.code !== 200) {
    throw new ApiError(body.code, body.message || `HTTP ${response.status}`)
  }

  return body
}
