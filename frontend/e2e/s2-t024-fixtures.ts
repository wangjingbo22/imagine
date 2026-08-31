export const T024_TRIP_ID = '10000000-0000-4000-8000-000000000024'
export const T024_V1_ID = '20000000-0000-4000-8000-000000000024'
export const T024_V2_ID = '30000000-0000-4000-8000-000000000024'

export const tripSnapshot = {
  schemaVersion: '1.0',
  tripId: T024_TRIP_ID,
  mode: 'SINGLE',
  status: 'PLAN_REVIEW',
  cityContext: {
    countryCode: 'CN',
    cityCode: '110000',
    cityName: '北京市',
    center: { longitude: 116.407387, latitude: 39.904179 },
    providerConfig: { provider: 'AMAP', coordinateSystem: 'GCJ02' },
  },
  startDate: '2026-09-05',
  endDate: '2026-09-05',
  currency: 'CNY',
  totalBudgetCents: 35000,
  participants: [{
    participantId: '40000000-0000-4000-8000-000000000024',
    nickname: '组织者',
    budgetCapCents: 35000,
    preferences: [{ type: 'INTEREST', value: '历史文化' }],
    assistanceProfile: {
      type: 'LOW_STAMINA',
      childAge: null,
      walkLimits: { maxContinuousMeters: 500, maxDailyMeters: 3000 },
      maxTransfers: 2,
      restInterval: 90,
      napWindow: null,
      avoidStairs: false,
    },
  }],
  days: [{
    dayIndex: 0,
    date: '2026-09-05',
    dailyBudgetCents: 35000,
    startLocationText: '北京站',
    endLocationText: '北京站',
    timeWindow: { start: '09:00:00', end: '20:00:00' },
  }],
}

const tasks = [
  { taskId: 'task-1', order: 1, title: '中国国家博物馆', category: '博物馆', timeRange: '09:30–11:00', durationMinutes: 90, transport: '步行', costCents: 0, walkMeters: 420, note: '高德事实已核验' },
  { taskId: 'task-2', order: 2, title: '午餐与休息', category: '餐饮', timeRange: '11:30–13:00', durationMinutes: 90, transport: '公交', costCents: 8500, walkMeters: 260, note: '包含关怀休息时间' },
  { taskId: 'task-3', order: 3, title: '故宫博物院', category: '历史文化', timeRange: '14:00–17:00', durationMinutes: 180, transport: '公交', costCents: 6000, walkMeters: 480, note: '返程时间已保留' },
]

function plan(planId: string, version: 1 | 2, status: string, reason: string) {
  return {
    schemaVersion: '1.0',
    planId,
    tripSnapshot,
    version,
    parentId: version === 1 ? null : T024_V1_ID,
    reason,
    metrics: { totalCostCents: version === 1 ? 14500 : 13800, bufferCents: version === 1 ? 20500 : 21200, totalWalkMeters: version === 1 ? 1160 : 980, transferCount: 2, validationStatus: 'PASS' },
    days: [{ dayIndex: 0, date: '2026-09-05', tasks }],
    constraintsSnapshot: [{ ruleId: 'CARE.WALK', scope: 'trip', hardness: 'HARD', status: 'PASS', description: '步行限制通过', details: {} }],
    sourcesSnapshot: [{ provider: 'AMAP', sourceStatus: 'ONLINE', fetchedAt: '2026-09-05T01:00:00Z', isStale: false, referenceId: 'fact-route-1' }],
    status,
    createdAt: '2026-09-05T01:00:00Z',
    confirmedAt: status === 'PROPOSED' ? null : '2026-09-05T01:05:00Z',
  }
}

export const currentPlanV1 = plan(T024_V1_ID, 1, 'CURRENT', 'INITIAL_PLAN')
export const proposedPlanV2 = plan(T024_V2_ID, 2, 'PROPOSED', 'FATIGUE')
export const currentPlanV2 = plan(T024_V2_ID, 2, 'CURRENT', 'FATIGUE')

export function tripState(kind: 'execute' | 'diff' | 'summary') {
  const completed = kind === 'summary'
  const current = completed ? currentPlanV2 : currentPlanV1
  const events = tasks.flatMap((task, index) => {
    if (!completed && index > 0) return []
    return [{
      schemaVersion: '1.0',
      eventId: `50000000-0000-4000-8000-00000000002${index}`,
      tripId: T024_TRIP_ID,
      taskId: task.taskId,
      planVersionId: current.planId,
      eventType: 'COMPLETE',
      amountCents: null,
      idempotencyKey: `t024-complete-${index}`,
      occurredAt: `2026-09-05T0${index + 3}:00:00Z`,
    }]
  })
  return {
    tripId: T024_TRIP_ID,
    tripStatus: completed ? 'COMPLETED' : kind === 'diff' ? 'REPLAN_REVIEW' : 'EXECUTING',
    currentPlan: current,
    proposedPlans: kind === 'diff' ? [proposedPlanV2] : [],
    events,
    actualBudget: { tripId: T024_TRIP_ID, planVersionId: current.planId, plannedBudgetCents: 35000, actualSpentCents: 13200, remainingBudgetCents: 21800, expenseEventCount: 2 },
  }
}

