import type {
  AssistanceProfile,
  CityContext,
  CreateSingleDayTrip,
  Preference,
  TripDraftInput,
} from '../domain/trip'

export interface TripContractContext {
  tripId: string
  participantId: string
  cityContext: CityContext
  nickname: string
  startLocationText: string
  endLocationText: string
  dailyBudgetCents?: number
}

function toSecondPrecisionTime(value: string) {
  return value.length === 5 ? `${value}:00` : value
}

function createPreferences(input: TripDraftInput): Preference[] {
  return [
    ...input.interests.map((value): Preference => ({
      type: 'INTEREST',
      value,
      weight: 4,
      isHard: false,
    })),
    ...input.mustVisit.map((value): Preference => ({
      type: 'MUST_VISIT',
      value,
      weight: 5,
      isHard: true,
    })),
    ...input.avoidPlaces.map((value): Preference => ({
      type: 'AVOID_PLACE',
      value,
      weight: 5,
      isHard: true,
    })),
  ]
}

export function buildAssistanceProfile(input: TripDraftInput): AssistanceProfile {
  const unconstrainedWalk = {
    maxContinuousMeters: null,
    maxDailyMeters: null,
  }

  switch (input.assistanceMode) {
    case 'family':
      return {
        type: 'PARENT_CHILD',
        childAge: null,
        walkLimits: unconstrainedWalk,
        maxTransfers: null,
        restInterval: null,
        napWindow: { start: '13:00:00', end: '14:00:00' },
        avoidStairs: false,
      }
    case 'low-mobility':
      return {
        type: 'LOW_STAMINA',
        childAge: null,
        walkLimits: {
          maxContinuousMeters: input.assistanceProfile.maxSegmentWalkMeters,
          maxDailyMeters: null,
        },
        maxTransfers: input.assistanceProfile.maxTransfers,
        restInterval: input.assistanceProfile.restIntervalMinutes,
        napWindow: null,
        avoidStairs: false,
      }
    case 'assisted':
      return {
        type: 'MOBILITY_ASSISTANCE_BETA',
        childAge: null,
        walkLimits: unconstrainedWalk,
        maxTransfers: null,
        restInterval: null,
        napWindow: null,
        avoidStairs: true,
      }
    case 'standard':
      return {
        type: 'ORDINARY',
        childAge: null,
        walkLimits: unconstrainedWalk,
        maxTransfers: null,
        restInterval: null,
        napWindow: null,
        avoidStairs: false,
      }
  }
}

export function buildCreateSingleDayTrip(
  input: TripDraftInput,
  context: TripContractContext,
): CreateSingleDayTrip {
  return {
    schemaVersion: '1.0',
    tripId: context.tripId,
    mode: 'SINGLE',
    status: 'DRAFT',
    cityContext: context.cityContext,
    startDate: input.travelDate,
    endDate: input.travelDate,
    currency: 'CNY',
    totalBudgetCents: input.budgetCents,
    participants: [
      {
        participantId: context.participantId,
        nickname: context.nickname,
        budgetCapCents: input.budgetCents,
        preferences: createPreferences(input),
        assistanceProfile: buildAssistanceProfile(input),
      },
    ],
    days: [
      {
        dayIndex: 0,
        date: input.travelDate,
        dailyBudgetCents: context.dailyBudgetCents ?? input.budgetCents,
        startLocationText: context.startLocationText,
        endLocationText: context.endLocationText,
        timeWindow: {
          start: toSecondPrecisionTime(input.startTime),
          end: toSecondPrecisionTime(input.endTime),
        },
      },
    ],
  }
}
