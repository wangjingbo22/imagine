import { ArrowLeft, PencilLine, Plus, ReceiptText, Wallet } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getParentTripSync } from '../api/parentTripApi'
import { AppShell } from '../components/AppShell'
import type { ParentTripDay } from '../domain/parentTrip'
import { parentTripOrganizerTokenKey } from '../services/parentTripCollaboration'

type ExpenseCategory = '交通' | '门票' | '餐饮' | '其他'
type FactStatus = 'REALTIME' | 'ESTIMATED' | 'UNKNOWN'

type LedgerLine = {
  id: string
  day: number
  category: ExpenseCategory
  name: string
  amountCents: number | null
  source: string
  status: FactStatus
  adjustmentCents: number
}

const statusLabel: Record<FactStatus, string> = {
  REALTIME: '实时来源',
  ESTIMATED: '估算',
  UNKNOWN: '待确认',
}

function yuan(cents: number | null): string {
  if (cents === null) return '待确认'
  return `¥${(cents / 100).toFixed(cents % 100 === 0 ? 0 : 2)}`
}

function fallbackLedgerLines(): LedgerLine[] {
  return [
    { id: 'metro', day: 1, category: '交通', name: '地铁与接驳', amountCents: 1200, source: '高德路线费用', status: 'ESTIMATED', adjustmentCents: 0 },
    { id: 'museum', day: 1, category: '门票', name: '首都博物馆', amountCents: 0, source: '场馆公开票价', status: 'REALTIME', adjustmentCents: 0 },
    { id: 'lunch', day: 1, category: '餐饮', name: '午餐', amountCents: 6500, source: '行程预算估算', status: 'ESTIMATED', adjustmentCents: 0 },
    { id: 'park', day: 2, category: '门票', name: '景山公园', amountCents: 200, source: '场馆公开票价', status: 'REALTIME', adjustmentCents: 0 },
    { id: 'taxi', day: 2, category: '交通', name: '返程打车', amountCents: null, source: '尚未取得费用', status: 'UNKNOWN', adjustmentCents: 0 },
  ]
}

function buildLedgerLines(day: ParentTripDay): LedgerLine[] {
  const baseBudget = day.budgetCents ?? 0
  const transport = day.budgetCents ? Math.max(Math.round(baseBudget * 0.35), 0) : null
  const tickets = day.budgetCents ? Math.max(Math.round(baseBudget * 0.20), 0) : null
  const dining = day.budgetCents ? Math.max(Math.round(baseBudget * 0.25), 0) : null
  const other = day.budgetCents ? Math.max(baseBudget - (transport ?? 0) - (tickets ?? 0) - (dining ?? 0), 0) : null

  return [
    { id: `${day.dayIndex}-transport`, day: day.dayIndex + 1, category: '交通', name: '交通与接驳预算', amountCents: transport, source: '父行程日预算分配', status: day.budgetCents !== null ? 'ESTIMATED' : 'UNKNOWN', adjustmentCents: 0 },
    { id: `${day.dayIndex}-tickets`, day: day.dayIndex + 1, category: '门票', name: '门票与活动预算', amountCents: tickets, source: '父行程日预算分配', status: day.budgetCents !== null ? 'ESTIMATED' : 'UNKNOWN', adjustmentCents: 0 },
    { id: `${day.dayIndex}-food`, day: day.dayIndex + 1, category: '餐饮', name: '餐饮预算', amountCents: dining, source: '父行程日预算分配', status: day.budgetCents !== null ? 'ESTIMATED' : 'UNKNOWN', adjustmentCents: 0 },
    { id: `${day.dayIndex}-other`, day: day.dayIndex + 1, category: '其他', name: '其他与备用预算', amountCents: other, source: '父行程日预算分配', status: day.budgetCents !== null ? 'ESTIMATED' : 'UNKNOWN', adjustmentCents: 0 },
  ]
}

