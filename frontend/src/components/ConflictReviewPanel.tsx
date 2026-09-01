import { AlertTriangle, CheckCircle2, ShieldCheck, UserRound } from 'lucide-react'
import type { CollaborationAggregate, CollaborationIssue } from '../domain/collaboration'
import {
  organizerRelaxations,
  participantRelaxations,
} from '../domain/collaboration'
import { userFacingErrorMessage } from '../utils/userFacingError'

type ConflictReviewPanelProps = {
  state: CollaborationAggregate
  busy?: boolean
  onResolve: (itemId: string, relaxationId: string) => void
}

const SHARED_BUDGET_CONFLICT_RULE = 'S2T003.BUDGET.CAP_BELOW_SHARED'

function IssueCard({
  issue,
  busy,
  onResolve,
}: {
  issue: CollaborationIssue
  busy: boolean
  onResolve: ConflictReviewPanelProps['onResolve']
}) {
  const organizerOptions = organizerRelaxations(issue)
  const memberOptions = participantRelaxations(issue)
  const sharedBudgetOption = issue.ruleId === SHARED_BUDGET_CONFLICT_RULE
    ? organizerOptions[0]
    : undefined

  if (sharedBudgetOption) {
    return <article className="conflict-review__budget-action" aria-label="共享预算冲突处理">
      <button
        className="button button--soft"
        disabled={busy}
        onClick={() => onResolve(issue.itemId, sharedBudgetOption.relaxationId)}
        type="button"
      >由组织者降低共享预算</button>
    </article>
  }

  return <article className="conflict-review__item" aria-labelledby={`issue-${issue.itemId}`}>
    <header>
      <span className="conflict-review__icon" aria-hidden="true"><AlertTriangle size={18} /></span>
      <div>
        <h4 id={`issue-${issue.itemId}`}>{userFacingErrorMessage(issue.reason, '此项资料存在冲突，请选择一种处理方式。')}</h4>
      </div>
    </header>
    <div className="conflict-review__actions" aria-label="允许的放宽方式">
      {organizerOptions.map((option) => <button
        className="button button--soft"
        disabled={busy}
        key={option.relaxationId}
        onClick={() => onResolve(issue.itemId, option.relaxationId)}
        type="button"
      >{option.label}</button>)}
      {memberOptions.map((option) => <div className="conflict-review__member-action" key={option.relaxationId}>
        <UserRound size={16} aria-hidden="true" />
        <span>{option.label}</span>
        <small>需对应成员本人处理</small>
      </div>)}
      {issue.allowedRelaxations.length === 0 && <p>请返回对应问题补齐或更正资料。</p>}
    </div>
  </article>
}

export function ConflictReviewPanel({ state, busy = false, onResolve }: ConflictReviewPanelProps) {
  const ready = state.status === 'READY_TO_PLAN' && state.canPlan
  const memberIds = new Set(state.participants.filter((item) => item.role === 'MEMBER').map((item) => item.participantId))
  const waitingMemberIssues = state.confirmationItems.filter((issue) => (
    issue.code !== 'CONFLICT'
    && issue.participantId !== null
    && memberIds.has(issue.participantId)
  ))
  const actionableIssues = state.confirmationItems.filter((issue) => !waitingMemberIssues.includes(issue))
  const waitingMembers = state.participants.filter((item) => (
    item.role === 'MEMBER' && item.confirmationStatus !== 'CONFIRMED'
  ))
  const organizerNeedsConfirmation = state.participants.some((item) => (
    item.role === 'ORGANIZER' && item.confirmationStatus !== 'CONFIRMED'
  ))
  return <section className={`conflict-review${ready ? ' is-ready' : ''}`} aria-live="polite" aria-busy={busy}>
    <header className="conflict-review__heading">
      <span aria-hidden="true">{ready ? <CheckCircle2 size={20} /> : <ShieldCheck size={20} />}</span>
      <div>
        <h3>{ready
          ? '全部确认完成'
          : actionableIssues.length > 0
            ? '多人确认项需要处理'
            : waitingMembers.length > 0
              ? '等待成员填写并确认'
              : organizerNeedsConfirmation
                ? '等待组织者确认最新安排'
                : '正在核对最新状态'}</h3>
        <p>{ready
          ? '全员已确认当前版本，可以生成推荐方案。'
          : actionableIssues.length > 0
            ? `${actionableIssues.length} 项需要处理，另有 ${waitingMemberIssues.length} 项等待成员填写。`
            : waitingMembers.length > 0
              ? `${waitingMembers.length} 位成员尚未完成自己的资料。`
              : organizerNeedsConfirmation
                ? '成员已完成确认，请点击上方按钮确认审批后的最新共同安排。'
                : '请刷新状态获取最新确认结果。'}</p>
      </div>
    </header>
    {!ready && waitingMembers.length > 0 && <div className="conflict-review__waiting-members">
      {waitingMembers.map((participant) => <article key={participant.participantId}>
        <UserRound size={17} aria-hidden="true" />
        <div><strong>{participant.role === 'MEMBER' ? `成员 ${Math.max(1, Number(participant.memberKey.split('-')[1]) - 1)}` : '组织者'}</strong><small>{participant.accessStatus === 'NOT_INVITED' ? '等待组织者发送邀请' : participant.accessStatus === 'INVITED' ? '邀请已发送，等待打开' : '等待本人填写并确认'}</small></div>
      </article>)}
    </div>}
    {!ready && actionableIssues.map((issue) => <IssueCard
      busy={busy}
      issue={issue}
      key={issue.itemId}
      onResolve={onResolve}
    />)}
    {!ready && actionableIssues.length === 0 && waitingMembers.length === 0 && <p className="conflict-review__waiting" role="status">
      {organizerNeedsConfirmation
        ? '成员已经确认，请由组织者确认最新共同安排。'
        : '当前没有需要处理的确认项，请刷新状态。'}
    </p>}
  </section>
}
