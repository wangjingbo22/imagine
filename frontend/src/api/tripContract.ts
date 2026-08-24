import type {
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
        assistanceProfile: null,
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
