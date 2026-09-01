import {
  CalendarDays,
  Check,
  ChevronRight,
  Copy,
  MapPin,
  RefreshCw,
  UserPlus,
  Users,
  WalletCards,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  createParentTrip,
  createParentTripInvitation,
  getParentTripSync,
  updateParentTripDayBudget,
} from '../api/parentTripApi'
import { AppShell } from '../components/AppShell'
import type {
  ParentTrip,
  ParentTripInvitationCreated,
  ParentTripMemberProfile,
  ParentTripSyncView,
} from '../domain/parentTrip'
import {
  createParentIdempotencyKey,
  parentTripOrganizerTokenKey,
  PARENT_TRIP_POLL_INTERVAL_MS,
} from '../services/parentTripCollaboration'
import {
  futureDateValue,
  localDateValue,
  validateFutureDate,
} from '../services/tripTimeConstraints'

const citySuggestions = ['北京', '上海', '成都', '西安', '杭州']
const MIN_DAY_COUNT = 2
const MAX_DAY_COUNT = 30
const MAX_PARTICIPANT_COUNT = 20
const yuan = (cents: number | null) => cents === null ? '尚未生成' : `¥${(cents / 100).toFixed(0)}`
const accessLabel: Record<ParentTripMemberProfile['accessStatus'], string> = {
  ORGANIZER_ACTIVE: '组织者',
  INVITED: '等待加入',
  MEMBER_ACTIVE: '已加入',
}

