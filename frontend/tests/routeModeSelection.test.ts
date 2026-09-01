import assert from 'node:assert/strict'
import test from 'node:test'

import { routeModeCandidates } from '../src/services/amapPlan.ts'

test('does not select cycling unless it is explicitly allowed', () => {
  assert.deepEqual(routeModeCandidates(4_000, Number.POSITIVE_INFINITY), [
    'TRANSIT',
    'DRIVING',
    'WALKING',
  ])
})

test('keeps walking first for a short segment', () => {
  assert.deepEqual(routeModeCandidates(900, Number.POSITIVE_INFINITY), [
    'WALKING',
    'TRANSIT',
    'DRIVING',
  ])
})

test('allows cycling only for an explicit cycling preference', () => {
  assert.deepEqual(routeModeCandidates(4_000, Number.POSITIVE_INFINITY, true), [
    'BICYCLING',
    'TRANSIT',
    'DRIVING',
    'WALKING',
  ])
})

test('keeps cycling as a fallback for an explicitly allowed long segment', () => {
  assert.deepEqual(routeModeCandidates(12_000, Number.POSITIVE_INFINITY, true), [
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
