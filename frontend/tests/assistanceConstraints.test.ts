import assert from 'node:assert/strict'
import test from 'node:test'

import type { AssistanceProfile } from '../src/domain/trip.ts'
import { compileAssistanceConstraints } from '../src/services/assistanceConstraints.ts'

function profile(overrides: Partial<AssistanceProfile>): AssistanceProfile {
  return {
    type: 'ORDINARY',
    childAge: null,
    walkLimits: { maxContinuousMeters: null, maxDailyMeters: null },
    maxTransfers: null,
    restInterval: null,
    napWindow: null,
    avoidStairs: false,
    ...overrides,
  }
}

test('ordinary profile compiles to no T007 care constraints', () => {
  assert.deepEqual(compileAssistanceConstraints(profile({})), [])
})

test('parent-child profile freezes nap then return rules', () => {
  assert.deepEqual(compileAssistanceConstraints(profile({
    type: 'PARENT_CHILD',
    childAge: 8,
    napWindow: { start: '13:00:00', end: '14:00:00' },
  })), [
    {
      field: 'napWindow',
      operator: 'BLOCK',
      value: { start: '13:00:00', end: '14:00:00' },
      scope: 'DAY',
      hardness: 'HARD',
    },
    {
      field: 'return',
      operator: 'ARRIVE_BY',
      value: {
        endLocationPath: 'days[0].endLocationText',
        deadlinePath: 'days[0].timeWindow.end',
      },
      scope: 'DAY',
      hardness: 'HARD',
    },
  ])
})

test('low-stamina profile freezes walking, transfers, and rest order', () => {
  assert.deepEqual(compileAssistanceConstraints(profile({
    type: 'LOW_STAMINA',
    walkLimits: { maxContinuousMeters: 500, maxDailyMeters: 3_000 },
    maxTransfers: 2,
    restInterval: 90,
  })), [
    {
      field: 'walkLimits.maxContinuousMeters',
      operator: 'LTE',
      value: 500,
      scope: 'ROUTE_SEGMENT',
      hardness: 'HARD',
    },
    {
      field: 'walkLimits.maxDailyMeters',
      operator: 'LTE',
      value: 3_000,
      scope: 'DAY',
      hardness: 'HARD',
    },
    {
      field: 'maxTransfers',
      operator: 'LTE',
      value: 2,
      scope: 'ROUTE',
      hardness: 'HARD',
    },
    {
      field: 'restInterval',
      operator: 'LTE',
      value: 90,
      scope: 'ROUTE',
      hardness: 'HARD',
    },
  ])
})

test('mobility-assistance profile freezes avoid-stairs rule', () => {
  assert.deepEqual(compileAssistanceConstraints(profile({
    type: 'MOBILITY_ASSISTANCE_BETA',
    avoidStairs: true,
  })), [{
    field: 'avoidStairs',
    operator: 'EQ',
    value: true,
    scope: 'ROUTE_SEGMENT',
    hardness: 'HARD',
  }])
})
