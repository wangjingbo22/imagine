import { Heart, LogIn, LogOut, MapPin, Save, UserRound } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  loginAccount,
  registerAccount,
  updateAccountProfile,
} from '../api/accountApi'
import { AppShell } from '../components/AppShell'
import type { CurrentUser } from '../domain/account'
import { safeReturnPath } from '../services/accountReturnPath'
import { useAccountSession } from '../session/useAccountSession'

type AccountMode = 'login' | 'register'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function interestsFromText(value: string): string[] {
  return value
    .split(',')
    .map((interest) => interest.trim())
    .filter(Boolean)
}

type ProfileDraft = {
  displayName: string
  homeCity: string
  interests: string
}

function profileValues(user: CurrentUser): ProfileDraft {
  return {
    displayName: user.displayName,
    homeCity: user.homeCity ?? '',
    interests: user.interests.join(', '),
  }
}

export function AccountPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const returnTo = safeReturnPath(location.search)
  const { user, isInitializing, setCurrentUser, logout } = useAccountSession()
  const [mode, setMode] = useState<AccountMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [registerDisplayName, setRegisterDisplayName] = useState('')
  const [profileDraft, setProfileDraft] = useState<ProfileDraft | null>(null)
  const [authenticating, setAuthenticating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const profile = user ? profileDraft ?? profileValues(user) : null

  useEffect(() => {
    if (user && returnTo) {
      navigate(returnTo, { replace: true })
    }
  }, [navigate, returnTo, user])

  function switchMode(nextMode: AccountMode) {
    setMode(nextMode)
    setError('')
    setNotice('')
  }

  function updateProfileDraft(change: Partial<ProfileDraft>) {
    if (!user) return
    setProfileDraft((current) => ({
      ...(current ?? profileValues(user)),
      ...change,
    }))
  }

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setAuthenticating(true)
    setError('')
    setNotice('')
    try {
      const response = mode === 'login'
        ? await loginAccount({ email, password })
        : await registerAccount({ email, password, displayName: registerDisplayName })
      setCurrentUser(response.data)
      setProfileDraft(null)
      setRegisterDisplayName('')
      setPassword('')
      if (returnTo) {
        navigate(returnTo, { replace: true })
        return
      }
      setNotice(mode === 'login' ? '已登录' : '账户已创建')
    } catch (caught) {
      setError(errorMessage(caught, '账户请求失败，请稍后重试'))
    } finally {
      setAuthenticating(false)
    }
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!profile) return
    const interestValues = interestsFromText(profile.interests)
    if (interestValues.length > 8) {
      setError('兴趣最多填写 8 项')
      setNotice('')
      return
    }
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const response = await updateAccountProfile({
        displayName: profile.displayName,
        homeCity: profile.homeCity.trim() || null,
        interests: interestValues,
      })
      setCurrentUser(response.data)
      setProfileDraft(null)
      setNotice('画像已更新')
    } catch (caught) {
      setError(errorMessage(caught, '画像保存失败，请稍后重试'))
    } finally {
      setSaving(false)
    }
  }

  async function signOut() {
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await logout()
      setEmail('')
      setPassword('')
      setRegisterDisplayName('')
      setProfileDraft(null)
      setMode('login')
      setNotice('已退出账户')
    } catch (caught) {
      setError(errorMessage(caught, '退出失败，请稍后重试'))
    } finally {
      setSaving(false)
    }
  }

  if (isInitializing && !user) {
    return (
      <AppShell compact>
        <main className="account-layout">
          <section className="account-panel account-panel--loading" aria-busy="true">
            <UserRound size={24} />
            <p>正在读取账户</p>
          </section>
        </main>
      </AppShell>
    )
  }

  return (
    <AppShell compact>
      <main className="account-layout">
        <section className="account-intro">
          <p className="section-kicker">YOUR JOURNEY</p>
          <h1>{user ? '把熟悉的偏好，留给下一次出发。' : '从你的账户，开始一段更贴合的旅程。'}</h1>
          <p>保存常用城市与兴趣，规划时可以少填一点，让行程更快进入真正重要的部分。</p>
        </section>

        {user && profile ? (
          <section className="account-panel account-panel--profile">
            <div className="account-panel__heading">
              <div className="account-avatar"><UserRound size={22} /></div>
              <div>
                <p className="section-kicker">SIGNED IN</p>
                <h2>{user.email}</h2>
              </div>
            </div>
            <form className="account-form" onSubmit={(event) => void saveProfile(event)}>
              <label>
                <span>显示名称</span>
                <input value={profile.displayName} onChange={(event) => updateProfileDraft({ displayName: event.target.value })} maxLength={80} required />
              </label>
              <label>
                <span><MapPin size={15} /> 常用城市</span>
                <input value={profile.homeCity} onChange={(event) => updateProfileDraft({ homeCity: event.target.value })} maxLength={80} placeholder="例如：北京" />
              </label>
              <label>
                <span><Heart size={15} /> 兴趣</span>
                <input value={profile.interests} onChange={(event) => updateProfileDraft({ interests: event.target.value })} placeholder="用逗号分隔，最多 8 项" />
              </label>
              <div className="account-form__actions">
                <button className="button button--primary" type="submit" disabled={saving}>
                  <Save size={17} /> {saving ? '保存中' : '保存画像'}
                </button>
                <button className="button button--soft" type="button" onClick={() => void signOut()} disabled={saving}>
                  <LogOut size={17} /> 退出
                </button>
              </div>
            </form>
            {notice && <p className="account-notice" role="status">{notice}</p>}
            {error && <p className="account-error" role="alert">{error}</p>}
          </section>
        ) : (
          <section className="account-panel">
            <div className="account-switcher" role="group" aria-label="账户操作">
              <button className={mode === 'login' ? 'is-active' : ''} type="button" aria-pressed={mode === 'login'} onClick={() => switchMode('login')}>登录</button>
              <button className={mode === 'register' ? 'is-active' : ''} type="button" aria-pressed={mode === 'register'} onClick={() => switchMode('register')}>注册</button>
            </div>
            <div className="account-panel__heading">
              <div className="account-avatar"><LogIn size={22} /></div>
              <div>
                <p className="section-kicker">{mode === 'login' ? 'WELCOME BACK' : 'NEW ACCOUNT'}</p>
                <h2>{mode === 'login' ? '登录你的行知账户' : '创建行知账户'}</h2>
              </div>
            </div>
            <form className="account-form" onSubmit={(event) => void submitAuth(event)}>
              {mode === 'register' && (
                <label>
                  <span>显示名称</span>
                  <input value={registerDisplayName} onChange={(event) => setRegisterDisplayName(event.target.value)} maxLength={80} required />
                </label>
              )}
              <label>
                <span>邮箱</span>
                <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" required />
              </label>
              <label>
                <span>密码</span>
                <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={12} maxLength={128} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required />
              </label>
              <button className="button button--primary button--block" type="submit" disabled={authenticating}>
                <LogIn size={17} /> {authenticating ? '处理中' : mode === 'login' ? '登录账户' : '创建账户'}
              </button>
            </form>
            {notice && <p className="account-notice" role="status">{notice}</p>}
            {error && <p className="account-error" role="alert">{error}</p>}
          </section>
        )}
      </main>
    </AppShell>
  )
}
