export type MealKind = 'LUNCH' | 'DINNER'

export interface MealSlot {
  kind: MealKind
  label: '午餐' | '晚餐'
  start: string
  end: string
}

const diningTerms = [
  '餐饮服务', '中餐厅', '外国餐厅', '餐厅', '饭店', '快餐', '小吃',
  '火锅', '咖啡厅', '茶艺馆', '甜品店', '美食街', '美食城',
  '美食广场', '小吃街', '餐饮街', '食街', '夜市',
]

const lodgingTerms = [
  '住宿服务', '宾馆酒店', '经济型连锁酒店', '酒店', '宾馆', '旅馆',
  '民宿', '客栈', '公寓酒店', '招待所',
]

const standardMealSlots: readonly MealSlot[] = [
  { kind: 'LUNCH', label: '午餐', start: '12:00', end: '13:00' },
  { kind: 'DINNER', label: '晚餐', start: '18:00', end: '19:00' },
]

function normalizedPlaceText(name: string, category: string | null | undefined) {
  return `${name} ${category ?? ''}`.normalize('NFKC').trim().toLowerCase()
}

function minutesSinceMidnight(value: string) {
  const [hour, minute] = value.split(':').map(Number)
  return hour * 60 + minute
}

export function isLodgingPlaceLike(
  name: string,
  category: string | null | undefined,
) {
  const text = normalizedPlaceText(name, category)
  return lodgingTerms.some((term) => text.includes(term))
}

export function isDiningPlaceLike(
  name: string,
  category: string | null | undefined,
) {
  if (isLodgingPlaceLike(name, category)) return false
  const text = normalizedPlaceText(name, category)
  return diningTerms.some((term) => text.includes(term))
}

export function requiredMealSlots(windowStart: string, windowEnd: string) {
  const start = minutesSinceMidnight(windowStart)
  const end = minutesSinceMidnight(windowEnd)
  return standardMealSlots.filter((slot) => (
    start <= minutesSinceMidnight(slot.start) &&
    minutesSinceMidnight(slot.end) <= end
  ))
}
