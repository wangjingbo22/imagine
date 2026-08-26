import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildNaturalLanguageParseInput,
  splitPlaceInput,
  toRecognizedFormPatch,
} from '../src/services/tripDraftRecognition.ts'

test('recognition request excludes seeded Beijing form defaults', () => {
  const input = buildNaturalLanguageParseInput({
    tripId: '11111111-1111-4111-8111-111111111111',
    naturalLanguageRequest: '9月3日去洛阳，预算500元',
    assistanceMode: 'low-mobility',
    assistanceProfile: {
      maxSegmentWalkMeters: 500,
      maxTransfers: 2,
      restIntervalMinutes: 90,
    },
  })

  assert.equal(input.cityName, null)
  assert.equal(input.travelDate, null)
  assert.equal(input.startLocationText, null)
  assert.equal(input.budgetCents, null)
  assert.deepEqual(input.interests, [])
  assert.equal(input.naturalLanguageRequest, '9月3日去洛阳，预算500元')
})

test('recognized fields are converted to editable form values', () => {
  const patch = toRecognizedFormPatch({
    cityName: '洛阳',
    travelDate: '2026-09-03',
    startTime: '09:30',
    endTime: '19:00',
    startLocationText: '洛阳龙门站',
    endLocationText: '洛阳龙门站',
    budgetCents: 50_000,
    interests: ['历史文化'],
    mustVisit: ['龙门石窟'],
    avoidPlaces: ['丽景门'],
  })

  assert.equal(patch.cityName, '洛阳')
  assert.equal(patch.budgetYuan, '500')
  assert.equal(patch.endSameAsStart, true)
  assert.equal(patch.mustVisitText, '龙门石窟')
  assert.equal(patch.avoidPlacesText, '丽景门')
})

test('multiple recognized places remain separate contract values', () => {
  assert.deepEqual(splitPlaceInput('龙门石窟、白马寺，洛阳博物馆'), [
    '龙门石窟',
    '白马寺',
    '洛阳博物馆',
  ])
})
