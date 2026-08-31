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
  CreateDayTrip,
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
import type {
  AdjustmentRecognitionSource,
  ConfirmedExecutionAdjustmentEvent,
  ConfirmedExecutionAdjustmentEventInput,
  ExecutionAdjustmentDecision,
  ExecutionAdjustmentDecisionView,
  ExecutionAdjustmentParseInput,
  ExecutionAdjustmentReplanPreview,
  ExecutionAdjustmentReplanRequest,
  ExecutionEventDraft,
  ExecutionEventParseOutcome,
} from '../domain/executionAdjustment'
import { ApiError, request, requestBare } from './client'
import { createExpenseChangeReplanRequest } from '../services/executionReplan'
import type { ProviderFactPlaceSet } from '../services/recommendationSelection'

export const USE_PLAN_VERSION_API =
  (import.meta.env?.VITE_USE_PLAN_VERSION_API ?? 'true') === 'true'
export const USE_WORKFLOW_API =
  (import.meta.env?.VITE_USE_WORKFLOW_API ?? 'true') === 'true'

function organizerHeaders(organizerToken?: string | null): Record<string, string> {
  return organizerToken ? { 'X-Organizer-Token': organizerToken } : {}
}

function isAdjustmentRecognitionSource(
  value: string | null,
): value is AdjustmentRecognitionSource {
  return value === 'BAILIAN' ||
    value === 'DETERMINISTIC_FORM' ||
    value === 'DEGRADED_FORM'
}

