import { AlertTriangle, CheckCircle2, ShieldCheck, UserRound } from 'lucide-react'
import type { CollaborationAggregate, CollaborationIssue } from '../domain/collaboration'
import {
  organizerRelaxations,
  participantIdsForIssue,
  participantRelaxations,
} from '../domain/collaboration'

type ConflictReviewPanelProps = {
  state: CollaborationAggregate
  busy?: boolean
  onResolve: (itemId: string, relaxationId: string) => void
}

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
  const participantIds = participantIdsForIssue(issue)

  return <article className="conflict-review__item" aria-labelledby={`issue-${issue.itemId}`}>
    <header>
      <span className="conflict-review__icon" aria-hidden="true"><AlertTriangle size={18} /></span>
      <div>
        <h4 id={`issue-${issue.itemId}`}>{issue.reason}</h4>
        <code>{issue.ruleId}</code>
      </div>
    </header>
    <dl className="conflict-review__facts">
      <div><dt>涉及成员 participantId</dt><dd>{participantIds.length > 0
        ? participantIds.map((participantId) => <code key={participantId}>{participantId}</code>)
        : <span>共享行程字段（由组织者处理）</span>}</dd></div>
      <div><dt>字段</dt><dd><code>{issue.fieldPath}</code></dd></div>
    </dl>
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
  return <section className={`conflict-review${ready ? ' is-ready' : ''}`} aria-live="polite" aria-busy={busy}>
    <header className="conflict-review__heading">
      <span aria-hidden="true">{ready ? <CheckCircle2 size={20} /> : <ShieldCheck size={20} />}</span>
      <div>
        <h3>{ready ? '硬冲突已全部解决' : actionableIssues.length > 0 ? '多人硬冲突与确认项' : '等待成员独立填写'}</h3>
        <p>{ready
          ? '全员已在当前版本确认，可以进入 Provider 查询和唯一推荐。'
          : actionableIssues.length > 0
            ? `${actionableIssues.length} 项需要处理，另有 ${waitingMemberIssues.length} 项等待成员填写；完成前不会调用 Provider 或规划器。`
            : `${waitingMembers.length} 位成员尚未完成自己的资料；全员确认前不会调用 Provider 或规划器。`}</p>
      </div>
    </header>
    {!ready && waitingMembers.length > 0 && <div className="conflict-review__waiting-members">
      {waitingMembers.map((participant) => <article key={participant.participantId}>
        <UserRound size={17} aria-hidden="true" />
        <div><strong>{participant.memberKey === 'member-2' ? '成员 1' : participant.memberKey === 'member-3' ? '成员 2' : participant.memberKey}</strong><small>{participant.accessStatus === 'NOT_INVITED' ? '等待组织者发送邀请' : participant.accessStatus === 'INVITED' ? '邀请已发送，等待打开' : '等待本人填写并确认'}</small></div>
      </article>)}
    </div>}
    {!ready && actionableIssues.map((issue) => <IssueCard
      busy={busy}
      issue={issue}
      key={issue.itemId}
      onResolve={onResolve}
    />)}
    {!ready && actionableIssues.length === 0 && waitingMembers.length === 0 && <p className="conflict-review__waiting" role="status">
      当前没有硬冲突，仍需等待所有成员在最新版本重新确认。
    </p>}
  </section>
}
