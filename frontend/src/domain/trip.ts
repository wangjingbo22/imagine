export type AssistanceMode = 'standard' | 'family' | 'low-mobility' | 'assisted'

export type PlanTaskStatus = 'completed' | 'current' | 'upcoming' | 'removed'

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
  validationStatus: 'PASS' | 'WARNING' | 'FAIL'
  tasks: PlanTask[]
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
