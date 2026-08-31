import type {
  AssistanceMode,
  AssistanceProfile,
  CandidatePlanRequest,
  PreferenceType,
  TripDraftInput,
} from '../domain/trip'
import {
  compileGroupAssistanceConstraints,
  planningCareFromConstraints,
} from './assistanceConstraints'

const assistanceModeByType = {
  ORDINARY: 'standard',
  PARENT_CHILD: 'family',
  LOW_STAMINA: 'low-mobility',
  MOBILITY_ASSISTANCE_BETA: 'assisted',
} as const satisfies Record<string, AssistanceMode>

function preferenceValues(
  request: CandidatePlanRequest,
  type: PreferenceType,
) {
  return [...new Set(request.trip.participants.flatMap((participant) => (
    participant.preferences
      ?.filter((preference) => preference.type === type)
      .map((preference) => preference.value) ?? []
  )))]
}

function groupAssistanceMode(profiles: AssistanceProfile[]): AssistanceMode {
  if (profiles.some((profile) => profile.type === 'MOBILITY_ASSISTANCE_BETA')) {
    return 'assisted'
  }
  if (profiles.some((profile) => profile.type === 'PARENT_CHILD')) return 'family'
  if (profiles.some((profile) => profile.type === 'LOW_STAMINA')) return 'low-mobility'
  return 'standard'
}

export function restoreDraftFromPlanningFacts(
  request: CandidatePlanRequest,
): TripDraftInput {
  const profiles = request.trip.participants
    .map((participant) => participant.assistanceProfile)
    .filter((profile): profile is AssistanceProfile => Boolean(profile))
  const care = planningCareFromConstraints(
    compileGroupAssistanceConstraints(profiles),
  )
  const assistanceMode = profiles.length === 1
    ? assistanceModeByType[profiles[0].type]
    : groupAssistanceMode(profiles)
  return {
    schemaVersion: '1.0',
    cityName: request.trip.cityContext.cityName,
    travelDate: request.trip.startDate,
    startTime: request.trip.days[0].timeWindow.start.slice(0, 5),
    endTime: request.trip.days[0].timeWindow.end.slice(0, 5),
    startLocationText: request.trip.days[0].startLocationText,
    endLocationText: request.trip.days[0].endLocationText,
    budgetCents: request.trip.totalBudgetCents,
    interests: preferenceValues(request, 'INTEREST'),
    mustVisit: preferenceValues(request, 'MUST_VISIT'),
    avoidPlaces: preferenceValues(request, 'AVOID_PLACE'),
    assistanceMode,
    assistanceProfile: {
      maxSegmentWalkMeters: care.maxContinuousMeters,
      maxTransfers: care.maxTransfers,
      restIntervalMinutes: care.restInterval,
    },
    naturalLanguageRequest: '从服务端签发的规划事实恢复',
  }
}
