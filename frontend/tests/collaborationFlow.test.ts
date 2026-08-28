import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import type { CareDraft, TripDraftRevision } from '../src/domain/collaboration.ts'
import {
  invitationTokenFromText,
  singleParticipantPlanningDraft,
} from '../src/services/collaborationDraft.ts'

const token = 'a'.repeat(43)

function revision(participantCount = 1): TripDraftRevision {
  const participants = Array.from({ length: participantCount }, (_, index) => ({
    memberKey: `member-${index + 1}` as 'member-1' | 'member-2' | 'member-3',
    nickname: `成员${index + 1}`,
    budgetCapCents: 50_000,
    interests: ['美食'],
    mustVisit: ['博物馆'],
    avoidPlaces: ['拥挤商场'],
    careDraft: {
      assistanceTypeHint: 'ORDINARY' as const,
      childAge: null,
      walkLimits: { maxContinuousMeters: null, maxDailyMeters: null },
      maxTransfers: null,
      restIntervalMinutes: null,
      napWindow: null,
      avoidStairs: false,
    },
  }))
  return {
    schemaVersion: '1.0',
    draftId: '20000000-0000-4000-8000-000000000001',
    revision: 1,
    tripId: '30000000-0000-4000-8000-000000000001',
    understanding: {
      schemaVersion: '1.0',
      trip: {
        cityName: '杭州', travelDate: '2026-08-29', startTime: '09:00', endTime: '20:00',
        startLocationText: '杭州东站', endLocationText: '杭州东站', budgetCents: 50_000,
      },
      participants,
      fieldEvidence: [], missingFields: [], ambiguities: [], confirmationQuestions: [],
    },
    memberBindings: Object.fromEntries(participants.map((item, index) => [
      item.memberKey,
      `10000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
    ])) as TripDraftRevision['memberBindings'],
    sourceDigest: 'f'.repeat(64),
    createdAt: '2026-08-28T10:00:00+08:00',
  }
}

test('only one complete authoritative revision maps to the legacy single planning draft', () => {
  const single = singleParticipantPlanningDraft(revision())
  assert.equal(single?.cityName, '杭州')
  assert.equal(single?.naturalLanguageRequest, '2026-08-29前往杭州；09:00至20:00；杭州东站到杭州东站')
  assert.equal(single?.assistanceMode, 'standard')
  assert.deepEqual(single?.collaborationCareProfile, {
    type: 'ORDINARY',
    childAge: null,
    walkLimits: { maxContinuousMeters: null, maxDailyMeters: null },
    maxTransfers: null,
    restInterval: null,
    napWindow: null,
    avoidStairs: false,
  })
  assert.equal(singleParticipantPlanningDraft(revision(2)), null)
  const incomplete = revision()
  incomplete.understanding.missingFields.push({
    fieldPath: 'trip.cityName', memberKey: null, code: 'MISSING', questionKey: 'CITY_REQUIRED',
  })
  assert.equal(singleParticipantPlanningDraft(incomplete), null)
  const unknownCare = revision()
  unknownCare.understanding.participants[0]!.careDraft = null
  assert.equal(singleParticipantPlanningDraft(unknownCare), null)
  const lossyCare = revision()
  lossyCare.understanding.participants[0]!.careDraft = {
    ...lossyCare.understanding.participants[0]!.careDraft!,
    assistanceTypeHint: 'PARENT_CHILD',
    napWindow: { start: '12:30', end: '14:00' },
  }
  const customFamily = singleParticipantPlanningDraft(lossyCare)
  assert.equal(customFamily?.assistanceMode, 'family')
  assert.deepEqual(customFamily?.collaborationCareProfile.napWindow, {
    start: '12:30:00',
    end: '14:00:00',
  })
})

test('all READY single care presets and explicit overrides map without losing facts', () => {
  const cases: Array<{
    care: CareDraft
    mode: NonNullable<ReturnType<typeof singleParticipantPlanningDraft>>['assistanceMode']
    expectedProfile: NonNullable<ReturnType<typeof singleParticipantPlanningDraft>>['collaborationCareProfile']
  }> = [
    {
      care: {
        assistanceTypeHint: 'LOW_STAMINA', childAge: null,
        walkLimits: { maxContinuousMeters: null, maxDailyMeters: null },
        maxTransfers: null, restIntervalMinutes: null, napWindow: null,
        avoidStairs: null,
      },
      mode: 'low-mobility',
      expectedProfile: {
        type: 'LOW_STAMINA', childAge: null,
        walkLimits: { maxContinuousMeters: 500, maxDailyMeters: null },
        maxTransfers: 2, restInterval: 90, napWindow: null, avoidStairs: false,
      },
    },
    {
      care: {
        assistanceTypeHint: 'PARENT_CHILD', childAge: 6,
        walkLimits: { maxContinuousMeters: 650, maxDailyMeters: 3_200 },
        maxTransfers: 1, restIntervalMinutes: 55,
        napWindow: { start: '12:40', end: '13:35' }, avoidStairs: true,
      },
      mode: 'family',
      expectedProfile: {
        type: 'PARENT_CHILD', childAge: 6,
        walkLimits: { maxContinuousMeters: 650, maxDailyMeters: 3_200 },
        maxTransfers: 1, restInterval: 55,
        napWindow: { start: '12:40:00', end: '13:35:00' }, avoidStairs: true,
      },
    },
    {
      care: {
        assistanceTypeHint: 'MOBILITY_ASSISTANCE_BETA', childAge: null,
        walkLimits: { maxContinuousMeters: 300, maxDailyMeters: 1_500 },
        maxTransfers: 0, restIntervalMinutes: 40, napWindow: null,
        avoidStairs: false,
      },
      mode: 'assisted',
      expectedProfile: {
        type: 'MOBILITY_ASSISTANCE_BETA', childAge: null,
        walkLimits: { maxContinuousMeters: 300, maxDailyMeters: 1_500 },
        maxTransfers: 0, restInterval: 40, napWindow: null, avoidStairs: false,
      },
    },
  ]

  for (const { care, mode, expectedProfile } of cases) {
    const input = revision()
    input.understanding.participants[0]!.careDraft = care
    const draft = singleParticipantPlanningDraft(input)
    assert.ok(draft)
    assert.equal(draft.assistanceMode, mode)
    assert.deepEqual(draft.collaborationCareDraft, care)
    assert.deepEqual(draft.collaborationCareProfile, expectedProfile)
    assert.deepEqual(draft.assistanceProfile, {
      maxSegmentWalkMeters: expectedProfile.walkLimits.maxContinuousMeters,
      maxTransfers: expectedProfile.maxTransfers,
      restIntervalMinutes: expectedProfile.restInterval,
    })
  }
})

test('invitation token is read from the hash/body value and malformed text is rejected', () => {
  assert.equal(invitationTokenFromText(token), token)
  assert.equal(invitationTokenFromText(`https://example.test/join#token=${token}`), token)
  assert.equal(invitationTokenFromText(`https://example.test/join/${token}`), token)
  assert.equal(invitationTokenFromText('short-token'), null)
})

test('collaboration API preserves capabilities and optimistic concurrency fields', async () => {
  const api = await readFile(new URL('../src/api/collaborationApi.ts', import.meta.url), 'utf8')
  assert.match(api, /'\/api\/v2\/trips\/conversations'/)
  assert.match(api, /headers: \{ 'Idempotency-Key': idempotencyKey \}/)
  assert.match(api, /JSON\.stringify\(\{ schemaVersion: '1\.0', \.\.\.input \}\)/)
  assert.match(api, /candidate\.fallback\?\.mode === 'FIXED_QUESTIONS'/)
  assert.match(api, /participants\/\$\{encodeURIComponent\(input\.participantId\)\}\/invitations/)
  assert.match(api, /expectedVersion: input\.expectedVersion/)
  assert.match(api, /'\/api\/v2\/participant-invitations\/redeem'/)
  assert.match(api, /body: JSON\.stringify\(\{ schemaVersion: '1\.0', token \}\)/)
  assert.match(api, /'X-Participant-Session': input\.participantSessionToken/)
  assert.match(api, /baseRevision: input\.baseRevision/)
  assert.doesNotMatch(api, /member-session[^'`]*\$\{[^}]*token/)
})

test('organizer page serially rolls the collaboration version and fails closed for group planning context', async () => {
  const page = await readFile(new URL('../src/pages/ConversationPlannerPage.tsx', import.meta.url), 'utf8')
  assert.match(page, /for \(const participant of state\.participants\.filter/)
  assert.match(page, /expectedVersion = invitation\.collaborationVersion/)
  assert.match(page, /setLinks\(\(current\) => current\.includes\(link\)/)
  assert.match(page, /accessStatus: 'INVITED'/)
  assert.match(page, /singleParticipantPlanningDraft\(revision\)/)
  assert.match(page, /多人 Trip 尚不能无损转换/)
  assert.doesNotMatch(page, /mode:\s*'GROUP'/)
})

test('recommendation route consumes the guarded server Trip without legacy reconfirmation', async () => {
  const [page, api] = await Promise.all([
    readFile(new URL('../src/pages/RecommendationPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/api/tripApi.ts', import.meta.url), 'utf8'),
  ])
  assert.match(page, /getCollaborationPlanningTrip\(tripId, token\)/)
  assert.doesNotMatch(page, /confirmDraft|saveConstraintDraft|confirmConstraints/)
  assert.match(api, /\/api\/v2\/trips\/\$\{tripId\}\/planning-trip/)
  assert.match(api, /'X-Organizer-Token': organizerToken/)
})

test('a new invitation never falls through to another participant last session', async () => {
  const page = await readFile(new URL('../src/pages/MemberConversationPage.tsx', import.meta.url), 'utf8')
  assert.match(page, /let capability = token\s*\? window\.sessionStorage\.getItem\(`participant-session:\$\{token\}`\)\s*:\s*window\.sessionStorage\.getItem\('participant-session:last'\)/)
  assert.match(page, /window\.history\.replaceState\(null, '', '\/join'\)/)
})