export function ParentTripPage() {
  const { parentTripId = '' } = useParams()
  const navigate = useNavigate()
  const [trip, setTrip] = useState<ParentTrip | null>(null)
  const [syncView, setSyncView] = useState<ParentTripSyncView | null>(null)
  const [invitation, setInvitation] = useState<ParentTripInvitationCreated | null>(null)
  const [invitationUrl, setInvitationUrl] = useState('')
  const [copyDone, setCopyDone] = useState(false)
  const [form, setForm] = useState(() => ({ title: '周末同城之旅', cityName: '北京', startDate: futureDateValue(), dayCount: 2, totalBudget: '1000' }))
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [inviteBusy, setInviteBusy] = useState(false)
  const [temporalNow, setTemporalNow] = useState(() => new Date())
  const [budgetDrafts, setBudgetDrafts] = useState<Record<number, string>>({})
  const [budgetBusyDay, setBudgetBusyDay] = useState<number | null>(null)
  const startDateError = validateFutureDate(form.startDate, temporalNow)

  useEffect(() => {
    const timer = window.setInterval(() => setTemporalNow(new Date()), 60_000)
    return () => window.clearInterval(timer)
  }, [])

  const load = useCallback(async (id: string) => {
    const token = window.sessionStorage.getItem(parentTripOrganizerTokenKey(id))
    if (!token) throw new Error('当前浏览器没有该父行程的组织者凭证。')
    const next = await getParentTripSync({ parentTripId: id, parentToken: token })
    setSyncView(next)
    setTrip(next.parentTrip)
    setBudgetDrafts((current) => Object.fromEntries(
      next.parentTrip.days.map((day) => [
        day.dayIndex,
        current[day.dayIndex] ?? String(day.budgetCents / 100),
      ]),
    ))
    if (
      invitation &&
      next.visibleProfiles.some(
        (profile) => (
          profile.participantId === invitation.participantId &&
          profile.accessStatus === 'MEMBER_ACTIVE'
        ),
      )
    ) {
      setInvitation(null)
      setInvitationUrl('')
      setCopyDone(false)
    }
    setError('')
  }, [invitation])

  useEffect(() => {
    if (!parentTripId) return
    let active = true
    let inFlight = false
    const refresh = async () => {
      if (inFlight) return
      inFlight = true
      try {
        await load(parentTripId)
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : '父行程同步失败。')
      } finally {
        inFlight = false
      }
    }
    void refresh()
    const timer = window.setInterval(
      () => void refresh(),
      PARENT_TRIP_POLL_INTERVAL_MS,
    )
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [load, parentTripId])

  async function create() {
    const submittedAt = new Date()
    const submittedDateError = validateFutureDate(form.startDate, submittedAt)
    if (submittedDateError) {
      setTemporalNow(submittedAt)
      setError(submittedDateError)
      return
    }
    setBusy(true)
    setError('')
    try {
      if (!Number.isInteger(form.dayCount) || form.dayCount < MIN_DAY_COUNT || form.dayCount > MAX_DAY_COUNT) {
        throw new Error(`目前支持 ${MIN_DAY_COUNT}–${MAX_DAY_COUNT} 天，请填写有效天数。`)
      }
      const id = crypto.randomUUID()
      const token = `${crypto.randomUUID()}${crypto.randomUUID()}`
      const totalBudgetCents = Math.round(Number(form.totalBudget) * 100)
      if (!Number.isFinite(totalBudgetCents) || totalBudgetCents < 0) throw new Error('请填写有效的行程总预算。')
      const baseBudget = Math.floor(totalBudgetCents / form.dayCount)
      const remainder = totalBudgetCents % form.dayCount
      const values = Array.from(
        { length: form.dayCount },
        (_, index) => baseBudget + (index < remainder ? 1 : 0),
      )
      window.sessionStorage.setItem(parentTripOrganizerTokenKey(id), token)
      const created = await createParentTrip({
        parentTripId: id,
        title: form.title,
        cityName: form.cityName,
        startDate: form.startDate,
        dayBudgetCents: values,
        parentToken: token,
      })
      setTrip(created)
      navigate(`/parent-trips/${id}`, { replace: true })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '父行程创建失败。')
    } finally {
      setBusy(false)
    }
  }

  async function createInvitation() {
    if (!trip || !syncView) return
    const parentToken = window.sessionStorage.getItem(
      parentTripOrganizerTokenKey(trip.parentTripId),
    )
    if (!parentToken) {
      setError('当前浏览器没有该父行程的组织者凭证。')
      return
    }
    setInviteBusy(true)
    setCopyDone(false)
    setError('')
    try {
      const created = await createParentTripInvitation({
        parentTripId: trip.parentTripId,
        parentToken,
        expectedSyncVersion: syncView.syncVersion,
        idempotencyKey: createParentIdempotencyKey('invite'),
      })
      if (!created.linkAvailable || !created.invitationUrl) {
        throw new Error('邀请链接不可用，请刷新成员状态。')
      }
      setInvitation(created)
      setInvitationUrl(new URL(created.invitationUrl, window.location.origin).toString())
      await load(trip.parentTripId)
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : '邀请创建失败。'
      await load(trip.parentTripId).catch(() => undefined)
      setError(message)
    } finally {
      setInviteBusy(false)
    }
  }

  async function copyInvitation() {
    if (!invitationUrl) return
    try {
      await navigator.clipboard.writeText(invitationUrl)
      setCopyDone(true)
    } catch {
      setError('邀请链接复制失败，请手动选择链接。')
    }
  }

  async function saveDayBudget(dayIndex: number) {
    if (!trip) return
    const parentToken = window.sessionStorage.getItem(
      parentTripOrganizerTokenKey(trip.parentTripId),
    )
    if (!parentToken) {
      setError('当前浏览器没有该父行程的组织者凭证。')
      return
    }
    const budgetCents = Math.round(Number(budgetDrafts[dayIndex]) * 100)
    if (!Number.isFinite(budgetCents) || budgetCents < 0) {
      setError('请填写有效的当日预算。')
      return
    }
    setBudgetBusyDay(dayIndex)
    setError('')
    try {
      const updated = await updateParentTripDayBudget({
        parentTripId: trip.parentTripId,
        dayIndex,
        budgetCents,
        parentToken,
      })
      setTrip(updated)
      setBudgetDrafts((current) => ({
        ...current,
        [dayIndex]: String(budgetCents / 100),
      }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '当日预算修改失败。')
    } finally {
      setBudgetBusyDay(null)
    }
  }

  function enterDay(dayIndex: number) {
    if (!trip) return
    const day = trip.days[dayIndex]
    if (day.childTripId) {
      navigate(`/workspace?tripId=${day.childTripId}&parentTripId=${trip.parentTripId}`)
      return
    }
    navigate(`/plan?parentTripId=${trip.parentTripId}&dayIndex=${day.dayIndex}&city=${encodeURIComponent(trip.cityName)}&date=${day.date}&budget=${day.budgetCents}`)
  }

  const memberLimitReached = (syncView?.visibleProfiles.length ?? 1) >= MAX_PARTICIPANT_COUNT
  const placeMemory = trip?.placeMemory ?? []
  const rememberedDays = trip?.days.map((day) => ({
    day,
    places: placeMemory.filter((item) => item.dayIndex === day.dayIndex),
  })).filter((item) => item.places.length > 0) ?? []

  return <AppShell><main className="parent-trip-page">
    {!trip ? <section className="parent-trip-card"><p className="eyebrow">多日同行</p><h1>创建多天同城行程</h1><p className="parent-trip-card__lead">一次创建 2–30 天的行程框架，再逐日完成具体规划。</p>
      <label>行程名称<input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
      <div className="parent-trip-grid"><label>城市<input list="parent-trip-city-suggestions" value={form.cityName} onChange={(event) => setForm({ ...form, cityName: event.target.value })} placeholder="输入目的城市" required /></label>
      <label>开始日期<input aria-invalid={Boolean(startDateError)} min={localDateValue(temporalNow)} type="date" value={form.startDate} onFocus={() => setTemporalNow(new Date())} onChange={(event) => { setError(''); setForm({ ...form, startDate: event.target.value }) }} /></label>
      <label>天数<input type="number" min={MIN_DAY_COUNT} max={MAX_DAY_COUNT} step="1" inputMode="numeric" value={form.dayCount} onChange={(event) => setForm({ ...form, dayCount: Number(event.target.value) })} aria-describedby="parent-trip-day-hint" /><small id="parent-trip-day-hint">自定义填写，支持 2–30 天</small></label></div>
      <datalist id="parent-trip-city-suggestions">{citySuggestions.map((city) => <option key={city} value={city} />)}</datalist>
      {startDateError && <p className="form-error" role="alert">{startDateError}</p>}
      <div className="parent-trip-budget-inputs"><label>多日行程总预算（元）<input type="number" min="0" inputMode="decimal" value={form.totalBudget} onChange={(event) => setForm({ ...form, totalBudget: event.target.value })} /><small>创建后会自动平均分配到每天；进入单日规划时无需再次填写。</small></label></div>
      <button className="button button--primary" disabled={busy || Boolean(startDateError)} onClick={() => void create()}>创建父行程 <ChevronRight size={18} /></button>
    </section> : <><section className="parent-trip-hero"><div><p className="eyebrow">同城 {trip.days.length} 天父行程</p><h1>{trip.title}</h1><p>{trip.cityName} · {trip.startDate} 至 {trip.endDate}</p></div>
      <div className="parent-trip-sync-state"><span>{syncView ? `${syncView.visibleProfiles.length} 人同行` : '同步中'}</span><button className="icon-button" type="button" title="立即刷新" aria-label="立即刷新" onClick={() => void load(trip.parentTripId).catch((caught: Error) => setError(caught.message))}><RefreshCw size={18} /></button></div></section>
      <section className="parent-budget-summary"><div><WalletCards/><span>分配总预算</span><strong>{yuan(trip.totalBudgetCents)}</strong></div><div><span>已生成计划合计</span><strong>{yuan(trip.plannedCostCents)}</strong></div><div><span>已记录支出合计</span><strong>{yuan(trip.actualSpentCents)}</strong></div></section>
      <Link className="button button--soft" to={`/budget-ledger?parentTripId=${trip.parentTripId}`}>查看预算账本</Link>

      <section className="parent-collaboration" aria-label="同行成员">
        <header><div><Users size={22} /><h2>同行成员</h2></div><button className="button button--soft" type="button" disabled={!syncView || memberLimitReached || inviteBusy} onClick={() => void createInvitation()}><UserPlus size={17} />{inviteBusy ? '生成中' : '生成成员邀请'}</button></header>
        {invitationUrl && <div className="parent-invitation"><div><span>邀请链接</span>{invitation && <small>有效期至 {new Date(invitation.expiresAt).toLocaleString('zh-CN')}</small>}</div><div><input aria-label="成员邀请链接" readOnly value={invitationUrl} /><button className="icon-button" type="button" title="复制邀请链接" aria-label="复制邀请链接" onClick={() => void copyInvitation()}>{copyDone ? <Check size={18} /> : <Copy size={18} />}</button></div></div>}
        <div className="parent-participant-list">{syncView?.visibleProfiles.map((profile) => <article key={profile.participantId}><div className={`parent-participant-avatar parent-participant-avatar--${profile.accessStatus.toLowerCase()}`}>{profile.nickname.slice(0, 1)}</div><div><strong>{profile.nickname}</strong><span>{accessLabel[profile.accessStatus]}</span></div><div className="parent-participant-details"><span>{profile.interests.length ? profile.interests.join(' · ') : '兴趣待填写'}</span><b>{profile.budgetCapCents === null ? '预算待填写' : `个人上限 ${yuan(profile.budgetCapCents)}`}</b></div></article>)}</div>
      </section>

      {placeMemory.length > 0 && <section className="parent-place-memory" aria-label="跨日地点记忆">
        <header><div><MapPin size={22} /><h2>跨日地点记忆</h2></div><strong>{placeMemory.length} 个地点已占用</strong></header>
        <div className="parent-place-memory__days">{rememberedDays.map(({ day, places }) => <article key={day.dayIndex}><div><b>第 {day.dayIndex + 1} 天</b><span>{day.date}</span></div><ul>{places.map((place) => <li key={`${place.planId}:${place.placeId}`}><span>{place.placeName}</span><small>{place.planStatus === 'CURRENT' ? '已确认' : '计划草稿'}</small></li>)}</ul></article>)}</div>
      </section>}

      <section className="parent-days">{trip.days.map((day) => <article key={day.dayIndex} className="parent-day-card"><div className="parent-day-date"><CalendarDays/><div><b>第 {day.dayIndex + 1} 天</b><span>{day.date}</span></div></div>
        <div className="parent-day-budget-editor"><label htmlFor={`day-budget-${day.dayIndex}`}>当日预算（元）</label><div><input id={`day-budget-${day.dayIndex}`} type="number" min="0" inputMode="decimal" value={budgetDrafts[day.dayIndex] ?? String(day.budgetCents / 100)} onChange={(event) => setBudgetDrafts((current) => ({ ...current, [day.dayIndex]: event.target.value }))} /><button className="button button--soft" type="button" disabled={budgetBusyDay === day.dayIndex || Number(budgetDrafts[day.dayIndex]) * 100 === day.budgetCents} onClick={() => void saveDayBudget(day.dayIndex)}>{budgetBusyDay === day.dayIndex ? '保存中' : '保存预算'}</button></div></div>
        <dl><div><dt>计划费用</dt><dd>{yuan(day.plannedCostCents)}</dd></div><div><dt>实际支出</dt><dd>{yuan(day.actualSpentCents)}</dd></div></dl>
        <p className={`parent-day-status parent-day-status--${day.costStatus.toLowerCase()}`}>{day.childTripId ? `单日 Trip · ${day.childStatus}` : '尚未创建单日 Trip'}</p>
        <button className="button button--primary" onClick={() => enterDay(day.dayIndex)}>{day.childTripId ? '进入当日行程' : '创建当日行程'} <ChevronRight size={17}/></button></article>)}</section></>}
    {error && <p className="inline-error" role="alert">{error}</p>}
    <p className="parent-trip-scope">当前范围不包含酒店、跨城搜索预订或跨日自动重规划。</p>
  </main></AppShell>
}
