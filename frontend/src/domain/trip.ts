export type AssistanceMode = 'standard' | 'family' | 'low-mobility' | 'assisted'

export type AssistanceType =
  | 'ORDINARY'
  | 'PARENT_CHILD'
  | 'LOW_STAMINA'
  | 'MOBILITY_ASSISTANCE_BETA'

export interface WalkLimits {
  maxContinuousMeters: number | null
  maxDailyMeters: number | null
}

export interface NapWindow {
  start: string
  end: string
}

export interface AssistanceProfile {
  type: AssistanceType
  childAge: number | null
  walkLimits: WalkLimits
  maxTransfers: number | null
  restInterval: number | null
  napWindow: NapWindow | null
  avoidStairs: boolean
}

export type PlanTaskStatus = 'completed' | 'current' | 'upcoming' | 'removed'

export type ValidationStatus = 'PASS' | 'WARNING' | 'NEEDS_CONFIRMATION' | 'FAIL'

export type TripMode = 'SINGLE'

export type TripStatus =
  | 'DRAFT'
  | 'CONSTRAINT_CONFIRMED'
  | 'PLANNING'
  | 'PLAN_REVIEW'
  | 'CONFIRMED'
  | 'EXECUTING'
  | 'REPLAN_REVIEW'
  | 'COMPLETED'

export type PreferenceType = 'INTEREST' | 'MUST_VISIT' | 'AVOID_PLACE'

export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface TripDraftInput {
  schemaVersion: '1.0'
  cityName: string
  travelDate: string
  startTime: string
  endTime: string
  budgetCents: number
  interests: string[]
  mustVisit: string[]
  avoidPlaces: string[]
  assistanceMode: AssistanceMode
  assistanceProfile: {
    maxSegmentWalkMeters: number
    maxTransfers: number
    restIntervalMinutes: number
  }
  naturalLanguageRequest: string
}

export interface TripDraftParseInput extends Omit<
  TripDraftInput,
  'cityName' | 'travelDate' | 'startTime' | 'endTime' | 'budgetCents'
> {
  tripId: string
  cityName: string | null
  travelDate: string | null
  startTime: string | null
  endTime: string | null
  budgetCents: number | null
}

export interface TripDraftConfirmationItem {
  itemId: string
  path: string
  code: 'missing' | 'ambiguous' | 'conflict' | 'invalid'
  message: string
  candidates: string[]
}

export interface TripDraftParseResult {
  tripId: string
  status: 'DRAFT'
  parsed: {
    cityName: string | null
    travelDate: string | null
    startTime: string | null
    endTime: string | null
    budgetCents: number | null
    interests: string[]
    mustVisit: string[]
    avoidPlaces: string[]
  }
  confirmationItems: TripDraftConfirmationItem[]
  canPlan: boolean
  trip: CreateSingleDayTrip | null
}

export interface GeoPoint {
  longitude: number
  latitude: number
}

export interface ProviderConfig {
  provider: 'AMAP'
  coordinateSystem: 'GCJ02'
}

export interface CityContext {
  countryCode: 'CN'
  cityCode: string
  cityName: string
  center: GeoPoint
  providerConfig: ProviderConfig
}

export type SourceStatus =
  | 'ONLINE'
  | 'VERIFIED_CACHE'
  | 'USER_CONFIRMED'
  | 'ESTIMATED'
  | 'UNKNOWN'

export interface Provenance {
  provider: 'AMAP'
  sourceStatus: SourceStatus
  fetchedAt: string
  isStale: boolean
}

export interface CityResolution {
  cityContext: CityContext
  adCode?: string | null
  formattedAddress?: string | null
  provenance: Provenance
}

export interface PriceFact {
  amountCents: number | null
  currency: 'CNY'
  kind: string
  provenance: Provenance
}

export interface Place {
  placeId: string
  name: string
  address: string | null
  cityCode: string
  adCode: string | null
  location: GeoPoint
  category: string | null
  telephone: string | null
  rating: number | null
  priceReference: PriceFact
  provenance: Provenance
}

export interface PlaceCollection {
  cityCode: string
  total: number
  places: Place[]
  provenance: Provenance
}

export interface AddressResolution {
  formattedAddress: string
  cityCode: string
  adCode: string | null
  location: GeoPoint
  provenance: Provenance
}

export type TravelMode = 'WALKING' | 'TRANSIT' | 'DRIVING' | 'BICYCLING'

export interface RouteStep {
  instruction: string | null
  road: string | null
  distanceMeters: number | null
  durationSeconds: number | null
  transport: string | null
}

export interface ProviderRoute {
  routeId: string
  mode: TravelMode
  origin: GeoPoint
  destination: GeoPoint
  distanceMeters: number
  durationSeconds: number
  walkingDistanceMeters: number | null
  transferCount: number | null
  steps: RouteStep[]
  priceReference: PriceFact
  provenance: Provenance
}

export interface RouteCollection {
  cityCode: string
  routes: ProviderRoute[]
  provenance: Provenance
}

export interface Preference {
  type: PreferenceType
  value: string
  weight: 1 | 2 | 3 | 4 | 5
  isHard: boolean
}

export interface Participant {
  participantId: string
  nickname: string
  budgetCapCents: number
  preferences?: Preference[]
  assistanceProfile?: AssistanceProfile | null
}

export interface TimeWindow {
  start: string
  end: string
}

export interface TripDayInput {
  dayIndex: 0
  date: string
  dailyBudgetCents: number
  startLocationText: string
  endLocationText: string
  timeWindow: TimeWindow
}

export interface CreateSingleDayTrip {
  schemaVersion: '1.0'
  tripId: string
  mode: TripMode
  status: 'DRAFT'
  cityContext: CityContext
  startDate: string
  endDate: string
  currency: 'CNY'
  totalBudgetCents: number
  participants: [Participant]
  days: [TripDayInput]
}

