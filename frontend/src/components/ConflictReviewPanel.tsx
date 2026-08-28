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
  return <section className={`conflict-review${ready ? ' is-ready' : ''}`} aria-live="polite" aria-busy={busy}>
    <header className="conflict-review__heading">
      <span aria-hidden="true">{ready ? <CheckCircle2 size={20} /> : <ShieldCheck size={20} />}</span>
      <div>
        <h3>{ready ? '硬冲突已全部解决' : '多人硬冲突与确认项'}</h3>
        <p>{ready
          ? '全员已在当前版本确认，可以进入 Provider 查询和唯一推荐。'
          : `${state.progress.openIssueCount} 项待处理；未解决前不会调用 Provider 或规划器。`}</p>
      </div>
    </header>
    {!ready && state.confirmationItems.map((issue) => <IssueCard
      busy={busy}
      issue={issue}
      key={issue.itemId}
      onResolve={onResolve}
    />)}
    {!ready && state.confirmationItems.length === 0 && <p className="conflict-review__waiting" role="status">
      当前没有硬冲突，仍需等待所有成员在最新版本重新确认。
    </p>}
  </section>
}