export const planDiff = {
  tripId: T024_TRIP_ID,
  basePlanId: T024_V1_ID,
  candidatePlanId: T024_V2_ID,
  baseVersion: 1,
  candidateVersion: 2,
  items: [
    { category: 'TIME', changeType: 'CHANGED', key: 'task-3-time', label: '故宫结束时间', before: '17:00', after: '16:40' },
    { category: 'CARE', changeType: 'CHANGED', key: 'rest', label: '疲劳后休息安排', before: '每90分钟', after: '每60分钟' },
  ],
  metricsDelta: { totalCostCents: -700, totalWalkMeters: -180, transferCount: 0 },
}

export const tripSummary = {
  tripId: T024_TRIP_ID,
  tripStatus: 'COMPLETED',
  plannedCostCents: 13800,
  actualCostCents: 13200,
  differenceCents: -600,
  completedTaskIds: ['task-1', 'task-2', 'task-3'],
  skippedTaskIds: [],
  totalTasks: 3,
  currentPlanVersion: 2,
  planHistory: [
    { planId: T024_V1_ID, version: 1, status: 'SUPERSEDED', reason: 'INITIAL_PLAN' },
    { planId: T024_V2_ID, version: 2, status: 'CURRENT', reason: 'FATIGUE' },
  ],
  events: tripState('summary').events,
}

export const recommendationBundle = {
  candidates: Array.from({ length: 6 }, (_, index) => ({ factRefId: `place-fact-${index + 1}`, placeId: `place-${index + 1}`, name: ['中国国家博物馆', '故宫博物院', '景山公园', '天坛公园', '北海公园', '首都博物馆'][index], category: '历史文化' })),
  recommendations: [{ placeId: 'place-3', reason: '提供休息缓冲' }, { placeId: 'place-1', reason: '符合历史文化兴趣' }, { placeId: 'place-2', reason: '与起终点顺路' }],
  usedDeterministicFallback: false,
  trustedPlan: {
    tasks: [2, 0, 1].map((index) => ({ factRefId: `place-fact-${index + 1}`, placeId: `place-${index + 1}`, name: ['中国国家博物馆', '故宫博物院', '景山公园'][index], category: '历史文化' })),
    memberScores: [{ participantId: '40000000-0000-4000-8000-000000000024', score: 92, penaltyRuleIds: [], reasons: ['关怀约束与预算均满足'] }],
    lowestMemberScore: 92,
    carePoints: ['单段步行不超过500米', '每90分钟安排休息'],
    compromises: [],
    unknownFacts: [],
    confirmationMessage: '地点事实与关怀约束已核验，请组织者确认。',
  },
  factSetId: 'fact-set-t024-browser-fixture',
  providerFactDigest: 'c'.repeat(64),
  provenance: Array.from({ length: 6 }, (_, index) => ({
    factRefId: `place-fact-${index + 1}`,
    providerObjectId: `place-${index + 1}`,
    sourceStatus: 'ONLINE',
    fetchedAt: '2026-09-05T01:00:00Z',
    isStale: false,
  })),
}

export const organizerRevision = {
  schemaVersion: '1.0',
  draftId: '60000000-0000-4000-8000-000000000024',
  revision: 1,
  tripId: T024_TRIP_ID,
  understanding: {
    schemaVersion: '1.0',
    trip: {
      cityName: '北京', travelDate: '2026-09-05', startTime: '09:00', endTime: '20:00',
      startLocationText: '北京站', endLocationText: '北京站', budgetCents: 35000,
    },
    participants: [{
      memberKey: 'member-1', nickname: '组织者', budgetCapCents: 35000,
      interests: ['历史文化'], mustVisit: [], avoidPlaces: [],
      careDraft: {
        assistanceTypeHint: 'ORDINARY', childAge: null,
        walkLimits: { maxContinuousMeters: null, maxDailyMeters: null },
        maxTransfers: null, restIntervalMinutes: null, napWindow: null, avoidStairs: false,
      },
    }],
    fieldEvidence: [], missingFields: [], ambiguities: [], confirmationQuestions: [],
  },
  memberBindings: { 'member-1': '40000000-0000-4000-8000-000000000024' },
  sourceDigest: 'a'.repeat(64),
  createdAt: '2026-09-05T00:30:00Z',
}

export const organizerConversation = {
  revision: organizerRevision,
  organizerAccess: {
    tripId: T024_TRIP_ID,
    organizerParticipantId: '40000000-0000-4000-8000-000000000024',
    organizerToken: 't024-browser-only-token',
    organizerTokenAvailable: true,
    collaborationVersion: 1,
  },
}

export function collaborationState(ready: boolean) {
  return {
    schemaVersion: '1.0', tripId: T024_TRIP_ID,
    draftId: organizerRevision.draftId, currentRevision: 1,
    organizerParticipantId: organizerConversation.organizerAccess.organizerParticipantId,
    status: ready ? 'READY_TO_PLAN' : 'COLLECTING_MEMBERS',
    collaborationVersion: ready ? 2 : 1,
    policyVersion: 'S2-T003.1',
    readinessDigest: ready ? 'b'.repeat(64) : null,
    canPlan: ready,
    progress: { expectedCount: 1, confirmedCount: ready ? 1 : 0, openIssueCount: 0 },
    participants: [{
      participantId: organizerConversation.organizerAccess.organizerParticipantId,
      memberKey: 'member-1', role: 'ORGANIZER', accessStatus: 'ORGANIZER_ACTIVE',
      confirmationStatus: ready ? 'CONFIRMED' : 'UNCONFIRMED',
      confirmedRevision: ready ? 1 : null,
    }],
    confirmationItems: [],
  }
}