export const tripApi = {
  async parseExecutionAdjustment(
    input: ExecutionAdjustmentParseInput,
    organizerToken: string,
  ): Promise<ExecutionEventParseOutcome> {
    const response = await requestBare<ExecutionEventDraft>(
      '/api/v1/execution-adjustments/parse',
      {
        method: 'POST',
        headers: { 'X-Organizer-Token': organizerToken },
        body: JSON.stringify(input),
      },
    )
    const source = response.headers.get('X-Recognition-Source')
    if (!isAdjustmentRecognitionSource(source)) {
      throw new ApiError(
        'EXECUTION_ADJUSTMENT_RECOGNITION_HEADER_INVALID',
        '服务端没有返回有效的执行调整识别来源。',
      )
    }
    return {
      draft: response.data,
      recognition: {
        source,
        model: response.headers.get('X-Recognition-Model'),
        degradedReason: response.headers.get('X-Degraded-Reason'),
      },
    }
  },

  confirmExecutionAdjustment(
    tripId: string,
    input: ConfirmedExecutionAdjustmentEventInput,
    organizerToken: string,
  ) {
    return request<ConfirmedExecutionAdjustmentEvent>(
      `/api/v1/execution-adjustments/trips/${encodeURIComponent(tripId)}/events`,
      {
        method: 'POST',
        headers: { 'X-Organizer-Token': organizerToken },
        body: JSON.stringify(input),
      },
    )
  },

  previewExecutionReplan(
    tripId: string,
    input: ExecutionAdjustmentReplanRequest,
    organizerToken: string,
  ) {
    return request<ExecutionAdjustmentReplanPreview>(
      `/api/v1/trips/${encodeURIComponent(tripId)}/replans/from-adjustment`,
      {
        method: 'POST',
        headers: { 'X-Organizer-Token': organizerToken },
        body: JSON.stringify(input),
      },
    )
  },

  decideExecutionReplan(
    tripId: string,
    planId: string,
    decision: ExecutionAdjustmentDecision,
    organizerToken: string,
  ) {
    return request<ExecutionAdjustmentDecisionView>(
      `/api/v1/trips/${encodeURIComponent(tripId)}/replans/${encodeURIComponent(planId)}/decision`,
      {
        method: 'POST',
        headers: { 'X-Organizer-Token': organizerToken },
        body: JSON.stringify({ schemaVersion: '1.0', decision }),
      },
    )
  },

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

  getCollaborationPlanningTrip(tripId: string, organizerToken: string) {
    return request<CreateDayTrip>(
      `/api/v2/trips/${tripId}/planning-trip`,
      { headers: { 'X-Organizer-Token': organizerToken } },
    )
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

  confirmPlan(tripId: string, planId: string, organizerToken?: string | null) {
    return request<{
      tripId: string
      planId: string
      tripStatus: 'CONFIRMED'
      planStatus: 'CURRENT'
    }>(
      `/api/v1/trips/${tripId}/plan-versions/${planId}/confirm`,
      { method: 'POST', headers: organizerHeaders(organizerToken) },
    )
  },

  resolveCity(cityName: string) {
    return request<CityResolution>('/api/v1/cities/resolve', {
      method: 'POST',
      body: JSON.stringify({ schemaVersion: '1.0', cityName }),
    })
  },

  generatePlanVersion(
    tripId: string,
    candidate: CandidatePlanRequest,
    organizerToken?: string | null,
  ) {
    return request<StoredPlanVersion>(
      `/api/v1/trips/${tripId}/plan-versions/generate`,
      {
        method: 'POST',
        headers: organizerToken ? { 'X-Organizer-Token': organizerToken } : undefined,
        body: JSON.stringify(candidate),
      },
    )
  },

  getPlanReview(tripId: string, reviewId: string, organizerToken?: string | null) {
    return request<CandidatePlanReview>(
      `/api/v1/trips/${tripId}/plan-reviews/${reviewId}`,
      { headers: organizerHeaders(organizerToken) },
    )
  },

  confirmPlanReview(
    tripId: string,
    reviewId: string,
    confirmations: CandidateReviewConfirmationInput[],
    organizerToken?: string | null,
  ) {
    return request<StoredPlanVersion>(
      `/api/v1/trips/${tripId}/plan-reviews/${reviewId}/confirm`,
      {
        method: 'POST',
        headers: organizerHeaders(organizerToken),
        body: JSON.stringify({ schemaVersion: '1.0', confirmations }),
      },
    )
  },

  getPlanningFacts(tripId: string, organizerToken?: string | null) {
    return request<CandidatePlanRequest>(
      `/api/v1/trips/${tripId}/planning-facts`,
      { headers: organizerHeaders(organizerToken) },
    )
  },

  selectReplan(tripId: string, input: ReplanGenerationRequest) {
    return request<RegisteredReplan>(`/api/v1/trips/${tripId}/replans`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },

  replanFromEvents(tripId: string) {
    return request<RegisteredReplan>(`/api/v1/trips/${tripId}/replans/from-events`, {
      method: 'POST',
      body: JSON.stringify(createExpenseChangeReplanRequest()),
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
    organizerToken?: string | null,
  ) {
    return request<PlaceCollection>('/api/v1/places/search', {
      method: 'POST',
      headers: organizerHeaders(organizerToken),
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

  getPlaceDetail(
    tripId: string,
    cityContext: CityContext,
    placeId: string,
    organizerToken?: string | null,
  ) {
    return request<Place>('/api/v1/places/detail', {
      method: 'POST',
      headers: organizerHeaders(organizerToken),
      body: JSON.stringify({ schemaVersion: '1.0', tripId, cityContext, placeId }),
    })
  },

  forwardGeocode(
    tripId: string,
    cityContext: CityContext,
    address: string,
    organizerToken?: string | null,
  ) {
    return request<AddressResolution>('/api/v1/geocoding/forward', {
      method: 'POST',
      headers: organizerHeaders(organizerToken),
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
    organizerToken?: string | null,
  ) {
    return request<RouteCollection>('/api/v1/routes/plan', {
      method: 'POST',
      headers: organizerHeaders(organizerToken),
      body: JSON.stringify({
        schemaVersion: '1.0', tripId, cityContext, origin, destination, mode, strategy,
      }),
    })
  },

  getProviderFactSetPlaces(
    tripId: string,
    factSetId: string,
    providerFactDigest: string,
    organizerToken: string,
  ) {
    const path = `/api/v1/trips/${encodeURIComponent(tripId)}` +
      `/provider-fact-sets/${encodeURIComponent(factSetId)}/places` +
      `?providerFactDigest=${encodeURIComponent(providerFactDigest)}`
    return request<ProviderFactPlaceSet>(path, {
      headers: organizerHeaders(organizerToken),
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

  saveArrivalEvidence(tripId: string, input: Record<string, unknown>) {
    return request<any>(`/api/v1/trips/${tripId}/arrival-evidence`, { method: 'POST', body: JSON.stringify(input) })
  },

  decideArrival(tripId: string, input: Record<string, unknown>) {
    return request<any>(`/api/v1/trips/${tripId}/arrival-decision`, { method: 'POST', body: JSON.stringify(input) })
  },

  getSummary(tripId: string) {
    return request<TripSummary>(`/api/v1/trips/${tripId}/summary`)
  },
}
