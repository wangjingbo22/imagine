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

export interface ExecutionEventInput {
  taskId: string
  eventType: 'START' | 'COMPLETE' | 'SKIP' | 'EXPENSE'
  amountCents?: number
  idempotencyKey: string
}

export interface TripSummary {
  plannedCostCents: number
  actualCostCents: number
  completedTasks: number
  totalTasks: number
  planAdjustmentCount: number
}
