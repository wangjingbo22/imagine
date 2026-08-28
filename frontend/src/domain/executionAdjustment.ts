import type {
  CandidateAssessment,
  PlanV2DecisionResult,
  PlanVersionDiff,
  PlanningConstraint,
  ReplanValidationReport,
  StoredPlanVersion,
} from './trip'

export type ExecutionAdjustmentType = 'LATE' | 'FATIGUE'
export type FatigueLevel = 'MILD' | 'MODERATE' | 'SEVERE'
export type AdjustmentRecognitionSource =
  | 'BAILIAN'
  | 'DETERMINISTIC_FORM'
  | 'DEGRADED_FORM'

export type AdjustmentClarificationKey =
  | 'EVENT_TYPE_REQUIRED'
  | 'LATE_MINUTES_REQUIRED'
  | 'FATIGUE_LEVEL_REQUIRED'

export interface ExecutionAdjustmentParseInput {
  schemaVersion: '1.0'
  rawText: string
  taskId: string
  currentTask: {
    taskId: string
    title: string
  }
}

export interface AdjustmentClarificationQuestion {
  questionKey: AdjustmentClarificationKey
  prompt: string
  options: string[]
}

export interface ExecutionEventDraft {
  schemaVersion: '1.0'
  eventType: ExecutionAdjustmentType | null
  taskId: string
  lateMinutes: number | null
  fatigueLevel: FatigueLevel | null
  clarificationQuestions: AdjustmentClarificationQuestion[]
}

export interface ExecutionEventParseOutcome {
  draft: ExecutionEventDraft
  recognition: {
    source: AdjustmentRecognitionSource
    model: string | null
    degradedReason: string | null
  }
}

export interface ConfirmedExecutionAdjustment {
  schemaVersion: '1.0'
  confirmationStatus: 'CONFIRMED'
  eventType: ExecutionAdjustmentType
  taskId: string
  lateMinutes: number | null
  fatigueLevel: FatigueLevel | null
}

export interface ConfirmedExecutionAdjustmentEventInput
  extends ConfirmedExecutionAdjustment {
  planVersionId: string
  idempotencyKey: string
  occurredAt: string
}

export interface ConfirmedExecutionAdjustmentEvent
  extends ConfirmedExecutionAdjustmentEventInput {
  eventId: string
  tripId: string
}

export interface RemainingConstraintContext {
  remainingTimeMinutes: number | null
  remainingWalkBudgetMeters: number | null
  maxSegmentWalkMeters: number | null
  restIntervalMinutes: number | null
}

export interface EventConstraintSet {
  schemaVersion: '1.0'
  policyVersion: 'S2-T020-1.0'
  sourceEvent: ConfirmedExecutionAdjustment
  constraints: PlanningConstraint[]
  reasons: Array<{
    reasonCode: string
    message: string
  }>
  inputDigest: string
}

export interface ExecutionAdjustmentReplanRequest {
  schemaVersion: '1.0'
  adjustmentEventId: string
  adjustment: ConfirmedExecutionAdjustment
  lockedTaskIds: string[]
  explainDifferences: boolean
}

export type DifferenceExplanation =
  | {
      status: 'GENERATED'
      summary: string
      model: string | null
      degradedReason: null
    }
  | {
      status: 'UNAVAILABLE'
      summary: null
      model: null
      degradedReason: string | null
    }
  | {
      status: 'NOT_REQUESTED'
      summary: null
      model: null
      degradedReason: string | null
    }

export interface ExecutionAdjustmentReplanPreview {
  schemaVersion: '1.0'
  outcome: 'SELECTED'
  currentPlanId: string
  currentPlanChanged: false
  candidatePlan: StoredPlanVersion
  diff: PlanVersionDiff
  eventConstraints: EventConstraintSet
  derivedContext: RemainingConstraintContext
  frozenTaskIds: string[]
  assessments: CandidateAssessment[]
  validationReport: ReplanValidationReport
  explanation: DifferenceExplanation
}

export type ExecutionAdjustmentDecision = 'ACCEPT' | 'REJECT'

export interface ExecutionAdjustmentDecisionRequest {
  schemaVersion: '1.0'
  decision: ExecutionAdjustmentDecision
}

export interface ExecutionAdjustmentDecisionView {
  schemaVersion: '1.0'
  result: PlanV2DecisionResult
}
