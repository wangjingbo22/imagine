import assert from 'node:assert/strict'
import test from 'node:test'

import { requiredMealSlots } from '../src/services/itineraryPlaces.ts'

test('meal slots are required only when the confirmed window contains the whole meal', () => {
  assert.deepEqual(
    requiredMealSlots('09:00', '18:00').map((slot) => slot.kind),
    ['LUNCH'],
  )
  assert.deepEqual(requiredMealSlots('06:00', '11:00'), [])
  assert.deepEqual(requiredMealSlots('13:00', '17:30'), [])
  assert.deepEqual(
    requiredMealSlots('09:00', '20:00').map((slot) => slot.kind),
    ['LUNCH', 'DINNER'],
  )
})
