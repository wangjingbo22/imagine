import {
  CalendarDays,
  CircleDollarSign,
  LogOut,
  RefreshCw,
  Save,
  UserRound,
} from 'lucide-react'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  getParentTripSync,
  redeemParentTripInvitation,
  updateParentTripMemberProfile,
} from '../api/parentTripApi'
import { AppShell } from '../components/AppShell'
import type { ParentTripSyncView } from '../domain/parentTrip'
import {
  capturePendingInvitation,
  clearParentMemberSession,
  clearPendingInvitation,
  PARENT_TRIP_POLL_INTERVAL_MS,
  parseParentInvitationToken,
  readParentMemberSession,
  readPendingInvitation,
  storeParentMemberSession,
} from '../services/parentTripCollaboration'

const yuan = (cents: number | null) => (
  cents === null ? '尚未生成' : `¥${(cents / 100).toFixed(0)}`
)

type ProfileForm = {
  nickname: string
  interests: string
  budgetCapYuan: string
}

const emptyProfile: ProfileForm = {
  nickname: '',
  interests: '',
  budgetCapYuan: '',
}

function profileForm(profile: ParentTripSyncView['visibleProfiles'][number]): ProfileForm {
  return {
    nickname: profile.nickname,
    interests: profile.interests.join('，'),
    budgetCapYuan: profile.budgetCapCents === null
      ? ''
      : String(profile.budgetCapCents / 100),
  }
}

