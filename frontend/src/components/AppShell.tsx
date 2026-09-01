import { ArrowLeft, CircleHelp, SlidersHorizontal, UserRound } from 'lucide-react'
import { useEffect, useState, type PropsWithChildren } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { getCurrentUser } from '../api/accountApi'
import type { CurrentUser } from '../domain/account'
import { BrandMark } from './BrandMark'

interface AppShellProps extends PropsWithChildren {
  compact?: boolean
}

export function AppShell({ children, compact = false }: AppShellProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const isHome = location.pathname === '/'
  const [user, setUser] = useState<CurrentUser | null>(null)

  useEffect(() => {
    let active = true
    void getCurrentUser().then(({ data }) => { if (active) setUser(data) }).catch(() => { if (active) setUser(null) })
    return () => { active = false }
  }, [location.pathname])
  const modelSettingsPath = user ? '/model-settings' : '/account?returnTo=%2Fmodel-settings'

  /**
   * 返回按钮应恢复用户刚才所在的业务页面，而不是把所有流程都强制送回首页。
   * 浏览器没有站内历史（例如用户直接粘贴邀请链接打开）时，才退回首页，避免
   * `navigate(-1)` 把用户带到站外页面或产生看起来“没有反应”的空历史返回。
   */
  const goBack = () => {
    const hasInAppHistory = window.history.length > 1 && location.key !== 'default'
    if (hasInAppHistory) {
      navigate(-1)
      return
    }
    navigate('/', { replace: true })
  }

  return (
    <div className={compact ? 'app-shell app-shell--compact' : 'app-shell'}>
      <header className="topbar">
        <div className="topbar__inner">
          {isHome ? (
            <BrandMark />
          ) : (
            <button
              aria-label="返回上一个页面"
              className="topbar__back"
              onClick={goBack}
              title="返回上一个页面"
              type="button"
            >
              <ArrowLeft size={18} />
              <BrandMark />
            </button>
          )}
          <nav className="topbar__nav" aria-label="主导航">
            <span className="topbar__status">
              <span className="status-dot" />
              {user ? `你好，${user.displayName}` : '请登录'}
            </span>
            <button className="icon-button" type="button" aria-label="帮助">
              <CircleHelp size={19} />
            </button>
            <Link className="icon-button" to={modelSettingsPath} aria-label="模型设置" title="模型设置"><SlidersHorizontal size={18} /></Link>
            <Link className="avatar" to="/account" aria-label={user ? `${user.displayName}的账户` : '账户'} title={user?.displayName ?? '账户'}>
              {user ? user.displayName.slice(0, 1).toUpperCase() : <UserRound size={16} />}
            </Link>
          </nav>
        </div>
      </header>
      {children}
    </div>
  )
}
