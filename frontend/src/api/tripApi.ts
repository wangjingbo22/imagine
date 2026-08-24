import type {
  ApiResponse,
  CityResolution,
  CreateSingleDayTrip,
  ExecutionEventInput,
  PlanSnapshot,
  PlanVersionProposal,
  StoredPlanVersion,
  TripDraftInput,
  TripSummary,
  TripPlanState,
} from '../domain/trip'
import { ApiError } from './client'
import { mockPlanV1, mockSummary } from '../mocks/trip'
import { request } from './client'

const USE_MOCK_API = (import.meta.env.VITE_USE_MOCK_API ?? 'true') === 'true'
export const USE_PLAN_VERSION_API =
  (import.meta.env.VITE_USE_PLAN_VERSION_API ?? 'true') === 'true'

async function mockResponse<T>(data: T): Promise<ApiResponse<T>> {
  await new Promise((resolve) => window.setTimeout(resolve, 480))
  return { code: 200, message: 'success', data }
}

export const tripApi = {
  createDraft(input: TripDraftInput) {
    if (USE_MOCK_API) {
      return mockResponse({ tripId: crypto.randomUUID(), draft: input })
    }
    throw new ApiError(
      'TRIP_DRAFT_ENDPOINT_UNREGISTERED',
      '自然语言表单解析接口尚未由后端登记；请先通过解析/城市 Provider 生成 CreateSingleDayTrip。',
    )
  },

  submitNormalizedTrip(path: string, input: CreateSingleDayTrip) {
    if (USE_MOCK_API) {
      return mockResponse(input)
    }
    return request<CreateSingleDayTrip>(path, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },

  generatePlan(tripId: string) {
    if (USE_MOCK_API) {
      return mockResponse(mockPlanV1)
    }
    return request<PlanSnapshot>(`/api/v1/trips/${tripId}/plans`, { method: 'POST' })
  },

  confirmConstraints<TConstraints>(tripId: string, constraints: TConstraints) {
    if (USE_MOCK_API) {
      return mockResponse({ tripId, status: 'CONSTRAINT_CONFIRMED', constraints })
    }
    return request<{ tripId: string; status: string; constraints: TConstraints }>(
      `/api/v1/trips/${tripId}/constraints`,
      {
        method: 'PUT',
        body: JSON.stringify(constraints),
      },
    )
  },

  confirmPlan(tripId: string, planId: string) {
    if (!USE_PLAN_VERSION_API) {
      return mockResponse({ tripId, planId, status: 'CURRENT' })
    }
    return request<{
      tripId: string
      planId: string
      tripStatus: 'CONFIRMED'
      planStatus: 'CURRENT'
    }>(
      `/api/v1/trips/${tripId}/plan-versions/${planId}/confirm`,
      { method: 'POST' },
    )
  },

  resolveCity(cityName: string) {
    return request<CityResolution>('/api/v1/cities/resolve', {
      method: 'POST',
      body: JSON.stringify({ schemaVersion: '1.0', cityName }),
    })
  },

  registerPlanVersion(tripId: string, proposal: PlanVersionProposal) {
    return request<StoredPlanVersion>(`/api/v1/trips/${tripId}/plan-versions`, {
      method: 'POST',
      body: JSON.stringify(proposal),
    })
  },

  startExecution(tripId: string) {
    return request<{
      tripId: string
      planId: string
      tripStatus: 'EXECUTING'
      planStatus: 'CURRENT'
    }>(`/api/v1/trips/${tripId}/execution/start`, { method: 'POST' })
  },

  getTrip(tripId: string): Promise<ApiResponse<TripPlanState>> {
    if (!USE_PLAN_VERSION_API) {
      return mockResponse({
        tripId,
        tripStatus: 'EXECUTING',
        currentPlan: null,
        proposedPlans: [],
        events: [],
      })
    }
    return request<TripPlanState>(`/api/v1/trips/${tripId}`)
  },

  createExecutionEvent(tripId: string, input: ExecutionEventInput) {
    if (USE_MOCK_API) {
      return mockResponse({ eventId: crypto.randomUUID(), ...input })
    }
    return request<{ eventId: string }>(`/api/v1/trips/${tripId}/events`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },

  updatePlan(tripId: string, feedback: string) {
    if (USE_MOCK_API) {
      return mockResponse({
        tripId,
        currentPlan: mockPlanV1,
        feedback,
        status: 'UPDATED',
      })
    }
    return request<{ tripId: string; currentPlan: PlanSnapshot; status: string }>(
      `/api/v1/trips/${tripId}/plan-feedback`,
      {
        method: 'POST',
        body: JSON.stringify({ feedback }),
      },
    )
  },

  getSummary(tripId: string) {
    if (USE_MOCK_API) {
      return mockResponse(mockSummary)
    }
    return request<TripSummary>(`/api/v1/trips/${tripId}/summary`)
  },
}
