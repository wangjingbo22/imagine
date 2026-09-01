export type ParentTripDay = {
  dayIndex: number; date: string; budgetCents: number; childTripId: string | null
  childBudgetCents: number | null; plannedCostCents: number | null
  actualSpentCents: number | null; remainingBudgetCents: number | null
  childStatus: string; costStatus: 'NOT_AVAILABLE' | 'PLANNED' | 'ACTUAL_RECORDED'
}

export type ParentTrip = {
  schemaVersion: '1.0'; parentTripId: string; title: string; cityName: string
  startDate: string; endDate: string; totalBudgetCents: number
  plannedCostCents: number | null; actualSpentCents: number | null; days: ParentTripDay[]
}
