import type {
  ApiResponse,
  ExecutionEventInput,
  PlanSnapshot,
  TripDraftInput,
  TripSummary,
} from '../domain/trip'
import { mockPlanV1, mockPlanV2, mockSummary } from '../mocks/trip'
import { request } from './client'

const USE_MOCK_API = (import.meta.env.VITE_USE_MOCK_API ?? 'true') === 'true'

async function mockResponse<T>(data: T): Promise<ApiResponse<T>> {
  await new Promise((resolve) => window.setTimeout(resolve, 480))
  return { code: 200, message: 'success', data }
}

export const tripApi = {
  createDraft(input: TripDraftInput) {
    if (USE_MOCK_API) {
      return mockResponse({ tripId: 'trip-demo-2026', draft: input })
    }
    return request<{ tripId: string; draft: TripDraftInput }>('/api/v1/trips/drafts', {
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
    if (USE_MOCK_API) {
      return mockResponse({ tripId, planId, status: 'CURRENT' })
    }
    return request<{ tripId: string; planId: string; status: string }>(
      `/api/v1/trips/${tripId}/plans/${planId}/confirm`,
      { method: 'POST' },
    )
  },

  getTrip(tripId: string) {
    if (USE_MOCK_API) {
      return mockResponse({ tripId, currentPlan: mockPlanV1, events: [] })
    }
    return request<{ tripId: string; currentPlan: PlanSnapshot; events: unknown[] }>(
      `/api/v1/trips/${tripId}`,
    )
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

  replan(tripId: string) {
    if (USE_MOCK_API) {
      return mockResponse(mockPlanV2)
    }
    return request<PlanSnapshot>(`/api/v1/trips/${tripId}/replans`, { method: 'POST' })
  },

  decidePlan(tripId: string, planId: string, decision: 'ACCEPT' | 'REJECT') {
    if (USE_MOCK_API) {
      return mockResponse({
        tripId,
        planId,
        status: decision === 'ACCEPT' ? 'CURRENT' : 'REJECTED',
      })
    }
    return request<{ tripId: string; planId: string; status: string }>(
      `/api/v1/trips/${tripId}/plans/${planId}/decision`,
      {
        method: 'POST',
        body: JSON.stringify({ decision }),
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
