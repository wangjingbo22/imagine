import { ArrowLeft, PencilLine, Plus, ReceiptText, Wallet } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AppShell } from '../components/AppShell'

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

const seedLines: LedgerLine[] = [
  { id: 'metro', day: 1, category: '交通', name: '地铁与接驳', amountCents: 1200, source: '高德路线费用', status: 'ESTIMATED', adjustmentCents: 0 },
  { id: 'museum', day: 1, category: '门票', name: '首都博物馆', amountCents: 0, source: '场馆公开票价', status: 'REALTIME', adjustmentCents: 0 },
  { id: 'lunch', day: 1, category: '餐饮', name: '午餐', amountCents: 6500, source: '行程预算估算', status: 'ESTIMATED', adjustmentCents: 0 },
  { id: 'park', day: 2, category: '门票', name: '景山公园', amountCents: 200, source: '场馆公开票价', status: 'REALTIME', adjustmentCents: 0 },
  { id: 'taxi', day: 2, category: '交通', name: '返程打车', amountCents: null, source: '尚未取得费用', status: 'UNKNOWN', adjustmentCents: 0 },
]

function yuan(cents: number) {
  return `¥${(cents / 100).toFixed(cents % 100 === 0 ? 0 : 2)}`
}

export function BudgetLedgerPage() {
  const [lines, setLines] = useState(seedLines)
  const [editing, setEditing] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [notice, setNotice] = useState('')

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
            <h1>北京周末关怀行程</h1>
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
