import { CalendarDays, ChevronRight, RefreshCw, WalletCards } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { createParentTrip, getParentTrip } from '../api/parentTripApi'
import { AppShell } from '../components/AppShell'
import type { ParentTrip } from '../domain/parentTrip'

const cities = ['北京', '上海', '成都', '西安', '杭州']
const yuan = (cents: number | null) => cents === null ? '尚未生成' : `¥${(cents / 100).toFixed(0)}`
const parentTokenKey = (id: string) => `parent-trip-token:${id}`

export function ParentTripPage() {
  const { parentTripId = '' } = useParams()
  const navigate = useNavigate()
  const [trip, setTrip] = useState<ParentTrip | null>(null)
  const [form, setForm] = useState({ title: '周末同城之旅', cityName: '北京', startDate: '2026-09-06', dayCount: 2, budgets: ['500', '500', '500'] })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function load(id: string) {
    const token = window.sessionStorage.getItem(parentTokenKey(id))
    if (!token) { setError('当前浏览器没有该父行程的组织者凭证。'); return }
    setTrip(await getParentTrip(id, token))
  }
  useEffect(() => { if (parentTripId) void load(parentTripId).catch((e: Error) => setError(e.message)) }, [parentTripId])

  async function create() {
    setBusy(true); setError('')
    try {
      const id = crypto.randomUUID()
      const token = `${crypto.randomUUID()}${crypto.randomUUID()}`
      const values = form.budgets.slice(0, form.dayCount).map((value) => Math.round(Number(value) * 100))
      if (values.some((value) => !Number.isFinite(value) || value < 0)) throw new Error('请填写有效的每日预算。')
      window.sessionStorage.setItem(parentTokenKey(id), token)
      const created = await createParentTrip({ parentTripId: id, title: form.title, cityName: form.cityName,
        startDate: form.startDate, dayBudgetCents: values, parentToken: token })
      setTrip(created); navigate(`/parent-trips/${id}`, { replace: true })
    } catch (caught) { setError(caught instanceof Error ? caught.message : '父行程创建失败。') }
    finally { setBusy(false) }
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

  return <AppShell><main className="parent-trip-page">
    {!trip ? <section className="parent-trip-card"><p className="eyebrow">SPRINT 3 · T012</p><h1>创建 2–3 天同城父行程</h1>
      <p>父行程只负责逐日入口和预算汇总；每天仍使用已有的单日行程流程。</p>
      <label>行程名称<input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
      <div className="parent-trip-grid"><label>城市<select value={form.cityName} onChange={(e) => setForm({ ...form, cityName: e.target.value })}>{cities.map((city) => <option key={city}>{city}</option>)}</select></label>
      <label>开始日期<input type="date" value={form.startDate} onChange={(e) => setForm({ ...form, startDate: e.target.value })} /></label>
      <label>天数<select value={form.dayCount} onChange={(e) => setForm({ ...form, dayCount: Number(e.target.value) })}><option value={2}>2 天</option><option value={3}>3 天</option></select></label></div>
      <div className="parent-trip-budget-inputs">{form.budgets.slice(0, form.dayCount).map((value, index) => <label key={index}>第 {index + 1} 天预算（元）<input type="number" min="0" value={value} onChange={(e) => setForm({ ...form, budgets: form.budgets.map((v, i) => i === index ? e.target.value : v) })} /></label>)}</div>
      <button className="button button--primary" disabled={busy} onClick={() => void create()}>创建父行程 <ChevronRight size={18} /></button>
    </section> : <><section className="parent-trip-hero"><div><p className="eyebrow">同城 {trip.days.length} 天父行程</p><h1>{trip.title}</h1><p>{trip.cityName} · {trip.startDate} 至 {trip.endDate}</p></div>
      <button className="button button--soft" onClick={() => void load(trip.parentTripId)}><RefreshCw size={17} />刷新</button></section>
      <section className="parent-budget-summary"><div><WalletCards/><span>分配总预算</span><strong>{yuan(trip.totalBudgetCents)}</strong></div><div><span>已生成计划合计</span><strong>{yuan(trip.plannedCostCents)}</strong></div><div><span>已记录支出合计</span><strong>{yuan(trip.actualSpentCents)}</strong></div></section>
      <section className="parent-days">{trip.days.map((day) => <article key={day.dayIndex} className="parent-day-card"><div className="parent-day-date"><CalendarDays/><div><b>第 {day.dayIndex + 1} 天</b><span>{day.date}</span></div></div>
        <dl><div><dt>当日预算</dt><dd>{yuan(day.budgetCents)}</dd></div><div><dt>计划费用</dt><dd>{yuan(day.plannedCostCents)}</dd></div><div><dt>实际支出</dt><dd>{yuan(day.actualSpentCents)}</dd></div></dl>
        <p className={`parent-day-status parent-day-status--${day.costStatus.toLowerCase()}`}>{day.childTripId ? `单日 Trip · ${day.childStatus}` : '尚未创建单日 Trip'}</p>
        <button className="button button--primary" onClick={() => enterDay(day.dayIndex)}>{day.childTripId ? '进入当日行程' : '创建当日行程'} <ChevronRight size={17}/></button></article>)}</section></>}
    {error && <p className="inline-error" role="alert">{error}</p>}
    <p className="parent-trip-scope">当前范围不包含酒店、跨城搜索预订或跨日自动重规划。</p>
  </main></AppShell>
}
