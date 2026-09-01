import { LogIn, LogOut, UserRound } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  loginAccount,
  registerAccount,
} from '../api/accountApi'
import { AppShell } from '../components/AppShell'
import { useAccountSession } from '../session/useAccountSession'

type AccountMode = 'login' | 'register'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

export function AccountPage() {
  const navigate = useNavigate()
  const { user, isInitializing, setCurrentUser, logout } = useAccountSession()
  const [mode, setMode] = useState<AccountMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [registerDisplayName, setRegisterDisplayName] = useState('')
  const [authenticating, setAuthenticating] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  function switchMode(nextMode: AccountMode) {
    setMode(nextMode)
    setError('')
    setNotice('')
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
      setRegisterDisplayName('')
      setPassword('')
      navigate('/model-settings', { replace: true })
    } catch (caught) {
      setError(errorMessage(caught, '账户请求失败，请稍后重试'))
    } finally {
      setAuthenticating(false)
    }
  }

  async function signOut() {
    setError('')
    setNotice('')
    try {
      await logout()
      setEmail('')
      setPassword('')
      setRegisterDisplayName('')
      setMode('login')
      setNotice('已退出账户')
    } catch (caught) {
      setError(errorMessage(caught, '退出失败，请稍后重试'))
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
          <h1>{user ? '账户已登录。' : '登录后开始规划你的旅程。'}</h1>
          <p>登录后绑定模型与 API Key，即可开始创建你的行程。</p>
        </section>

        {user ? (
          <section className="account-panel account-panel--profile">
            <div className="account-panel__heading">
              <div className="account-avatar"><UserRound size={22} /></div>
              <div>
                <p className="section-kicker">SIGNED IN</p>
                <h2>{user.email}</h2>
              </div>
            </div>
            <div className="account-form__actions">
              <button className="button button--primary" type="button" onClick={() => navigate('/model-settings')}>
                绑定模型
              </button>
              <button className="button button--soft" type="button" onClick={() => void signOut()}>
                <LogOut size={17} /> 退出
              </button>
            </div>
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
