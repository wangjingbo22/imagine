import type {
  ApiResponse,
  AddressResolution,
  AssistanceProfile,
  CandidatePlanRequest,
  CandidatePlanReview,
  CandidateReviewConfirmationInput,
  CityResolution,
  CityContext,
  ConstraintConfirmationResult,
  ConstraintProfileState,
  CreateSingleDayTrip,
  ExecutionEvent,
  ExecutionEventInput,
  PlanV2DecisionResult,
  PlanVersionDiff,
  Place,
  PlaceCollection,
  GeoPoint,
  RouteCollection,
  ReplanGenerationRequest,
  RegisteredReplan,
  TravelMode,
  StoredPlanVersion,
  TripDraftParseInput,
  TripDraftParseResult,
  TripSummary,
  TripPlanState,
} from '../domain/trip'
import { request } from './client'

export const USE_PLAN_VERSION_API =
  (import.meta.env.VITE_USE_PLAN_VERSION_API ?? 'true') === 'true'
export const USE_WORKFLOW_API =
  (import.meta.env.VITE_USE_WORKFLOW_API ?? 'true') === 'true'

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

  saveConstraintDraft(tripId: string, profile: AssistanceProfile) {
    return request<ConstraintProfileState>(`/api/v1/trips/${tripId}/constraints`, {
      method: 'PUT',
      body: JSON.stringify(profile),
    })
  },

  confirmConstraints(tripId: string) {
    return request<ConstraintConfirmationResult>(
      `/api/v1/trips/${tripId}/constraints/confirm`,
      { method: 'POST' },
    )
  },

  getConstraints(tripId: string) {
    return request<ConstraintProfileState>(`/api/v1/trips/${tripId}/constraints`)
  },

  confirmPlan(tripId: string, planId: string) {
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

  generatePlanVersion(tripId: string, candidate: CandidatePlanRequest) {
    return request<StoredPlanVersion>(
      `/api/v1/trips/${tripId}/plan-versions/generate`,
      {
        method: 'POST',
        body: JSON.stringify(candidate),
      },
    )
  },

  getPlanReview(tripId: string, reviewId: string) {
    return request<CandidatePlanReview>(
      `/api/v1/trips/${tripId}/plan-reviews/${reviewId}`,
    )
  },

  confirmPlanReview(
    tripId: string,
    reviewId: string,
    confirmations: CandidateReviewConfirmationInput[],
  ) {
    return request<StoredPlanVersion>(
      `/api/v1/trips/${tripId}/plan-reviews/${reviewId}/confirm`,
      {
        method: 'POST',
        body: JSON.stringify({ schemaVersion: '1.0', confirmations }),
      },
    )
  },

  getPlanningFacts(tripId: string) {
    return request<CandidatePlanRequest>(
      `/api/v1/trips/${tripId}/planning-facts`,
    )
  },

  selectReplan(tripId: string, input: ReplanGenerationRequest) {
    return request<RegisteredReplan>(`/api/v1/trips/${tripId}/replans`, {
      method: 'POST',
      body: JSON.stringify(input),
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
    return request<TripPlanState>(`/api/v1/trips/${tripId}`)
  },

  createExecutionEvent(tripId: string, input: ExecutionEventInput) {
    return request<ExecutionEvent>(`/api/v1/trips/${tripId}/events`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },

  getSummary(tripId: string) {
    return request<TripSummary>(`/api/v1/trips/${tripId}/summary`)
  },
}
