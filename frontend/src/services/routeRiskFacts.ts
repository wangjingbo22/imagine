import type { FacilityEvidence, ProviderRoute, TravelMode } from '../domain/trip'

export const DEFAULT_PREFERRED_WALK_METERS = 1_500

export function preferredTravelMode(
  directDistanceMeters: number,
  maxContinuousWalkMeters: number | null,
): TravelMode {
  const preferredWalkMeters = maxContinuousWalkMeters === null
    ? DEFAULT_PREFERRED_WALK_METERS
    : Math.max(100, maxContinuousWalkMeters) * 0.8
  return directDistanceMeters <= preferredWalkMeters ? 'WALKING' : 'TRANSIT'
}

export function facilityEvidenceNeedsConfirmation(evidence: FacilityEvidence) {
  return evidence.status === 'NEEDS_CONFIRMATION' ||
    evidence.provenance.sourceStatus === 'UNKNOWN'
}

export function hasCompleteRouteRiskFacts(route: ProviderRoute) {
  if (route.routeId.length > 120) return false
  if (route.mode !== 'TRANSIT') return true
  return route.walkingDistanceMeters !== null && route.transferCount !== null
}

export function routeWalkingMeters(route: ProviderRoute) {
  if (route.mode === 'WALKING') return route.distanceMeters
  if (route.mode === 'TRANSIT') return route.walkingDistanceMeters ?? 0
  return 0
}
