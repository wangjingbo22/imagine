import type {
  AssistanceProfile,
  ConstraintValue,
  PlanningConstraint,
} from '../domain/trip'

export interface GroupPlanningCare {
  maxContinuousMeters: number | null
  maxTransfers: number | null
  restInterval: number | null
  napWindow: { start: string; end: string } | null
  avoidStairs: boolean
}

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

function constraintKey(constraint: PlanningConstraint) {
  return [
    constraint.field,
    constraint.operator,
    constraint.scope,
    constraint.hardness,
  ].join('|')
}

function sameValue(left: ConstraintValue, right: ConstraintValue) {
  return JSON.stringify(left) === JSON.stringify(right)
}

function isNapWindow(
  value: ConstraintValue | undefined,
): value is { start: string; end: string } {
  return Boolean(
    value &&
    !Array.isArray(value) &&
    typeof value === 'object' &&
    typeof value.start === 'string' &&
    typeof value.end === 'string',
  )
}

export function compileGroupAssistanceConstraints(
  profiles: Array<AssistanceProfile | null | undefined>,
): PlanningConstraint[] {
  const grouped = new Map<string, PlanningConstraint[]>()
  for (const profile of profiles) {
    if (!profile) continue
    for (const constraint of compileAssistanceConstraints(profile)) {
      const key = constraintKey(constraint)
      grouped.set(key, [...(grouped.get(key) ?? []), constraint])
    }
  }

  return [...grouped.values()].map((entries) => {
    const first = entries[0]
    if (entries.every((entry) => sameValue(entry.value, first.value))) {
      return first
    }
    if (
      first.operator === 'LTE' &&
      entries.every((entry) => typeof entry.value === 'number')
    ) {
      return {
        ...first,
        value: Math.min(...entries.map((entry) => entry.value as number)),
      }
    }
    if (
      first.field === 'napWindow' &&
      entries.every((entry) => isNapWindow(entry.value))
    ) {
      const windows = entries.map((entry) => entry.value).filter(isNapWindow)
      return {
        ...first,
        value: {
          start: windows.map((window) => window.start).sort()[0],
          end: windows.map((window) => window.end).sort().at(-1)!,
        },
      }
    }
    throw new Error(`多人关怀硬约束无法确定性合并：${first.field}`)
  })
}

export function planningCareFromConstraints(
  constraints: PlanningConstraint[],
): GroupPlanningCare {
  const valueFor = (field: string) => constraints.find(
    (constraint) => constraint.field === field,
  )?.value
  const maxContinuousMeters = valueFor('walkLimits.maxContinuousMeters')
  const maxTransfers = valueFor('maxTransfers')
  const restInterval = valueFor('restInterval')
  const napWindow = valueFor('napWindow')
  return {
    maxContinuousMeters: typeof maxContinuousMeters === 'number'
      ? maxContinuousMeters
      : null,
    maxTransfers: typeof maxTransfers === 'number' ? maxTransfers : null,
    restInterval: typeof restInterval === 'number' ? restInterval : null,
    napWindow: isNapWindow(napWindow) ? napWindow : null,
    avoidStairs: valueFor('avoidStairs') === true,
  }
}
