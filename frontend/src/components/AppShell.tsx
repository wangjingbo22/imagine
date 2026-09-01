import { ArrowLeft, CircleHelp, SlidersHorizontal, UserRound } from 'lucide-react'
import { useEffect, useState, type PropsWithChildren } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { getCurrentUser } from '../api/accountApi'
import type { CurrentUser } from '../domain/account'
import { BrandMark } from './BrandMark'

interface AppShellProps extends PropsWithChildren {
  compact?: boolean
}

export function AppShell({ children, compact = false }: AppShellProps) {
  const location = useLocation()
  const isHome = location.pathname === '/'
  const [user, setUser] = useState<CurrentUser | null>(null)

  useEffect(() => {
    let active = true
    void getCurrentUser().then(({ data }) => { if (active) setUser(data) }).catch(() => { if (active) setUser(null) })
    return () => { active = false }
  }, [location.pathname])
  const modelSettingsPath = user ? '/model-settings' : '/account?returnTo=%2Fmodel-settings'

  return (
    <div className={compact ? 'app-shell app-shell--compact' : 'app-shell'}>
      <header className="topbar">
        <div className="topbar__inner">
          {isHome ? (
            <BrandMark />
          ) : (
            <Link className="topbar__back" to="/">
              <ArrowLeft size={18} />
              <BrandMark />
            </Link>
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
