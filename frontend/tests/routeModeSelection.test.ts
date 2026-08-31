import assert from 'node:assert/strict'
import test from 'node:test'

import { routeModeCandidates } from '../src/services/amapPlan.ts'

test('prefers walking for a short segment', () => {
  assert.deepEqual(routeModeCandidates(900, Number.POSITIVE_INFINITY), [
    'WALKING',
    'BICYCLING',
    'TRANSIT',
    'DRIVING',
  ])
})

test('prefers bicycling for a medium segment', () => {
  assert.deepEqual(routeModeCandidates(4_000, Number.POSITIVE_INFINITY), [
    'BICYCLING',
    'TRANSIT',
    'DRIVING',
    'WALKING',
  ])
})

test('prefers public transit for a long segment', () => {
  assert.deepEqual(routeModeCandidates(12_000, Number.POSITIVE_INFINITY), [
    'TRANSIT',
    'BICYCLING',
    'DRIVING',
    'WALKING',
  ])
})

test('does not prefer bicycling for a care profile that disallows it', () => {
  assert.deepEqual(routeModeCandidates(4_000, 500, false), [
    'TRANSIT',
    'DRIVING',
    'WALKING',
  ])
})