export interface PlanTripSnapshot extends Omit<CreateSingleDayTrip, 'status'> {
  status: 'PLAN_REVIEW'
}

export interface ValidationIssue {
  path: string
  code: string
  message: string
  context?: Record<string, string>
  candidates?: string[]
}

export interface TripSchemaErrorResponse {
  code: 'TRIP_SCHEMA_INVALID' | 'TRIP_CONFIRMATION_REQUIRED'
  schemaVersion: '1.0'
  errors: ValidationIssue[]
}

export interface PlanTask {
  id: string
  order: number
  title: string
  category: string
  timeRange: string
  durationMinutes: number
  transport: string
  costCents: number
  walkMeters: number
  note: string
  status: PlanTaskStatus
  coordinates: [number, number]
}

export interface PlanSnapshot {
  id: string
  version: number
  cityName: string
  totalCostCents: number
  bufferCents: number
  totalWalkMeters: number
  transferCount: number
  validationStatus: ValidationStatus
  tasks: PlanTask[]
}

export interface RouteRiskResult {
  ruleId: string
  status: ValidationStatus
  routeSegment: string | null
  observed: Record<string, unknown>
  suggestion: string | null
}

export interface RouteRiskReport {
  status: ValidationStatus
  results: RouteRiskResult[]
}

export type PlanVersionStatus = 'PROPOSED' | 'CURRENT' | 'REJECTED' | 'SUPERSEDED'
export type PlanVersionReason =
  | 'INITIAL_PLAN'
  | 'EXPENSE_CHANGE'
  | 'DELAY'
  | 'FATIGUE'
  | 'USER_FEEDBACK'
  | 'OTHER'

export type PlanDiffCategory = 'PLACE' | 'TIME' | 'ROUTE' | 'COST' | 'CARE'
export type PlanDiffChangeType = 'RETAINED' | 'REMOVED' | 'ADDED' | 'CHANGED'

export interface PlanVersionProposal {
  schemaVersion: '1.0'
  planId: string
  tripSnapshot: PlanTripSnapshot
  version: 1 | 2
  parentId: string | null
  reason: PlanVersionReason
  metrics: {
    totalCostCents: number
    bufferCents: number
    totalWalkMeters: number
    transferCount: number
    validationStatus: 'PASS'
  }
  days: [{
    dayIndex: 0
    date: string
    tasks: Array<{
      taskId: string
      order: number
      title: string
      category: string
      timeRange: string
      durationMinutes: number
      transport: string
      costCents: number
      walkMeters: number
      note: string
    }>
  }]
  constraintsSnapshot: Array<{
    ruleId: string
    scope: string
    hardness: 'HARD' | 'SOFT'
    status: 'PASS' | 'WARNING' | 'FAIL' | 'NEEDS_CONFIRMATION'
    description: string
    details: Record<string, string>
  }>
  sourcesSnapshot: Array<{
    provider: string
    sourceStatus: 'ONLINE' | 'VERIFIED_CACHE' | 'USER_CONFIRMED' | 'ESTIMATED' | 'UNKNOWN'
    fetchedAt: string
    isStale: boolean
    referenceId: string | null
  }>
}

export interface StoredPlanVersion extends PlanVersionProposal {
  status: PlanVersionStatus
  createdAt: string
  confirmedAt: string | null
}

export interface TripPlanState {
  tripId: string
  tripStatus: TripStatus
  currentPlan: StoredPlanVersion | null
  proposedPlans: StoredPlanVersion[]
  events: ExecutionEvent[]
}

export interface PlanDiffItem {
  category: PlanDiffCategory
  changeType: PlanDiffChangeType
  key: string
  label: string
  before: string | number | null
  after: string | number | null
}

export interface PlanVersionDiff {
  tripId: string
  basePlanId: string
  candidatePlanId: string
  baseVersion: number
  candidateVersion: number
  items: PlanDiffItem[]
  metricsDelta: {
    totalCostCents: number
    totalWalkMeters: number
    transferCount: number
  }
}

export interface PlanV2DecisionResult {
  tripId: string
  candidatePlanId: string
  decision: 'ACCEPTED' | 'REJECTED'
  tripStatus: 'EXECUTING'
  currentPlanId: string
  candidateStatus: PlanVersionStatus
  previousCurrentStatus: PlanVersionStatus
}

export interface ExecutionEventInput {
  taskId: string
  planVersionId: string
  eventType: 'START' | 'COMPLETE' | 'SKIP' | 'EXPENSE'
  amountCents?: number | null
  idempotencyKey: string
}

export interface ExecutionEvent extends ExecutionEventInput {
  eventId: string
  tripId: string
  occurredAt: string
}

export type ConstraintProfileStatus = 'DRAFT' | 'CONSTRAINT_CONFIRMED'

export interface ConstraintProfileState {
  tripId: string
  status: ConstraintProfileStatus
  assistanceProfile: AssistanceProfile
  updatedAt: string
  confirmedAt: string | null
}

export interface ConstraintConfirmationResult {
  tripId: string
  status: 'CONSTRAINT_CONFIRMED'
  assistanceProfile: AssistanceProfile
  confirmedAt: string
}

export interface PlanHistoryItem {
  planId: string
  version: number
  status: PlanVersionStatus
  reason: PlanVersionReason
}

export interface TripSummary {
  tripId: string
  tripStatus: TripStatus
  plannedCostCents: number
  actualCostCents: number
  differenceCents: number
  completedTaskIds: string[]
  skippedTaskIds: string[]
  totalTasks: number
  currentPlanVersion: number
  planHistory: PlanHistoryItem[]
  events: ExecutionEvent[]
}
