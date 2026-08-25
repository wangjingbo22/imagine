import type {
  ApiResponse,
  AddressResolution,
  CityResolution,
  CityContext,
  CreateSingleDayTrip,
  ExecutionEventInput,
  PlanSnapshot,
  PlanV2DecisionResult,
  PlanVersionProposal,
  PlanVersionDiff,
  Place,
  PlaceCollection,
  GeoPoint,
  RouteCollection,
  TravelMode,
  StoredPlanVersion,
  TripDraftParseInput,
  TripDraftParseResult,
  TripSummary,
  TripPlanState,
} from '../domain/trip'
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
  createDraft(input: TripDraftParseInput) {
    return request<TripDraftParseResult>('/api/v1/trips/drafts/parse', {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },

  confirmDraft(input: TripDraftParseInput) {
    return request<CreateSingleDayTrip>('/api/v1/trips/drafts/confirm', {
      method: 'POST',
      body: JSON.stringify(input),
    })
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

  suggestPlaces(
    tripId: string,
    cityContext: CityContext,
    keywords: string,
    types: string[] = [],
    limit = 10,
  ) {
    return request<PlaceCollection>('/api/v1/places/suggestions', {
      method: 'POST',
      body: JSON.stringify({
        schemaVersion: '1.0', tripId, cityContext, keywords, types, limit,
      }),
    })
  },

  searchPlaces(
    tripId: string,
    cityContext: CityContext,
    keywords: string,
    types: string[] = [],
    page = 1,
    pageSize = 20,
  ) {
    return request<PlaceCollection>('/api/v1/places/search', {
      method: 'POST',
      body: JSON.stringify({
        schemaVersion: '1.0', tripId, cityContext, keywords, types, page, pageSize,
      }),
    })
  },

  searchNearbyPlaces(
    tripId: string,
    cityContext: CityContext,
    center: GeoPoint,
    filters: { keywords?: string; types?: string[] },
    radiusMeters = 3_000,
    page = 1,
    pageSize = 20,
  ) {
    return request<PlaceCollection>('/api/v1/places/nearby', {
      method: 'POST',
      body: JSON.stringify({
        schemaVersion: '1.0',
        tripId,
        cityContext,
        center,
        radiusMeters,
        keywords: filters.keywords ?? null,
        types: filters.types ?? [],
        page,
        pageSize,
      }),
    })
  },

  getPlaceDetail(tripId: string, cityContext: CityContext, placeId: string) {
    return request<Place>('/api/v1/places/detail', {
      method: 'POST',
      body: JSON.stringify({ schemaVersion: '1.0', tripId, cityContext, placeId }),
    })
  },

  forwardGeocode(tripId: string, cityContext: CityContext, address: string) {
    return request<AddressResolution>('/api/v1/geocoding/forward', {
      method: 'POST',
      body: JSON.stringify({ schemaVersion: '1.0', tripId, cityContext, address }),
    })
  },

  reverseGeocode(tripId: string, cityContext: CityContext, location: GeoPoint) {
    return request<AddressResolution>('/api/v1/geocoding/reverse', {
      method: 'POST',
      body: JSON.stringify({ schemaVersion: '1.0', tripId, cityContext, location }),
    })
  },

  planRoute(
    tripId: string,
    cityContext: CityContext,
    origin: GeoPoint,
    destination: GeoPoint,
    mode: TravelMode,
    strategy: number | null = null,
  ) {
    return request<RouteCollection>('/api/v1/routes/plan', {
      method: 'POST',
      body: JSON.stringify({
        schemaVersion: '1.0', tripId, cityContext, origin, destination, mode, strategy,
      }),
    })
  },

  getPlanDiff(tripId: string, planId: string) {
    return request<PlanVersionDiff>(
      `/api/v1/trips/${tripId}/plan-versions/${planId}/diff`,
    )
  },

  acceptPlanV2(tripId: string, planId: string) {
    return request<PlanV2DecisionResult>(
      `/api/v1/trips/${tripId}/plan-versions/${planId}/accept`,
      { method: 'POST' },
    )
  },

  rejectPlanV2(tripId: string, planId: string) {
    return request<PlanV2DecisionResult>(
      `/api/v1/trips/${tripId}/plan-versions/${planId}/reject`,
      { method: 'POST' },
    )
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
