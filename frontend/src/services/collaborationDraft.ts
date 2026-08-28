import type {
  AssistanceMode,
  AssistanceProfile,
  TripDraftInput,
} from '../domain/trip'
import type {
  CareDraft,
  TripDraftRevision,
} from '../domain/collaboration'

const invitationTokenPattern = /^[A-Za-z0-9_-]{43}$/

const assistanceModeByType = {
  ORDINARY: 'standard',
  PARENT_CHILD: 'family',
  LOW_STAMINA: 'low-mobility',
  MOBILITY_ASSISTANCE_BETA: 'assisted',
} as const satisfies Record<AssistanceProfile['type'], AssistanceMode>

export type CollaborationPlanningDraft = TripDraftInput & {
  /** Raw revision fact plus its deterministic effective profile; the server stays authoritative. */
  collaborationCareDraft: CareDraft
  collaborationCareProfile: AssistanceProfile
}

function toSecondPrecision(value: string): string {
  return value.length === 5 ? `${value}:00` : value
}

function assistancePreset(type: AssistanceProfile['type']): AssistanceProfile {
  const emptyWalkLimits = {
    maxContinuousMeters: null,
    maxDailyMeters: null,
  }
  switch (type) {
    case 'PARENT_CHILD':
      return {
        type,
        childAge: null,
        walkLimits: emptyWalkLimits,
        maxTransfers: null,
        restInterval: null,
        napWindow: { start: '13:00:00', end: '14:00:00' },
        avoidStairs: false,
      }
    case 'LOW_STAMINA':
      return {
        type,
        childAge: null,
        walkLimits: { maxContinuousMeters: 500, maxDailyMeters: null },
        maxTransfers: 2,
        restInterval: 90,
        napWindow: null,
        avoidStairs: false,
      }
    case 'MOBILITY_ASSISTANCE_BETA':
      return {
        type,
        childAge: null,
        walkLimits: emptyWalkLimits,
        maxTransfers: null,
        restInterval: null,
        napWindow: null,
        avoidStairs: true,
      }
    case 'ORDINARY':
      return {
        type,
        childAge: null,
        walkLimits: emptyWalkLimits,
        maxTransfers: null,
        restInterval: null,
        napWindow: null,
        avoidStairs: false,
      }
  }
}

function exactAssistanceProfile(care: CareDraft | null): AssistanceProfile | null {
  if (!care?.assistanceTypeHint) return null
  const preset = assistancePreset(care.assistanceTypeHint)
  const explicitNapWindow = care.napWindow?.start && care.napWindow.end
    ? {
        start: toSecondPrecision(care.napWindow.start),
        end: toSecondPrecision(care.napWindow.end),
      }
    : null

  return {
    type: care.assistanceTypeHint,
    childAge: care.childAge ?? preset.childAge,
    walkLimits: {
      maxContinuousMeters: care.walkLimits.maxContinuousMeters ??
        preset.walkLimits.maxContinuousMeters,
      maxDailyMeters: care.walkLimits.maxDailyMeters ??
        preset.walkLimits.maxDailyMeters,
    },
    maxTransfers: care.maxTransfers ?? preset.maxTransfers,
    restInterval: care.restIntervalMinutes ?? preset.restInterval,
    napWindow: explicitNapWindow ?? preset.napWindow,
    avoidStairs: care.avoidStairs ?? preset.avoidStairs,
  }
}

export function singleParticipantPlanningDraft(
  revision: TripDraftRevision,
): CollaborationPlanningDraft | null {
  const understanding = revision.understanding
  if (
    understanding.participants.length !== 1 ||
    understanding.missingFields.length > 0 ||
    understanding.ambiguities.length > 0 ||
    understanding.confirmationQuestions.length > 0
  ) return null

  const participant = understanding.participants[0]
  const trip = understanding.trip
  if (
    !participant ||
    !revision.memberBindings[participant.memberKey] ||
    !trip.cityName ||
    !trip.travelDate ||
    !trip.startTime ||
    !trip.endTime ||
    !trip.startLocationText ||
    !trip.endLocationText ||
    trip.budgetCents === null
  ) return null

  const care = participant.careDraft
  const exactCareProfile = exactAssistanceProfile(care)
  if (!care || !exactCareProfile) return null

  return {
    schemaVersion: '1.0',
    cityName: trip.cityName,
    travelDate: trip.travelDate,
    startTime: trip.startTime,
    endTime: trip.endTime,
    startLocationText: trip.startLocationText,
    endLocationText: trip.endLocationText,
    budgetCents: trip.budgetCents,
    interests: [...participant.interests],
    mustVisit: [...participant.mustVisit],
    avoidPlaces: [...participant.avoidPlaces],
    assistanceMode: assistanceModeByType[exactCareProfile.type],
    assistanceProfile: {
      maxSegmentWalkMeters: exactCareProfile.walkLimits.maxContinuousMeters,
      maxTransfers: exactCareProfile.maxTransfers,
      restIntervalMinutes: exactCareProfile.restInterval,
    },
    collaborationCareDraft: {
      ...care,
      walkLimits: { ...care.walkLimits },
      napWindow: care.napWindow ? { ...care.napWindow } : null,
    },
    collaborationCareProfile: exactCareProfile,
    naturalLanguageRequest: [
      `${trip.travelDate}前往${trip.cityName}`,
      `${trip.startTime}至${trip.endTime}`,
      `${trip.startLocationText}到${trip.endLocationText}`,
    ].join('；'),
  }
}

export function invitationTokenFromText(value: string): string | null {
  const trimmed = value.trim()
  if (invitationTokenPattern.test(trimmed)) return trimmed
  try {
    const parsed = new URL(trimmed, 'https://local.invalid')
    const hashToken = new URLSearchParams(parsed.hash.replace(/^#/, '')).get('token')
    if (hashToken && invitationTokenPattern.test(hashToken)) return hashToken
    const queryToken = parsed.searchParams.get('token')
    if (queryToken && invitationTokenPattern.test(queryToken)) return queryToken
    const pathToken = parsed.pathname.split('/').filter(Boolean).at(-1)
    return pathToken && invitationTokenPattern.test(pathToken) ? pathToken : null
  } catch {
    return null
  }
}
