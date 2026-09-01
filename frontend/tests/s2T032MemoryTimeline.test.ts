import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import {
  assistanceProfileDetails,
  extractBoundTimelinePhotos,
  memoryPlanStatusLabel,
  memoryTimelineItemTitle,
  orderMemoryTimelineItems,
  type MemoryTimelineItem,
} from '../src/components/MemoryTimelinePanel.tsx'

function timelineItem(
  itemId: string,
  occurredAt: string,
  overrides: Partial<MemoryTimelineItem> = {},
): MemoryTimelineItem {
  return {
    itemId,
    kind: 'TASK_STARTED',
    occurredAt,
    title: itemId,
    taskId: null,
    eventId: null,
    eventType: 'START',
    planVersionId: null,
    planVersion: null,
    planStatus: null,
    amountCents: null,
    cumulativeActualCostCents: null,
    completionRatePercent: null,
    assistanceProfile: null,
    photo: null,
    ...overrides,
  }
}

test('T032 memory items render by real occurredAt while preserving server tie order', () => {
  const items = [
    timelineItem('later', '2026-09-05T05:00:00Z'),
    timelineItem('same-time-first', '2026-09-05T03:00:00Z'),
    timelineItem('earlier', '2026-09-05T01:00:00Z'),
    timelineItem('same-time-second', '2026-09-05T03:00:00Z'),
  ]

  assert.deepEqual(
    orderMemoryTimelineItems(items).map((item) => item.itemId),
    ['earlier', 'same-time-first', 'same-time-second', 'later'],
  )
  assert.deepEqual(items.map((item) => item.itemId), [
    'later',
    'same-time-first',
    'earlier',
    'same-time-second',
  ])
})

test('plan versions use Chinese presentation labels instead of API enums', () => {
  const item = timelineItem('plan-current', '2026-09-05T01:00:00Z', {
    kind: 'PLAN_VERSION',
    eventType: null,
    planVersion: 1,
    planStatus: 'CURRENT',
    title: '行程方案 V1：CURRENT',
  })

  assert.equal(memoryPlanStatusLabel('CURRENT'), '当前使用')
  assert.equal(memoryPlanStatusLabel('REJECTED'), '已拒绝')
  assert.equal(memoryPlanStatusLabel('UNKNOWN_STATUS'), '状态待确认')
  assert.equal(memoryTimelineItemTitle(item), '行程方案 V1：当前使用')
})

test('T032 memory photos require the timeline item and media to bind the same task', () => {
  const activePhoto = {
    mediaId: 'media-active',
    taskId: 'task-1',
    dataUrl: 'data:image/jpeg;base64,ACTIVE',
    mimeType: 'image/jpeg',
    byteSize: 128,
    createdAt: '2026-09-05T04:00:00Z',
  }
  const items = [
    timelineItem('photo:active', activePhoto.createdAt, {
      kind: 'PHOTO',
      taskId: 'task-1',
      eventType: null,
      photo: activePhoto,
    }),
    timelineItem('photo:wrong-task', '2026-09-05T04:01:00Z', {
      kind: 'PHOTO',
      taskId: 'task-2',
      eventType: null,
      photo: { ...activePhoto, mediaId: 'media-wrong' },
    }),
    timelineItem('photo:missing', '2026-09-05T04:02:00Z', {
      kind: 'PHOTO',
      taskId: 'task-3',
      eventType: null,
    }),
  ]

  const result = extractBoundTimelinePhotos(items)
  assert.deepEqual(result.photos.map((photo) => photo.mediaId), ['media-active'])
  assert.deepEqual(result.invalidItemIds, ['photo:wrong-task', 'photo:missing'])
  assert.doesNotMatch(JSON.stringify(result), /DELETED-PHOTO/)
})

test('T032 memory care summary exposes deterministic confirmed restrictions', () => {
  assert.deepEqual(assistanceProfileDetails({
    type: 'LOW_STAMINA',
    childAge: null,
    walkLimits: { maxContinuousMeters: 500, maxDailyMeters: 3000 },
    maxTransfers: 2,
    restInterval: 60,
    napWindow: null,
    avoidStairs: true,
  }), [
    '低体力关怀',
    '单段步行不超过 500 米',
    '全天步行不超过 3000 米',
    '单程换乘不超过 2 次',
    '每 60 分钟安排休息',
    '路线避开楼梯',
  ])
  assert.deepEqual(assistanceProfileDetails(null), [
    '未提供单一关怀档案；多人行程请查看各成员确认卡',
  ])
})

test('T032 workspace consumes MemoryTimeline without removing the legacy summary', async () => {
  const [panel, workspace, photos, css] = await Promise.all([
    readFile(new URL('../src/components/MemoryTimelinePanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/WorkspacePage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/MemoryPhotoStrip.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/styles/white-web.css', import.meta.url), 'utf8'),
  ])

  assert.match(panel, /\/api\/v1\/trips\/\$\{encodeURIComponent\(tripId\)\}\/memory-timeline/)
  assert.match(panel, /role="status" aria-live="polite"/)
  assert.match(panel, /role="alert"/)
  assert.match(panel, /<time dateTime=\{item\.occurredAt\}>/)
  assert.match(panel, /participantCareResults/)
  assert.match(panel, /participant\.nickname/)
  assert.match(panel, /participant\.assistanceProfile/)
  assert.match(panel, /<MemoryPhotoStrip[\s\S]*photos=\{boundPhotos\.photos\}/)
  assert.match(workspace, /tripApi\.getSummary\(tripId\)/)
  assert.match(workspace, /<MemoryTimelinePanel/)
  assert.doesNotMatch(workspace, /<MemoryPhotoStrip/)
  assert.match(photos, /Promise\.allSettled/)
  assert.match(photos, /photo\.taskId !== result\.value\.task\.id/)
  assert.match(photos, /summary-media__error" role="alert"/)
  assert.match(css, /\.memory-timeline-panel__error \.button,[\s\S]*min-height: 44px/)
  assert.match(css, /\.memory-timeline-summary \{[\s\S]*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)/)
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.memory-timeline-summary \{[\s\S]*repeat\(2, minmax\(0, 1fr\)\)/)
})