export function BudgetLedgerPage() {
  const [searchParams] = useSearchParams()
  const parentTripId = searchParams.get('parentTripId')
  const [lines, setLines] = useState<LedgerLine[]>(fallbackLedgerLines)
  const [title, setTitle] = useState('北京周末关怀行程')
  const [editing, setEditing] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!parentTripId) return
    const token = window.sessionStorage.getItem(parentTripOrganizerTokenKey(parentTripId))
    if (!token) {
      setNotice('未找到该父行程的组织者凭证，正在显示本地示例预算账本。')
      setLines(fallbackLedgerLines())
      return
    }
    void getParentTripSync({ parentTripId, parentToken: token })
      .then((sync) => {
        setTitle(sync.parentTrip.title)
        setLines(sync.parentTrip.days.flatMap((day) => buildLedgerLines(day)))
        if (sync.parentTrip.days.length === 0) {
          setNotice('当前父行程尚无日预算，账本已展示空白基线。')
        }
      })
      .catch((error: Error) => {
        setNotice(`父行程账本读取失败：${error.message}`)
        setLines(fallbackLedgerLines())
      })
  }, [parentTripId])

  const totals = useMemo(() => {
    const planned = lines.reduce((sum, line) => sum + (line.amountCents ?? 0), 0)
    const adjustment = lines.reduce((sum, line) => sum + line.adjustmentCents, 0)
    const unknown = lines.filter((line) => line.amountCents === null).length
    return { planned, adjustment, total: planned + adjustment, unknown }
  }, [lines])

  function startEdit(line: LedgerLine) {
    setEditing(line.id)
    setInput(line.adjustmentCents ? String(line.adjustmentCents / 100) : '')
    setNotice('')
  }

  function saveAdjustment(line: LedgerLine) {
    const amount = Number(input)
    if (!Number.isFinite(amount)) {
      setNotice('请输入有效的人民币金额，可为负数。')
      return
    }
    setLines((current) => current.map((item) => (
      item.id === line.id ? { ...item, adjustmentCents: Math.round(amount * 100) } : item
    )))
    setEditing(null)
    setNotice(`已记录“${line.name}”的手动修正；不会发起支付。`)
  }

  return (
    <AppShell>
      <main className="ledger-page">
        <Link className="ledger-back" to="/workspace"><ArrowLeft size={18} /> 返回行程工作台</Link>
        <header className="ledger-hero" data-reveal>
          <div>
            <p className="eyebrow"><ReceiptText size={14} /> 父行程 · 预算透明度</p>
            <h1>{title}</h1>
            <p>费用按日和类别汇总；每一项都保留来源与事实状态，未知费用不会被当作 ¥0。</p>
          </div>
          <div className="ledger-total"><Wallet size={20} /><span>已计入预算</span><strong>{yuan(totals.total)}</strong></div>
        </header>

        <section className="ledger-summary" aria-label="预算汇总" data-reveal>
          <article><span>计划费用</span><strong>{yuan(totals.planned)}</strong></article>
          <article><span>手动修正</span><strong>{totals.adjustment === 0 ? '¥0' : `${totals.adjustment > 0 ? '+' : '−'}${yuan(Math.abs(totals.adjustment))}`}</strong></article>
          <article className={totals.unknown ? 'is-warning' : ''}><span>待确认费用</span><strong>{totals.unknown} 项</strong></article>
        </section>

        <section className="ledger-card" data-reveal>
          <div className="ledger-card__header"><div><h2>费用账本</h2><p>仅记录预算和人工修正，不包含任何支付能力。</p></div><button type="button" className="button button--soft" onClick={() => setNotice('新增费用由行程生成或后续账本服务写入；当前页面只允许修正既有明细。')}><Plus size={17} /> 新增费用</button></div>
          {notice && <p className="ledger-notice" role="status">{notice}</p>}
          <div className="ledger-table-wrap">
            <table className="ledger-table">
              <thead><tr><th>日期</th><th>类别</th><th>费用项</th><th>来源 / 状态</th><th>预算</th><th>手动修正</th></tr></thead>
              <tbody>{lines.map((line) => <tr key={line.id}>
                <td>第 {line.day} 天</td><td><span className="ledger-category">{line.category}</span></td><td>{line.name}</td>
                <td><span className={`ledger-status ledger-status--${line.status.toLowerCase()}`}>{statusLabel[line.status]}</span><small>{line.source}</small></td>
                <td>{line.amountCents === null ? <span className="ledger-unknown">待确认</span> : yuan(line.amountCents)}</td>
                <td>{editing === line.id ? <span className="ledger-edit"><input aria-label={`${line.name} 手动修正金额`} autoFocus inputMode="decimal" value={input} onChange={(event) => setInput(event.target.value)} /><button type="button" onClick={() => saveAdjustment(line)}>保存</button></span> : <button className="ledger-adjust" type="button" onClick={() => startEdit(line)}><PencilLine size={15} />{line.adjustmentCents ? `${line.adjustmentCents > 0 ? '+' : '−'}${yuan(Math.abs(line.adjustmentCents))}` : '修正'}</button>}</td>
              </tr>)}</tbody>
            </table>
          </div>
        </section>
      </main>
    </AppShell>
  )
}
