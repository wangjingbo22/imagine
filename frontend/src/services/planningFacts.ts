import type {
  AssistanceMode,
  CandidatePlanRequest,
  PreferenceType,
  TripDraftInput,
} from '../domain/trip'

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
  return request.trip.participants[0].preferences
    ?.filter((preference) => preference.type === type)
    .map((preference) => preference.value) ?? []
}

export function restoreDraftFromPlanningFacts(
  request: CandidatePlanRequest,
): TripDraftInput {
  const participant = request.trip.participants[0]
  const profile = participant.assistanceProfile
  const assistanceMode = profile
    ? assistanceModeByType[profile.type]
    : 'standard'
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
      maxSegmentWalkMeters: profile?.walkLimits.maxContinuousMeters ?? null,
      maxTransfers: profile?.maxTransfers ?? null,
      restIntervalMinutes: profile?.restInterval ?? null,
    },
    naturalLanguageRequest: '从服务端签发的规划事实恢复',
  }
}
