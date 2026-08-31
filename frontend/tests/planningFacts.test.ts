import assert from 'node:assert/strict'
import test from 'node:test'

import type { CandidatePlanRequest } from '../src/domain/trip.ts'
import { restoreDraftFromPlanningFacts } from '../src/services/planningFacts.ts'

function requestFixture(): CandidatePlanRequest {
  return {
    schemaVersion: '1.0',
    trip: {
      schemaVersion: '1.0',
      tripId: '11111111-1111-4111-8111-111111111111',
      mode: 'SINGLE',
      status: 'PLANNING',
      cityContext: {
        countryCode: 'CN',
        cityCode: '110100',
        cityName: '北京市',
        center: { longitude: 116.4, latitude: 39.9 },
        providerConfig: { provider: 'AMAP', coordinateSystem: 'GCJ02' },
      },
      startDate: '2026-08-25',
      endDate: '2026-08-25',
      currency: 'CNY',
      totalBudgetCents: 35_000,
      participants: [{
        participantId: '22222222-2222-4222-8222-222222222222',
        nickname: '旅客',
        budgetCapCents: 35_000,
        preferences: [
          { type: 'INTEREST', value: '博物馆', weight: 4, isHard: false },
          { type: 'MUST_VISIT', value: '故宫', weight: 5, isHard: true },
          { type: 'AVOID_PLACE', value: '楼梯', weight: 5, isHard: true },
        ],
        assistanceProfile: {
          type: 'LOW_STAMINA',
          childAge: null,
          walkLimits: { maxContinuousMeters: 480, maxDailyMeters: null },
          maxTransfers: 1,
          restInterval: 75,
          napWindow: null,
          avoidStairs: false,
        },
      }],
      days: [{
        dayIndex: 0,
        date: '2026-08-25',
        dailyBudgetCents: 35_000,
        startLocationText: '北京市中心',
        endLocationText: '故宫',
        timeWindow: { start: '09:00:00', end: '20:00:00' },
      }],
    },
    startLocation: {} as CandidatePlanRequest['startLocation'],
    endLocation: {} as CandidatePlanRequest['endLocation'],
    taskFacts: [],
    confirmedConstraints: [],
  }
}

test('signed planning facts restore search inputs after a browser refresh', () => {
  const restored = restoreDraftFromPlanningFacts(requestFixture())
  assert.deepEqual(restored, {
    schemaVersion: '1.0',
    cityName: '北京市',
    travelDate: '2026-08-25',
    startTime: '09:00',
    endTime: '20:00',
    startLocationText: '北京市中心',
    endLocationText: '故宫',
    budgetCents: 35_000,
    interests: ['博物馆'],
    mustVisit: ['故宫'],
    avoidPlaces: ['楼梯'],
    assistanceMode: 'low-mobility',
    assistanceProfile: {
      maxSegmentWalkMeters: 480,
      maxTransfers: 1,
      restIntervalMinutes: 75,
    },
    naturalLanguageRequest: '从服务端签发的规划事实恢复',
  })
})

test('missing optional assistance data stays unconstrained instead of inventing limits', () => {
  const request = requestFixture()
  request.trip.participants[0].assistanceProfile = null
  const restored = restoreDraftFromPlanningFacts(request)
  assert.equal(restored.assistanceMode, 'standard')
  assert.deepEqual(restored.assistanceProfile, {
    maxSegmentWalkMeters: null,
    maxTransfers: null,
    restIntervalMinutes: null,
  })
})

test('group planning facts restore every member preference and the strictest shared care limits', () => {
  const request = requestFixture()
  request.trip.mode = 'GROUP'
  request.trip.participants.push({
    participantId: '33333333-3333-4333-8333-333333333333',
    nickname: '同行成员',
    budgetCapCents: 30_000,
    preferences: [
      { type: 'INTEREST', value: '建筑', weight: 4, isHard: false },
      { type: 'MUST_VISIT', value: '天坛', weight: 5, isHard: true },
      { type: 'AVOID_PLACE', value: '拥挤商场', weight: 5, isHard: true },
    ],
    assistanceProfile: {
      type: 'LOW_STAMINA',
      childAge: null,
      walkLimits: { maxContinuousMeters: 320, maxDailyMeters: null },
      maxTransfers: 0,
      restInterval: 45,
      napWindow: null,
      avoidStairs: false,
    },
  })

  const restored = restoreDraftFromPlanningFacts(request)
  assert.deepEqual(restored.interests, ['博物馆', '建筑'])
  assert.deepEqual(restored.mustVisit, ['故宫', '天坛'])
  assert.deepEqual(restored.avoidPlaces, ['楼梯', '拥挤商场'])
  assert.equal(restored.assistanceMode, 'low-mobility')
  assert.deepEqual(restored.assistanceProfile, {
    maxSegmentWalkMeters: 320,
    maxTransfers: 0,
    restIntervalMinutes: 45,
  })
})
