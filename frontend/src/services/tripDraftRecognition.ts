import type {
  AssistanceMode,
  TripDraftParseInput,
  TripDraftParseResult,
} from '../domain/trip'

interface RecognitionInputOptions {
  tripId: string
  naturalLanguageRequest: string
  assistanceMode: AssistanceMode
  assistanceProfile: TripDraftParseInput['assistanceProfile']
}

export interface RecognizedFormPatch {
  cityName: string | null
  travelDate: string | null
  startTime: string | null
  endTime: string | null
  startLocationText: string | null
  endLocationText: string | null
  endSameAsStart: boolean
  budgetYuan: string | null
  interests: string[]
  mustVisitText: string
  avoidPlacesText: string
}

export function buildNaturalLanguageParseInput(
  options: RecognitionInputOptions,
): TripDraftParseInput {
  return {
    schemaVersion: '1.0',
    tripId: options.tripId,
    naturalLanguageRequest: options.naturalLanguageRequest.trim(),
    cityName: null,
    travelDate: null,
    startTime: null,
    endTime: null,
    startLocationText: null,
    endLocationText: null,
    budgetCents: null,
    interests: [],
    mustVisit: [],
    avoidPlaces: [],
    assistanceMode: options.assistanceMode,
    assistanceProfile: options.assistanceProfile,
  }
}

export function toRecognizedFormPatch(
  parsed: TripDraftParseResult['parsed'],
): RecognizedFormPatch {
  return {
    cityName: parsed.cityName,
    travelDate: parsed.travelDate,
    startTime: parsed.startTime,
    endTime: parsed.endTime,
    startLocationText: parsed.startLocationText,
    endLocationText: parsed.endLocationText,
    endSameAsStart: Boolean(
      parsed.startLocationText &&
      parsed.endLocationText === parsed.startLocationText,
    ),
    budgetYuan: parsed.budgetCents === null
      ? null
      : String(parsed.budgetCents / 100),
    interests: parsed.interests,
    mustVisitText: parsed.mustVisit.join('、'),
    avoidPlacesText: parsed.avoidPlaces.join('、'),
  }
}

export function splitPlaceInput(value: string): string[] {
  return [...new Set(
    value
      .split(/[、,，;；\n]/)
      .map((item) => item.trim())
      .filter(Boolean),
  )]
}