export function ParentTripMemberPage() {
  const { token, parentTripId = '' } = useParams()
  const navigate = useNavigate()
  const [syncView, setSyncView] = useState<ParentTripSyncView | null>(null)
  const [profileDraft, setProfileDraft] = useState<ProfileForm | null>(null)
  const [error, setError] = useState('')
  const [phase, setPhase] = useState<'JOINING' | 'LOADING' | 'READY' | 'ERROR'>(
    parentTripId ? 'LOADING' : 'JOINING',
  )
  const [saving, setSaving] = useState(false)
  const [joinAttempt, setJoinAttempt] = useState(0)
  const [reloadIndex, setReloadIndex] = useState(0)

  useEffect(() => {
    if (parentTripId) return
    const routeToken = parseParentInvitationToken(token)
    const pending = token
      ? (routeToken ? capturePendingInvitation(routeToken) : null)
      : readPendingInvitation()
    if (token) {
      window.history.replaceState(window.history.state, '', '/parent-join')
    }
    let cancelled = false
    const redemption = pending
      ? redeemParentTripInvitation(pending)
      : Promise.reject(new Error('邀请凭证不可用，请联系组织者重新发送。'))
    void redemption
      .then((redeemed) => {
        if (
          !redeemed.sessionTokenAvailable ||
          !redeemed.memberSessionToken
        ) {
          throw new Error('成员会话未签发，请重新打开邀请。')
        }
        storeParentMemberSession(
          redeemed.parentTripId,
          redeemed.memberSessionToken,
        )
        clearPendingInvitation()
        if (!cancelled) {
          navigate(`/parent-trips/${redeemed.parentTripId}/member`, {
            replace: true,
          })
        }
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        setPhase('ERROR')
        setError(caught instanceof Error ? caught.message : '加入父行程失败。')
      })
    return () => {
      cancelled = true
    }
  }, [joinAttempt, navigate, parentTripId, token])

  useEffect(() => {
    if (!parentTripId) return
    const memberSessionToken = readParentMemberSession(parentTripId)

    let cancelled = false
    let inFlight = false
    const refresh = async () => {
      if (inFlight) return
      inFlight = true
      try {
        if (!memberSessionToken) {
          throw new Error('当前浏览器没有该父行程的成员会话。')
        }
        const next = await getParentTripSync({
          parentTripId,
          memberSessionToken,
        })
        if (!cancelled) {
          setSyncView(next)
          setPhase('READY')
          setError('')
        }
      } catch (caught) {
        if (!cancelled) {
          setPhase((current) => current === 'READY' ? current : 'ERROR')
          setError(caught instanceof Error ? caught.message : '父行程同步失败。')
        }
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
      cancelled = true
      window.clearInterval(timer)
    }
  }, [parentTripId, reloadIndex])

  const ownProfile = useMemo(
    () => syncView?.visibleProfiles.find(
      (item) => item.participantId === syncView.viewerParticipantId,
    ) ?? null,
    [syncView],
  )

  const profile = profileDraft ?? (ownProfile ? profileForm(ownProfile) : emptyProfile)
  const dirty = profileDraft !== null

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!syncView || !parentTripId) return
    const memberSessionToken = readParentMemberSession(parentTripId)
    if (!memberSessionToken) {
      setError('成员会话已丢失，请重新打开邀请。')
      return
    }
    const nickname = profile.nickname.trim()
    const interests = profile.interests
      .split(/[,，]/)
      .map((item) => item.trim())
      .filter(Boolean)
    const normalizedInterests = interests.map((item) => item.toLocaleLowerCase())
    const budgetValue = profile.budgetCapYuan.trim()
    const budgetCapCents = budgetValue === ''
      ? null
      : Math.round(Number(budgetValue) * 100)
    if (!nickname) {
      setError('请填写成员昵称。')
      return
    }
    if (new Set(normalizedInterests).size !== interests.length) {
      setError('兴趣标签不能重复。')
      return
    }
    if (
      budgetCapCents !== null &&
      (!Number.isFinite(budgetCapCents) || budgetCapCents < 0)
    ) {
      setError('请填写有效的预算上限。')
      return
    }

    setSaving(true)
    setError('')
    try {
      const next = await updateParentTripMemberProfile({
        parentTripId,
        memberSessionToken,
        expectedSyncVersion: syncView.syncVersion,
        nickname,
        interests,
        budgetCapCents,
      })
      setProfileDraft(null)
      setSyncView(next)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '成员资料保存失败。')
      setReloadIndex((value) => value + 1)
    } finally {
      setSaving(false)
    }
  }

  function leaveMemberView() {
    if (parentTripId) clearParentMemberSession(parentTripId)
    navigate('/', { replace: true })
  }

  if (!syncView || !ownProfile || phase !== 'READY') {
    return <AppShell><main className="parent-member-page">
      <section className="parent-member-state" aria-live="polite">
        <RefreshCw className={phase === 'ERROR' ? '' : 'is-spinning'} size={26} />
        <h1>{phase === 'JOINING' ? '正在加入父行程' : phase === 'ERROR' ? '无法打开父行程' : '正在同步父行程'}</h1>
        {error && <p className="inline-error" role="alert">{error}</p>}
        {phase === 'ERROR' && !parentTripId && <button className="button button--soft" type="button" onClick={() => { setPhase('JOINING'); setError(''); setJoinAttempt((value) => value + 1) }}>重试</button>}
      </section>
    </main></AppShell>
  }

  const trip = syncView.parentTrip
  return <AppShell><main className="parent-member-page">
    <header className="parent-member-header">
      <div><p className="eyebrow">成员行程</p><h1>{trip.title}</h1><p>{trip.cityName} · {trip.startDate} 至 {trip.endDate}</p></div>
      <div className="parent-member-actions">
        <span>已同步 {new Date(syncView.changedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
        <button className="icon-button" type="button" title="立即刷新" aria-label="立即刷新" onClick={() => setReloadIndex((value) => value + 1)}><RefreshCw size={18} /></button>
        <button className="icon-button" type="button" title="退出成员视图" aria-label="退出成员视图" onClick={leaveMemberView}><LogOut size={18} /></button>
      </div>
    </header>

    <section className="parent-member-budget" aria-label="父行程预算">
      <CircleDollarSign size={24} />
      <div><span>分配总预算</span><strong>{yuan(trip.totalBudgetCents)}</strong></div>
      <div><span>计划合计</span><strong>{yuan(trip.plannedCostCents)}</strong></div>
      <div><span>实际支出</span><strong>{yuan(trip.actualSpentCents)}</strong></div>
    </section>

    <div className="parent-member-layout">
      <form className="parent-member-profile" onSubmit={(event) => void saveProfile(event)}>
        <header><UserRound size={21} /><div><h2>我的资料</h2><span>版本 {ownProfile.profileVersion}</span></div></header>
        <label htmlFor="parent-member-nickname">昵称</label>
        <input id="parent-member-nickname" maxLength={40} value={profile.nickname} onChange={(event) => setProfileDraft({ ...profile, nickname: event.target.value })} />
        <label htmlFor="parent-member-interests">兴趣标签</label>
        <input id="parent-member-interests" maxLength={240} value={profile.interests} onChange={(event) => setProfileDraft({ ...profile, interests: event.target.value })} />
        <label htmlFor="parent-member-budget">个人预算上限（元）</label>
        <input id="parent-member-budget" type="number" min="0" step="0.01" value={profile.budgetCapYuan} onChange={(event) => setProfileDraft({ ...profile, budgetCapYuan: event.target.value })} />
        <button className="button button--primary" type="submit" disabled={saving || !dirty}><Save size={17} />{saving ? '保存中' : '保存资料'}</button>
      </form>

      <section className="parent-member-days" aria-label="每日子行程状态">
        <header><CalendarDays size={21} /><h2>每日行程</h2></header>
        {trip.days.map((day) => <article className="parent-member-day" key={day.dayIndex}>
          <div><strong>第 {day.dayIndex + 1} 天</strong><span>{day.date}</span></div>
          <div><span>预算 {yuan(day.budgetCents)}</span><b>{day.childTripId ? day.childStatus : '尚未创建'}</b></div>
        </article>)}
      </section>
    </div>
    {error && <p className="inline-error parent-member-error" role="alert">{error}</p>}
  </main></AppShell>
}
