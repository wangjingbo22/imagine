import type {
  CandidatePlanPreview,
  CandidatePlanRequest,
  PlanSnapshot,
  ProviderRoute,
} from '../domain/trip'
import type {
  AmapSegmentReplacementResult,
  LocationEvidence,
  PlanningIssue,
} from './amapPlan'

export interface LocalSegmentRouteFailure {
  segmentIndex: number
  route: ProviderRoute
  message: string
}

export interface SegmentRouteReplacementDisplayState {
  candidateRequest: CandidatePlanRequest
  providerPlan: PlanSnapshot
  locationEvidence: LocationEvidence
  persistedPlanId: string | null
  restoredPlan: PlanSnapshot | null
  planningIssue: PlanningIssue | null
  localFailure: LocalSegmentRouteFailure | null
}

export interface SegmentRouteReplacementTransition {
  kind: 'SUCCESS' | 'LOCAL_FAILURE'
  state: SegmentRouteReplacementDisplayState
}

const routeModeLabels = {
  WALKING: '步行',
  TRANSIT: '公共交通',
  DRIVING: '驾车',
  BICYCLING: '骑行',
} as const

function routeWalkingMeters(route: ProviderRoute) {
  if (route.mode === 'WALKING') return route.distanceMeters
  return route.walkingDistanceMeters ?? 0
}

function minutesBetween(startAt: string, endAt: string) {
  const toMinutes = (value: string) => {
    const [hours = '0', minutes = '0'] = value.split(':')
    return Number(hours) * 60 + Number(minutes)
  }
  return Math.max(0, toMinutes(endAt) - toMinutes(startAt))
}

function displayCandidatePlan(
  previous: PlanSnapshot,
  candidate: CandidatePlanRequest,
  preview: CandidatePlanPreview,
): PlanSnapshot {
  const metrics = preview.metrics
  return {
    ...previous,
    totalCostCents: metrics?.totalCostCents ?? previous.totalCostCents,
    bufferCents: metrics?.knownBudgetBufferCents ?? previous.bufferCents,
    totalWalkMeters: metrics?.totalWalkMeters ?? previous.totalWalkMeters,
    transferCount: metrics?.transferCount ?? previous.transferCount,
    validationStatus: preview.validationStatus,
    tasks: candidate.taskFacts.map((fact, index) => {
      const priorTask = previous.tasks[index]
      const knownCosts = [fact.place.priceReference.amountCents, fact.route.priceReference.amountCents]
      const costCents = knownCosts.reduce<number>((total, amount) => total + (amount ?? 0), 0)
      return {
        ...priorTask,
        id: fact.taskId,
        order: fact.order,
        title: fact.title,
        category: fact.category,
        timeRange: `${fact.startAt.slice(0, 5)}—${fact.endAt.slice(0, 5)}`,
        durationMinutes: minutesBetween(fact.startAt, fact.endAt),
        transport: `${routeModeLabels[fact.route.mode]} ${fact.route.distanceMeters} 米 · 约${Math.max(1, Math.round(fact.route.durationSeconds / 60))} 分钟`,
        costCents,
        priceKnown: knownCosts.every((amount) => amount !== null),
        walkMeters: routeWalkingMeters(fact.route),
        note: fact.note,
      }
    }),
  }
}

function withReplacementEvidence(
  evidence: LocationEvidence,
  result: AmapSegmentReplacementResult,
) {
  return {
    ...evidence,
    routes: evidence.routes.map((route, index) =>
      index === result.evidence.segmentIndex ? result.evidence.route : route,
    ),
  }
}

function localFailureMessage(preview: CandidatePlanPreview) {
  return preview.constraintResults
    .map((item) => item.suggestion)
    .find((item): item is string => Boolean(item)) ?? '路线变更未通过计划校验。'
}

function candidatePreviewIssue(preview: CandidatePlanPreview): PlanningIssue | null {
  if (preview.validationStatus !== 'FAIL') {
    return null
  }
  const suggestions = preview.constraintResults
    .filter((result) => result.status === 'FAIL')
    .map((result) => result.suggestion?.trim())
    .filter((suggestion): suggestion is string => Boolean(suggestion))
  return {
    code: 'CANDIDATE_PREVIEW_REJECTED',
    message: suggestions.length > 0
      ? suggestions.join(' ')
      : '候选路线未通过服务端预览校验。',
    review: null,
  }
}

export function applySegmentReplacementResult(
  current: SegmentRouteReplacementDisplayState,
  result: AmapSegmentReplacementResult,
): SegmentRouteReplacementTransition {
  const locationEvidence = withReplacementEvidence(current.locationEvidence, result)
  if (result.candidateRequest) {
    return {
      kind: 'SUCCESS',
      state: {
        ...current,
        candidateRequest: result.candidateRequest,
        providerPlan: displayCandidatePlan(
          current.providerPlan,
          result.candidateRequest,
          result.preview,
        ),
        locationEvidence,
        persistedPlanId: null,
        restoredPlan: null,
        planningIssue: candidatePreviewIssue(result.preview),
        localFailure: null,
      },
    }
  }

  const message = localFailureMessage(result.preview)
  return {
    kind: 'LOCAL_FAILURE',
    state: {
      ...current,
      // Keep this valid candidate only as the base for another mode selection.
      candidateRequest: current.candidateRequest,
      // The returned route has no schedule/cost facts, so do not synthesize them.
      providerPlan: { ...current.providerPlan, validationStatus: 'FAIL' },
      locationEvidence,
      persistedPlanId: null,
      restoredPlan: null,
      planningIssue: {
        code: 'SEGMENT_ROUTE_SCHEDULE_FAILURE',
        message,
        review: null,
      },
      localFailure: {
        segmentIndex: result.evidence.segmentIndex,
        route: result.evidence.route,
        message,
      },
    },
  }
}
