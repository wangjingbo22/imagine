import type { FacilityEvidence, ProviderRoute } from '../domain/trip'

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
