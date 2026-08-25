import type { AssistanceProfile, PlanningConstraint } from '../domain/trip'

export function compileAssistanceConstraints(
  profile: AssistanceProfile,
): PlanningConstraint[] {
  const constraints: PlanningConstraint[] = []
  if (profile.walkLimits.maxContinuousMeters !== null) {
    constraints.push({
      field: 'walkLimits.maxContinuousMeters',
      operator: 'LTE',
      value: profile.walkLimits.maxContinuousMeters,
      scope: 'ROUTE_SEGMENT',
      hardness: 'HARD',
    })
  }
  if (profile.walkLimits.maxDailyMeters !== null) {
    constraints.push({
      field: 'walkLimits.maxDailyMeters',
      operator: 'LTE',
      value: profile.walkLimits.maxDailyMeters,
      scope: 'DAY',
      hardness: 'HARD',
    })
  }
  if (profile.maxTransfers !== null) {
    constraints.push({
      field: 'maxTransfers',
      operator: 'LTE',
      value: profile.maxTransfers,
      scope: 'ROUTE',
      hardness: 'HARD',
    })
  }
  if (profile.restInterval !== null) {
    constraints.push({
      field: 'restInterval',
      operator: 'LTE',
      value: profile.restInterval,
      scope: 'ROUTE',
      hardness: 'HARD',
    })
  }
  if (profile.napWindow !== null) {
    constraints.push({
      field: 'napWindow',
      operator: 'BLOCK',
      value: {
        start: profile.napWindow.start,
        end: profile.napWindow.end,
      },
      scope: 'DAY',
      hardness: 'HARD',
    })
  }
  if (profile.type === 'PARENT_CHILD') {
    constraints.push({
      field: 'return',
      operator: 'ARRIVE_BY',
      value: {
        endLocationPath: 'days[0].endLocationText',
        deadlinePath: 'days[0].timeWindow.end',
      },
      scope: 'DAY',
      hardness: 'HARD',
    })
  }
  if (profile.avoidStairs) {
    constraints.push({
      field: 'avoidStairs',
      operator: 'EQ',
      value: true,
      scope: 'ROUTE_SEGMENT',
      hardness: 'HARD',
    })
  }
  return constraints
}
